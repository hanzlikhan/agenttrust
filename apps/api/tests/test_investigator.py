"""LangGraph investigator tests (M11) against real PostgreSQL.

No Ollama runs in this environment, so the fallback path is what gets
exercised: template report, schema-valid, evidence refs real. The
validator and the no-tool-bindings structural guarantee are tested
directly.
"""

import uuid

from agenttrust_api.incidents import investigator
from agenttrust_api.incidents.investigator import (
    build_investigation_graph,
    run_investigation,
    validate_report,
)
from agenttrust_api.models import Incident

from .helpers import REFUND_ARGS, authorize, execute


def _tamper_incident(client, key_headers, run_id, idem):
    resp = authorize(client, key_headers, run_id, "refund_payment", REFUND_ARGS, idem)
    assert resp.status_code == 201, resp.text
    call_id = resp.json()["tool_call_id"]
    tampered = dict(REFUND_ARGS, amount_minor=REFUND_ARGS["amount_minor"] + 5000)
    exec_resp = execute(client, key_headers, call_id, tampered)
    assert exec_resp.status_code == 409
    return uuid.UUID(exec_resp.json().get("tool_call_id", call_id))


def test_fallback_produces_schema_valid_template_report(
    db_session, client, key_headers, run_id, policy_stack
):
    # No Ollama is reachable here; the analyzer must fall back to the
    # deterministic template and still produce a valid, stored report.
    _tamper_incident(client, key_headers, run_id, "inv-t1")
    session, _ = db_session
    incident = session.query(Incident).filter_by(category="authorization_tamper").one()

    report, analyzer_kind = run_investigation(
        session, incident_id=incident.id, project_id=incident.project_id
    )
    assert analyzer_kind == "template"
    assert report["classification"] == "Authorization tampering attempt"
    assert report["uncertainty"]  # facts-vs-hypotheses labeling required
    assert report["recommended_checks"]
    for cause in report["possible_causes"]:
        assert cause["confidence"] in ("low", "medium", "high")
        assert cause["evidence_refs"]

    # The report is stored on the incident with the analyzer kind.
    session.refresh(incident)
    assert incident.analysis_json["classification"] == report["classification"]
    assert incident.analyzer_kind == "template"
    assert incident.status == "INVESTIGATING"


def test_fallback_cites_only_real_evidence(
    db_session, client, key_headers, run_id, policy_stack
):
    _tamper_incident(client, key_headers, run_id, "inv-t2")
    session, _ = db_session
    incident = session.query(Incident).filter_by(category="authorization_tamper").one()

    report, _ = run_investigation(
        session, incident_id=incident.id, project_id=incident.project_id
    )
    from agenttrust_api.incidents.service import evidence_events

    real_refs = {e.event_id for e in evidence_events(session, incident)}
    assert real_refs, "incident must have evidence"
    cited = set(report["evidence_refs"])
    for cause in report["possible_causes"]:
        cited.update(cause["evidence_refs"])
    assert cited <= real_refs, "report cites evidence it was not given"


def test_analyze_endpoint_labels_deterministic_report(
    db_session, client, key_headers, run_id, policy_stack
):
    _tamper_incident(client, key_headers, run_id, "inv-t3")
    headers, _raw = key_headers
    session, _ = db_session
    incident = session.query(Incident).filter_by(category="authorization_tamper").one()

    resp = client.post(f"/api/v1/incidents/{incident.id}/analyze", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["report"]["analyzer_kind"] == "template"
    assert body["report"]["uncertainty"]
    assert body["report"]["recommended_checks"]


def test_validator_rejects_fabricated_evidence_ref():
    report = investigator._template_analyze(
        evidence=[], evidence_refs=["evt-real-1"], category="grant_replay",
        reason_code=None,
    )
    assert validate_report(report, known_evidence_refs={"evt-real-1"}) == []
    report["evidence_refs"].append("evt-invented-9")
    errors = validate_report(report, known_evidence_refs={"evt-real-1"})
    assert any("unknown" in e for e in errors)


def test_validator_rejects_missing_uncertainty():
    report = investigator._template_analyze(
        evidence=[], evidence_refs=["evt-real-1"], category="grant_replay",
        reason_code=None,
    )
    report["uncertainty"] = ""
    errors = validate_report(report, known_evidence_refs={"evt-real-1"})
    assert errors, "empty uncertainty must fail schema validation"


def test_validator_rejects_forbidden_action_claims():
    report = investigator._template_analyze(
        evidence=[], evidence_refs=["evt-real-1"], category="grant_replay",
        reason_code=None,
    )
    report["summary"] += " The policy was updated to prevent recurrence."
    errors = validate_report(report, known_evidence_refs={"evt-real-1"})
    assert any("forbidden" in e for e in errors)

    report2 = investigator._template_analyze(
        evidence=[], evidence_refs=["evt-real-1"], category="grant_replay",
        reason_code=None,
    )
    report2["possible_causes"][0]["cause"] += " I approved the retry."
    errors2 = validate_report(report2, known_evidence_refs={"evt-real-1"})
    assert any("forbidden" in e for e in errors2)


def test_analyzer_binds_no_tools(db_session, client, key_headers, run_id, policy_stack):
    """Structural guarantee: the investigation graph has exactly three
    pure nodes. No tool-calling node can approve, execute, or change policy."""
    session, _ = db_session
    compiled = build_investigation_graph(
        session, incident_id=uuid.uuid4(), project_id=uuid.uuid4()
    )
    assert set(compiled.nodes) == {
        "__start__",
        "collect_evidence",
        "analyze",
        "validate",
    }
