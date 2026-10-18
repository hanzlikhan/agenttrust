"""Integration tests for the authorize flow against real PostgreSQL.

Covers: run/tool/policy setup, ALLOW/DENY/REVIEW decisions with atomic
persistence, idempotent replay, idempotency conflicts, cross-project isolation,
non-mutating simulation, and policy version immutability.
"""

import uuid

import pytest

from agenttrust_api.models import (
    AgentRun,
    MockOrder,
    PolicyDecision,
    Project,
    ToolCall,
    User,
)
from agenttrust_api.policy.rules import REFUND_PAYMENT_SCHEMA
from agenttrust_api.util import utcnow

V1_RULES = {
    "tool_name": "refund_payment",
    "currency": "USD",
    "auto_approve_max_minor": 10000,
    "review_max_minor": 50000,
}

REFUND_ARGS = {"order_id": "ORD-100", "amount_minor": 4000, "currency": "USD"}


@pytest.fixture()
def key_headers(client, admin_headers, project_id):
    resp = client.post(
        "/api/v1/keys",
        json={"project_id": str(project_id), "name": "test-key", "scopes": ["*"]},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['api_key']}"}


@pytest.fixture()
def orders(db_session):
    session, _ = db_session
    rows = [
        ("ORD-100", 40000, 40000, "USD", True),
        ("ORD-200", 100000, 100000, "USD", False),
        ("ORD-300", 20000, 5000, "USD", True),
    ]
    for ref, total, remaining, currency, eligible in rows:
        session.add(
            MockOrder(
                order_ref=ref,
                total_minor=total,
                refundable_remaining_minor=remaining,
                currency=currency,
                eligible=eligible,
                status="open",
                created_at=utcnow(),
            )
        )
    session.flush()


@pytest.fixture()
def policy_stack(client, admin_headers, project_id, orders):
    """Register refund_payment v1 and activate refund-policy v1."""
    resp = client.post(
        "/api/v1/tools",
        json={
            "project_id": str(project_id),
            "slug": "refund_payment",
            "version": 1,
            "schema_json": REFUND_PAYMENT_SCHEMA,
            "risk_class": "high_impact",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text

    resp = client.post(
        "/api/v1/policies",
        json={"project_id": str(project_id), "name": "refund-policy", "rules_json": V1_RULES},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    policy_id = resp.json()["id"]
    assert resp.json()["active_version_id"] is None  # draft until activated

    resp = client.post(f"/api/v1/policies/{policy_id}/activate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["activated_version"] == 1
    return policy_id


@pytest.fixture()
def run_id(client, key_headers):
    resp = client.post(
        "/api/v1/runs",
        json={"agent_name": "refund-agent", "agent_version": "0.2.0"},
        headers=key_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "RUNNING"
    assert body["trace_id"]
    return body["run_id"]


def _authorize(client, key_headers, run_id, tool_name, arguments, idem_key):
    return client.post(
        "/api/v1/tool-calls/authorize",
        json={
            "run_id": run_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "idempotency_key": idem_key,
        },
        headers=key_headers,
    )


def _call_and_decision(db_session, tool_call_id):
    from uuid import UUID

    session, _ = db_session
    call = session.get(ToolCall, UUID(tool_call_id))
    decision = (
        session.query(PolicyDecision)
        .filter(PolicyDecision.tool_call_id == call.id)
        .one()
    )
    return call, decision


def test_authorize_allow_persists_atomically(client, key_headers, policy_stack, run_id, db_session):
    resp = _authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "k-allow-1")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["outcome"] == "ALLOW"
    assert body["reason_code"] == "AUTO_APPROVED"
    assert body["policy_version"] == 1
    assert body["approval_id"] is None
    assert body["explanation"]

    call, decision = _call_and_decision(db_session, body["tool_call_id"])
    assert call.state == "AUTHORIZED"
    assert decision.outcome == "ALLOW"
    assert decision.reason_code == "AUTO_APPROVED"
    assert decision.version.version == 1
    assert call.args_hash and len(call.args_hash) == 64
    # Redacted args keep the allowlisted demo fields only.
    assert set(call.args_redacted) == {"order_id", "amount_minor", "currency"}


def test_authorize_review(client, key_headers, policy_stack, run_id, db_session):
    args = {"order_id": "ORD-100", "amount_minor": 15000, "currency": "USD"}
    resp = _authorize(client, key_headers, run_id, "refund_payment", args, "k-review-1")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["outcome"] == "REVIEW"
    assert body["reason_code"] == "APPROVAL_REQUIRED"
    # Phase 5: REVIEW creates a real pending approval (supersedes ADR-016's
    # approval_id null).
    approval_id = body["approval_id"]
    assert uuid.UUID(approval_id)
    from agenttrust_api.models import Approval

    session, _ = db_session
    approval = session.get(Approval, uuid.UUID(approval_id))
    assert approval is not None
    assert approval.state == "PENDING"
    assert approval.tool_call_id == uuid.UUID(body["tool_call_id"])
    assert approval.row_version == 1


def test_authorize_deny_over_cap(client, key_headers, policy_stack, run_id, db_session):
    args = {"order_id": "ORD-100", "amount_minor": 90000, "currency": "USD"}
    resp = _authorize(client, key_headers, run_id, "refund_payment", args, "k-deny-1")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["outcome"], body["reason_code"]) == ("DENY", "AMOUNT_EXCEEDS_MAX")
    call, _ = _call_and_decision(db_session, body["tool_call_id"])
    assert call.state == "DENIED"


def test_authorize_deny_ineligible(client, key_headers, policy_stack, run_id):
    args = {"order_id": "ORD-200", "amount_minor": 4000, "currency": "USD"}
    resp = _authorize(client, key_headers, run_id, "refund_payment", args, "k-deny-2")
    assert resp.json()["reason_code"] == "INELIGIBLE_ORDER"


def test_authorize_deny_missing_order(client, key_headers, policy_stack, run_id):
    args = {"order_id": "ORD-999", "amount_minor": 4000, "currency": "USD"}
    resp = _authorize(client, key_headers, run_id, "refund_payment", args, "k-deny-3")
    assert resp.json()["reason_code"] == "MISSING_CONTEXT"


def test_authorize_deny_unknown_tool_persisted(
    client, key_headers, policy_stack, run_id, db_session
):
    resp = _authorize(client, key_headers, run_id, "wire_transfer", REFUND_ARGS, "k-deny-4")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["outcome"], body["reason_code"]) == ("DENY", "UNKNOWN_TOOL")
    assert body["policy_version"] is None
    call, _ = _call_and_decision(db_session, body["tool_call_id"])
    assert call.tool_id is None  # no registered tool to reference
    assert call.args_redacted == {}  # unknown tools redact to nothing


def test_authorize_malformed_arguments_denied(client, key_headers, policy_stack, run_id):
    args = {"order_id": "ORD-100", "amount_minor": "4000", "currency": "USD"}
    resp = _authorize(client, key_headers, run_id, "refund_payment", args, "k-deny-5")
    assert resp.status_code == 201, resp.text
    assert resp.json()["reason_code"] == "MALFORMED_ARGUMENTS"


def test_authorize_float_amount_rejected(client, key_headers, policy_stack, run_id):
    args = {"order_id": "ORD-100", "amount_minor": 4000.0, "currency": "USD"}
    resp = _authorize(client, key_headers, run_id, "refund_payment", args, "k-deny-6")
    assert resp.json()["reason_code"] == "MALFORMED_ARGUMENTS"


def test_idempotent_replay_returns_same_decision(
    client, key_headers, policy_stack, run_id, db_session
):
    first = _authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "k-replay-1")
    assert first.status_code == 201
    second = _authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "k-replay-1")
    assert second.status_code == 200
    assert second.json()["decision_id"] == first.json()["decision_id"]
    assert second.json()["tool_call_id"] == first.json()["tool_call_id"]

    session, _ = db_session
    count = session.query(ToolCall).count()
    assert count == 1
    assert session.query(PolicyDecision).count() == 1


def test_idempotency_key_reuse_with_different_args_conflicts(
    client, key_headers, policy_stack, run_id
):
    first = _authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "k-conflict-1")
    assert first.status_code == 201
    other = {"order_id": "ORD-100", "amount_minor": 5000, "currency": "USD"}
    second = _authorize(client, key_headers, run_id, "refund_payment", other, "k-conflict-1")
    assert second.status_code == 409
    assert second.json()["error_code"] == "idempotency_conflict"


def test_authorize_run_from_other_project_404(client, key_headers, db_session):
    session, _ = db_session
    other_owner = User(username="intruder")
    session.add(other_owner)
    session.flush()
    other_project = Project(name="other", owner_id=other_owner.id)
    session.add(other_project)
    session.flush()
    foreign_run = AgentRun(
        project_id=other_project.id, agent_id=None, state="RUNNING", started_at=utcnow()
    )
    session.add(foreign_run)
    session.flush()

    resp = _authorize(
        client, key_headers, str(foreign_run.id), "refund_payment", REFUND_ARGS, "k-404-1"
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "run_not_found"


def test_authorize_unknown_run_404(client, key_headers, policy_stack):
    import uuid

    resp = _authorize(
        client, key_headers, str(uuid.uuid4()), "refund_payment", REFUND_ARGS, "k-404-2"
    )
    assert resp.status_code == 404


def test_simulate_writes_nothing(
    client, admin_headers, key_headers, policy_stack, run_id, db_session, project_id
):
    session, _ = db_session
    before_calls = session.query(ToolCall).count()
    before_decisions = session.query(PolicyDecision).count()

    # project_id is required; null is rejected without side effects.
    resp = client.post(
        "/api/v1/policies/simulate",
        json={"project_id": None, "tool_name": "refund_payment", "arguments": REFUND_ARGS},
        headers=admin_headers,
    )
    assert resp.status_code == 422

    resp = client.post(
        "/api/v1/policies/simulate",
        json={
            "project_id": str(project_id),
            "tool_name": "refund_payment",
            "arguments": {"order_id": "ORD-100", "amount_minor": 15000, "currency": "USD"},
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["outcome"], body["reason_code"]) == ("REVIEW", "APPROVAL_REQUIRED")
    assert body["evaluated_with_draft"] is False

    assert session.query(ToolCall).count() == before_calls
    assert session.query(PolicyDecision).count() == before_decisions


def test_policy_activation_immutability(
    client, admin_headers, key_headers, policy_stack, run_id, db_session, project_id
):
    policy_id = policy_stack
    # Draft v2 with a higher auto-approve cap; not activated yet.
    v2_rules = dict(V1_RULES, auto_approve_max_minor=50000)
    resp = client.post(
        "/api/v1/policies",
        json={
            "project_id": str(project_id),
            "name": "refund-policy",
            "rules_json": v2_rules,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["active_version_id"] is not None  # v1 still active

    # Authorize still uses v1: 40000 -> REVIEW under v1.
    args = {"order_id": "ORD-100", "amount_minor": 40000, "currency": "USD"}
    resp = _authorize(client, key_headers, run_id, "refund_payment", args, "k-immut-1")
    assert resp.json()["policy_version"] == 1
    assert resp.json()["outcome"] == "REVIEW"

    # Simulate previews the draft without activating it.
    resp = client.post(
        "/api/v1/policies/simulate",
        json={
            "project_id": str(project_id),
            "tool_name": "refund_payment",
            "arguments": args,
        },
        headers=admin_headers,
    )
    assert resp.json()["outcome"] == "ALLOW"
    assert resp.json()["evaluated_with_draft"] is True
    assert resp.json()["policy_version"] == 2

    # Activate v2: new decisions use v2; the old decision still references v1.
    resp = client.post(f"/api/v1/policies/{policy_id}/activate", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["activated_version"] == 2

    resp = _authorize(client, key_headers, run_id, "refund_payment", args, "k-immut-2")
    assert resp.json()["policy_version"] == 2
    assert resp.json()["outcome"] == "ALLOW"

    # Activating again with no new draft is a 409, not a silent no-op.
    resp = client.post(f"/api/v1/policies/{policy_id}/activate", headers=admin_headers)
    assert resp.status_code == 409

    session, _ = db_session
    versions = {d.version.version for d in session.query(PolicyDecision).all()}
    assert versions == {1, 2}
