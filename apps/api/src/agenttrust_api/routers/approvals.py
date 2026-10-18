"""Human approval workflow HTTP layer (M10).

Thin transport over approvals/service.py, which owns the state machine,
optimistic concurrency, separation of duties, and revalidation. REVIEW
decisions create a PENDING approval row atomically with the decision
(see policy/service.py).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from ..approvals.service import (
    decide_approval as service_decide_approval,
)
from ..approvals.service import (
    expire_due_for_project,
    expire_if_due,
    scoped_approval,
)
from ..db import get_db
from ..deps import (
    SCOPE_APPROVALS_READ,
    AppError,
    has_scope,
    require_api_key,
    require_reviewer,
    require_scopes,
)
from ..models import ApiKey, Approval, Event, MockOrder, ToolCall
from ..schemas import (
    ApprovalDecisionInfo,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalDetailResponse,
    ApprovalOrderFacts,
    ApprovalQueueItem,
    ApprovalQueueResponse,
    ApprovalRequesterInfo,
    ApprovalStatusResponse,
    ApprovalToolCallInfo,
    EventPublic,
)

router = APIRouter(tags=["approvals"])

_queue_auth = require_scopes(SCOPE_APPROVALS_READ, limit_per_minute=False)


def _queue_item(approval: Approval) -> ApprovalQueueItem:
    call = approval.tool_call
    tool = call.tool
    decision = call.decision
    redacted = call.args_redacted or {}
    order_id = redacted.get("order_id")
    amount = redacted.get("amount_minor")
    currency = redacted.get("currency")
    return ApprovalQueueItem(
        approval_id=approval.id,
        tool_call_id=call.id,
        tool_name=tool.slug if tool is not None else "unknown",
        state=approval.state,  # type: ignore[arg-type]
        reason_code=decision.reason_code if decision is not None else "UNKNOWN",
        order_id=order_id if isinstance(order_id, str) else None,
        amount_minor=amount if isinstance(amount, int) else None,
        currency=currency if isinstance(currency, str) else None,
        expires_at=approval.expires_at,
        row_version=approval.row_version,
        created_at=approval.created_at,
    )


@router.get("/approvals", response_model=ApprovalQueueResponse)
def list_approvals(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(_queue_auth),
    state: str | None = Query(default=None, pattern="^(PENDING|APPROVED|REJECTED|EXPIRED)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ApprovalQueueResponse:
    """List approvals for the project. Applies lazy expiry on read."""
    expire_due_for_project(db, key.project_id)
    query = (
        db.query(Approval)
        .join(ToolCall, Approval.tool_call_id == ToolCall.id)
        .filter(ToolCall.project_id == key.project_id)
    )
    if state is not None:
        query = query.filter(Approval.state == state)
    total = query.with_entities(func.count()).scalar() or 0
    rows = query.order_by(desc(Approval.created_at)).limit(limit).offset(offset).all()
    return ApprovalQueueResponse(
        approvals=[_queue_item(a) for a in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _check_approval_visibility(db: Session, approval: Approval, key: ApiKey) -> None:
    """Reviewer keys (`approvals:read`) and the requesting key may view."""
    if not (has_scope(key, SCOPE_APPROVALS_READ) or key.id == approval.requester_key_id):
        raise AppError("insufficient_scope", "Not authorized to view this approval.", 403)


def _detail(db: Session, approval: Approval) -> ApprovalDetailResponse:
    call = approval.tool_call
    tool = call.tool
    decision = call.decision
    redacted = call.args_redacted or {}
    order_facts = None
    order_id = redacted.get("order_id")
    if isinstance(order_id, str):
        order = db.query(MockOrder).filter(MockOrder.order_ref == order_id).one_or_none()
        if order is not None:
            order_facts = ApprovalOrderFacts(
                order_ref=order.order_ref,
                eligible=order.eligible,
                remaining_minor=order.refundable_remaining_minor,
                currency=order.currency,
            )
    requester = db.get(ApiKey, approval.requester_key_id)
    reviewer_prefix = None
    if approval.reviewer_key_id is not None:
        reviewer = db.get(ApiKey, approval.reviewer_key_id)
        reviewer_prefix = reviewer.key_prefix if reviewer is not None else None
    history = (
        db.query(Event)
        .filter(
            Event.project_id == approval.tool_call.project_id,
            Event.payload_redacted["approval_id"].astext == str(approval.id),
        )
        .order_by(Event.project_seq)
        .all()
    )
    return ApprovalDetailResponse(
        approval_id=approval.id,
        tool_call_id=call.id,
        state=approval.state,  # type: ignore[arg-type]
        reason=approval.reason,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        row_version=approval.row_version,
        created_at=approval.created_at,
        tool_call=ApprovalToolCallInfo(
            tool_call_id=call.id,
            tool_name=tool.slug if tool is not None else "unknown",
            args_redacted=redacted,
            args_hash=call.args_hash,
            idempotency_key=call.idempotency_key,
            state=call.state,
        ),
        decision=ApprovalDecisionInfo(
            decision_id=decision.id,
            outcome=decision.outcome,
            reason_code=decision.reason_code,
            explanation=decision.explanation,
            policy_version=decision.version.version if decision.version else None,
        )
        if decision is not None
        else ApprovalDecisionInfo(
            decision_id=call.id,
            outcome="UNKNOWN",
            reason_code="UNKNOWN",
            explanation="No decision recorded.",
            policy_version=None,
        ),
        order_facts=order_facts,
        requester=ApprovalRequesterInfo(
            key_name=requester.name if requester is not None else "",
            key_prefix=requester.key_prefix if requester is not None else "",
        ),
        reviewer_key_prefix=reviewer_prefix,
        events=[
            EventPublic(
                event_id=e.event_id,
                kind=e.kind,
                project_seq=e.project_seq,
                run_id=e.run_id,
                received_at=e.received_at,
                payload=e.payload_redacted,
            )
            for e in history
        ],
    )


@router.get("/approvals/{approval_id}", response_model=ApprovalDetailResponse)
def get_approval(
    approval_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> ApprovalDetailResponse:
    """Full review context for one approval. Lazy expiry applies on read."""
    approval = scoped_approval(db, approval_id, key.project_id)
    _check_approval_visibility(db, approval, key)
    expire_if_due(db, approval)
    return _detail(db, approval)


@router.get("/approvals/{approval_id}/status", response_model=ApprovalStatusResponse)
def get_approval_status(
    approval_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> ApprovalStatusResponse:
    """Lightweight approval state for SDK polling (`wait_for_approval`)."""
    approval = scoped_approval(db, approval_id, key.project_id)
    _check_approval_visibility(db, approval, key)
    expire_if_due(db, approval)
    return ApprovalStatusResponse(
        approval_id=approval.id,
        tool_call_id=approval.tool_call_id,
        state=approval.state,  # type: ignore[arg-type]
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
    )


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalDecisionResponse)
def decide_approval(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_reviewer),
) -> ApprovalDecisionResponse:
    """Approve or reject a pending approval.

    Guards, in order: project scoping (404), separation of duties (403),
    lazy expiry (410), terminal-state handling (200 on identical re-decision,
    409 on conflict), optimistic concurrency (409 on stale version), business
    revalidation for approvals (409 `approval_stale` when facts changed).

    Approving mints a single-use execution grant; it never executes the tool.
    """
    result = service_decide_approval(
        db=db,
        approval_id=approval_id,
        project_id=key.project_id,
        reviewer_key=key,
        decision=payload.decision,
        reason=payload.reason,
        expected_row_version=payload.expected_row_version,
    )
    return ApprovalDecisionResponse(
        approval_id=result.approval_id,
        state=result.state,  # type: ignore[arg-type]
        decided_at=result.decided_at,
        row_version=result.row_version,
        reason=result.reason,
        grant_id=result.grant_id,
        grant_expires_at=result.grant_expires_at,
    )
