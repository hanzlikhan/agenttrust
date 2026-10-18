"""Evaluation benchmark runner (M12).

Runs the 100-case dataset against the REAL authorize/execute stack on an
ISOLATED database (created fresh per run, migrated, seeded with the fixed
seed), measures per-case latency, asserts outcome AND actual execution /
side effects, persists ``evaluation_runs`` / ``evaluation_results`` rows
on the main database, and emits ``benchmark-report.json``.

One command: ``python -m agenttrust_api.evaluation.run --db <main-url>``.

Quality gates from spec section 13.2 are reported as TARGETS next to the
measured values — the runner never invents or asserts universal
guarantees; it reports what it measured.
"""

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import UUID, uuid4

import psycopg
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command as alembic_command

from ..deps import AppError
from ..gateway.service import execute_tool_call
from ..models import (
    AgentRun,
    ApiKey,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    Membership,
    MockOrder,
    Project,
    ToolExecution,
    User,
)
from ..policy.service import authorize_tool_call
from ..security import generate_api_key
from ..seed import MOCK_ORDERS, seed_policy_stack
from ..util import utcnow
from .dataset import DATASET_VERSION, SUITE_ID, EvalCase, build_dataset, dataset_hash

# Spec section 13.2 quality gates, reported as targets with measured values.
GATE_TARGETS = {
    "accuracy": 1.0,
    "false_allow": 0,
    "false_deny": 0,
    "unauthorized_executions": 0,
    "duplicate_effects": 0,
    "latency_p95_ms": 500.0,
}


def _replace_dbname(url: str, new_name: str) -> str:
    parts = urlparse(url)
    path = "/" + new_name
    return urlunparse(parts._replace(path=path))


def _libpq_url(url: str) -> str:
    """Convert a SQLAlchemy URL to libpq conninfo format for raw psycopg use."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _maintenance_url(url: str) -> str:
    return _libpq_url(_replace_dbname(url, "postgres"))


def create_isolated_db(main_db_url: str, eval_db_name: str) -> str:
    """Drop/create the isolated eval database. Returns its URL.

    DESTRUCTIVE (DROP DATABASE + pg_terminate_backend). For the local CLI
    operator only — never call from a request handler (Phase 8 audit
    HIGH-2). The HTTP benchmark path uses prepare_eval_db_shared() instead.
    Refuses when the name matches the main database (DB HIGH-1).
    """
    _assert_eval_db_safe(main_db_url, eval_db_name)
    eval_url = _replace_dbname(main_db_url, eval_db_name)
    with psycopg.connect(_maintenance_url(main_db_url), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (eval_db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{eval_db_name}"')
            cur.execute(f'CREATE DATABASE "{eval_db_name}"')
            cur.execute(
                f'GRANT CREATE ON SCHEMA public TO "{urlparse(main_db_url).username}"'
            )
    return eval_url


# Single-flight guard for HTTP-triggered benchmarks: the shared eval DB is
# truncated and re-seeded per run, so concurrent runs would corrupt each
# other. The CLI path (destructive, per-run DB names) does not need it.
_http_eval_lock = threading.Lock()


def _assert_eval_db_safe(main_db_url: str, eval_db_name: str) -> None:
    """Refuse to run destructive DDL against the main database.

    Phase 8 audit DB HIGH-1: ``--eval-db`` is interpolated into
    ``DROP DATABASE``. A typo or hostile value matching the main DB name
    would destroy production data. This is a hard refusal, not a warning.
    """
    main_db_name = urlparse(main_db_url).path.lstrip("/").split("?")[0]
    if not eval_db_name or eval_db_name == main_db_name:
        raise ValueError(
            f"refusing destructive benchmark: eval database name "
            f"'{eval_db_name}' matches the main database '{main_db_name}'. "
            f"Choose a distinct --eval-db name."
        )
    if not eval_db_name.startswith("agenttrust_eval"):
        raise ValueError(
            f"refusing destructive benchmark: eval database name "
            f"'{eval_db_name}' must start with 'agenttrust_eval'."
        )


def prepare_eval_db_shared(main_db_url: str, eval_db_name: str) -> str:
    """Prepare the shared HTTP eval database WITHOUT destructive DDL.

    Creates the database only if it does not exist (no DROP, no session
    termination), migrates it, then truncates every table so each run starts
    from a clean, seeded state. Callers must hold _http_eval_lock.
    """
    eval_url = _replace_dbname(main_db_url, eval_db_name)
    with psycopg.connect(_maintenance_url(main_db_url), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (eval_db_name,)
        ).fetchone()
        if not exists:
            with conn.cursor() as cur:
                cur.execute(f'CREATE DATABASE "{eval_db_name}"')
                cur.execute(
                    f'GRANT CREATE ON SCHEMA public TO "{urlparse(main_db_url).username}"'
                )
    migrate_eval_db(eval_url)
    with psycopg.connect(_libpq_url(eval_url), autocommit=True) as conn:
        tables = conn.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
        ).fetchall()
        if tables:
            quoted = ", ".join(f'"{t[0]}"' for t in tables)
            conn.execute(f"TRUNCATE {quoted} CASCADE")
    return eval_url


def _alembic_ini_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # src/agenttrust_api/evaluation -> <repo>/apps/api
    return os.path.normpath(os.path.join(here, "..", "..", "..", "alembic.ini"))


def migrate_eval_db(eval_db_url: str) -> None:
    cfg = AlembicConfig(_alembic_ini_path())
    cfg.set_main_option("sqlalchemy.url", eval_db_url)
    alembic_command.upgrade(cfg, "head")


def seed_eval_db(session: Session) -> dict[str, UUID]:
    """Seed user/project/key/run + policy stack. Returns ids."""
    owner = User(username=f"eval-owner-{uuid4().hex[:8]}")
    session.add(owner)
    session.flush()
    project = Project(name="eval", owner_id=owner.id)
    session.add(project)
    session.flush()
    session.add(Membership(user_id=owner.id, project_id=project.id, role="owner"))
    _raw, prefix, digest = generate_api_key()
    key = ApiKey(
        project_id=project.id,
        name="eval-runner",
        key_prefix=prefix,
        key_hash=digest,
        scopes=["*"],
    )
    session.add(key)
    session.flush()
    run = AgentRun(project_id=project.id, state="RUNNING")
    session.add(run)
    session.flush()
    seed_policy_stack(session, project)
    session.commit()
    policy_version = _active_policy_version(session, project.id)
    return {
        "project_id": project.id,
        "key_id": key.id,
        "run_id": run.id,
        "policy_version": policy_version,
    }


def _active_policy_version(session: Session, project_id: UUID) -> int | None:
    from ..models import Policy

    policy = (
        session.query(Policy)
        .filter(Policy.project_id == project_id, Policy.name == "refund-policy")
        .first()
    )
    return policy.active_version.version if policy and policy.active_version else None


def reset_orders(session: Session) -> None:
    """Restore mock orders to the fixed seed state before every case."""
    for order_ref, _total, remaining, _currency, _eligible in MOCK_ORDERS:
        session.query(MockOrder).filter(MockOrder.order_ref == order_ref).update(
            {"refundable_remaining_minor": remaining, "status": "open"}
        )
    session.commit()


def _git_commit() -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        out = subprocess.run(  # noqa: S603 - fixed command, no user input
            [git, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=os.path.dirname(_alembic_ini_path()),
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _host_info() -> dict[str, Any]:
    ram_bytes: int | None = None
    if hasattr(os, "sysconf"):
        try:
            ram_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError):
            ram_bytes = None
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": ram_bytes,
    }


def upsert_cases(session: Session, cases: list[EvalCase]) -> dict[str, UUID]:
    """Idempotently upsert the dataset into evaluation_cases."""
    key_to_id: dict[str, UUID] = {}
    for case in cases:
        row = (
            session.query(EvaluationCase)
            .filter(EvaluationCase.case_key == case.case_key)
            .one_or_none()
        )
        payload = {
            "tool_name": case.tool_name,
            "arguments": case.arguments,
            "execute_args": case.execute_args,
            "execute_twice": case.execute_twice,
        }
        expected = {
            "outcome": case.expected_outcome,
            "reason": case.expected_reason,
            "executed": case.expected_executed,
            "side_effects": case.expected_side_effects,
        }
        if row is None:
            row = EvaluationCase(
                suite_id=SUITE_ID,
                case_key=case.case_key,
                case_type=case.case_type,
                input_json=payload,
                expected_outcome_json=expected,
            )
            session.add(row)
            session.flush()
        else:
            row.suite_id = SUITE_ID
            row.case_type = case.case_type
            row.input_json = payload
            row.expected_outcome_json = expected
        key_to_id[case.case_key] = row.id
    session.commit()
    return key_to_id


def _run_one_case(
    eval_session: Session, case: EvalCase, ids: dict[str, UUID]
) -> dict[str, Any]:
    """Drive one case through the real stack; measure what actually happened."""
    reset_orders(eval_session)
    project_id = ids["project_id"]
    order = (
        eval_session.query(MockOrder)
        .filter(MockOrder.order_ref == str(case.arguments.get("order_id", "")))
        .first()
    )
    balance_before = order.refundable_remaining_minor if order else None

    t0 = time.perf_counter()
    outcome = "ERROR"
    reason: str | None = None
    error: str | None = None
    call_id: UUID | None = None
    try:
        auth = authorize_tool_call(
            db=eval_session,
            project_id=project_id,
            run_id=ids["run_id"],
            tool_name=case.tool_name,
            arguments=case.arguments,
            idempotency_key=f"eval-{case.case_key}",
            requester_key_id=ids["key_id"],
        )
        outcome = auth.outcome
        reason = auth.reason_code
        call_id = auth.tool_call_id
    except AppError as exc:
        outcome = "ERROR"
        reason = exc.error_code
        error = f"{exc.error_code}: {exc.message}"
    latency_ms = int((time.perf_counter() - t0) * 1000)

    executed = False
    side_effects = 0
    if outcome == "ALLOW" and call_id is not None:
        try:
            if case.execute_twice:
                for _ in range(2):
                    execute_tool_call(
                        db=eval_session,
                        project_id=project_id,
                        call_id=call_id,
                        arguments=case.arguments,
                    )
            else:
                execute_tool_call(
                    db=eval_session,
                    project_id=project_id,
                    call_id=call_id,
                    arguments=case.execute_args
                    if case.execute_args is not None
                    else case.arguments,
                )
        except AppError as exc:
            error = (error + " | " if error else "") + f"{exc.error_code}: {exc.message}"
        row = (
            eval_session.query(ToolExecution)
            .filter(ToolExecution.call_id == call_id)
            .one_or_none()
        )
        executed = row is not None and row.state == "SUCCEEDED"

    if order is not None and balance_before is not None:
        balance_after = (
            eval_session.query(MockOrder)
            .filter(MockOrder.id == order.id)
            .one()
            .refundable_remaining_minor
        )
        delta = balance_before - balance_after
        amount = case.arguments.get("amount_minor")
        if isinstance(amount, int) and delta == amount and delta > 0:
            side_effects = 1
        elif delta != 0:
            side_effects = -1  # unexpected mutation: never silently pass

    return {
        "outcome": outcome,
        "reason": reason,
        "executed": executed,
        "side_effects": side_effects,
        "latency_ms": latency_ms,
        "error": error,
    }


def _percentile(values: list[int], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(pct / 100 * len(ordered))))
    return float(ordered[rank])


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    false_allow = sum(
        1
        for r in results
        if r["expected_outcome"] in ("DENY", "ERROR", "REVIEW")
        and r["actual_outcome"] == "ALLOW"
    )
    false_deny = sum(
        1
        for r in results
        if r["expected_outcome"] == "ALLOW" and r["actual_outcome"] != "ALLOW"
    )
    unauthorized_executions = sum(
        1
        for r in results
        if r["actual_executed"] and r["expected_outcome"] != "ALLOW"
    )
    duplicate_effects = sum(1 for r in results if r["actual_side_effects"] > 1)
    latencies = [r["latency_ms"] for r in results]
    by_type: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = by_type.setdefault(r["case_type"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if r["passed"] else 0
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "accuracy": (passed / total) if total else None,
        "false_allow": false_allow,
        "false_deny": false_deny,
        "unauthorized_executions": unauthorized_executions,
        "duplicate_effects": duplicate_effects,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": float(max(latencies)) if latencies else None,
        },
        "by_type": by_type,
    }


def run_benchmark(
    *,
    main_db_url: str,
    eval_db_name: str = "agenttrust_eval",
    case_keys: list[str] | None = None,
    out_path: str | None = None,
    project_id: UUID | None = None,
    destructive: bool = True,
) -> dict[str, Any]:
    """Run the full benchmark. Returns the report dict.

    Phase 8 audit HIGH-2/DB HIGH-1: destructive mode drops and recreates
    the eval database. It MUST NOT be pointed at the main database — refuse
    if ``eval_db_name`` matches the database named in ``main_db_url``.

    `project_id` is the tenant that owns the run's results (the caller's
    project on the HTTP path; the CLI passes --project-id or None).
    `destructive=True` (CLI default) drop/creates the eval DB; the HTTP
    path MUST pass `destructive=False` so no DDL is reachable over the
    network (Phase 8 audit HIGH-2).
    """
    if destructive:
        _assert_eval_db_safe(main_db_url, eval_db_name)

    dataset = build_dataset()
    if case_keys is not None:
        wanted = set(case_keys)
        dataset = [c for c in dataset if c.case_key in wanted]
        if not dataset:
            raise ValueError("no dataset cases matched case_keys")

    if destructive:
        eval_db_url = create_isolated_db(main_db_url, eval_db_name)
        migrate_eval_db(eval_db_url)
        return _run_benchmark_inner(
            main_db_url=main_db_url,
            eval_db_url=eval_db_url,
            dataset=dataset,
            out_path=out_path,
            project_id=project_id,
        )
    # Non-destructive (HTTP) path: the shared eval DB is truncated per run,
    # so the entire run — prepare through results — is single-flight.
    with _http_eval_lock:
        eval_db_url = prepare_eval_db_shared(main_db_url, eval_db_name)
        return _run_benchmark_inner(
            main_db_url=main_db_url,
            eval_db_url=eval_db_url,
            dataset=dataset,
            out_path=out_path,
            project_id=project_id,
        )


def _run_benchmark_inner(
    *,
    main_db_url: str,
    eval_db_url: str,
    dataset: list["EvalCase"],
    out_path: str | None,
    project_id: UUID | None,
) -> dict[str, Any]:
    """Drive the dataset against a prepared eval DB; persist results on main."""
    eval_engine = create_engine(eval_db_url)
    eval_session = sessionmaker(bind=eval_engine, expire_on_commit=False)()
    try:
        ids = seed_eval_db(eval_session)

        main_engine = create_engine(main_db_url)
        main_session = sessionmaker(bind=main_engine, expire_on_commit=False)()
        try:
            case_id_map = upsert_cases(main_session, dataset)
            run = EvaluationRun(
                project_id=project_id,
                suite_id=SUITE_ID,
                dataset_version=DATASET_VERSION,
                policy_version=(
                    str(ids["policy_version"])
                    if ids["policy_version"] is not None
                    else None
                ),
                code_version=_git_commit(),
                started_at=utcnow(),
                status="RUNNING",
            )
            main_session.add(run)
            main_session.flush()

            rows: list[dict[str, Any]] = []
            for case in dataset:
                actual = _run_one_case(eval_session, case, ids)
                passed = (
                    actual["outcome"] == case.expected_outcome
                    and (case.expected_reason is None or actual["reason"] == case.expected_reason)
                    and actual["executed"] == case.expected_executed
                    and actual["side_effects"] == case.expected_side_effects
                )
                main_session.add(
                    EvaluationResult(
                        run_id=run.id,
                        case_id=case_id_map[case.case_key],
                        actual_outcome_json={
                            "outcome": actual["outcome"],
                            "reason": actual["reason"],
                            "executed": actual["executed"],
                            "side_effects": actual["side_effects"],
                            "error": actual["error"],
                        },
                        passed=passed,
                        latency_ms=actual["latency_ms"],
                    )
                )
                rows.append(
                    {
                        "case_key": case.case_key,
                        "case_type": case.case_type,
                        "passed": passed,
                        "expected_outcome": case.expected_outcome,
                        "expected_reason": case.expected_reason,
                        "expected_executed": case.expected_executed,
                        "expected_side_effects": case.expected_side_effects,
                        "actual_outcome": actual["outcome"],
                        "actual_reason": actual["reason"],
                        "actual_executed": actual["executed"],
                        "actual_side_effects": actual["side_effects"],
                        "latency_ms": actual["latency_ms"],
                        "error": actual["error"],
                    }
                )
            metrics = compute_metrics(rows)
            run.finished_at = utcnow()
            run.status = "COMPLETE"
            main_session.commit()

            report = {
                "suite_id": SUITE_ID,
                "run_id": str(run.id),
                "dataset_version": DATASET_VERSION,
                "dataset_sha256": dataset_hash(),
                "policy_version": (
                    str(ids["policy_version"])
                    if ids["policy_version"] is not None
                    else None
                ),
                "code_version": run.code_version,
                "host": _host_info(),
                "model": "none",
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "metrics": metrics,
                "gate_targets": GATE_TARGETS,
                "results": rows,
                "limitations": [
                    "Single-machine local run: latency percentiles reflect "
                    "this host only.",
                    "Policy version is the seeded refund-policy v1; results do "
                    "not generalize to other policies.",
                    "Tamper/replay cases exercise the gateway, not network or "
                    "human adversaries.",
                    "The dataset is synthetic; it measures policy-stack "
                    "correctness, not real-world fraud.",
                ],
            }
            if out_path:
                with open(out_path, "w", encoding="utf-8") as fh:
                    json.dump(report, fh, indent=2, default=str)
            return report
        finally:
            main_session.close()
            main_engine.dispose()
    finally:
        eval_session.close()
        eval_engine.dispose()


def drop_eval_db(main_db_url: str, eval_db_name: str) -> None:
    with psycopg.connect(_maintenance_url(main_db_url), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (eval_db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{eval_db_name}"')
