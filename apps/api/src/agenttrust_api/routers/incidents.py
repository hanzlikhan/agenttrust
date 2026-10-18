"""Incident investigation HTTP layer (M11).

Thin transport over incidents/service.py (state machine) and
incidents/investigator.py (LangGraph analysis). Analysis runs
synchronously in-request: there is no background worker yet, so a busy
model call blocks the HTTP worker — the Ollama timeout
(AGENTTRUST_ANALYZE_TIMEOUT_SECONDS) bounds it, and the deterministic
template fallback keeps the endpoint usable with no model at all.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import (
    ApiKey,
    AppError,
    require_reviewer,
    require_scopes,
)
from ..incidents import detector as incident_detector
from ..incidents import investigator as investigator_module
from ..incidents.service import (
    evidence_events,
    list_incidents,
    scoped_incident,
    transition_status,
)
from ..models import IncidentEvidence
from ..schemas import (
    EventPublic,
    IncidentAnalysisPublic,
    IncidentAnalyzeResponse,
    IncidentCausePublic,
    IncidentDetailResponse,
    IncidentListItem,
    IncidentListResponse,
    IncidentScanResponse,
    IncidentStatusRequest,
    IncidentStatusResponse,
)
from ..util import utcnow

router = APIRouter(tags=["incidents"])

_list_auth = require_scopes("incidents:read", limit_per_minute=False)


def _analysis_public(incident) -> IncidentAnalysisPublic | None:
    if not incident.analysis_json:
        return None
    report = incident.analysis_json
    return IncidentAnalysisPublic(
        analyzer_kind=incident.analyzer_kind or "template",
        classification=report["classification"],
        summary=report["summary"],
        possible_causes=[
            IncidentCausePublic(
                cause=c["cause"],
                confidence=c["confidence"],
                evidence_refs=c["evidence_refs"],
            )
            for c in report["possible_causes"]
        ],
        evidence_refs=report["evidence_refs"],
        uncertainty=report["uncertainty"],
        recommended_checks=report["recommended_checks"],
        analyzed_at=report.get("analyzed_at") or incident.opened_at,
    )


def _detail(incident, db: Session) -> IncidentDetailResponse:
    events = evidence_events(db, incident)
    return IncidentDetailResponse(
        incident_id=incident.id,
        project_id=incident.project_id,
        category=incident.category,
        severity=incident.severity,
        status=incident.status,
        opened_at=incident.opened_at,
        resolved_at=incident.resolved_at,
        summary=incident.summary,
        tool_call_id=incident.tool_call_id,
        analysis=_analysis_public(incident),
        evidence=[
            EventPublic(
                event_id=e.event_id,
                kind=e.kind,
                project_seq=e.project_seq,
                run_id=e.run_id,
                received_at=e.received_at,
                payload=e.payload_redacted,
            )
            for e in events
        ],
    )


@router.get("/incidents", response_model=IncidentListResponse)
def list_incidents_route(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    key: ApiKey = Depends(_list_auth),
    db: Session = Depends(get_db),
) -> IncidentListResponse:
    rows, total = list_incidents(
        db,
        project_id=key.project_id,
        status=status,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    items = []
    for incident in rows:
        count = (
            db.query(IncidentEvidence)
            .filter(IncidentEvidence.incident_id == incident.id)
            .count()
        )
        items.append(
            IncidentListItem(
                incident_id=incident.id,
                category=incident.category,
                severity=incident.severity,
                status=incident.status,
                opened_at=incident.opened_at,
                resolved_at=incident.resolved_at,
                summary=incident.summary,
                evidence_count=count,
            )
        )
    return IncidentListResponse(
        incidents=items, total=total, limit=limit, offset=offset
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
def get_incident(
    incident_id: UUID,
    key: ApiKey = Depends(_list_auth),
    db: Session = Depends(get_db),
) -> IncidentDetailResponse:
    incident = scoped_incident(db, incident_id, key.project_id)
    return _detail(incident, db)


@router.post("/incidents/{incident_id}/analyze", response_model=IncidentAnalyzeResponse)
def analyze_incident(
    incident_id: UUID,
    # Scoped + rate-limited (Phase 8 audit MEDIUM-3): analysis runs the
    # LangGraph pipeline synchronously and can block a worker, so it is not
    # open to every project key.
    key: ApiKey = Depends(require_scopes("incidents:read")),
    db: Session = Depends(get_db),
) -> IncidentAnalyzeResponse:
    """Run the LangGraph investigation synchronously and store the report.

    Synchronous because no background worker exists yet; the Ollama call is
    bounded by AGENTTRUST_ANALYZE_TIMEOUT_SECONDS and the deterministic
    template fallback keeps this usable with no model installed.
    """
    report, analyzer_kind = investigator_module.run_investigation(
        db, incident_id=incident_id, project_id=key.project_id
    )
    report = dict(report)
    report.setdefault("analyzed_at", utcnow().isoformat())
    incident = scoped_incident(db, incident_id, key.project_id)
    analysis = _analysis_public(incident)
    if analysis is None:
        raise AppError(
            "analysis_missing",
            "Analysis completed but no report was stored.",
            502,
        )
    return IncidentAnalyzeResponse(incident_id=incident.id, report=analysis)


@router.post("/incidents/scan", response_model=IncidentScanResponse)
def scan_incidents(
    key: ApiKey = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> IncidentScanResponse:
    """Run pattern triggers over recent project history."""
    report = incident_detector.scan_project(db, project_id=key.project_id)
    return IncidentScanResponse(
        incidents_created=report["incidents_created"],
        checked=report["checked"],
    )


@router.patch("/incidents/{incident_id}", response_model=IncidentStatusResponse)
def update_incident_status(
    incident_id: UUID,
    body: IncidentStatusRequest,
    key: ApiKey = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> IncidentStatusResponse:
    incident = scoped_incident(db, incident_id, key.project_id)
    incident = transition_status(db, incident=incident, new_status=body.status)
    return IncidentStatusResponse(
        incident_id=incident.id,
        status=incident.status,
        resolved_at=incident.resolved_at,
    )
