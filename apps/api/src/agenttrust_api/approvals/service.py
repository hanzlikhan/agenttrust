"""Approval domain logic (M10), separated from HTTP transport.

All state transitions happen here so they can be driven by the router, by
tests with independent sessions, and (later) by background workers. Every
mutating path commits its own transaction and records durable events.

State machine: PENDING -> APPROVED | REJECTED | EXPIRED. Terminal states never
move backwards. Decisions use optimistic concurrency on `row_version`.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..deps import AppError
from ..events import record_event
from ..gateway.service import mint_grant
from ..models import (
    ApiKey,
    Approval,
    MockOrder,
    Policy,
    PolicyVersion,
    ToolCall,
)
from ..util import utcnow


@dataclass
class DecisionResult:
    approval_id: UUID
    state: str
    decided_at: datetime | None
    row_version: int
    reason: str | None
    grant_id: UUID | None
    grant_expires_at: datetime | None


def scoped_approval(db: Session, approval_id: UUID, project_id: UUID) -> Approval:
    """Load an approval scoped to the project. 404 leaks nothing."""
    approval = db.get(Approval, approval_id)
    if approval is None or approval.tool_call.project_id != project_id:
        raise AppError("approval_not_found", "Approval not found.", 404)
    return approval


def expire_if_due(db: Session, approval: Approval) -> bool:
    """Lazily transition a PENDING approval past its expiry.

    Records `approval.expired` and commits. Returns True when the approval
    expired (callers then report 410 / show EXPIRED).

    Phase 8 audit LOW-3: the row is re-read with FOR UPDATE, so concurrent
    expirers serialize — the second sees EXPIRED and returns False instead
    of recording a duplicate event.
    """
    if approval.state != "PENDING" or approval.expires_at > utcnow():
        return False
    locked = (
        db.query(Approval)
        .filter(Approval.id == approval.id)
        .with_for_update()
        .one_or_none()
    )
    if locked is None or locked.state != "PENDING":
        # Lost the race: another request already expired (or decided) it.
        return False
    locked.state = "EXPIRED"
    locked.decided_at = utcnow()
    db.flush()
    record_event(
        db,
        project_id=locked.tool_call.project_id,
        run_id=locked.tool_call.run_id,
        kind="approval.expired",
        payload_redacted={
            "approval_id": str(locked.id),
            "tool_call_id": str(locked.tool_call_id),
        },
    )
    db.commit()
    return True


def expire_due_for_project(db: Session, project_id: UUID) -> None:
    """Apply lazy expiry to every overdue PENDING approval in the project."""
    due = (
        db.query(Approval)
        .join(ToolCall, Approval.tool_call_id == ToolCall.id)
        .filter(
            ToolCall.project_id == project_id,
            Approval.state == "PENDING",
            Approval.expires_at <= utcnow(),
        )
        .all()
    )
    for approval in due:
        expire_if_due(db, approval)


def revalidate_business_facts(db: Session, call: ToolCall) -> str | None:
    """Return None when trusted facts still support execution, else a problem.

    The order must still exist, be eligible, and cover the amount; the
    deciding policy version must still be the active one. Any change means
    the human reviewed stale facts and the approval cannot stand.
    """
    redacted = call.args_redacted or {}
    order_id = redacted.get("order_id")
    amount_minor = redacted.get("amount_minor")
    currency = redacted.get("currency")
    if not isinstance(order_id, str) or not isinstance(amount_minor, int):
        return "business_facts_changed"
    order = db.query(MockOrder).filter(MockOrder.order_ref == order_id).one_or_none()
    if (
        order is None
        or not order.eligible
        or order.currency != currency
        or order.refundable_remaining_minor < amount_minor
    ):
        return "business_facts_changed"
    decision = call.decision
    if decision is not None and decision.version_id is not None:
        version = db.get(PolicyVersion, decision.version_id)
        policy = db.get(Policy, version.policy_id) if version is not None else None
        if policy is None or policy.active_version_id != decision.version_id:
            return "policy_version_changed"
    return None


def _transition(
    db: Session,
    approval_id: UUID,
    expected_version: int,
    new_state: str,
    reviewer_key_id: UUID,
    reason: str | None,
) -> int:
    """Optimistic-concurrency state transition. Returns rows updated (0 or 1)."""
    result = db.execute(
        update(Approval)
        .where(
            Approval.id == approval_id,
            Approval.row_version == expected_version,
            Approval.state == "PENDING",
        )
        .values(
            state=new_state,
            reviewer_key_id=reviewer_key_id,
            reason=reason,
            decided_at=utcnow(),
            row_version=Approval.row_version + 1,
        )
    )
    db.flush()
    return result.rowcount


def _conflict() -> AppError:
    return AppError(
        "approval_conflict",
        "Approval changed while deciding; refresh and retry.",
        409,
    )


def decide_approval(
    *,
    db: Session,
    approval_id: UUID,
    project_id: UUID,
    reviewer_key: ApiKey,
    decision: str,
    reason: str | None,
    expected_row_version: int | None,
) -> DecisionResult:
    """Approve or reject a pending approval. Commits; raises AppError on failure.

    `decision` is "approved" or "rejected" (case-insensitive). Guards, in
    order: project scoping (404), separation of duties (403), lazy expiry
    (410), terminal-state handling (idempotent re-decision or 409),
    optimistic concurrency (409), business revalidation for approvals
    (409 `approval_stale`, approval moved to REJECTED/facts_changed).

    Approving mints a single-use execution grant; it never executes the tool.
    """
    approval = scoped_approval(db, approval_id, project_id)

    # Separation of duties: the requesting credential may never decide its
    # own approval, even if it somehow holds the reviewer scope.
    if reviewer_key.id == approval.requester_key_id:
        raise AppError(
            "sod_violation",
            "The credential that requested this action cannot decide it: "
            "separation of duties.",
            403,
        )

    if expire_if_due(db, approval):
        raise AppError(
            "approval_expired",
            "This approval has expired; request a fresh review.",
            410,
        )

    want = decision.upper()  # APPROVED | REJECTED
    if want not in ("APPROVED", "REJECTED"):
        raise AppError("invalid_decision", "Decision must be approved or rejected.", 422)

    if approval.state != "PENDING":
        if approval.state == want and approval.reviewer_key_id == reviewer_key.id:
            # Idempotent re-decision by the same reviewer.
            return _result(db, approval)
        raise AppError(
            "approval_conflict",
            f"This approval is already {approval.state}; refresh and retry.",
            409,
        )

    expected = (
        expected_row_version if expected_row_version is not None else approval.row_version
    )
    project_id_of_call = approval.tool_call.project_id
    run_id = approval.tool_call.run_id

    if want == "REJECTED":
        if _transition(db, approval.id, expected, "REJECTED", reviewer_key.id, reason) == 0:
            raise _conflict()
        db.refresh(approval)
        record_event(
            db,
            project_id=project_id_of_call,
            run_id=run_id,
            kind="approval.rejected",
            payload_redacted={
                "approval_id": str(approval.id),
                "tool_call_id": str(approval.tool_call_id),
                "reviewer_key_prefix": reviewer_key.key_prefix,
                "reason": reason,
            },
        )
        db.commit()
        return _result(db, approval)

    # APPROVED: revalidate trusted business facts inside the decision
    # transaction before minting the grant.
    problem = revalidate_business_facts(db, approval.tool_call)
    if problem is not None:
        if (
            _transition(db, approval.id, expected, "REJECTED", reviewer_key.id, "facts_changed")
            == 0
        ):
            raise _conflict()
        db.refresh(approval)
        record_event(
            db,
            project_id=project_id_of_call,
            run_id=run_id,
            kind="approval.rejected",
            payload_redacted={
                "approval_id": str(approval.id),
                "tool_call_id": str(approval.tool_call_id),
                "reviewer_key_prefix": reviewer_key.key_prefix,
                "reason": "facts_changed",
                "problem": problem,
            },
        )
        db.commit()
        raise AppError(
            "approval_stale",
            "Trusted business facts changed while waiting for review; "
            "a fresh review is required.",
            409,
        )

    if _transition(db, approval.id, expected, "APPROVED", reviewer_key.id, reason) == 0:
        raise _conflict()
    db.refresh(approval)
    grant = mint_grant(
        db,
        tool_call_id=approval.tool_call_id,
        digest=approval.tool_call.args_hash,
        policy_version_id=approval.tool_call.decision.version_id
        if approval.tool_call.decision is not None
        else None,
    )
    record_event(
        db,
        project_id=project_id_of_call,
        run_id=run_id,
        kind="approval.approved",
        payload_redacted={
            "approval_id": str(approval.id),
            "tool_call_id": str(approval.tool_call_id),
            "reviewer_key_prefix": reviewer_key.key_prefix,
            "grant_id": str(grant.id),
            "reason": reason,
        },
    )
    db.commit()
    result = _result(db, approval)
    result.grant_id = grant.id
    result.grant_expires_at = grant.expires_at
    return result


def _result(db: Session, approval: Approval) -> DecisionResult:
    """Build the decision response. Phase 8 audit LOW-6: on an idempotent
    re-decision of an APPROVED approval, look up the existing grant so the
    caller gets its id and expiry instead of None."""
    db.refresh(approval)
    grant_id = None
    grant_expires_at = None
    if approval.state == "APPROVED":
        from ..models import ExecutionGrant

        grant = (
            db.query(ExecutionGrant)
            .filter(ExecutionGrant.tool_call_id == approval.tool_call_id)
            .order_by(ExecutionGrant.created_at.desc())
            .first()
        )
        if grant is not None:
            grant_id = grant.id
            grant_expires_at = grant.expires_at
    return DecisionResult(
        approval_id=approval.id,
        state=approval.state,
        decided_at=approval.decided_at,
        row_version=approval.row_version,
        reason=approval.reason,
        grant_id=grant_id,
        grant_expires_at=grant_expires_at,
    )
