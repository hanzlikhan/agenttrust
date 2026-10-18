"""SDK end-to-end tests (M02): the installed `agenttrust` package against the
real API over real HTTP (uvicorn in a thread). Proves the SDK never executes
on DENY/REVIEW/unreachable paths.
"""

import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
from agenttrust import (
    AgentTrust,
    ApprovalRequired,
    AuthorizationDenied,
    ConfigurationError,
    PolicyServiceUnavailable,
)

from agenttrust_api.db import SessionLocal
from agenttrust_api.main import create_app
from agenttrust_api.models import (
    ApiKey,
    MockOrder,
    Policy,
    PolicyVersion,
    Project,
    ToolCall,
    ToolDefinition,
    ToolExecution,
    User,
)
from agenttrust_api.policy.rules import REFUND_PAYMENT_SCHEMA
from agenttrust_api.security import generate_api_key
from agenttrust_api.util import utcnow

from .helpers import V1_RULES


@pytest.fixture(scope="module")
def live_server():
    """Run the real app on 127.0.0.1 (thread); yields the base URL."""
    app = create_app()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
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
def sdk_stack():
    """Committed project stack with unique refs; cleaned up afterwards."""
    suffix = uuid.uuid4().hex[:8]
    session = SessionLocal()
    try:
        user = User(username=f"sdk-{suffix}")
        session.add(user)
        session.flush()
        project = Project(name=f"sdk-{suffix}", owner_id=user.id)
        session.add(project)
        session.flush()
        raw, prefix, digest = generate_api_key()
        session.add(
            ApiKey(
                project_id=project.id,
                name="sdk",
                key_prefix=prefix,
                key_hash=digest,
                scopes=["*"],
            )
        )
        session.add(
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
        session.add(policy)
        session.flush()
        version = PolicyVersion(
            policy_id=policy.id,
            version=1,
            rules_json=V1_RULES,
            created_by="test",
            activated_at=utcnow(),
            created_at=utcnow(),
        )
        session.add(version)
        session.flush()
        policy.active_version_id = version.id
        order_ref = f"ORD-SDK-{suffix}"
        session.add(
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
        session.commit()
        yield {
            "api_key": raw,
            "project_id": project.id,
            "order_ref": order_ref,
        }
    finally:
        session.query(MockOrder).filter(
            MockOrder.order_ref == f"ORD-SDK-{suffix}"
        ).delete()
        # Delete tool calls first: approvals reference api_keys with RESTRICT,
        # so approvals must go (via tool_call CASCADE) before keys can.
        session.query(ToolCall).filter(
            ToolCall.project_id == project.id
        ).delete(synchronize_session=False)
        session.query(Project).filter(Project.name == f"sdk-{suffix}").delete()
        session.query(User).filter(User.username == f"sdk-{suffix}").delete()
        session.commit()
        session.close()


def _protect(trust):
    @trust.protect(tool="refund_payment")
    def refund_payment(order_id: str, amount_minor: int, currency: str = "USD"):
        raise NotImplementedError  # never executed by the SDK

    return refund_payment


def _balance_via_session(order_ref):
    session = SessionLocal()
    try:
        order = session.query(MockOrder).filter(MockOrder.order_ref == order_ref).one()
        return order.refundable_remaining_minor
    finally:
        session.close()


def test_sdk_allow_executes_via_gateway(live_server, sdk_stack, migrated_db_url):
    trust = AgentTrust(api_key=sdk_stack["api_key"], base_url=live_server)
    refund_payment = _protect(trust)
    order_ref = sdk_stack["order_ref"]
    with trust.run(agent="sdk-test"):
        result = refund_payment(order_id=order_ref, amount_minor=4000, currency="USD")
    assert result["amount_minor"] == 4000
    assert result["remaining_minor"] == 36000
    assert _balance_via_session(order_ref) == 36000


def test_sdk_deny_raises_and_never_executes(live_server, sdk_stack, migrated_db_url):
    trust = AgentTrust(api_key=sdk_stack["api_key"], base_url=live_server)
    refund_payment = _protect(trust)
    order_ref = sdk_stack["order_ref"]
    with trust.run(agent="sdk-test"):
        with pytest.raises(AuthorizationDenied) as exc_info:
            refund_payment(order_id=order_ref, amount_minor=90000, currency="USD")
    assert exc_info.value.reason_code == "AMOUNT_EXCEEDS_MAX"
    assert exc_info.value.tool_call_id is not None
    session = SessionLocal()
    try:
        # The execute endpoint was never hit: no execution row for this
        # project, balance untouched.
        count = (
            session.query(ToolExecution)
            .join(ToolCall, ToolExecution.call_id == ToolCall.id)
            .filter(ToolCall.project_id == sdk_stack["project_id"])
            .count()
        )
        assert count == 0
    finally:
        session.close()
    assert _balance_via_session(order_ref) == 40000


def test_sdk_review_raises_approval_required(live_server, sdk_stack, migrated_db_url):
    trust = AgentTrust(api_key=sdk_stack["api_key"], base_url=live_server)
    refund_payment = _protect(trust)
    with trust.run(agent="sdk-test"):
        with pytest.raises(ApprovalRequired):
            refund_payment(
                order_id=sdk_stack["order_ref"], amount_minor=15000, currency="USD"
            )


def test_sdk_unavailable_fails_closed(live_server, sdk_stack, migrated_db_url):
    # Nothing listens on port 9: connection refused.
    trust = AgentTrust(api_key=sdk_stack["api_key"], base_url="http://127.0.0.1:9", timeout=1.0)
    refund_payment = _protect(trust)
    with pytest.raises(PolicyServiceUnavailable):
        with trust.run(agent="sdk-test"):
            refund_payment(
                order_id=sdk_stack["order_ref"], amount_minor=4000, currency="USD"
            )
    assert _balance_via_session(sdk_stack["order_ref"]) == 40000


def test_sdk_requires_run_context(live_server, sdk_stack, migrated_db_url):
    trust = AgentTrust(api_key=sdk_stack["api_key"], base_url=live_server)
    refund_payment = _protect(trust)
    with pytest.raises(ConfigurationError):
        refund_payment(order_id=sdk_stack["order_ref"], amount_minor=4000, currency="USD")


def test_sdk_rejects_empty_api_key():
    with pytest.raises(ConfigurationError):
        AgentTrust(api_key="  ")
