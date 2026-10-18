"""Evaluation benchmark HTTP layer (M12).

``POST /evaluations/run`` executes the full 100-case benchmark
synchronously with a generous timeout: there is no background worker
yet, so this endpoint blocks the HTTP worker for the duration of the run
(tens of seconds locally — measured and reported, not estimated). The
report is regenerated deterministically from stored
``evaluation_runs`` / ``evaluation_results`` rows, so re-fetching is free.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ApiKey, AppError, require_reviewer, require_scopes
from ..evaluation import service as eval_service
from ..evaluation.dataset import SUITE_ID, dataset_hash
from ..models import EvaluationCase, EvaluationResult, EvaluationRun
from ..schemas import (
    CaseExpectation,
    EvaluationCaseResult,
    EvaluationMetrics,
    EvaluationRunDetailResponse,
    EvaluationRunListResponse,
    EvaluationRunSummary,
    LatencyStats,
)

router = APIRouter(tags=["evaluations"])

_read_auth = require_scopes("evaluations:read", limit_per_minute=False)


def _summary(run: EvaluationRun, db: Session) -> EvaluationRunSummary:
    results = (
        db.query(EvaluationResult).filter(EvaluationResult.run_id == run.id).all()
    )
    passed = sum(1 for r in results if r.passed)
    return EvaluationRunSummary(
        run_id=run.id,
        suite_id=run.suite_id,
        dataset_version=run.dataset_version,
        policy_version=run.policy_version,
        code_version=run.code_version,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
    )


def _detail(run: EvaluationRun, db: Session) -> EvaluationRunDetailResponse:
    rows = (
        db.query(EvaluationResult, EvaluationCase)
        .join(EvaluationCase, EvaluationResult.case_id == EvaluationCase.id)
        .filter(EvaluationResult.run_id == run.id)
        .order_by(EvaluationCase.case_key)
        .all()
    )
    flat: list[dict] = []
    detail_results: list[EvaluationCaseResult] = []
    for result, case in rows:
        expected = case.expected_outcome_json
        actual = result.actual_outcome_json
        flat.append(
            {
                "case_type": case.case_type,
                "passed": result.passed,
                "expected_outcome": expected["outcome"],
                "actual_outcome": actual["outcome"],
                "actual_executed": actual["executed"],
                "actual_side_effects": actual["side_effects"],
                "latency_ms": result.latency_ms,
            }
        )
        detail_results.append(
            EvaluationCaseResult(
                case_key=case.case_key,
                case_type=case.case_type,
                expected=CaseExpectation(
                    outcome=expected["outcome"], executed=expected["executed"]
                ),
                actual=CaseExpectation(
                    outcome=actual["outcome"], executed=actual["executed"]
                ),
                passed=result.passed,
                latency_ms=result.latency_ms,
                error=actual.get("error"),
            )
        )
    metrics_raw = eval_service.compute_metrics(flat)
    metrics = EvaluationMetrics(
        total=metrics_raw["total"],
        passed=metrics_raw["passed"],
        failed=metrics_raw["failed"],
        accuracy=metrics_raw["accuracy"],
        false_allow=metrics_raw["false_allow"],
        false_deny=metrics_raw["false_deny"],
        unauthorized_executions=metrics_raw["unauthorized_executions"],
        duplicate_effects=metrics_raw["duplicate_effects"],
        latency_ms=LatencyStats(**metrics_raw["latency_ms"]),
        by_type=metrics_raw["by_type"],
    )
    return EvaluationRunDetailResponse(
        run=_summary(run, db), metrics=metrics, results=detail_results
    )


def _report_dict(detail: EvaluationRunDetailResponse) -> dict:
    run = detail.run
    return {
        "suite_id": run.suite_id,
        "run_id": str(run.run_id),
        "dataset_version": run.dataset_version,
        "dataset_sha256": dataset_hash(),
        "policy_version": run.policy_version,
        "code_version": run.code_version,
        "model": "none",
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "metrics": detail.metrics.model_dump(),
        "gate_targets": eval_service.GATE_TARGETS,
        "results": [
            {
                "case_key": r.case_key,
                "case_type": r.case_type,
                "expected": r.expected.model_dump(),
                "actual": r.actual.model_dump(),
                "passed": r.passed,
                "latency_ms": r.latency_ms,
                "error": r.error,
            }
            for r in detail.results
        ],
        "limitations": [
            "Single-machine local run: latency percentiles reflect this host only.",
            "Policy version is the seeded refund-policy v1; results do not generalize.",
            "Tamper/replay cases exercise the gateway, not network or human adversaries.",
            "The dataset is synthetic; it measures policy-stack correctness, not real-world fraud.",
        ],
    }


@router.post("/evaluations/run", response_model=EvaluationRunDetailResponse)
def run_evaluation(
    key: ApiKey = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> EvaluationRunDetailResponse:
    """Run the full benchmark synchronously (reviewer key required).

    Reviewer-gated (not the admin token) so the project dashboard can
    trigger it; it remains a heavyweight operation. No background worker
    exists yet, so this blocks the HTTP worker for the duration of the run.
    Locally the 100-case suite completes in seconds; the exact measured
    duration is reported in the response.

    Safety (Phase 8 audit HIGH-2): this endpoint NEVER issues DDL. It runs
    with ``destructive=False`` against a shared, truncated eval database
    under a single-flight lock — no DROP DATABASE, no session termination.
    Destructive per-run databases are CLI-only.
    """
    from ..config import settings

    report = eval_service.run_benchmark(
        main_db_url=settings.DATABASE_URL,
        eval_db_name="agenttrust_eval_http",
        out_path=None,
        project_id=key.project_id,
        destructive=False,
    )
    run = db.get(EvaluationRun, UUID(report["run_id"]))
    if run is None or run.project_id != key.project_id:
        raise AppError("evaluation_run_missing", "Run completed but was not stored.", 502)
    return _detail(run, db)


@router.get("/evaluations/runs", response_model=EvaluationRunListResponse)
def list_evaluation_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    key: ApiKey = Depends(_read_auth),
    db: Session = Depends(get_db),
) -> EvaluationRunListResponse:
    # Tenant isolation (Phase 8 audit HIGH-1): only this project's runs.
    query = db.query(EvaluationRun).filter(
        EvaluationRun.suite_id == SUITE_ID,
        EvaluationRun.project_id == key.project_id,
    )
    total = query.count()
    runs = query.order_by(desc(EvaluationRun.started_at)).limit(limit).offset(offset).all()
    return EvaluationRunListResponse(
        runs=[_summary(run, db) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/evaluations/runs/{run_id}", response_model=EvaluationRunDetailResponse)
def get_evaluation_run(
    run_id: UUID,
    key: ApiKey = Depends(_read_auth),
    db: Session = Depends(get_db),
) -> EvaluationRunDetailResponse:
    run = db.get(EvaluationRun, run_id)
    if (
        run is None
        or run.suite_id != SUITE_ID
        or run.project_id != key.project_id
    ):
        raise AppError("evaluation_run_not_found", "Evaluation run not found.", 404)
    return _detail(run, db)


@router.get("/evaluations/runs/{run_id}/report")
def download_evaluation_report(
    run_id: UUID,
    key: ApiKey = Depends(_read_auth),
    db: Session = Depends(get_db),
) -> Response:
    run = db.get(EvaluationRun, run_id)
    if (
        run is None
        or run.suite_id != SUITE_ID
        or run.project_id != key.project_id
    ):
        raise AppError("evaluation_run_not_found", "Evaluation run not found.", 404)
    import json

    detail = _detail(run, db)
    body = json.dumps(_report_dict(detail), indent=2, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=benchmark-{run_id}.json"},
    )
