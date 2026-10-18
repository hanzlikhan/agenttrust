"""Dashboard read endpoints (M09): REST snapshots for the live UI.

All endpoints are project-scoped to the caller's API key and serve only
committed database rows. The browser pairs the initial snapshot with the
SSE stream (`/events/stream`) and applies deltas itself; these endpoints
never push.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AppError, require_api_key
from ..models import (
    Agent,
    AgentRun,
    ApiKey,
    Approval,
    Event,
    Outbox,
    PolicyDecision,
    ToolCall,
    ToolDefinition,
    ToolExecution,
)
from ..schemas import (
    AnalyticsDayItem,
    AnalyticsResponse,
    DashboardSummary,
    DeniedToolItem,
    EventPublic,
    PercentileStats,
    RunDetailResponse,
    RunListResponse,
    RunSummaryItem,
)
from ..util import utcnow

router = APIRouter(tags=["dashboard"])

_MAX_LIMIT = 100


def _limit(value: int) -> int:
    return max(1, min(value, _MAX_LIMIT))


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> DashboardSummary:
    """Counters derived only from committed rows (never fabricated)."""
    pid = key.project_id

    runs_total = db.query(func.count(AgentRun.id)).filter(AgentRun.project_id == pid).scalar() or 0
    runs_by_state = {
        row[0]: row[1]
        for row in db.query(AgentRun.state, func.count(AgentRun.id))
        .filter(AgentRun.project_id == pid)
        .group_by(AgentRun.state)
        .all()
    }
    tool_calls_total = (
        db.query(func.count(ToolCall.id)).filter(ToolCall.project_id == pid).scalar() or 0
    )
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
    events_total = (
        db.query(func.count(Event.event_id)).filter(Event.project_id == pid).scalar() or 0
    )
    outbox_pending = (
        db.query(func.count(Outbox.id))
        .join(Event, Outbox.event_id == Event.event_id)
        .filter(Event.project_id == pid, Outbox.published_at.is_(None))
        .scalar()
        or 0
    )
    return DashboardSummary(
        project_id=pid,
        runs_total=runs_total,
        runs_by_state=runs_by_state,
        tool_calls_total=tool_calls_total,
        decisions_total=sum(decisions_by_outcome.values()),
        decisions_by_outcome=decisions_by_outcome,
        executions_total=executions_total,
        events_total=events_total,
        outbox_pending=outbox_pending,
    )


@router.get("/dashboard/runs", response_model=RunListResponse)
def dashboard_runs(
    status: str | None = Query(default=None, max_length=32),
    agent_name: str | None = Query(default=None, max_length=128),
    started_after: datetime | None = Query(default=None),
    started_before: datetime | None = Query(default=None),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> RunListResponse:
    """Paginated, filterable run list — newest first (server-side)."""
    query = (
        db.query(AgentRun, Agent.name, Agent.version, func.count(ToolCall.id))
        .outerjoin(Agent, AgentRun.agent_id == Agent.id)
        .outerjoin(ToolCall, ToolCall.run_id == AgentRun.id)
        .filter(AgentRun.project_id == key.project_id)
        .group_by(AgentRun.id, Agent.name, Agent.version)
    )
    if status:
        query = query.filter(AgentRun.state == status)
    if agent_name:
        query = query.filter(Agent.name == agent_name)
    if started_after is not None:
        query = query.filter(AgentRun.started_at >= started_after)
    if started_before is not None:
        query = query.filter(AgentRun.started_at <= started_before)

    total = query.count()
    ordered = query.order_by(
        AgentRun.started_at.asc() if order == "asc" else AgentRun.started_at.desc()
    )
    rows = ordered.offset(offset).limit(_limit(limit)).all()
    return RunListResponse(
        runs=[
            RunSummaryItem(
                run_id=run.id,
                trace_id=run.trace_id,
                agent_name=name or "unknown",
                agent_version=version or "unknown",
                state=run.state,
                started_at=run.started_at,
                ended_at=run.ended_at,
                tool_call_count=count,
            )
            for run, name, version, count in rows
        ],
        total=total,
        limit=_limit(limit),
        offset=offset,
    )


@router.get("/dashboard/runs/{run_id}", response_model=RunDetailResponse)
def dashboard_run_detail(
    run_id: UUID,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> RunDetailResponse:
    """One run with its events in project_seq order — the SSE snapshot."""
    row = (
        db.query(AgentRun, Agent.name, Agent.version, func.count(ToolCall.id))
        .outerjoin(Agent, AgentRun.agent_id == Agent.id)
        .outerjoin(ToolCall, ToolCall.run_id == AgentRun.id)
        .filter(AgentRun.id == run_id, AgentRun.project_id == key.project_id)
        .group_by(AgentRun.id, Agent.name, Agent.version)
        .first()
    )
    if row is None:
        # 404 without leaking whether the run exists in another project.
        raise AppError("run_not_found", "Run not found.", 404)
    run, name, version, count = row
    events = (
        db.query(Event)
        .filter(Event.run_id == run.id, Event.project_id == key.project_id)
        .order_by(Event.project_seq.asc())
        .limit(1000)
        .all()
    )
    return RunDetailResponse(
        run_id=run.id,
        trace_id=run.trace_id,
        project_id=run.project_id,
        agent_name=name or "unknown",
        agent_version=version or "unknown",
        state=run.state,
        started_at=run.started_at,
        ended_at=run.ended_at,
        tool_call_count=count,
        events=[
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


# ---------------------------------------------------------------------------
# Phase 6: analytics aggregates (M09). All metrics derive from committed
# rows inside the caller's project and the requested window; empty inputs
# produce empty arrays / nulls, never invented numbers.
# ---------------------------------------------------------------------------

_OUTCOMES = ("ALLOW", "DENY", "REVIEW")


def _nearest_rank_percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile (pct in 0..100) over an ascending-sorted list."""
    n = len(sorted_values)
    rank = math.ceil(pct / 100.0 * n)
    return float(sorted_values[max(0, min(rank - 1, n - 1))])


def _stats(values: list[float]) -> PercentileStats:
    if not values:
        return PercentileStats(p50=None, p95=None, count=0)
    ordered = sorted(values)
    return PercentileStats(
        p50=_nearest_rank_percentile(ordered, 50),
        p95=_nearest_rank_percentile(ordered, 95),
        count=len(ordered),
    )


@router.get("/dashboard/analytics", response_model=AnalyticsResponse)
def dashboard_analytics(
    window_days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> AnalyticsResponse:
    """Window aggregates over committed rows: decisions/day, execution
    latency, top denied tools, approval turnaround. UTC calendar days."""
    pid = key.project_id
    window_start = utcnow() - timedelta(days=window_days)

    # Decisions per UTC calendar day and outcome (zero-filled for days present).
    decision_rows = (
        db.query(
            func.date_trunc("day", PolicyDecision.decided_at).label("day"),
            PolicyDecision.outcome,
            func.count(PolicyDecision.id),
        )
        .join(ToolCall, PolicyDecision.tool_call_id == ToolCall.id)
        .filter(ToolCall.project_id == pid, PolicyDecision.decided_at >= window_start)
        .group_by("day", PolicyDecision.outcome)
        .order_by("day")
        .all()
    )
    days: dict[str, dict[str, int]] = {}
    for day_ts, outcome, count in decision_rows:
        if outcome not in _OUTCOMES:
            continue
        day_key = day_ts.date().isoformat()
        bucket = days.setdefault(day_key, dict.fromkeys(_OUTCOMES, 0))
        bucket[outcome] += count
    decisions_by_day = [
        AnalyticsDayItem(day=day, **counts) for day, counts in days.items()
    ]

    # Execution latency from finished executions that started inside the window.
    execution_rows = (
        db.query(ToolExecution.started_at, ToolExecution.finished_at)
        .join(ToolCall, ToolExecution.call_id == ToolCall.id)
        .filter(
            ToolCall.project_id == pid,
            ToolExecution.started_at >= window_start,
            ToolExecution.finished_at.is_not(None),
        )
        .all()
    )
    execution_latency_ms = _stats(
        [(finished - started).total_seconds() * 1000.0 for started, finished in execution_rows]
    )

    # Top denied registered tools by decision count inside the window.
    denied_rows = (
        db.query(ToolDefinition.slug, func.count(ToolCall.id).label("deny_count"))
        .join(ToolCall, ToolCall.tool_id == ToolDefinition.id)
        .join(PolicyDecision, PolicyDecision.tool_call_id == ToolCall.id)
        .filter(
            ToolCall.project_id == pid,
            PolicyDecision.outcome == "DENY",
            PolicyDecision.decided_at >= window_start,
        )
        .group_by(ToolDefinition.slug)
        .order_by(func.count(ToolCall.id).desc(), ToolDefinition.slug.asc())
        .limit(10)
        .all()
    )
    top_denied_tools = [
        DeniedToolItem(tool_name=slug, deny_count=deny_count)
        for slug, deny_count in denied_rows
    ]

    # Approval turnaround for approvals decided inside the window.
    approval_rows = (
        db.query(Approval.created_at, Approval.decided_at)
        .join(ToolCall, Approval.tool_call_id == ToolCall.id)
        .filter(
            ToolCall.project_id == pid,
            Approval.state != "PENDING",
            Approval.decided_at.is_not(None),
            Approval.decided_at >= window_start,
        )
        .all()
    )
    approval_turnaround_s = _stats(
        [(decided - created).total_seconds() for created, decided in approval_rows]
    )

    return AnalyticsResponse(
        window_days=window_days,
        decisions_by_day=decisions_by_day,
        execution_latency_ms=execution_latency_ms,
        top_denied_tools=top_denied_tools,
        approval_turnaround_s=approval_turnaround_s,
    )
