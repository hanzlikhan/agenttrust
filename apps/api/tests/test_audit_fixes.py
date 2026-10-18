"""Regression tests for Phase 8 independent audit findings.

HIGH-1: evaluation runs are tenant-isolated by project_id.
HIGH-2: the HTTP benchmark path performs no destructive DDL.
MEDIUM-3: incident analyze requires the incidents:read scope (and rate limit).
MEDIUM-4: telemetry ingest scrubs secrets and caps payload size.
MEDIUM-5: key issuance defaults to least-privilege (no scopes).
"""

import uuid
from unittest import mock

from agenttrust_api import models
from agenttrust_api.evaluation import service as eval_service


def _issue_key(client, admin_headers, project_id, scopes):
    resp = client.post(
        "/api/v1/keys",
        json={"project_id": str(project_id), "name": f"k-{uuid.uuid4().hex[:6]}", "scopes": scopes},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['api_key']}"}


def _second_project(db_session):
    session, _ = db_session
    owner = models.User(username=f"owner2-{uuid.uuid4().hex[:8]}")
    session.add(owner)
    session.flush()
    project = models.Project(name="second", owner_id=owner.id)
    session.add(project)
    session.flush()
    session.add(models.Membership(user_id=owner.id, project_id=project.id, role="owner"))
    session.flush()
    return project


def _seed_eval_run(db_session, project_id):
    """Insert a completed evaluation run owned by project_id."""
    session, _ = db_session
    run = models.EvaluationRun(
        project_id=project_id,
        suite_id="refund-policy-v1",
        dataset_version="1.0",
        code_version="test",
        status="COMPLETE",
    )
    session.add(run)
    session.flush()
    return run


# ---------------------------------------------------------------------------
# HIGH-1: cross-project evaluation isolation
# ---------------------------------------------------------------------------


def test_eval_runs_are_project_scoped(db_session, client, admin_headers):
    session, project_a = db_session
    project_b = _second_project(db_session)
    run_a = _seed_eval_run(db_session, project_a.id)
    _seed_eval_run(db_session, project_b.id)
    session.commit()

    headers_b = _issue_key(client, admin_headers, project_b.id, ["evaluations:read"])

    # Project B lists only its own run.
    resp = client.get("/api/v1/evaluations/runs", headers=headers_b)
    assert resp.status_code == 200, resp.text
    ids = [r["run_id"] for r in resp.json()["runs"]]
    assert str(run_a.id) not in ids
    assert len(ids) == 1

    # Project B cannot fetch A's run detail or report.
    resp = client.get(f"/api/v1/evaluations/runs/{run_a.id}", headers=headers_b)
    assert resp.status_code == 404
    resp = client.get(f"/api/v1/evaluations/runs/{run_a.id}/report", headers=headers_b)
    assert resp.status_code == 404

    # Project A sees its own run.
    headers_a = _issue_key(client, admin_headers, project_a.id, ["evaluations:read"])
    resp = client.get(f"/api/v1/evaluations/runs/{run_a.id}", headers=headers_a)
    assert resp.status_code == 200, resp.text


def test_eval_run_requires_evaluations_read_scope(db_session, client, admin_headers):
    session, project = db_session
    _seed_eval_run(db_session, project.id)
    session.commit()
    # Key with no scopes cannot list runs.
    headers = _issue_key(client, admin_headers, project.id, [])
    resp = client.get("/api/v1/evaluations/runs", headers=headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# HIGH-2: no destructive DDL on the HTTP benchmark path
# ---------------------------------------------------------------------------


def test_http_benchmark_uses_nondestructive_prepare():
    with mock.patch.object(
        eval_service, "create_isolated_db"
    ) as mock_create, mock.patch.object(
        eval_service, "prepare_eval_db_shared", return_value="postgresql://fake/eval"
    ) as mock_prepare:
        # We only assert routing here; the real prepare is exercised in the
        # smoke test below. Patch _run_benchmark_inner to avoid a full run.
        with mock.patch.object(
            eval_service, "_run_benchmark_inner", return_value={"run_id": "x"}
        ):
            eval_service.run_benchmark(
                main_db_url="postgresql://u:p@localhost:5432/main",
                eval_db_name="agenttrust_eval_http",
                destructive=False,
            )
        mock_create.assert_not_called()
        mock_prepare.assert_called_once()


def test_http_benchmark_end_to_end_nondestructive(migrated_db_url):
    """The nondestructive path truncates and re-seeds without DROP DATABASE."""
    # Create a project via a committed connection (visible to the benchmark's
    # own engine, unlike the transactional db_session fixture).
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(migrated_db_url)
    Session = sessionmaker(bind=engine)
    s = Session()
    owner = models.User(username=f"harness-{uuid.uuid4().hex[:8]}")
    s.add(owner)
    s.flush()
    project = models.Project(name="harness", owner_id=owner.id)
    s.add(project)
    s.commit()
    project_id = project.id
    s.close()

    try:
        report = eval_service.run_benchmark(
            main_db_url=migrated_db_url,
            eval_db_name="agenttrust_eval_http_test",
            case_keys=["allow-001"],
            out_path=None,
            project_id=project_id,
            destructive=False,
        )
        assert report["metrics"]["total"] == 1
        assert report["metrics"]["passed"] == 1
        # The run is owned by the caller's project.
        s = Session()
        run = s.get(models.EvaluationRun, uuid.UUID(report["run_id"]))
        assert run.project_id == project_id
        s.close()
    finally:
        # Clean up the harness project (cascades to the eval run).
        s = Session()
        s.query(models.Project).filter(models.Project.id == project_id).delete()
        s.commit()
        s.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# MEDIUM-3: analyze endpoint requires scope
# ---------------------------------------------------------------------------


def test_analyze_requires_incidents_read_scope(
    db_session, client, admin_headers, key_headers, run_id, policy_stack
):
    from .helpers import REFUND_ARGS, authorize, execute

    session, project = db_session
    # Create an incident via tamper.
    resp = authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, "med3-a")
    call_id = resp.json()["tool_call_id"]
    tampered = dict(REFUND_ARGS, amount_minor=REFUND_ARGS["amount_minor"] + 5000)
    execute(client, key_headers, call_id, tampered)
    incident = session.query(models.Incident).first()
    assert incident is not None

    # Key with only agent:run cannot analyze.
    weak = _issue_key(client, admin_headers, project.id, ["agent:run"])
    resp = client.post(f"/api/v1/incidents/{incident.id}/analyze", headers=weak)
    assert resp.status_code == 403, resp.text

    # Key with incidents:read can (template fallback, no Ollama here).
    strong = _issue_key(client, admin_headers, project.id, ["incidents:read"])
    resp = client.post(f"/api/v1/incidents/{incident.id}/analyze", headers=strong)
    assert resp.status_code == 200, resp.text
    assert resp.json()["report"]["analyzer_kind"] == "template"


# ---------------------------------------------------------------------------
# MEDIUM-4: telemetry ingest scrubs secrets and caps size
# ---------------------------------------------------------------------------


def test_telemetry_ingest_scrubs_secrets(db_session, client, key_headers, run_id):
    headers, _raw = key_headers
    resp = client.post(
        f"/api/v1/runs/{run_id}/events",
        json={
            "events": [
                {
                    "kind": "agent.thinking",
                    "payload": {
                        "api_key": "sk-live-should-be-redacted",
                        "nested": {"password": "hunter2"},
                        "token_value": "at_abc123",
                        "innocent": "hello",
                    },
                }
            ]
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    session, _ = db_session
    event = session.query(models.Event).filter(models.Event.kind == "agent.thinking").one()
    payload = event.payload_redacted
    assert payload["api_key"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"
    assert payload["token_value"] == "[REDACTED]"
    assert payload["innocent"] == "hello"


def test_telemetry_ingest_rejects_oversize_payload(db_session, client, key_headers, run_id):
    headers, _raw = key_headers
    big = "x" * 40000
    resp = client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"events": [{"kind": "agent.thinking", "payload": {"blob": big}}]},
        headers=headers,
    )
    assert resp.status_code == 413, resp.text


# ---------------------------------------------------------------------------
# MEDIUM-5: key issuance defaults to no scopes
# ---------------------------------------------------------------------------


def test_key_issuance_defaults_to_no_scopes(client, admin_headers, project_id):
    resp = client.post(
        "/api/v1/keys",
        json={"project_id": str(project_id), "name": "least-priv"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["scopes"] == []
