"""Seed a realistic demo dataset for the AgentTrust dashboard and demos.

Usage:
    PYTHONPATH=src python -m agenttrust_api.seed_demo

Layers on top of the base `seed` module (idempotent tool/policy/orders):
an `Agent` row, demo requester/reviewer keys, and — only once — a small
scenario history driven through the real HTTP stack (TestClient against
the live database):

  run-1  "refund-support-agent"  $40 ALLOW + execute (SUCCEEDED)
  run-1  $150 REVIEW -> reviewer APPROVED -> execute (SUCCEEDED)
  run-1  $900 DENY (AMOUNT_EXCEEDS_MAX, never executed)
  run-2  $50 ALLOW + tampered execute -> 409 -> high `authorization_tamper`
         incident (OPEN)

The raw key secrets print copy-once, only when first created. Re-running
is safe: the scenario is skipped when demo runs already exist.

Requires: DATABASE_URL set, `alembic upgrade head` applied, API not
strictly required to be running (the scenario uses an in-process client).
"""

from __future__ import annotations

import sys
from uuid import uuid4

from fastapi.testclient import TestClient

from . import seed
from .db import SessionLocal, get_db
from .main import create_app
from .models import Agent, AgentRun, ApiKey, MockOrder, Project
from .security import generate_api_key
from .util import utcnow

REQUESTER_SCOPES = ["agent:run", "agent:authorize", "agent:execute", "approvals:read"]
REVIEWER_SCOPES = ["approvals:decide", "incidents:read"]


def _ensure_key(session, project: Project, name: str, scopes: list[str]) -> str | None:
    """Return the raw secret only when the key is first created."""
    existing = (
        session.query(ApiKey).filter(ApiKey.project_id == project.id, ApiKey.name == name).first()
    )
    if existing is not None:
        return None
    raw, prefix, digest = generate_api_key()
    session.add(
        ApiKey(
            id=uuid4(),
            project_id=project.id,
            key_prefix=prefix,
            key_hash=digest,
            name=name,
            scopes=scopes,
            created_at=utcnow(),
        )
    )
    session.commit()
    return raw


def _demo_runs_exist(session) -> bool:
    return (
        session.query(AgentRun)
        .join(Agent, AgentRun.agent_id == Agent.id)
        .filter(Agent.name == "refund-support-agent")
        .count()
        > 0
    )


def _run_scenario(requester_key: str) -> None:
    app = create_app()
    session = SessionLocal()
    app.dependency_overrides[get_db] = lambda: session
    headers = {"Authorization": f"Bearer {requester_key}"}
    try:
        with TestClient(app) as client:
            # --- run-1: the happy path, a review, and a denial ---
            r = client.post(
                "/api/v1/runs",
                json={"agent_name": "refund-support-agent", "agent_version": "0.3.0"},
                headers=headers,
            )
            r.raise_for_status()
            run1 = r.json()["run_id"]

            def authorize(tool_args, idem, run_id=run1):
                resp = client.post(
                    "/api/v1/tool-calls/authorize",
                    json={
                        "run_id": run_id,
                        "tool_name": "refund_payment",
                        "arguments": tool_args,
                        "idempotency_key": idem,
                    },
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()

            def execute(call_id, tool_args):
                resp = client.post(
                    f"/api/v1/tool-calls/{call_id}/execute",
                    json={"arguments": tool_args},
                    headers=headers,
                )
                return resp

            # $40 ALLOW + execute
            s1_args = {"order_id": "ORD-100", "amount_minor": 4000, "currency": "USD"}
            a1 = authorize(s1_args, "demo-s1")
            if not (a1["outcome"] == "ALLOW"):
                raise RuntimeError('demo scenario failed: a1["outcome"] == "ALLOW"')
            e1 = execute(a1["tool_call_id"], s1_args)
            if e1.status_code != 201:
                raise RuntimeError(f"demo execute failed: {e1.status_code} {e1.text}")

            # $150 REVIEW -> left PENDING so the dashboard shows an active approval
            a2 = authorize(
                {"order_id": "ORD-100", "amount_minor": 15000, "currency": "USD"}, "demo-s2"
            )
            if not (a2["outcome"] == "REVIEW" and a2["approval_id"]):
                raise RuntimeError("demo scenario failed: expected REVIEW + approval_id")

            # $900 DENY, never executed
            a3 = authorize(
                {"order_id": "ORD-100", "amount_minor": 90000, "currency": "USD"}, "demo-s3"
            )
            if not (a3["outcome"] == "DENY"):
                raise RuntimeError('demo scenario failed: a3["outcome"] == "DENY"')

            # --- run-2: tamper -> 409 -> OPEN incident ---
            r = client.post(
                "/api/v1/runs",
                json={"agent_name": "refund-support-agent", "agent_version": "0.3.0"},
                headers=headers,
            )
            r.raise_for_status()
            run2 = r.json()["run_id"]
            a4 = authorize(
                {"order_id": "ORD-300", "amount_minor": 5000, "currency": "USD"},
                "demo-s4",
                run_id=run2,
            )
            if not (a4["outcome"] == "ALLOW"):
                raise RuntimeError('demo scenario failed: a4["outcome"] == "ALLOW"')
            tampered = execute(
                a4["tool_call_id"],
                {"order_id": "ORD-300", "amount_minor": 900000, "currency": "USD"},
            )
            if tampered.status_code != 409:
                raise RuntimeError(
                    f"demo tamper expected 409, got {tampered.status_code}"
                )
    finally:
        app.dependency_overrides.clear()
        session.close()


def main() -> int:
    seed.main()
    session = SessionLocal()
    try:
        project = session.query(Project).order_by(Project.created_at).first()
        if project is None:
            print("error: no project; run the base seed first", file=sys.stderr)
            return 2

        agent = (
            session.query(Agent)
            .filter(Agent.project_id == project.id, Agent.name == "refund-support-agent")
            .first()
        )
        if agent is None:
            agent = Agent(project_id=project.id, name="refund-support-agent", version="0.3.0")
            session.add(agent)
            session.commit()
            print("demo agent created: refund-support-agent")

        req_secret = _ensure_key(session, project, "demo-requester", REQUESTER_SCOPES)
        rev_secret = _ensure_key(session, project, "demo-reviewer", REVIEWER_SCOPES)
        if req_secret:
            print(f"demo requester key (copy once): {req_secret}")
        if rev_secret:
            print(f"demo reviewer key  (copy once): {rev_secret}")

        # Deterministic synthetic balances for the scenario.
        for ref, remaining in (("ORD-100", 40000), ("ORD-300", 5000)):
            order = (
                session.query(MockOrder).filter(MockOrder.order_ref == ref).first()
            )
            if order is not None:
                order.refundable_remaining_minor = remaining
        session.commit()

        if _demo_runs_exist(session):
            print("demo scenario already present; skipping (idempotent).")
            return 0

        # The secret is only printable at creation; the scenario needs the raw
        # key, so it can only run on the same invocation that created the key.
        if req_secret is None:
            print(
                "demo-requester key already existed; scenario cannot run without "
                "its raw secret. Delete the key and re-run to regenerate it.",
                file=sys.stderr,
            )
            return 2
        _run_scenario(req_secret)
        print("demo scenario seeded: 2 runs, 1 execution, 1 pending approval, "
              "1 denial, 1 OPEN tamper incident.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
