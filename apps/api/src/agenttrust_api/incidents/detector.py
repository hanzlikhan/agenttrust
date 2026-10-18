"""Deterministic incident detector (M11 baseline).

The detector is *observability, never enforcement*: it opens incident
records from evidence the request path already produced. A detector
failure must never change an authorization outcome, so every entry point
is total — unexpected situations simply produce no incident.

Two trigger families:

1. Discrete triggers, evaluated synchronously in the request path
   (cheap single-row checks only):
   - ``authorization_tamper`` (high): gateway rejected ``arguments_tampered``.
   - ``grant_replay`` (medium): gateway hit the defensive consumed-grant
     path — a grant was presented after consumption with no execution row,
     which the transactional claim should have made impossible.
   - ``amount_overflow`` (medium): policy denied ``AMOUNT_EXCEEDS_MAX``
     with an amount more than twice the review threshold.
2. Pattern triggers, evaluated on demand by ``POST /incidents/scan``:
   - ``repeated_denials`` (medium): >=5 DENY decisions from one API key in
     10 minutes.
   - ``tamper_pattern`` (high): >=3 ``arguments_tampered`` rejections
     project-wide in 1 hour.

Dedup: discrete triggers open at most one OPEN incident per
(category, tool_call_id); scan triggers at most one OPEN incident per
(category, project). Every incident links the exact event_ids that fired
it as evidence.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..events import record_event
from ..models import Event, Incident, PolicyDecision, ToolCall
from ..util import utcnow

# Discrete trigger reasons coming out of the gateway's rejection paths.
REASON_ARGUMENTS_TAMPERED = "arguments_tampered"
REASON_GRANT_CONSUMED = "grant_consumed"

# Policy reason code that can escalate to an amount-overflow incident.
REASON_AMOUNT_EXCEEDS_MAX = "AMOUNT_EXCEEDS_MAX"

# Pattern-trigger windows and thresholds (spec M11 baseline).
REPEATED_DENIALS_COUNT = 5
REPEATED_DENIALS_WINDOW = timedelta(minutes=10)
TAMPER_PATTERN_COUNT = 3
TAMPER_PATTERN_WINDOW = timedelta(hours=1)

# Overflow multiplier: deny at >2x the review threshold counts as an
# anomalous attempt rather than an ordinary over-limit request.
OVERFLOW_MULTIPLIER = 2


def _open_discrete(
    db: Session,
    *,
    project_id: UUID,
    run_id: UUID | None,
    tool_call_id: UUID | None,
    category: str,
    severity: str,
    summary: str,
    evidence_event_ids: list[str],
) -> Incident | None:
    """Open a discrete-trigger incident unless one is already OPEN.

    The incident, its evidence links, and the ``incident.created`` event
    are flushed; the caller owns the commit.

    Dedup is enforced by the database (partial unique indexes from
    migration 0008, Phase 8 audit MEDIUM-1): the SELECT is a fast path,
    and an IntegrityError on the racing insert is caught and treated as
    "already open". A savepoint (LOW-8) guarantees the incident row and
    its ``incident.created`` event commit atomically — a failure in
    ``record_event`` rolls back the incident instead of leaving a
    partial row.
    """
    if tool_call_id is not None:
        existing = (
            db.query(Incident)
            .filter(
                Incident.project_id == project_id,
                Incident.category == category,
                Incident.tool_call_id == tool_call_id,
                Incident.status == "OPEN",
            )
            .first()
        )
        if existing is not None:
            return None
    try:
        with db.begin_nested():  # savepoint: incident + created event are atomic
            incident = Incident(
                project_id=project_id,
                tool_call_id=tool_call_id,
                category=category,
                severity=severity,
                status="OPEN",
                summary=summary,
                opened_at=utcnow(),
            )
            db.add(incident)
            db.flush()
            _link_evidence(db, incident.id, evidence_event_ids)
            record_event(
                db,
                project_id=project_id,
                run_id=run_id,
                kind="incident.created",
                payload_redacted={
                    "incident_id": str(incident.id),
                    "category": category,
                    "severity": severity,
                    "tool_call_id": str(tool_call_id) if tool_call_id else None,
                },
            )
            db.flush()
    except IntegrityError:
        # Lost the race with a concurrent insert: the dedup indexes
        # guarantee an OPEN incident already exists. The savepoint was
        # rolled back automatically; the caller's transaction is intact.
        return None
    return incident


def _link_evidence(db: Session, incident_id: UUID, event_ids: list[str]) -> None:
    """Link evidence events, skipping ids that do not exist.

    The FK to ``events`` would reject unknown ids; skipping keeps the
    detector total when an event row is unexpectedly absent.
    """
    from ..models import IncidentEvidence

    for event_id in dict.fromkeys(event_ids):  # de-duplicated, order-stable
        exists = db.query(Event).filter(Event.event_id == event_id).first()
        if exists is None:
            continue
        db.add(IncidentEvidence(incident_id=incident_id, event_id=event_id))
    db.flush()


def on_execute_rejected(
    db: Session,
    *,
    project_id: UUID,
    run_id: UUID | None,
    call_id: UUID,
    reason: str,
    rejected_event_id: str,
) -> Incident | None:
    """Evaluate gateway-rejection triggers. Total: never raises."""
    try:
        if reason == REASON_ARGUMENTS_TAMPERED:
            return _open_discrete(
                db,
                project_id=project_id,
                run_id=run_id,
                tool_call_id=call_id,
                category="authorization_tamper",
                severity="high",
                summary=(
                    "Gateway rejected execution: presented arguments differ "
                    "from the authorized canonical hash."
                ),
                evidence_event_ids=[rejected_event_id],
            )
        if reason == REASON_GRANT_CONSUMED:
            return _open_discrete(
                db,
                project_id=project_id,
                run_id=run_id,
                tool_call_id=call_id,
                category="grant_replay",
                severity="medium",
                summary=(
                    "A consumed execution grant was presented again with no "
                    "recorded execution; the transactional claim should have "
                    "made this impossible."
                ),
                evidence_event_ids=[rejected_event_id],
            )
        return None
    except Exception:
        # Observability must never break enforcement.
        return None


def on_policy_decision(
    db: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    call: ToolCall,
    reason_code: str,
    arguments: dict[str, Any],
    review_max_minor: int,
    policy_event_id: str,
) -> Incident | None:
    """Evaluate policy-decision triggers. Total: never raises."""
    try:
        if reason_code != REASON_AMOUNT_EXCEEDS_MAX:
            return None
        amount = arguments.get("amount_minor")
        if not isinstance(amount, int):
            return None
        if amount <= OVERFLOW_MULTIPLIER * review_max_minor:
            return None
        return _open_discrete(
            db,
            project_id=project_id,
            run_id=run_id,
            tool_call_id=call.id,
            category="amount_overflow",
            severity="medium",
            summary=(
                f"Refund of {amount} minor units denied: more than "
                f"{OVERFLOW_MULTIPLIER}x the review threshold "
                f"({review_max_minor})."
            ),
            evidence_event_ids=[policy_event_id],
        )
    except Exception:
        return None


def _open_scan(
    db: Session,
    *,
    project_id: UUID,
    category: str,
    severity: str,
    summary: str,
    evidence_event_ids: list[str],
) -> Incident | None:
    """Open a scan-trigger incident unless one is already OPEN for the project."""
    existing = (
        db.query(Incident)
        .filter(
            Incident.project_id == project_id,
            Incident.category == category,
            Incident.status == "OPEN",
        )
        .first()
    )
    if existing is not None:
        return None
    return _open_discrete(
        db,
        project_id=project_id,
        run_id=None,
        tool_call_id=None,
        category=category,
        severity=severity,
        summary=summary,
        evidence_event_ids=evidence_event_ids,
    )


def scan_project(db: Session, *, project_id: UUID) -> dict[str, Any]:
    """Run pattern triggers over recent history. Returns a scan report.

    Commits created incidents. Total: never raises.
    """
    report: dict[str, Any] = {
        "incidents_created": 0,
        "checked": {"deny_windows": 0, "tamper_windows": 0},
    }
    try:
        now = utcnow()
        # --- repeated denials: >=5 DENYs from one key in 10 minutes ---
        deny_start = now - REPEATED_DENIALS_WINDOW
        rows = (
            db.query(ToolCall.requester_key_id, func.count(ToolCall.id))
            .join(PolicyDecision, PolicyDecision.tool_call_id == ToolCall.id)
            .filter(
                ToolCall.project_id == project_id,
                ToolCall.requester_key_id.is_not(None),
                PolicyDecision.outcome == "DENY",
                PolicyDecision.decided_at >= deny_start,
            )
            .group_by(ToolCall.requester_key_id)
            .having(func.count(ToolCall.id) >= REPEATED_DENIALS_COUNT)
            .all()
        )
        report["checked"]["deny_windows"] = len(rows)
        for key_id, count in rows:
            evidence_ids = [
                event_id
                for (event_id,) in (
                    db.query(Event.event_id)
                    .join(
                        ToolCall,
                        # policy.denied payload carries tool_call_id as text;
                        # casting the UUID column yields the same hyphenated form.
                        Event.payload_redacted["tool_call_id"].astext
                        == ToolCall.id.cast(sa.Text),
                    )
                    .filter(
                        Event.project_id == project_id,
                        Event.kind == "policy.denied",
                        Event.received_at >= deny_start,
                        ToolCall.requester_key_id == key_id,
                    )
                    .order_by(Event.project_seq.desc())
                    .limit(25)
                    .all()
                )
            ]
            incident = _open_scan(
                db,
                project_id=project_id,
                category="repeated_denials",
                severity="medium",
                summary=(
                    f"{count} denied tool calls from one API key in the last "
                    "10 minutes."
                ),
                evidence_event_ids=evidence_ids,
            )
            if incident is not None:
                report["incidents_created"] += 1

        # --- tamper pattern: >=3 arguments_tampered rejections in 1 hour ---
        tamper_start = now - TAMPER_PATTERN_WINDOW
        tamper_events = (
            db.query(Event)
            .filter(
                Event.project_id == project_id,
                Event.kind == "tool.execute_rejected",
                Event.received_at >= tamper_start,
                Event.payload_redacted["reason"].astext == REASON_ARGUMENTS_TAMPERED,
            )
            .order_by(Event.project_seq.desc())
            .limit(25)
            .all()
        )
        report["checked"]["tamper_windows"] = len(tamper_events)
        if len(tamper_events) >= TAMPER_PATTERN_COUNT:
            incident = _open_scan(
                db,
                project_id=project_id,
                category="tamper_pattern",
                severity="high",
                summary=(
                    f"{len(tamper_events)} argument-tampering rejections in "
                    "the last hour."
                ),
                evidence_event_ids=[e.event_id for e in tamper_events],
            )
            if incident is not None:
                report["incidents_created"] += 1

        db.commit()
        return report
    except Exception:
        # Phase 8 audit LOW-9: the rollback discards the incidents, so the
        # report must not claim they were created.
        db.rollback()
        report["incidents_created"] = 0
        return report
