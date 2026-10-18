"""Built-in service metrics (M17, Phase 8).

A lightweight Prometheus-style operational endpoint: counts derived only
from committed rows for the caller's project. Human-readable JSON (not
Prometheus text exposition) so the dashboard and scripts can consume it
without a parser.

Project-scoped to the caller's API key, like every other read endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_admin, require_api_key
from ..events import prune_old_events
from ..models import ApiKey, Approval, Incident, PolicyDecision, ToolCall, ToolExecution
from ..schemas import MetricsResponse
from ..util import utcnow

router = APIRouter(tags=["metrics"])


@router.post("/admin/maintenance/prune-events")
def prune_events(
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
) -> dict:
    """Delete events older than the retention window (Phase 8 audit MEDIUM-5).

    Admin-gated maintenance: enforces AGENTTRUST_EVENT_RETENTION_DAYS so
    the events/outbox tables do not grow unboundedly.
    """
    deleted = prune_old_events(db, retention_days=settings.AGENTTRUST_EVENT_RETENTION_DAYS)
    db.commit()
    return {
        "deleted_events": deleted,
        "retention_days": settings.AGENTTRUST_EVENT_RETENTION_DAYS,
        "pruned_at": utcnow().isoformat(),
    }


@router.get("/metrics", response_model=MetricsResponse)
def service_metrics(
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> MetricsResponse:
    """Operational counters for the caller's project (never fabricated)."""
    pid = key.project_id

    decision_rows = (
        db.query(PolicyDecision.outcome, func.count(PolicyDecision.id))
        .join(ToolCall, PolicyDecision.tool_call_id == ToolCall.id)
        .filter(ToolCall.project_id == pid)
        .group_by(PolicyDecision.outcome)
        .all()
    )
    decisions_by_outcome = {row[0]: row[1] for row in decision_rows}

    executions_total = (
        db.query(func.count(ToolExecution.id))
        .join(ToolCall, ToolExecution.call_id == ToolCall.id)
        .filter(ToolCall.project_id == pid)
        .scalar()
        or 0
    )

    active_approvals = (
        db.query(func.count(Approval.id))
        .join(ToolCall, Approval.tool_call_id == ToolCall.id)
        .filter(ToolCall.project_id == pid, Approval.state == "PENDING")
        .scalar()
        or 0
    )

    incident_rows = (
        db.query(Incident.status, func.count(Incident.id))
        .filter(Incident.project_id == pid)
        .group_by(Incident.status)
        .all()
    )
    incidents_by_status = {row[0]: row[1] for row in incident_rows}

    return MetricsResponse(
        project_id=pid,
        decisions_by_outcome=decisions_by_outcome,
        executions_total=executions_total,
        active_approvals=active_approvals,
        incidents_by_status=incidents_by_status,
        generated_at=utcnow(),
    )
