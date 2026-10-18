"""Pre-execution authorization (M06) and trusted execution gateway (M07)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import (
    SCOPE_AGENT_AUTHORIZE,
    SCOPE_AGENT_EXECUTE,
    require_scopes,
)
from ..gateway.service import execute_tool_call
from ..models import ApiKey
from ..policy.service import authorize_tool_call
from ..schemas import AuthorizeRequest, AuthorizeResponse, ExecuteRequest, ExecuteResponse

router = APIRouter(tags=["tool-calls"])

_authorize_auth = require_scopes(SCOPE_AGENT_AUTHORIZE)
_execute_auth = require_scopes(SCOPE_AGENT_EXECUTE)


@router.post("/tool-calls/authorize", response_model=AuthorizeResponse)
def authorize(
    payload: AuthorizeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(_authorize_auth),
) -> AuthorizeResponse:
    """Evaluate a tool call against the active deterministic policy.

    Returns 201 for a new decision, 200 when an idempotent replay returns the
    stored decision. The tool_call and policy_decision rows are persisted
    atomically in a single transaction; a REVIEW outcome also creates the
    pending approval row in the same transaction.
    """
    result = authorize_tool_call(
        db=db,
        project_id=key.project_id,
        run_id=payload.run_id,
        tool_name=payload.tool_name,
        arguments=payload.arguments,
        idempotency_key=payload.idempotency_key,
        requester_key_id=key.id,
    )
    response.status_code = 200 if result.replayed else 201
    return AuthorizeResponse(
        tool_call_id=result.tool_call_id,
        decision_id=result.decision_id,
        outcome=result.outcome,
        reason_code=result.reason_code,
        policy_version=result.policy_version,
        decided_at=result.decided_at,
        explanation=result.explanation,
        approval_id=result.approval_id,
    )


@router.post("/tool-calls/{call_id}/execute", response_model=ExecuteResponse)
def execute(
    call_id: UUID,
    payload: ExecuteRequest,
    response: Response,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(_execute_auth),
) -> ExecuteResponse:
    """Execute an authorized tool call through the trusted gateway.

    Returns 201 for a new execution, 200 when replaying a previous execution's
    stored result. DENY decisions never execute (409); REVIEW decisions
    execute only with a linked APPROVED approval (else 409); expired
    grants are 410; tampered arguments are 409. The side effect is applied at
    most once per tool call, inside a single transaction.
    """
    result = execute_tool_call(
        db=db,
        project_id=key.project_id,
        call_id=call_id,
        arguments=payload.arguments,
    )
    response.status_code = 200 if result.replayed else 201
    return ExecuteResponse(
        tool_call_id=result.tool_call_id,
        execution_id=result.execution_id,
        state=result.state,
        result=result.result,
        replayed=result.replayed,
    )
