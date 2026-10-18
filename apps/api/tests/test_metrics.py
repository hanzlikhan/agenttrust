"""Built-in service metrics (M17, Phase 8): project-scoped counters derived
only from committed rows. Tests drive the real HTTP stack."""

import uuid

from fastapi.testclient import TestClient

from agenttrust_api.main import create_app
from agenttrust_api.models import ApiKey, Project, User
from agenttrust_api.security import generate_api_key
from agenttrust_api.util import utcnow
from tests.helpers import authorize, execute


def _metrics(client: TestClient, headers: dict) -> dict:
    resp = client.get("/api/v1/metrics", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_metrics_counts_decisions_executions_and_pending_approval(
    client, key_headers, policy_stack, run_id
):
    headers, _raw = key_headers
    allow = authorize(
        client, key_headers, run_id, "refund_payment",
        {"order_id": "ORD-100", "amount_minor": 4000, "currency": "USD"}, "m-allow",
    )
    assert allow.json()["outcome"] == "ALLOW"
    deny = authorize(
        client, key_headers, run_id, "refund_payment",
        {"order_id": "ORD-100", "amount_minor": 90000, "currency": "USD"}, "m-deny",
    )
    assert deny.json()["outcome"] == "DENY"
    review = authorize(
        client, key_headers, run_id, "refund_payment",
        {"order_id": "ORD-100", "amount_minor": 15000, "currency": "USD"}, "m-review",
    )
    assert review.json()["outcome"] == "REVIEW"
    assert review.json()["approval_id"] is not None

    exec_resp = execute(client, key_headers, allow.json()["tool_call_id"])
    assert exec_resp.status_code == 201, exec_resp.text

    m = _metrics(client, headers)
    assert m["decisions_by_outcome"] == {"ALLOW": 1, "DENY": 1, "REVIEW": 1}
    assert m["executions_total"] == 1
    assert m["active_approvals"] == 1  # the REVIEW approval is still PENDING
    assert m["incidents_by_status"] == {}
    assert "project_id" in m and "generated_at" in m


def test_metrics_counts_open_incident(client, key_headers, policy_stack, run_id):
    headers, _raw = key_headers
    auth = authorize(
        client, key_headers, run_id, "refund_payment",
        {"order_id": "ORD-300", "amount_minor": 5000, "currency": "USD"}, "m-tamper",
    )
    call_id = auth.json()["tool_call_id"]
    tampered = execute(
        client, key_headers, call_id,
        {"order_id": "ORD-300", "amount_minor": 900000, "currency": "USD"},
    )
    assert tampered.status_code == 409, tampered.text

    m = _metrics(client, headers)
    assert m["incidents_by_status"].get("OPEN") == 1


def test_metrics_project_scoped(client, db_session):
    """A second project's metrics do not leak another project's rows."""
    session, _first_project = db_session
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f"met-{suffix}")
    session.add(user)
    session.flush()
    project = Project(name=f"met-{suffix}", owner_id=user.id)
    session.add(project)
    session.flush()
    raw, prefix, digest = generate_api_key()
    session.add(ApiKey(project_id=project.id, name="met", key_prefix=prefix,
                       key_hash=digest, scopes=["*"], created_at=utcnow()))
    session.commit()
    headers = {"Authorization": f"Bearer {raw}"}

    m = _metrics(client, headers)
    assert m["decisions_by_outcome"] == {}
    assert m["executions_total"] == 0
    assert m["active_approvals"] == 0
    assert m["incidents_by_status"] == {}
    assert m["project_id"] == str(project.id)


def test_metrics_requires_auth():
    app = create_app()
    with TestClient(app) as c:
        resp = c.get("/api/v1/metrics")
    assert resp.status_code in (401, 403), resp.text
