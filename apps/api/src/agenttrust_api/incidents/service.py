"""Incident domain logic (M11), separated from HTTP transport.

State machine: OPEN -> INVESTIGATING -> RESOLVED | DISMISSED, plus an
audited reopen RESOLVED -> INVESTIGATING. Every transition records a
durable event. Analysis reports are stored on the incident; the report
itself is produced by ``incidents/investigator.py``.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..deps import AppError
from ..events import record_event
from ..models import Event, Incident, IncidentEvidence
from ..util import utcnow

# Allowed status transitions (reopening a resolved incident is audited).
_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"INVESTIGATING", "RESOLVED", "DISMISSED"},
    "INVESTIGATING": {"RESOLVED", "DISMISSED"},
    "RESOLVED": {"INVESTIGATING"},
    "DISMISSED": set(),
}


def scoped_incident(db: Session, incident_id: UUID, project_id: UUID) -> Incident:
    """Load an incident scoped to the project. 404 leaks nothing."""
    incident = db.get(Incident, incident_id)
    if incident is None or incident.project_id != project_id:
        raise AppError("incident_not_found", "Incident not found.", 404)
    return incident


def list_incidents(
    db: Session,
    *,
    project_id: UUID,
    status: str | None,
    severity: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Incident], int]:
    """Project-scoped incident list, newest first."""
    query = db.query(Incident).filter(Incident.project_id == project_id)
    if status is not None:
        query = query.filter(Incident.status == status.upper())
    if severity is not None:
        query = query.filter(Incident.severity == severity.lower())
    total = query.count()
    rows = (
        query.order_by(desc(Incident.opened_at)).limit(limit).offset(offset).all()
    )
    return rows, total


def evidence_events(db: Session, incident: Incident) -> list[Event]:
    """The incident's evidence events in project_seq order."""
    return (
        db.query(Event)
        .join(IncidentEvidence, IncidentEvidence.event_id == Event.event_id)
        .filter(IncidentEvidence.incident_id == incident.id)
        .order_by(Event.project_seq.asc())
        .all()
    )


def transition_status(
    db: Session, *, incident: Incident, new_status: str
) -> Incident:
    """Move an incident through the state machine. Commits; raises on misuse.

    Phase 8 audit LOW-4: the row is re-read with FOR UPDATE so two
    concurrent reviewers cannot silently overwrite each other's transition
    (lost update). The event log records every transition for audit.
    """
    want = new_status.upper()
    locked = (
        db.query(Incident)
        .filter(Incident.id == incident.id)
        .with_for_update()
        .one_or_none()
    )
    if locked is None:
        raise AppError("incident_not_found", "Incident not found.", 404)
    allowed = _TRANSITIONS.get(locked.status, set())
    if want not in allowed:
        raise AppError(
            "incident_transition_invalid",
            f"Cannot move incident from {locked.status} to {want}.",
            409,
        )
    from_status = locked.status
    locked.status = want
    if want in ("RESOLVED", "DISMISSED"):
        locked.resolved_at = utcnow()
    else:
        locked.resolved_at = None
    record_event(
        db,
        project_id=locked.project_id,
        run_id=None,
        kind="incident.status_changed",
        payload_redacted={
            "incident_id": str(locked.id),
            "from_status": from_status,
            "to_status": want,
        },
    )
    db.commit()
    return locked


def store_analysis(
    db: Session,
    *,
    incident: Incident,
    report: dict[str, Any],
    analyzer_kind: str,
) -> Incident:
    """Persist an investigation report on the incident. Commits."""
    incident.analysis_json = report
    incident.analyzer_kind = analyzer_kind
    if incident.status == "OPEN":
        incident.status = "INVESTIGATING"
    record_event(
        db,
        project_id=incident.project_id,
        run_id=None,
        kind="incident.analyzed",
        payload_redacted={
            "incident_id": str(incident.id),
            "analyzer_kind": analyzer_kind,
            "classification": report.get("classification"),
        },
    )
    db.commit()
    return incident
