"""Agent run registration (M03)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import SCOPE_AGENT_RUN, require_scopes
from ..models import Agent, AgentRun, ApiKey
from ..schemas import RunCreateRequest, RunCreateResponse
from ..util import utcnow

router = APIRouter(tags=["runs"])


@router.post("/runs", status_code=201, response_model=RunCreateResponse)
def create_run(
    payload: RunCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_scopes(SCOPE_AGENT_RUN, limit_per_minute=False)),
) -> RunCreateResponse:
    """Register (or reuse) the agent identity and open a new run.

    The agent row is a get-or-create on (project, name, version): the SDK can
    report its identity without a separate registration step.
    """
    agent = (
        db.query(Agent)
        .filter(
            Agent.project_id == key.project_id,
            Agent.name == payload.agent_name,
            Agent.version == payload.agent_version,
        )
        .first()
    )
    if agent is None:
        agent = Agent(
            project_id=key.project_id,
            name=payload.agent_name,
            version=payload.agent_version,
            environment=payload.environment,
            created_at=utcnow(),
        )
        db.add(agent)
        db.flush()

    run = AgentRun(
        project_id=key.project_id,
        agent_id=agent.id,
        state="RUNNING",
        started_at=utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return RunCreateResponse(
        run_id=run.id,
        trace_id=run.trace_id,
        agent_name=agent.name,
        agent_version=agent.version,
        state=run.state,
        started_at=run.started_at,
    )
