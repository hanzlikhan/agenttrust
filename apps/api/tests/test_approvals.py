"""Human approval workflow tests (M10): durable queue, reviewer auth,
optimistic concurrency, expiry, separation of duties, revalidation,
rate limiting, and SDK wait_for_approval. All against real PostgreSQL."""

import threading
import uuid
from datetime import timedelta

import pytest

from agenttrust_api import models
from agenttrust_api.approvals.service import decide_approval as service_decide_approval
from agenttrust_api.db import SessionLocal
from agenttrust_api.deps import AppError
from agenttrust_api.models import ApiKey, MockOrder, Policy, PolicyVersion, Project, User
from agenttrust_api.security import generate_api_key
from agenttrust_api.util import utcnow

from .helpers import REFUND_ARGS

REVIEW_ARGS = {"order_id": "ORD-100", "amount_minor": 15000, "currency": "USD"}


@pytest.fixture()
def agent_key_headers(client, admin_headers, project_id):
    """API key with agent scopes only (no approval powers)."""
    resp = client.post(
        "/api/v1/keys",
        json={
            "project_id": str(project_id),
            "name": "agent-key",
            "scopes": ["agent:run", "agent:authorize", "agent:execute"],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['api_key']}"}, body["id"]


@pytest.fixture()
def reviewer_key_headers(client, admin_headers, project_id):
    """API key with approval scopes only (cannot authorize or execute)."""
    resp = client.post(
        "/api/v1/keys",
        json={
            "project_id": str(project_id),
            "name": "reviewer-key",
            "scopes": ["approvals:read", "approvals:decide"],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['api_key']}"}, body["id"]


@pytest.fixture()
def dual_key_headers(client, admin_headers, project_id):
    """Key with both agent and reviewer scopes (for the SoD test)."""
    resp = client.post(
        "/api/v1/keys",
        json={
            "project_id": str(project_id),
            "name": "dual-key",
            "scopes": ["agent:run", "agent:authorize", "agent:execute", "approvals:decide"],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['api_key']}"}, body["id"]


@pytest.fixture()
def agent_run_id(client, agent_key_headers):
    headers, _ = agent_key_headers
    resp = client.post(
        "/api/v1/runs",
        json={"agent_name": "approval-test-agent", "agent_version": "0.1.0"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["run_id"]


def authorize_review(client, agent_key_headers, run_id, arguments=None, key_suffix=""):
    """Authorize a $150 refund (REVIEW). Returns the response body."""
    headers, _ = agent_key_headers
    resp = client.post(
        "/api/v1/tool-calls/authorize",
        json={
            "run_id": run_id,
            "tool_name": "refund_payment",
            "arguments": arguments or REVIEW_ARGS,
            "idempotency_key": f"review-{uuid.uuid4().hex}{key_suffix}",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["outcome"] == "REVIEW", body
    assert body["approval_id"], "REVIEW must create a pending approval"
    return body


def decide(client, reviewer_key_headers, approval_id, verdict, reason=None, version=None):
    headers, _ = reviewer_key_headers
    body = {"decision": verdict}
    if reason is not None:
        body["reason"] = reason
    if version is not None:
        body["expected_row_version"] = version
    return client.post(f"/api/v1/approvals/{approval_id}/decision", json=body, headers=headers)


@pytest.fixture()
def review(client, agent_key_headers, agent_run_id, policy_stack):
    return authorize_review(client, agent_key_headers, agent_run_id)


def test_review_creates_pending_approval(client, reviewer_key_headers, review, db_session):
    headers, _ = reviewer_key_headers
    resp = client.get(f"/api/v1/approvals/{review['approval_id']}", headers=headers)
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["state"] == "PENDING"
    assert detail["row_version"] == 1
    assert detail["tool_call"]["tool_name"] == "refund_payment"
    assert detail["decision"]["reason_code"] == "APPROVAL_REQUIRED"
    assert detail["order_facts"]["order_ref"] == "ORD-100"
    assert detail["order_facts"]["eligible"] is True
    kinds = [e["kind"] for e in detail["events"]]
    assert "approval.created" in kinds
    # Expires ~15 minutes out.
    expires = detail["expires_at"]
    assert expires is not None


def test_approve_execute_moves_balance_once(
    client, agent_key_headers, reviewer_key_headers, review, db_session
):
    a_headers, _ = agent_key_headers
    approval_id = review["approval_id"]
    call_id = review["tool_call_id"]

    dec = decide(client, reviewer_key_headers, approval_id, "approved", reason="looks good")
    assert dec.status_code == 200, dec.text
    body = dec.json()
    assert body["state"] == "APPROVED"
    assert body["row_version"] == 2
    assert body["grant_id"], "approval must mint a single-use grant"

    from .helpers import execute, order_balance

    before = order_balance(db_session, "ORD-100")
    exe = execute(client, agent_key_headers, call_id)
    assert exe.status_code == 201, exe.text
    assert exe.json()["replayed"] is False
    assert order_balance(db_session, "ORD-100") == before - 15000

    again = execute(client, agent_key_headers, call_id)
    assert again.status_code == 200
    assert again.json()["replayed"] is True
    assert order_balance(db_session, "ORD-100") == before - 15000


def test_execute_review_without_approval_rejected(client, agent_key_headers, review):
    from .helpers import execute

    exe = execute(client, agent_key_headers, review["tool_call_id"])
    assert exe.status_code == 409
    assert exe.json()["error_code"] == "approval_required"


def test_racing_double_decisions_single_execution():
    """Two threads decide the same approval: one wins, no double execution."""
    from agenttrust_api.policy.rules import REFUND_PAYMENT_SCHEMA as SCHEMA
    from agenttrust_api.policy.service import authorize_tool_call

    suffix = uuid.uuid4().hex[:8]
    setup = SessionLocal()
    try:
        user = User(username=f"race-{suffix}")
        setup.add(user)
        setup.flush()
        project = Project(name=f"race-{suffix}", owner_id=user.id)
        setup.add(project)
        setup.flush()
        _raw, prefix, digest = generate_api_key()
        agent_key = ApiKey(
            project_id=project.id, name="agent", key_prefix=prefix,
            key_hash=digest, scopes=["agent:run", "agent:authorize", "agent:execute"],
        )
        setup.add(agent_key)
        _raw2, prefix2, digest2 = generate_api_key()
        reviewer_key = ApiKey(
            project_id=project.id, name="reviewer", key_prefix=prefix2,
            key_hash=digest2, scopes=["approvals:read", "approvals:decide"],
        )
        setup.add(reviewer_key)
        setup.flush()
        agent_key_id, reviewer_key_id, project_id = agent_key.id, reviewer_key.id, project.id
        from agenttrust_api.models import AgentRun, ToolDefinition
        run = AgentRun(project_id=project.id, state="RUNNING", started_at=utcnow())
        setup.add(run)
        setup.flush()
        run_id = run.id
        setup.add(ToolDefinition(project_id=project.id, slug="refund_payment", version=1,
                                 schema_json=SCHEMA, risk_class="high_impact", created_at=utcnow()))
        policy = Policy(project_id=project.id, name="refund-policy", created_at=utcnow())
        setup.add(policy)
        setup.flush()
        version = PolicyVersion(policy_id=policy.id, version=1,
                                rules_json={"tool_name": "refund_payment", "currency": "USD",
                                            "auto_approve_max_minor": 10000,
                                            "review_max_minor": 50000},
                                created_by="test", activated_at=utcnow(), created_at=utcnow())
        setup.add(version)
        setup.flush()
        policy.active_version_id = version.id
        setup.add(MockOrder(order_ref=f"ORD-RACE-{suffix}", total_minor=40000,
                            refundable_remaining_minor=40000, currency="USD",
                            eligible=True, status="open", created_at=utcnow()))
        setup.commit()

        authz = authorize_tool_call(
            db=setup, project_id=project_id, run_id=run_id, tool_name="refund_payment",
            arguments={"order_id": f"ORD-RACE-{suffix}", "amount_minor": 15000, "currency": "USD"},
            idempotency_key=f"race-{suffix}", requester_key_id=agent_key_id,
        )
        assert authz.outcome == "REVIEW"
        approval_id = authz.approval_id
        assert approval_id is not None
        setup.commit()
    finally:
        setup.close()

    outcomes: list = []
    errors: list = []

    def attempt():
        s = SessionLocal()
        try:
            key = s.get(ApiKey, reviewer_key_id)
            result = service_decide_approval(
                db=s, approval_id=approval_id, project_id=project_id,
                reviewer_key=key, decision="approved", reason=None,
                expected_row_version=None,
            )
            outcomes.append(result.state)
        except AppError as exc:
            errors.append(exc.error_code)
        finally:
            s.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert outcomes.count("APPROVED") == 1, (outcomes, errors)
    assert errors == ["approval_conflict"], errors

    # Exactly one grant was minted; execute once moves the balance once.
    s = SessionLocal()
    try:
        from agenttrust_api.gateway.service import execute_tool_call
        from agenttrust_api.models import ExecutionGrant, ToolExecution
        call_id = authz.tool_call_id
        grants = s.query(ExecutionGrant).filter(ExecutionGrant.tool_call_id == call_id).all()
        assert len(grants) == 1
        result = execute_tool_call(db=s, project_id=project_id, call_id=call_id, arguments=None)
        assert result.replayed is False
        again = execute_tool_call(db=s, project_id=project_id, call_id=call_id, arguments=None)
        assert again.replayed is True
        order = s.query(MockOrder).filter(MockOrder.order_ref == f"ORD-RACE-{suffix}").one()
        assert order.refundable_remaining_minor == 25000
        assert s.query(ToolExecution).filter(ToolExecution.call_id == call_id).count() == 1
    finally:
        s.close()
        # Cleanup committed rows.
        c = SessionLocal()
        try:
            for model, flt in [
                (models.Approval, models.Approval.tool_call_id == call_id),
                (models.ToolExecution, models.ToolExecution.call_id == call_id),
                (models.ExecutionGrant, models.ExecutionGrant.tool_call_id == call_id),
            ]:
                c.query(model).filter(flt).delete()
            c.query(models.PolicyDecision).filter(
                models.PolicyDecision.tool_call_id == call_id).delete()
            c.query(models.ToolCall).filter(models.ToolCall.id == call_id).delete()
            c.query(models.Event).filter(models.Event.project_id == project_id).delete()
            c.query(models.Outbox).delete()
            c.query(models.MockOrder).filter(
                models.MockOrder.order_ref == f"ORD-RACE-{suffix}").delete()
            c.query(ToolDefinition).filter(ToolDefinition.project_id == project_id).delete()
            c.query(PolicyVersion).filter(PolicyVersion.policy_id == policy.id).delete()
            c.query(Policy).filter(Policy.id == policy.id).delete()
            c.query(models.AgentRun).filter(models.AgentRun.id == run_id).delete()
            c.query(ApiKey).filter(ApiKey.project_id == project_id).delete()
            c.query(models.Membership).filter(models.Membership.project_id == project_id).delete()
            c.query(Project).filter(Project.id == project_id).delete()
            c.query(User).filter(User.username == f"race-{suffix}").delete()
            c.commit()
        finally:
            c.close()


def test_expired_approval_rejected(
    client, agent_key_headers, reviewer_key_headers, review, db_session
):
    session, _ = db_session
    approval = session.get(models.Approval, uuid.UUID(review["approval_id"]))
    approval.expires_at = utcnow() - timedelta(seconds=1)
    session.flush()

    dec = decide(client, reviewer_key_headers, review["approval_id"], "approved")
    assert dec.status_code == 410
    assert dec.json()["error_code"] == "approval_expired"

    session.refresh(approval)
    assert approval.state == "EXPIRED"

    from .helpers import execute
    exe = execute(client, agent_key_headers, review["tool_call_id"])
    assert exe.status_code == 409
    assert exe.json()["error_code"] == "approval_required"


def test_lazy_expiry_visible_in_queue(client, reviewer_key_headers, review, db_session):
    session, _ = db_session
    approval = session.get(models.Approval, uuid.UUID(review["approval_id"]))
    approval.expires_at = utcnow() - timedelta(seconds=1)
    session.flush()

    headers, _ = reviewer_key_headers
    resp = client.get("/api/v1/approvals?state=PENDING", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    resp = client.get("/api/v1/approvals", headers=headers)
    assert resp.status_code == 200
    states = [a["state"] for a in resp.json()["approvals"]]
    assert "EXPIRED" in states


def test_sod_self_approval_forbidden(client, dual_key_headers, agent_run_id, policy_stack):
    """A key holding approvals:decide still cannot decide its own request."""
    headers, _ = dual_key_headers
    resp = client.post(
        "/api/v1/tool-calls/authorize",
        json={
            "run_id": agent_run_id,
            "tool_name": "refund_payment",
            "arguments": REVIEW_ARGS,
            "idempotency_key": f"sod-{uuid.uuid4().hex}",
        },
        headers=headers,
    )
    # The dual key lacks agent:authorize... it HAS it. Authorize works.
    assert resp.status_code == 201, resp.text
    approval_id = resp.json()["approval_id"]

    dec = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approved"},
        headers=headers,
    )
    assert dec.status_code == 403
    assert dec.json()["error_code"] == "sod_violation"


def test_agent_key_cannot_decide(client, agent_key_headers, review):
    dec = decide(client, agent_key_headers, review["approval_id"], "approved")
    assert dec.status_code == 403
    assert dec.json()["error_code"] == "insufficient_scope"


def test_reviewer_key_cannot_authorize(client, reviewer_key_headers, agent_run_id, policy_stack):
    headers, _ = reviewer_key_headers
    resp = client.post(
        "/api/v1/tool-calls/authorize",
        json={
            "run_id": agent_run_id,
            "tool_name": "refund_payment",
            "arguments": REVIEW_ARGS,
            "idempotency_key": f"scope-{uuid.uuid4().hex}",
        },
        headers=headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "insufficient_scope"


def test_approve_after_balance_consumed_rejected(
    client, agent_key_headers, reviewer_key_headers, review, db_session
):
    session, _ = db_session
    order = session.query(MockOrder).filter(MockOrder.order_ref == "ORD-100").one()
    order.refundable_remaining_minor = 10000  # below the $150 under review
    session.flush()

    dec = decide(client, reviewer_key_headers, review["approval_id"], "approved")
    assert dec.status_code == 409
    assert dec.json()["error_code"] == "approval_stale"

    session.refresh(session.get(models.Approval, uuid.UUID(review["approval_id"])))
    approval = session.get(models.Approval, uuid.UUID(review["approval_id"]))
    assert approval.state == "REJECTED"
    assert approval.reason == "facts_changed"

    from .helpers import execute
    exe = execute(client, agent_key_headers, review["tool_call_id"])
    assert exe.status_code == 409


def test_reject_then_execute_rejected(client, agent_key_headers, reviewer_key_headers, review):
    dec = decide(client, reviewer_key_headers, review["approval_id"], "rejected", reason="nope")
    assert dec.status_code == 200
    assert dec.json()["state"] == "REJECTED"

    from .helpers import execute
    exe = execute(client, agent_key_headers, review["tool_call_id"])
    assert exe.status_code == 409
    assert exe.json()["error_code"] == "approval_required"


def test_tampered_args_post_approval_rejected(
    client, agent_key_headers, reviewer_key_headers, review, db_session
):
    from .helpers import execute, order_balance

    dec = decide(client, reviewer_key_headers, review["approval_id"], "approved")
    assert dec.status_code == 200

    before = order_balance(db_session, "ORD-100")
    tampered = dict(REVIEW_ARGS)
    tampered["amount_minor"] = 49000
    exe = execute(client, agent_key_headers, review["tool_call_id"], arguments=tampered)
    assert exe.status_code == 409
    assert exe.json()["error_code"] == "arguments_tampered"
    assert order_balance(db_session, "ORD-100") == before

    # The legitimate arguments still execute: the grant survived the tamper.
    ok = execute(client, agent_key_headers, review["tool_call_id"])
    assert ok.status_code == 201
    assert order_balance(db_session, "ORD-100") == before - 15000


def test_idempotent_redecision(client, reviewer_key_headers, review):
    first = decide(client, reviewer_key_headers, review["approval_id"], "approved")
    assert first.status_code == 200
    version = first.json()["row_version"]

    second = decide(client, reviewer_key_headers, review["approval_id"], "approved")
    assert second.status_code == 200
    assert second.json()["state"] == "APPROVED"
    assert second.json()["row_version"] == version  # no version bump on re-decision

    third = decide(client, reviewer_key_headers, review["approval_id"], "rejected")
    assert third.status_code == 409
    assert third.json()["error_code"] == "approval_conflict"


def test_stale_row_version_conflict(client, reviewer_key_headers, review):
    dec = decide(
        client, reviewer_key_headers, review["approval_id"], "approved",
        version=999,  # not the version the server holds
    )
    assert dec.status_code == 409
    assert dec.json()["error_code"] == "approval_conflict"


def test_rate_limit_429(client, agent_key_headers, agent_run_id, policy_stack, monkeypatch):
    from agenttrust_api import ratelimit
    from agenttrust_api.config import settings

    monkeypatch.setattr(settings, "AGENTTRUST_RATE_LIMIT_PER_MINUTE", 3)
    ratelimit.reset_buckets()
    try:
        headers, _ = agent_key_headers
        for _ in range(3):
            resp = client.post(
                "/api/v1/tool-calls/authorize",
                json={
                    "run_id": agent_run_id,
                    "tool_name": "refund_payment",
                    "arguments": REFUND_ARGS,
                    "idempotency_key": f"rl-{uuid.uuid4().hex}",
                },
                headers=headers,
            )
            assert resp.status_code == 201, resp.text
        limited = client.post(
            "/api/v1/tool-calls/authorize",
            json={
                "run_id": agent_run_id,
                "tool_name": "refund_payment",
                "arguments": REFUND_ARGS,
                "idempotency_key": f"rl-{uuid.uuid4().hex}",
            },
            headers=headers,
        )
        assert limited.status_code == 429
        body = limited.json()
        assert body["error_code"] == "rate_limited"
        assert body["retryable"] is True
    finally:
        ratelimit.reset_buckets()


def test_approval_queue_lists_pending(client, reviewer_key_headers, review):
    headers, _ = reviewer_key_headers
    resp = client.get("/api/v1/approvals?state=PENDING", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    item = next(a for a in body["approvals"] if a["approval_id"] == review["approval_id"])
    assert item["tool_name"] == "refund_payment"
    assert item["amount_minor"] == 15000
    assert item["order_id"] == "ORD-100"
    assert item["state"] == "PENDING"


def test_approval_events_recorded(client, reviewer_key_headers, review):
    decide(client, reviewer_key_headers, review["approval_id"], "approved")
    headers, _ = reviewer_key_headers
    resp = client.get(f"/api/v1/approvals/{review['approval_id']}", headers=headers)
    kinds = [e["kind"] for e in resp.json()["events"]]
    assert "approval.created" in kinds
    assert "approval.approved" in kinds
