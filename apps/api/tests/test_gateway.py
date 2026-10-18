"""Trusted gateway tests (M07) against real PostgreSQL.

The completion gate: an unsafe call provably never executes. Every unsafe
path below asserts the balance did not move AND no execution row exists.
"""

import threading
import uuid
from datetime import timedelta

from agenttrust_api.gateway.service import execute_tool_call
from agenttrust_api.models import (
    AgentRun,
    ApiKey,
    Event,
    ExecutionGrant,
    MockOrder,
    Outbox,
    Policy,
    PolicyDecision,
    PolicyVersion,
    Project,
    ToolCall,
    ToolDefinition,
    ToolExecution,
    User,
)
from agenttrust_api.policy.rules import REFUND_PAYMENT_SCHEMA
from agenttrust_api.policy.service import authorize_tool_call
from agenttrust_api.security import generate_api_key
from agenttrust_api.util import utcnow

from .helpers import REFUND_ARGS, V1_RULES, authorize, execute, order_balance


def _execution_count(db_session, call_id):
    session, _ = db_session
    return session.query(ToolExecution).filter(ToolExecution.call_id == call_id).count()


def _grant(db_session, call_id):
    session, _ = db_session
    return (
        session.query(ExecutionGrant).filter(ExecutionGrant.tool_call_id == call_id).one_or_none()
    )


def _events(db_session, kinds):
    session, _ = db_session
    rows = session.query(Event).filter(Event.kind.in_(kinds)).all()
    return {row.kind for row in rows}


def test_allow_execute_moves_balance_once(
    db_session, client, key_headers, run_id, policy_stack
):
    resp = authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "gw-k1")
    assert resp.status_code == 201, resp.text
    call_id = resp.json()["tool_call_id"]

    grant = _grant(db_session, call_id)
    assert grant is not None and grant.status == "ACTIVE"

    before = order_balance(db_session, "ORD-100")
    exec_resp = execute(client, key_headers, call_id, REFUND_ARGS)
    assert exec_resp.status_code == 201, exec_resp.text
    body = exec_resp.json()
    assert body["replayed"] is False
    assert body["result"]["amount_minor"] == 4000
    assert body["result"]["remaining_minor"] == before - 4000
    assert order_balance(db_session, "ORD-100") == before - 4000

    grant = _grant(db_session, call_id)
    assert grant.status == "CONSUMED" and grant.consumed_at is not None
    assert _execution_count(db_session, call_id) == 1

    expected = {"tool.requested", "policy.allowed", "tool.executing", "tool.succeeded"}
    assert expected <= _events(db_session, expected)
    session, _ = db_session
    assert session.query(Outbox).count() >= 4


def test_replay_execute_returns_original_result(
    db_session, client, key_headers, run_id, policy_stack
):
    resp = authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "gw-k2")
    call_id = resp.json()["tool_call_id"]
    first = execute(client, key_headers, call_id)
    assert first.status_code == 201
    balance_after = order_balance(db_session, "ORD-100")

    second = execute(client, key_headers, call_id)
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True
    assert second.json()["execution_id"] == first.json()["execution_id"]
    assert second.json()["result"] == first.json()["result"]
    assert order_balance(db_session, "ORD-100") == balance_after
    assert _execution_count(db_session, call_id) == 1


def test_tampered_arguments_rejected(
    db_session, client, key_headers, run_id, policy_stack
):
    resp = authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "gw-k3")
    call_id = resp.json()["tool_call_id"]
    before = order_balance(db_session, "ORD-100")

    tampered = {"order_id": "ORD-100", "amount_minor": 90000, "currency": "USD"}
    exec_resp = execute(client, key_headers, call_id, tampered)
    assert exec_resp.status_code == 409, exec_resp.text
    assert exec_resp.json()["error_code"] == "arguments_tampered"
    assert order_balance(db_session, "ORD-100") == before
    assert _execution_count(db_session, call_id) == 0
    # The legitimate grant survives: the real arguments still execute.
    grant = _grant(db_session, call_id)
    assert grant.status == "ACTIVE"
    ok = execute(client, key_headers, call_id, REFUND_ARGS)
    assert ok.status_code == 201


def test_expired_grant_rejected(
    db_session, client, key_headers, run_id, policy_stack
):
    resp = authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "gw-k4")
    call_id = resp.json()["tool_call_id"]
    session, _ = db_session
    grant = _grant(db_session, call_id)
    grant.expires_at = utcnow() - timedelta(seconds=1)
    session.flush()
    before = order_balance(db_session, "ORD-100")

    exec_resp = execute(client, key_headers, call_id)
    assert exec_resp.status_code == 410, exec_resp.text
    assert exec_resp.json()["error_code"] == "grant_expired"
    assert order_balance(db_session, "ORD-100") == before
    assert _execution_count(db_session, call_id) == 0


def test_deny_decision_never_executes_no_grant(
    db_session, client, key_headers, run_id, policy_stack
):
    denied = {"order_id": "ORD-100", "amount_minor": 90000, "currency": "USD"}
    resp = authorize(client, key_headers, run_id, "refund_payment", denied, "gw-k5")
    assert resp.json()["outcome"] == "DENY"
    call_id = resp.json()["tool_call_id"]
    assert _grant(db_session, call_id) is None  # no grant minted for DENY
    before = order_balance(db_session, "ORD-100")

    exec_resp = execute(client, key_headers, call_id)
    assert exec_resp.status_code == 409, exec_resp.text
    assert order_balance(db_session, "ORD-100") == before
    assert _execution_count(db_session, call_id) == 0


def test_review_decision_never_executes(
    db_session, client, key_headers, run_id, policy_stack
):
    review = {"order_id": "ORD-100", "amount_minor": 15000, "currency": "USD"}
    resp = authorize(client, key_headers, run_id, "refund_payment", review, "gw-k6")
    assert resp.json()["outcome"] == "REVIEW"
    call_id = resp.json()["tool_call_id"]
    before = order_balance(db_session, "ORD-100")

    exec_resp = execute(client, key_headers, call_id)
    assert exec_resp.status_code == 409, exec_resp.text
    assert exec_resp.json()["error_code"] == "approval_required"
    assert order_balance(db_session, "ORD-100") == before
    assert _execution_count(db_session, call_id) == 0


def test_execute_unknown_call_404(client, key_headers):
    headers, _raw = key_headers
    resp = client.post(
        f"/api/v1/tool-calls/{uuid.uuid4()}/execute", json={}, headers=headers
    )
    assert resp.status_code == 404


def test_concurrent_executes_single_side_effect(migrated_db_url):
    """Eight threads race one execute: exactly one wins, balance moves once."""
    from agenttrust_api.db import SessionLocal

    suffix = uuid.uuid4().hex[:8]
    setup = SessionLocal()
    try:
        user = User(username=f"conc-{suffix}")
        setup.add(user)
        setup.flush()
        project = Project(name=f"conc-{suffix}", owner_id=user.id)
        setup.add(project)
        setup.flush()
        _raw, prefix, digest = generate_api_key()
        api_key = ApiKey(
            project_id=project.id,
            name="conc",
            key_prefix=prefix,
            key_hash=digest,
            scopes=["*"],
        )
        setup.add(api_key)
        setup.flush()
        run = AgentRun(project_id=project.id, state="RUNNING", started_at=utcnow())
        setup.add(run)
        setup.flush()
        setup.add(
            ToolDefinition(
                project_id=project.id,
                slug="refund_payment",
                version=1,
                schema_json=REFUND_PAYMENT_SCHEMA,
                risk_class="high_impact",
                created_at=utcnow(),
            )
        )
        policy = Policy(project_id=project.id, name="refund-policy", created_at=utcnow())
        setup.add(policy)
        setup.flush()
        version = PolicyVersion(
            policy_id=policy.id,
            version=1,
            rules_json=V1_RULES,
            created_by="test",
            activated_at=utcnow(),
            created_at=utcnow(),
        )
        setup.add(version)
        setup.flush()
        policy.active_version_id = version.id
        order_ref = f"ORD-CONC-{suffix}"
        setup.add(
            MockOrder(
                order_ref=order_ref,
                total_minor=40000,
                refundable_remaining_minor=40000,
                currency="USD",
                eligible=True,
                status="open",
                created_at=utcnow(),
            )
        )
        setup.commit()

        args = {"order_id": order_ref, "amount_minor": 4000, "currency": "USD"}
        authz = authorize_tool_call(
            db=setup,
            project_id=project.id,
            run_id=run.id,
            tool_name="refund_payment",
            arguments=args,
            idempotency_key=f"conc-{suffix}",
            requester_key_id=api_key.id,
        )
        assert authz.outcome == "ALLOW"
        call_id = authz.tool_call_id
        project_id = project.id
    finally:
        setup.close()

    outcomes: list = []
    errors: list = []

    def worker():
        db = SessionLocal()
        try:
            outcomes.append(
                execute_tool_call(
                    db=db, project_id=project_id, call_id=call_id, arguments=args
                )
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"unexpected errors: {errors}"
    assert len(outcomes) == 8
    fresh = [o for o in outcomes if not o.replayed]
    replayed = [o for o in outcomes if o.replayed]
    assert len(fresh) == 1, f"expected exactly one real execution, got {len(fresh)}"
    assert len(replayed) == 7
    assert len({o.execution_id for o in outcomes}) == 1

    check = SessionLocal()
    try:
        order = (
            check.query(MockOrder).filter(MockOrder.order_ref == order_ref).one()
        )
        assert order.refundable_remaining_minor == 36000
        assert (
            check.query(ToolExecution).filter(ToolExecution.call_id == call_id).count()
            == 1
        )
    finally:
        # Cleanup committed rows so later tests see a clean database.
        check.query(MockOrder).filter(MockOrder.order_ref == order_ref).delete()
        check.query(Project).filter(Project.id == project_id).delete()
        check.commit()
        check.close()


def test_events_recorded_on_rejected_execute(
    db_session, client, key_headers, run_id, policy_stack
):
    denied = {"order_id": "ORD-100", "amount_minor": 90000, "currency": "USD"}
    resp = authorize(client, key_headers, run_id, "refund_payment", denied, "gw-k7")
    call_id = resp.json()["tool_call_id"]
    execute(client, key_headers, call_id)
    kinds = _events(db_session, {"tool.execute_rejected"})
    assert "tool.execute_rejected" in kinds
    session, _ = db_session
    call = session.get(ToolCall, call_id)
    assert call.state == "DENIED"
    decision = (
        session.query(PolicyDecision).filter(PolicyDecision.tool_call_id == call_id).one()
    )
    assert decision.outcome == "DENY"
