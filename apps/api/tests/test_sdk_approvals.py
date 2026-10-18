"""SDK wait_for_approval tests (M02/M10): poll-then-execute against the real
API over real HTTP (uvicorn in a thread)."""

import socket
import threading
import time
import uuid
from datetime import timedelta

import httpx
import pytest
import uvicorn
from agenttrust import (
    AgentTrust,
    ApprovalExpired,
    ApprovalRejected,
    ApprovalRequired,
    ApprovalTimeout,
)

from agenttrust_api.db import SessionLocal
from agenttrust_api.main import create_app
from agenttrust_api.models import (
    ApiKey,
    Approval,
    MockOrder,
    Policy,
    PolicyVersion,
    Project,
    ToolCall,
    ToolDefinition,
    User,
)
from agenttrust_api.policy.rules import REFUND_PAYMENT_SCHEMA
from agenttrust_api.security import generate_api_key
from agenttrust_api.util import utcnow

from .helpers import V1_RULES


@pytest.fixture(scope="module")
def live_server():
    app = create_app()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while True:
        try:
            httpx.get(f"{base}/health/live", timeout=1.0, trust_env=False)
            break
        except Exception:
            if time.time() > deadline:
                raise TimeoutError("test server did not start") from None
            time.sleep(0.1)
    yield base
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture()
def approval_stack(live_server):
    """Committed stack: project, agent key, reviewer key, tool, policy, order."""
    suffix = uuid.uuid4().hex[:8]
    session = SessionLocal()
    try:
        user = User(username=f"sdka-{suffix}")
        session.add(user)
        session.flush()
        project = Project(name=f"sdka-{suffix}", owner_id=user.id)
        session.add(project)
        session.flush()

        def make_key(name, scopes):
            raw, prefix, digest = generate_api_key()
            session.add(
                ApiKey(
                    project_id=project.id, name=name, key_prefix=prefix,
                    key_hash=digest, scopes=scopes,
                )
            )
            session.flush()
            return raw

        agent_raw = make_key("agent", ["agent:run", "agent:authorize", "agent:execute"])
        reviewer_raw = make_key("reviewer", ["approvals:read", "approvals:decide"])
        session.add(
            ToolDefinition(
                project_id=project.id, slug="refund_payment", version=1,
                schema_json=REFUND_PAYMENT_SCHEMA, risk_class="high_impact",
                created_at=utcnow(),
            )
        )
        policy = Policy(project_id=project.id, name="refund-policy", created_at=utcnow())
        session.add(policy)
        session.flush()
        version = PolicyVersion(
            policy_id=policy.id, version=1, rules_json=V1_RULES,
            created_by="test", activated_at=utcnow(), created_at=utcnow(),
        )
        session.add(version)
        session.flush()
        policy.active_version_id = version.id
        order_ref = f"ORD-SDKA-{suffix}"
        session.add(
            MockOrder(
                order_ref=order_ref, total_minor=40000,
                refundable_remaining_minor=40000, currency="USD",
                eligible=True, status="open", created_at=utcnow(),
            )
        )
        session.commit()
        yield {
            "base": live_server,
            "agent_key": agent_raw,
            "reviewer_key": reviewer_raw,
            "order_ref": order_ref,
            "suffix": suffix,
        }
    finally:
        session.query(MockOrder).filter(
            MockOrder.order_ref == f"ORD-SDKA-{suffix}").delete()
        # Delete tool calls first: approvals reference them (CASCADE) and
        # reference api_keys with RESTRICT, so keys cannot go first.
        session.query(ToolCall).filter(
            ToolCall.project_id == project.id).delete(synchronize_session=False)
        # Deleting the project cascades to keys, runs, events, policies.
        session.query(Project).filter(Project.name == f"sdka-{suffix}").delete()
        session.query(User).filter(User.username == f"sdka-{suffix}").delete()
        session.commit()
        session.close()


def _review_via_sdk(stack):
    """Trigger a REVIEW via the SDK; returns (trust, approval_id)."""
    trust = AgentTrust(api_key=stack["agent_key"], base_url=stack["base"])

    @trust.protect(tool="refund_payment")
    def refund_payment(order_id: str, amount_minor: int, currency: str = "USD"):
        raise NotImplementedError  # never executed by the SDK

    with trust.run(agent="sdk-approval-agent", version="0.1.0"):
        try:
            refund_payment(
                order_id=stack["order_ref"], amount_minor=15000, currency="USD"
            )
        except ApprovalRequired as exc:
            assert exc.approval_id, "REVIEW must carry an approval_id"
            return trust, exc.approval_id
    raise AssertionError("expected ApprovalRequired")


def _decide(stack, approval_id, verdict):
    resp = httpx.post(
        f"{stack['base']}/api/v1/approvals/{approval_id}/decision",
        json={"decision": verdict},
        headers={"Authorization": f"Bearer {stack['reviewer_key']}"},
        timeout=10.0,
        trust_env=False,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_wait_for_approval_executes_once(approval_stack):
    trust, approval_id = _review_via_sdk(approval_stack)
    _decide(approval_stack, approval_id, "approved")
    result = trust.wait_for_approval(approval_id, timeout_s=10, poll_interval_s=0.2)
    assert result["amount_minor"] == 15000
    assert result["remaining_minor"] == 25000


def test_wait_for_approval_rejected(approval_stack):
    trust, approval_id = _review_via_sdk(approval_stack)
    _decide(approval_stack, approval_id, "rejected")
    with pytest.raises(ApprovalRejected) as excinfo:
        trust.wait_for_approval(approval_id, timeout_s=10, poll_interval_s=0.2)
    assert excinfo.value.approval_id == approval_id


def test_wait_for_approval_expired(approval_stack):
    trust, approval_id = _review_via_sdk(approval_stack)
    session = SessionLocal()
    try:
        approval = session.get(Approval, uuid.UUID(approval_id))
        approval.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    finally:
        session.close()
    with pytest.raises(ApprovalExpired):
        trust.wait_for_approval(approval_id, timeout_s=10, poll_interval_s=0.2)


def test_wait_for_approval_timeout(approval_stack):
    trust, approval_id = _review_via_sdk(approval_stack)
    with pytest.raises(ApprovalTimeout):
        trust.wait_for_approval(approval_id, timeout_s=1, poll_interval_s=0.2)


def test_approval_required_carries_approval_id(approval_stack):
    _trust, approval_id = _review_via_sdk(approval_stack)
    assert uuid.UUID(approval_id)  # parses as a UUID
