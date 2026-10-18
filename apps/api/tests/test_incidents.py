"""Incident detector tests (M11) against real PostgreSQL.

Covers discrete triggers in the request path, dedup, the on-demand scan,
the state machine, and cross-project scoping of the incidents API.
"""

import uuid

from agenttrust_api.models import Event, Incident, IncidentEvidence

from .helpers import REFUND_ARGS, authorize, execute, order_balance


def _incidents(db_session, **filters):
    session, _ = db_session
    return session.query(Incident).filter_by(**filters).all()


def _tamper(client, key_headers, run_id, idem):
    """Authorize a clean call, then execute with mutated arguments."""
    resp = authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, idem)
    assert resp.status_code == 201, resp.text
    call_id = resp.json()["tool_call_id"]
    tampered = dict(REFUND_ARGS, amount_minor=REFUND_ARGS["amount_minor"] + 5000)
    exec_resp = execute(client, key_headers, call_id, tampered)
    return exec_resp, call_id


def test_tamper_triggers_high_incident(
    db_session, client, key_headers, run_id, policy_stack
):
    before = order_balance(db_session, "ORD-100")
    exec_resp, call_id = _tamper(client, key_headers, run_id, "inc-t1")
    assert exec_resp.status_code == 409, exec_resp.text
    assert exec_resp.json()["error_code"] == "arguments_tampered"

    incidents = _incidents(db_session, category="authorization_tamper")
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.severity == "high"
    assert incident.status == "OPEN"
    assert incident.tool_call_id == uuid.UUID(call_id)

    session, _ = db_session
    evidence = (
        session.query(IncidentEvidence)
        .filter(IncidentEvidence.incident_id == incident.id)
        .all()
    )
    assert len(evidence) == 1
    event = session.query(Event).filter(Event.event_id == evidence[0].event_id).one()
    assert event.kind == "tool.execute_rejected"

    created = session.query(Event).filter(Event.kind == "incident.created").all()
    assert len(created) == 1
    assert created[0].payload_redacted["incident_id"] == str(incident.id)
    # The tampered call provably never executed.
    assert order_balance(db_session, "ORD-100") == before


def test_tamper_dedup_no_duplicate_incident(
    db_session, client, key_headers, run_id, policy_stack
):
    exec_resp, call_id = _tamper(client, key_headers, run_id, "inc-t2")
    assert exec_resp.status_code == 409
    # A second tamper rejection on the same call reuses the OPEN incident.
    exec_resp2 = execute(
        client, key_headers, call_id, dict(REFUND_ARGS, amount_minor=9999)
    )
    assert exec_resp2.status_code == 409
    assert len(_incidents(db_session, category="authorization_tamper")) == 1


def test_amount_overflow_triggers_medium_incident(
    db_session, client, key_headers, run_id, policy_stack
):
    # 200000 > 2x review_max (50000) -> incident.
    resp = authorize(
        client,
        key_headers,
        run_id,
        "refund_payment",
        dict(REFUND_ARGS, amount_minor=200000),
        "inc-a1",
    )
    assert resp.status_code == 201
    assert resp.json()["reason_code"] == "AMOUNT_EXCEEDS_MAX"
    incidents = _incidents(db_session, category="amount_overflow")
    assert len(incidents) == 1
    assert incidents[0].severity == "medium"

    # 60000 is over the cap but within 2x review_max -> no incident.
    resp = authorize(
        client,
        key_headers,
        run_id,
        "refund_payment",
        dict(REFUND_ARGS, amount_minor=60000),
        "inc-a2",
    )
    assert resp.status_code == 201
    assert resp.json()["reason_code"] == "AMOUNT_EXCEEDS_MAX"
    assert len(_incidents(db_session, category="amount_overflow")) == 1


def test_scan_finds_repeated_denials(
    db_session, client, key_headers, run_id, policy_stack
):
    headers, _raw = key_headers
    for i in range(5):
        resp = authorize(
            client,
            key_headers,
            run_id,
            "refund_payment",
            dict(REFUND_ARGS, amount_minor=60000),
            f"inc-s{i}",
        )
        assert resp.status_code == 201

    resp = client.post("/api/v1/incidents/scan", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["incidents_created"] == 1
    incidents = _incidents(db_session, category="repeated_denials")
    assert len(incidents) == 1
    assert incidents[0].severity == "medium"

    # A second scan with no new denials must not open a duplicate.
    resp = client.post("/api/v1/incidents/scan", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["incidents_created"] == 0


def test_scan_finds_tamper_pattern(
    db_session, client, key_headers, run_id, policy_stack
):
    for i in range(3):
        exec_resp, _ = _tamper(client, key_headers, run_id, f"inc-p{i}")
        assert exec_resp.status_code == 409
    headers, _raw = key_headers
    resp = client.post("/api/v1/incidents/scan", headers=headers)
    assert resp.status_code == 200, resp.text
    incidents = _incidents(db_session, category="tamper_pattern")
    assert len(incidents) == 1
    assert incidents[0].severity == "high"


def test_incidents_api_lists_and_details(
    db_session, client, key_headers, run_id, policy_stack
):
    _tamper(client, key_headers, run_id, "inc-l1")
    headers, _raw = key_headers

    resp = client.get("/api/v1/incidents", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    item = body["incidents"][0]
    assert item["category"] == "authorization_tamper"
    assert item["evidence_count"] == 1

    resp = client.get("/api/v1/incidents?severity=low", headers=headers)
    assert resp.json()["total"] == 0

    incident_id = item["incident_id"]
    resp = client.get(f"/api/v1/incidents/{incident_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert len(detail["evidence"]) == 1
    assert detail["evidence"][0]["kind"] == "tool.execute_rejected"
    # Evidence events arrive in project_seq order.
    seqs = [e["project_seq"] for e in detail["evidence"]]
    assert seqs == sorted(seqs)


def test_incidents_api_cross_project_404(
    db_session, client, key_headers, run_id, policy_stack
):
    from agenttrust_api import models
    from agenttrust_api.security import generate_api_key
    from agenttrust_api.util import utcnow

    session, _ = db_session
    owner = models.User(username=f"owner-{uuid.uuid4().hex[:8]}")
    session.add(owner)
    session.flush()
    other = models.Project(name="other", owner_id=owner.id)
    session.add(other)
    session.flush()
    raw, prefix, digest = generate_api_key()
    session.add(
        models.ApiKey(
            project_id=other.id,
            name="other-key",
            key_prefix=prefix,
            key_hash=digest,
            scopes=["*"],
            created_at=utcnow(),
        )
    )
    session.flush()
    other_headers = {"Authorization": f"Bearer {raw}"}

    _tamper(client, key_headers, run_id, "inc-x1")
    incident_id = _incidents(db_session)[0].id

    resp = client.get(f"/api/v1/incidents/{incident_id}", headers=other_headers)
    assert resp.status_code == 404
    resp = client.get("/api/v1/incidents", headers=other_headers)
    assert resp.json()["total"] == 0
    # Analysis of another project's incident is also 404.
    resp = client.post(f"/api/v1/incidents/{incident_id}/analyze", headers=other_headers)
    assert resp.status_code == 404


def test_status_transitions(db_session, client, key_headers, run_id, policy_stack):
    _tamper(client, key_headers, run_id, "inc-q1")
    headers, _raw = key_headers
    incident_id = _incidents(db_session)[0].id

    resp = client.patch(
        f"/api/v1/incidents/{incident_id}", json={"status": "investigating"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "INVESTIGATING"

    resp = client.patch(
        f"/api/v1/incidents/{incident_id}", json={"status": "resolved"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "RESOLVED"
    assert resp.json()["resolved_at"] is not None

    # Terminal states cannot be dismissed out of; reopening to
    # INVESTIGATING is the audited path back.
    resp = client.patch(
        f"/api/v1/incidents/{incident_id}", json={"status": "dismissed"}, headers=headers
    )
    assert resp.status_code == 409
    resp = client.patch(
        f"/api/v1/incidents/{incident_id}", json={"status": "investigating"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "INVESTIGATING"
