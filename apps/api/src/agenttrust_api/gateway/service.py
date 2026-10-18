"""Trusted execution gateway (M07).

The gateway — not the SDK — decides what executes. Every execution runs in a
single database transaction that:

1. locks the execution grant row (FOR UPDATE),
2. re-verifies the grant is unconsumed, unexpired, and bound to the call's
   canonical argument hash,
3. re-verifies the decision outcome is ALLOW (DENY/REVIEW never execute),
4. locks the trusted business row (mock_orders FOR UPDATE) and re-checks
   eligibility and balance at execution time,
5. applies the side effect exactly once, marks the grant consumed, and records
   the execution row plus durable events.

Replay: a second execute for the same call returns the original execution row
(200) — the balance moves at most once no matter how many times the request
is retried. Money is integer minor units throughout.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..deps import AppError
from ..events import record_event
from ..models import (
    Approval,
    ExecutionGrant,
    MockOrder,
    PolicyDecision,
    ToolCall,
    ToolExecution,
)
from ..policy.canonical import args_hash
from ..util import utcnow

GRANT_TTL_SECONDS = 300  # single-use grants live 5 minutes (ADR-021)


@dataclass
class ExecuteResult:
    tool_call_id: UUID
    execution_id: UUID
    state: str
    result: dict[str, Any]
    replayed: bool  # True when a previous execution's result is returned


def mint_grant(
    db: Session,
    *,
    tool_call_id: UUID,
    digest: str,
    policy_version_id: UUID | None,
) -> ExecutionGrant:
    """Create a single-use execution grant. Flushes; the caller commits."""
    grant = ExecutionGrant(
        tool_call_id=tool_call_id,
        args_hash=digest,
        policy_version_id=policy_version_id,
        expires_at=utcnow() + timedelta(seconds=GRANT_TTL_SECONDS),
        consumed_at=None,
        status="ACTIVE",
        created_at=utcnow(),
    )
    db.add(grant)
    db.flush()
    return grant


def _rejected(
    db: Session,
    *,
    project_id: UUID,
    run_id: UUID | None,
    call_id: UUID,
    reason: str,
    detail: str,
    status_code: int,
) -> AppError:
    """Record a rejection event, commit it, and build the error to raise."""
    rejected_event = record_event(
        db,
        project_id=project_id,
        run_id=run_id,
        kind="tool.execute_rejected",
        payload_redacted={"tool_call_id": str(call_id), "reason": reason},
    )
    db.commit()
    # Phase 7 (M11): discrete incident triggers. The detector is total and
    # observability-only; it runs after the rejection is committed so it can
    # never change the enforcement outcome.
    # Phase 8 audit LOW-5: the post-detector commit is guarded — if the
    # detector left the session in a failed state, roll back and still
    # return the structured rejection (the enforcement outcome was already
    # committed above, so fail-closed holds).
    if reason in ("arguments_tampered", "grant_consumed"):
        from ..incidents import detector as incident_detector

        try:
            incident_detector.on_execute_rejected(
                db,
                project_id=project_id,
                run_id=run_id,
                call_id=call_id,
                reason=reason,
                rejected_event_id=rejected_event.event_id,
            )
            db.commit()
        except Exception:
            db.rollback()
    return AppError(reason, detail, status_code)


def execute_tool_call(
    *,
    db: Session,
    project_id: UUID,
    call_id: UUID,
    arguments: dict[str, Any] | None,
) -> ExecuteResult:
    """Execute an authorized tool call through the trusted gateway."""
    call = db.get(ToolCall, call_id)
    if call is None or call.project_id != project_id:
        # 404 without distinguishing "no such call" from "another project's call".
        raise AppError("tool_call_not_found", "Tool call not found.", 404)

    # Fast path: an execution row already exists → replay the original result.
    existing = (
        db.query(ToolExecution).filter(ToolExecution.call_id == call.id).one_or_none()
    )
    if existing is not None:
        return ExecuteResult(
            tool_call_id=call.id,
            execution_id=existing.id,
            state=existing.state,
            result=existing.result_json_redacted,
            replayed=True,
        )

    decision = (
        db.query(PolicyDecision).filter(PolicyDecision.tool_call_id == call.id).one_or_none()
    )
    if decision is None:
        raise _rejected(
            db,
            project_id=project_id,
            run_id=call.run_id,
            call_id=call.id,
            reason="decision_denied",
            detail="The policy decision for this call does not authorize execution.",
            status_code=409,
        )
    if decision.outcome == "REVIEW":
        # REVIEW executes only with a linked APPROVED approval. The approval
        # decision minted a single-use grant bound to the approved arguments;
        # the grant checks below enforce it exactly like an ALLOW grant.
        approval = (
            db.query(Approval).filter(Approval.tool_call_id == call.id).one_or_none()
        )
        if approval is None or approval.state != "APPROVED":
            raise _rejected(
                db,
                project_id=project_id,
                run_id=call.run_id,
                call_id=call.id,
                reason="approval_required",
                detail="This action requires human approval; it cannot execute yet.",
                status_code=409,
            )
    elif decision.outcome != "ALLOW":
        raise _rejected(
            db,
            project_id=project_id,
            run_id=call.run_id,
            call_id=call.id,
            reason="decision_denied",
            detail="The policy decision for this call does not authorize execution.",
            status_code=409,
        )

    # Lock the grant: concurrent executes serialize here. After acquiring the
    # lock, re-check the execution row — the winner may have committed while
    # this request waited.
    grant = (
        db.query(ExecutionGrant)
        .filter(ExecutionGrant.tool_call_id == call.id)
        .with_for_update()
        .one_or_none()
    )
    if grant is None:
        raise _rejected(
            db,
            project_id=project_id,
            run_id=call.run_id,
            call_id=call.id,
            reason="grant_not_found",
            detail="No execution grant exists for this call.",
            status_code=409,
        )
    winner = (
        db.query(ToolExecution).filter(ToolExecution.call_id == call.id).one_or_none()
    )
    if winner is not None:
        return ExecuteResult(
            tool_call_id=call.id,
            execution_id=winner.id,
            state=winner.state,
            result=winner.result_json_redacted,
            replayed=True,
        )
    if grant.consumed_at is not None or grant.status == "CONSUMED":
        # Defensive: a consumed grant with no execution row should be
        # impossible (both change in one transaction). Fail closed.
        raise _rejected(
            db,
            project_id=project_id,
            run_id=call.run_id,
            call_id=call.id,
            reason="grant_consumed",
            detail="This execution grant has already been consumed.",
            status_code=409,
        )
    if grant.expires_at <= utcnow():
        grant.status = "EXPIRED"
        raise _rejected(
            db,
            project_id=project_id,
            run_id=call.run_id,
            call_id=call.id,
            reason="grant_expired",
            detail="The execution grant has expired; request a fresh authorization.",
            status_code=410,
        )

    if arguments is not None and args_hash(arguments) != grant.args_hash:
        # Approved arguments were modified after authorization: refuse, and do
        # NOT consume the grant — the legitimate arguments may still execute.
        raise _rejected(
            db,
            project_id=project_id,
            run_id=call.run_id,
            call_id=call.id,
            reason="arguments_tampered",
            detail="Arguments do not match the authorized canonical hash.",
            status_code=409,
        )

    # Policy version pinning (Phase 8 audit LOW-10): the grant was minted
    # under a specific policy version. If the admin activated a newer
    # version after authorization, the grant no longer executes — the
    # caller must re-authorize under the current policy.
    if grant.policy_version_id is not None and call.tool is not None:
        from ..policy.service import _resolve_policy

        active_version, _, _ = _resolve_policy(db, project_id, call.tool.slug)
        if active_version is not None and active_version.id != grant.policy_version_id:
            raise _rejected(
                db,
                project_id=project_id,
                run_id=call.run_id,
                call_id=call.id,
                reason="policy_version_changed",
                detail="The active policy version changed after authorization; "
                "request a fresh authorization.",
                status_code=409,
            )

    # Trusted business facts, re-read under a row lock at execution time: the
    # world may have changed between authorize and execute (ADR-002).
    redacted = call.args_redacted or {}
    order_id = redacted.get("order_id")
    amount_minor = redacted.get("amount_minor")
    currency = redacted.get("currency")
    order = (
        db.query(MockOrder)
        .filter(MockOrder.order_ref == order_id)
        .with_for_update()
        .one_or_none()
        if isinstance(order_id, str)
        else None
    )
    if (
        order is None
        or not isinstance(amount_minor, int)
        or not order.eligible
        or order.refundable_remaining_minor < amount_minor
    ):
        # Business facts changed since authorization: refuse without consuming
        # the grant and without touching the balance.
        raise _rejected(
            db,
            project_id=project_id,
            run_id=call.run_id,
            call_id=call.id,
            reason="business_facts_changed",
            detail="Trusted business facts no longer support this execution.",
            status_code=409,
        )

    # Phase 8 audit LOW-10 (defense in depth): the policy layer guarantees
    # amount_minor >= 1, but the execute path re-checks before mutating the
    # balance so a future policy change cannot create a negative refund.
    if not isinstance(amount_minor, int) or amount_minor < 1:
        raise _rejected(
            db,
            project_id=project_id,
            run_id=call.run_id,
            call_id=call.id,
            reason="business_facts_changed",
            detail="Refund amount is not a positive integer.",
            status_code=409,
        )

    record_event(
        db,
        project_id=project_id,
        run_id=call.run_id,
        kind="tool.executing",
        payload_redacted={"tool_call_id": str(call.id), "grant_id": str(grant.id)},
    )
    order.refundable_remaining_minor -= amount_minor
    grant.status = "CONSUMED"
    grant.consumed_at = utcnow()
    execution = ToolExecution(
        call_id=call.id,
        state="SUCCEEDED",
        result_json_redacted={
            "order_id": order_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "remaining_minor": order.refundable_remaining_minor,
        },
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    db.add(execution)
    db.flush()
    record_event(
        db,
        project_id=project_id,
        run_id=call.run_id,
        kind="tool.succeeded",
        payload_redacted={
            "tool_call_id": str(call.id),
            "execution_id": str(execution.id),
            "order_id": order_id,
            "amount_minor": amount_minor,
            "remaining_minor": order.refundable_remaining_minor,
        },
    )
    call.state = "SUCCEEDED"
    db.commit()
    return ExecuteResult(
        tool_call_id=call.id,
        execution_id=execution.id,
        state="SUCCEEDED",
        result=execution.result_json_redacted,
        replayed=False,
    )
