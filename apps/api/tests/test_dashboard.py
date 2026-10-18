"""Dashboard read endpoints (M09): summary counters, paginated/filterable
run list, and run detail with its event timeline.

Fixtures commit a real stack via SessionLocal so the rows are visible to
every session, mirroring production reads.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from agenttrust_api.db import SessionLocal
from agenttrust_api.events import record_event
from agenttrust_api.main import create_app
from agenttrust_api.models import Agent, AgentRun, ApiKey, Project, User
from agenttrust_api.security import generate_api_key
from agenttrust_api.util import utcnow


@pytest.fixture()
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def stack():
    """Committed project + key + 3 runs (2 RUNNING, 1 COMPLETED) + events."""
    suffix = uuid.uuid4().hex[:8]
    session = SessionLocal()
    try:
        user = User(username=f"dash-{suffix}")
        session.add(user)
        session.flush()
        project = Project(name=f"dash-{suffix}", owner_id=user.id)
        session.add(project)
        session.flush()
        raw, prefix, digest = generate_api_key()
        session.add(
            ApiKey(project_id=project.id, name="dash", key_prefix=prefix,
                   key_hash=digest, scopes=["*"])
        )
        agent = Agent(project_id=project.id, name="dash-agent", version="1.0.0")
        session.add(agent)
        session.flush()
        run_ids = []
        for state in ["RUNNING", "RUNNING", "COMPLETED"]:
            run = AgentRun(
                project_id=project.id,
                agent_id=agent.id,
                state=state,
                started_at=utcnow(),
                ended_at=utcnow() if state == "COMPLETED" else None,
            )
            session.add(run)
            session.flush()
            run_ids.append(run.id)
        # Events on the first run, out of insertion order is impossible here;
        # project_seq assignment is what the detail endpoint sorts by.
        for kind in ["run.started", "tool.requested", "policy.allowed"]:
            record_event(
                session, project_id=project.id, run_id=run_ids[0],
                kind=kind, payload_redacted={},
            )
        session.commit()
        yield {"api_key": raw, "project_id": project.id, "run_ids": run_ids}
    finally:
        session.query(AgentRun).filter(AgentRun.project_id == project.id).delete()
        session.query(Agent).filter(Agent.project_id == project.id).delete()
        session.query(ApiKey).filter(ApiKey.project_id == project.id).delete()
        session.query(Project).filter(Project.id == project.id).delete()
        session.query(User).filter(User.username == f"dash-{suffix}").delete()
        session.commit()
        session.close()


def _auth(stack):
    return {"Authorization": f"Bearer {stack['api_key']}"}


def test_summary_counts_come_from_committed_rows(client, stack):
    resp = client.get("/api/v1/dashboard/summary", headers=_auth(stack))
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == str(stack["project_id"])
    assert body["runs_total"] == 3
    assert body["runs_by_state"] == {"RUNNING": 2, "COMPLETED": 1}
    assert body["events_total"] == 3
    # No decisions/executions seeded: counters are honestly zero, not fake.
    assert body["decisions_total"] == 0
    assert body["executions_total"] == 0


def test_runs_pagination_and_filters(client, stack):
    headers = _auth(stack)

    page1 = client.get("/api/v1/dashboard/runs?limit=2&offset=0", headers=headers).json()
    assert page1["total"] == 3
    assert len(page1["runs"]) == 2
    assert page1["limit"] == 2 and page1["offset"] == 0

    page2 = client.get("/api/v1/dashboard/runs?limit=2&offset=2", headers=headers).json()
    assert len(page2["runs"]) == 1

    completed = client.get("/api/v1/dashboard/runs?status=COMPLETED", headers=headers).json()
    assert completed["total"] == 1
    assert completed["runs"][0]["state"] == "COMPLETED"

    by_agent = client.get("/api/v1/dashboard/runs?agent_name=dash-agent", headers=headers).json()
    assert by_agent["total"] == 3

    missing = client.get("/api/v1/dashboard/runs?agent_name=nope", headers=headers).json()
    assert missing["total"] == 0 and missing["runs"] == []


def test_run_detail_includes_ordered_events(client, stack):
    run_id = stack["run_ids"][0]
    resp = client.get(f"/api/v1/dashboard/runs/{run_id}", headers=_auth(stack))
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == str(run_id)
    assert body["agent_name"] == "dash-agent"
    seqs = [e["project_seq"] for e in body["events"]]
    assert seqs == sorted(seqs), "events are not in project_seq order"
    assert [e["kind"] for e in body["events"]] == [
        "run.started",
        "tool.requested",
        "policy.allowed",
    ]


def test_run_detail_is_project_scoped(client, stack):
    # A random UUID: 404, and no hint about other projects' runs.
    resp = client.get(f"/api/v1/dashboard/runs/{uuid.uuid4()}", headers=_auth(stack))
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "run_not_found"


def test_dashboard_requires_auth(client, stack):
    assert client.get("/api/v1/dashboard/summary").status_code == 401
    assert client.get("/api/v1/dashboard/runs").status_code == 401


def test_ingest_endpoint_validates_input(client, stack):
    run_id = stack["run_ids"][0]
    headers = _auth(stack)

    ok = client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"events": [{"kind": "agent.note", "payload": {"a": 1}}]},
        headers=headers,
    )
    assert ok.status_code == 201
    assert ok.json()["accepted"] == 1

    bad_kind = client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"events": [{"kind": "Bad Kind!", "payload": {}}]},
        headers=headers,
    )
    assert bad_kind.status_code == 422

    too_many = client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"events": [{"kind": "x", "payload": {}} for _ in range(101)]},
        headers=headers,
    )
    assert too_many.status_code == 422

    foreign = client.post(
        f"/api/v1/runs/{uuid.uuid4()}/events",
        json={"events": [{"kind": "x", "payload": {}}]},
        headers=headers,
    )
    assert foreign.status_code == 404


def test_runs_date_range_and_order_filters(client, stack):
    """started_after/started_before filter by run start; order toggles sort."""
    headers = _auth(stack)
    past = "2000-01-01T00:00:00Z"
    future = "2999-01-01T00:00:00Z"

    inside = client.get(
        f"/api/v1/dashboard/runs?started_after={past}&started_before={future}",
        headers=headers,
    ).json()
    assert inside["total"] == 3

    before_past = client.get(
        f"/api/v1/dashboard/runs?started_before={past}", headers=headers
    ).json()
    assert before_past["total"] == 0 and before_past["runs"] == []

    after_future = client.get(
        f"/api/v1/dashboard/runs?started_after={future}", headers=headers
    ).json()
    assert after_future["total"] == 0 and after_future["runs"] == []

    bad_date = client.get(
        "/api/v1/dashboard/runs?started_after=not-a-date", headers=headers
    )
    assert bad_date.status_code == 422

    asc = client.get("/api/v1/dashboard/runs?order=asc&limit=3", headers=headers).json()
    desc = client.get(
        "/api/v1/dashboard/runs?order=desc&limit=3", headers=headers
    ).json()
    assert [r["run_id"] for r in asc["runs"]] == [
        r["run_id"] for r in reversed(desc["runs"])
    ]

    bad_order = client.get("/api/v1/dashboard/runs?order=sideways", headers=headers)
    assert bad_order.status_code == 422
