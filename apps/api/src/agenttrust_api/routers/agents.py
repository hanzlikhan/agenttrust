"""Agent directory read endpoints (M09): project-scoped agent list + detail.

Read-only snapshots over committed rows; per-agent run counts and recent
runs are computed from the runs/tool_calls tables the same transaction
sees. Nothing here mutates, and nothing is fabricated.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AppError, require_api_key
from ..models import Agent, AgentRun, ApiKey, ToolCall
from ..schemas import AgentDetailResponse, AgentListResponse, AgentRunItem, AgentSummaryItem

router = APIRouter(tags=["agents"])

_MAX_LIMIT = 100
_RECENT_RUNS_LIMIT = 20


def _limit(value: int) -> int:
    return max(1, min(value, _MAX_LIMIT))


@router.get("/agents", response_model=AgentListResponse)
def list_agents(
    limit: int = Query(default=20, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> AgentListResponse:
    """Paginated project agent list, each with run count + newest run time."""
    pid = key.project_id
    run_stats = (
        db.query(
            AgentRun.agent_id.label("agent_id"),
            func.count(AgentRun.id).label("run_count"),
            func.max(AgentRun.started_at).label("last_run_at"),
        )
        .filter(AgentRun.project_id == pid, AgentRun.agent_id.is_not(None))
        .group_by(AgentRun.agent_id)
        .subquery()
    )
    query = (
        db.query(Agent, run_stats.c.run_count, run_stats.c.last_run_at)
        .outerjoin(run_stats, run_stats.c.agent_id == Agent.id)
        .filter(Agent.project_id == pid)
    )
    total = query.count()
    rows = query.order_by(Agent.created_at.desc()).offset(offset).limit(_limit(limit)).all()
    return AgentListResponse(
        agents=[
            AgentSummaryItem(
                agent_id=agent.id,
                name=agent.name,
                version=agent.version,
                environment=agent.environment,
                run_count=count or 0,
                last_run_at=last_run_at,
            )
            for agent, count, last_run_at in rows
        ],
        total=total,
        limit=_limit(limit),
        offset=offset,
    )


@router.get("/agents/{agent_id}", response_model=AgentDetailResponse)
def get_agent(
    agent_id: UUID,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> AgentDetailResponse:
    """One agent with its 20 newest runs (newest first) + tool call counts."""
    pid = key.project_id
    agent = (
        db.query(Agent).filter(Agent.id == agent_id, Agent.project_id == pid).first()
    )
    if agent is None:
        # 404 without leaking whether the agent exists in another project.
        raise AppError("agent_not_found", "Agent not found.", 404)
    recent = (
        db.query(AgentRun, func.count(ToolCall.id))
        .outerjoin(ToolCall, ToolCall.run_id == AgentRun.id)
        .filter(AgentRun.agent_id == agent.id, AgentRun.project_id == pid)
        .group_by(AgentRun.id)
        .order_by(AgentRun.started_at.desc())
        .limit(_RECENT_RUNS_LIMIT)
        .all()
    )
    total_runs = (
        db.query(func.count(AgentRun.id))
        .filter(AgentRun.agent_id == agent.id, AgentRun.project_id == pid)
        .scalar()
        or 0
    )
    return AgentDetailResponse(
        agent_id=agent.id,
        name=agent.name,
        version=agent.version,
        environment=agent.environment,
        created_at=agent.created_at,
        recent_runs=[
            AgentRunItem(
                run_id=run.id,
                trace_id=run.trace_id,
                state=run.state,
                started_at=run.started_at,
                ended_at=run.ended_at,
                tool_call_count=count,
            )
            for run, count in recent
        ],
        total_runs=total_runs,
    )
