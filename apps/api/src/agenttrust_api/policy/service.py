"""Authorize-flow orchestration (M06).

Pipeline: run ownership check → argument size cap → canonical hash →
idempotency check → tool resolution → schema validation → trusted context
retrieval → active policy resolution → deterministic rule evaluation →
atomic persistence of (tool_call, policy_decision).

Fail-closed throughout: unknown tools, malformed arguments, missing trusted
context, and missing/misconfigured policies all produce persisted DENY
decisions. This module never logs raw arguments.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..deps import AppError
from ..events import record_event
from ..gateway.service import mint_grant
from ..models import (
    AgentRun,
    Approval,
    MockOrder,
    Policy,
    PolicyDecision,
    PolicyVersion,
    ToolCall,
    ToolDefinition,
)
from ..util import utcnow
from .canonical import MAX_ARGS_BYTES, args_hash, canonical_json, contains_float, redact_args
from .rules import (
    POLICY_FOR_TOOL,
    OrderFacts,
    Outcome,
    PolicyOutcome,
    RefundPolicyConfig,
    evaluate_refund,
)

OUTCOME_TO_STATE = {"ALLOW": "AUTHORIZED", "DENY": "DENIED", "REVIEW": "APPROVAL_PENDING"}


@dataclass
class AuthorizeResult:
    tool_call_id: UUID
    decision_id: UUID
    outcome: Outcome
    reason_code: str
    policy_version: int | None
    decided_at: datetime
    explanation: str
    replayed: bool  # True when an idempotent replay returned the stored decision
    approval_id: UUID | None = None  # set when outcome is REVIEW


@dataclass
class SimulateResult:
    outcome: Outcome
    reason_code: str
    policy_version: int | None
    evaluated_with_draft: bool
    explanation: str


def _latest_tool(db: Session, project_id: UUID, slug: str) -> ToolDefinition | None:
    return (
        db.query(ToolDefinition)
        .filter(ToolDefinition.project_id == project_id, ToolDefinition.slug == slug)
        .order_by(ToolDefinition.version.desc())
        .first()
    )


def _validate_schema(schema_json: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    """Return a short error description, or None when arguments are valid."""
    try:
        validator = Draft202012Validator(schema_json)
    except SchemaError:
        # Stored schema itself is corrupt: a server data problem, fail closed.
        return "registered tool schema is invalid"
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    if not errors:
        return None
    first = errors[0]
    location = "/".join(str(p) for p in first.path) or "<root>"
    return f"argument '{location}': {first.message}"


def _resolve_policy(
    db: Session, project_id: UUID, tool_slug: str
) -> tuple[PolicyVersion | None, RefundPolicyConfig | None, str | None]:
    """Resolve the active policy version and validated config.

    Returns (version, config, problem): problem is a DENY reason_code when the
    policy cannot be used; config is None in that case.
    """
    name = POLICY_FOR_TOOL.get(tool_slug)
    if name is None:
        return None, None, "POLICY_NOT_CONFIGURED"
    policy = (
        db.query(Policy)
        .filter(Policy.project_id == project_id, Policy.name == name)
        .first()
    )
    if policy is None or policy.active_version_id is None:
        return None, None, "POLICY_NOT_CONFIGURED"
    version = db.get(PolicyVersion, policy.active_version_id)
    if version is None:
        return None, None, "POLICY_NOT_CONFIGURED"
    try:
        config = RefundPolicyConfig.model_validate(version.rules_json)
    except ValidationError:
        return version, None, "POLICY_CONFIG_INVALID"
    return version, config, None


def _order_facts(db: Session, order_ref: Any) -> OrderFacts | None:
    """Fetch trusted order facts from the server-owned record."""
    if not isinstance(order_ref, str):
        return None
    order = db.query(MockOrder).filter(MockOrder.order_ref == order_ref).first()
    if order is None:
        return None
    return OrderFacts(
        order_ref=order.order_ref,
        total_minor=order.total_minor,
        remaining_minor=order.refundable_remaining_minor,
        currency=order.currency,
        eligible=order.eligible,
    )


def _problem_explanation(problem: str, tool_name: str) -> str:
    if problem == "POLICY_NOT_CONFIGURED":
        return f"No active policy is configured for tool '{tool_name}'; failing closed."
    return f"Active policy configuration for tool '{tool_name}' is invalid; failing closed."


def _stored_result(db: Session, call: ToolCall, replayed: bool) -> AuthorizeResult:
    decision = (
        db.query(PolicyDecision).filter(PolicyDecision.tool_call_id == call.id).one()
    )
    approval_id: UUID | None = None
    if decision.outcome == "REVIEW":
        approval = (
            db.query(Approval).filter(Approval.tool_call_id == call.id).one_or_none()
        )
        approval_id = approval.id if approval is not None else None
    return AuthorizeResult(
        tool_call_id=call.id,
        decision_id=decision.id,
        outcome=decision.outcome,
        reason_code=decision.reason_code,
        policy_version=decision.version.version if decision.version else None,
        decided_at=decision.decided_at,
        explanation=decision.explanation,
        replayed=replayed,
        approval_id=approval_id,
    )


OUTCOME_TO_EVENT = {"ALLOW": "policy.allowed", "DENY": "policy.denied", "REVIEW": "policy.review"}


def _persist_decision(
    *,
    db: Session,
    project_id: UUID,
    run_id: UUID,
    tool_name: str,
    tool_id: UUID | None,
    redacted: dict[str, Any],
    digest: str,
    idempotency_key: str,
    outcome: PolicyOutcome,
    version: PolicyVersion | None,
    requester_key_id: UUID,
) -> AuthorizeResult:
    """Persist tool_call + policy_decision atomically; handle idempotency races.

    Also records `tool.requested` and `policy.*` events with outbox rows, and
    mints a single-use execution grant when the outcome is ALLOW — all in the
    same transaction as the decision. When the outcome is REVIEW, a PENDING
    approval row is created in the same transaction (Phase 5; replaces the
    ADR-016 null).
    """
    call = ToolCall(
        project_id=project_id,
        run_id=run_id,
        tool_id=tool_id,
        requester_key_id=requester_key_id,
        args_redacted=redacted,
        args_hash=digest,
        state=OUTCOME_TO_STATE[outcome.outcome],
        idempotency_key=idempotency_key,
        created_at=utcnow(),
    )
    db.add(call)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race with a concurrent identical request: fall back to the
        # winner's stored decision instead of creating a duplicate.
        db.rollback()
        winner = (
            db.query(ToolCall)
            .filter(
                ToolCall.project_id == project_id,
                ToolCall.idempotency_key == idempotency_key,
            )
            .first()
        )
        if winner is None:
            raise AppError(
                "idempotency_race",
                "Concurrent request conflict; retry with the same idempotency key.",
                409,
                retryable=True,
            ) from None
        if winner.args_hash != digest:
            raise AppError(
                "idempotency_conflict",
                "Idempotency key was already used with different arguments.",
                409,
            ) from None
        return _stored_result(db, winner, replayed=True)

    decision = PolicyDecision(
        tool_call_id=call.id,
        version_id=version.id if version else None,
        outcome=outcome.outcome,
        reason_code=outcome.reason_code,
        explanation=outcome.explanation,
        decided_at=utcnow(),
    )
    db.add(decision)
    db.flush()
    record_event(
        db,
        project_id=project_id,
        run_id=run_id,
        kind="tool.requested",
        payload_redacted={
            "tool_call_id": str(call.id),
            "tool_name": tool_name,
            "args_hash": digest,
        },
    )
    policy_event = record_event(
        db,
        project_id=project_id,
        run_id=run_id,
        kind=OUTCOME_TO_EVENT[outcome.outcome],
        payload_redacted={
            "tool_call_id": str(call.id),
            "decision_id": str(decision.id),
            "outcome": outcome.outcome,
            "reason_code": outcome.reason_code,
            "policy_version": version.version if version else None,
        },
    )
    if outcome.outcome == "DENY" and outcome.reason_code == "AMOUNT_EXCEEDS_MAX":
        # Phase 7 (M11): discrete incident trigger for anomalous amounts.
        # Evaluated in the decision transaction; the detector is total and
        # can never change the DENY outcome.
        from ..incidents import detector as incident_detector

        review_max = 50000
        if version is not None and isinstance(version.rules_json, dict):
            review_max = int(version.rules_json.get("review_max_minor", review_max))
        incident_detector.on_policy_decision(
            db,
            project_id=project_id,
            run_id=run_id,
            call=call,
            reason_code=outcome.reason_code,
            arguments=redacted,
            review_max_minor=review_max,
            policy_event_id=policy_event.event_id,
        )
    if outcome.outcome == "ALLOW":
        # The grant is the only thing the gateway will honor at execution
        # time. Minted here, inside the decision transaction.
        mint_grant(
            db,
            tool_call_id=call.id,
            digest=digest,
            policy_version_id=version.id if version else None,
        )
    if outcome.outcome == "REVIEW":
        # A REVIEW decision suspends the action for a human reviewer. The
        # approval row is created atomically with the decision so a REVIEW
        # can never exist without its pending approval.
        approval = Approval(
            tool_call_id=call.id,
            requester_key_id=requester_key_id,
            reviewer_key_id=None,
            state="PENDING",
            reason=None,
            expires_at=utcnow() + timedelta(seconds=settings.AGENTTRUST_APPROVAL_TTL_SECONDS),
            decided_at=None,
            row_version=1,
            created_at=utcnow(),
        )
        db.add(approval)
        db.flush()
        record_event(
            db,
            project_id=project_id,
            run_id=run_id,
            kind="approval.created",
            payload_redacted={
                "approval_id": str(approval.id),
                "tool_call_id": str(call.id),
                "tool_name": tool_name,
                "reason_code": outcome.reason_code,
                "expires_at": approval.expires_at.isoformat(),
            },
        )
    db.commit()
    return _stored_result(db, call, replayed=False)


def authorize_tool_call(
    *,
    db: Session,
    project_id: UUID,
    run_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
    idempotency_key: str,
    requester_key_id: UUID,
) -> AuthorizeResult:
    """Evaluate one tool call and persist the decision atomically.

    `requester_key_id` is the API key that submitted the request; it is
    recorded on the approval row for REVIEW outcomes and enforces separation
    of duties at decision time.
    """
    run = db.get(AgentRun, run_id)
    if run is None or run.project_id != project_id:
        # 404 without distinguishing "no such run" from "another project's run".
        raise AppError("run_not_found", "Run not found.", 404)

    if not isinstance(arguments, dict):
        raise AppError("malformed_arguments", "Request arguments must be a JSON object.", 422)
    if contains_float(arguments):
        # Reject floats before schema validation: JSON Schema 2020-12 treats
        # 4000.0 as an "integer", but money must be integer minor units.
        schema_problem: str | None = (
            "float values are not permitted; amounts must be integer minor units"
        )
    else:
        schema_problem = None
    if len(canonical_json(arguments).encode("utf-8")) > MAX_ARGS_BYTES:
        raise AppError(
            "arguments_too_large",
            f"Arguments exceed the {MAX_ARGS_BYTES}-byte limit.",
            413,
        )
    digest = args_hash(arguments)

    existing = (
        db.query(ToolCall)
        .filter(
            ToolCall.project_id == project_id,
            ToolCall.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if existing.args_hash != digest:
            raise AppError(
                "idempotency_conflict",
                "Idempotency key was already used with different arguments.",
                409,
            )
        return _stored_result(db, existing, replayed=True)

    tool = _latest_tool(db, project_id, tool_name)
    redacted = redact_args(tool_name, arguments)

    if tool is None:
        outcome = PolicyOutcome(
            "DENY",
            "UNKNOWN_TOOL",
            f"Tool '{tool_name}' is not registered for this project; failing closed.",
        )
        return _persist_decision(
            db=db,
            project_id=project_id,
            run_id=run.id,
            tool_name=tool_name,
            tool_id=None,
            redacted=redacted,
            digest=digest,
            idempotency_key=idempotency_key,
            outcome=outcome,
            version=None,
            requester_key_id=requester_key_id,
        )

    version, config, problem = _resolve_policy(db, project_id, tool_name)

    if schema_problem is None:
        schema_problem = _validate_schema(tool.schema_json, arguments)
    if schema_problem is not None:
        outcome = PolicyOutcome(
            "DENY", "MALFORMED_ARGUMENTS", f"Arguments failed the tool schema: {schema_problem}."
        )
        return _persist_decision(
            db=db,
            project_id=project_id,
            run_id=run.id,
            tool_name=tool_name,
            tool_id=tool.id,
            redacted=redacted,
            digest=digest,
            idempotency_key=idempotency_key,
            outcome=outcome,
            version=version,
            requester_key_id=requester_key_id,
        )

    if problem is not None:
        outcome = PolicyOutcome("DENY", problem, _problem_explanation(problem, tool_name))
        return _persist_decision(
            db=db,
            project_id=project_id,
            run_id=run.id,
            tool_name=tool_name,
            tool_id=tool.id,
            redacted=redacted,
            digest=digest,
            idempotency_key=idempotency_key,
            outcome=outcome,
            version=version,
            requester_key_id=requester_key_id,
        )

    if config is None:  # defensive: _resolve_policy guarantees config when problem is None
        outcome = PolicyOutcome(
            "DENY",
            "POLICY_CONFIG_INVALID",
            _problem_explanation("POLICY_CONFIG_INVALID", tool_name),
        )
        return _persist_decision(
            db=db,
            project_id=project_id,
            run_id=run.id,
            tool_name=tool_name,
            tool_id=tool.id,
            redacted=redacted,
            digest=digest,
            idempotency_key=idempotency_key,
            outcome=outcome,
            version=version,
            requester_key_id=requester_key_id,
        )
    facts = _order_facts(db, arguments.get("order_id"))
    outcome = evaluate_refund(
        args=arguments, facts=facts, tool_registered=True, config=config
    )
    return _persist_decision(
        db=db,
        project_id=project_id,
        run_id=run.id,
        tool_name=tool_name,
        tool_id=tool.id,
        redacted=redacted,
        digest=digest,
        idempotency_key=idempotency_key,
        outcome=outcome,
        version=version,
        requester_key_id=requester_key_id,
    )


def simulate_decision(
    *,
    db: Session,
    project_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
) -> SimulateResult:
    """Preview the decision a policy version would make. Writes nothing.

    Evaluates against the latest version (an unactivated draft when one exists)
    so authors can preview before activating.
    """
    tool = _latest_tool(db, project_id, tool_name)
    if tool is None:
        return SimulateResult(
            "DENY",
            "UNKNOWN_TOOL",
            None,
            False,
            f"Tool '{tool_name}' is not registered for this project; failing closed.",
        )

    schema_problem = _validate_schema(tool.schema_json, arguments)
    if schema_problem is not None:
        return SimulateResult(
            "DENY", "MALFORMED_ARGUMENTS", None, False,
            f"Arguments failed the tool schema: {schema_problem}.",
        )

    name = POLICY_FOR_TOOL.get(tool_name)
    policy = (
        db.query(Policy).filter(Policy.project_id == project_id, Policy.name == name).first()
        if name
        else None
    )
    latest = None
    if policy is not None and policy.versions:
        latest = max(policy.versions, key=lambda v: v.version)
    if latest is None:
        return SimulateResult(
            "DENY", "POLICY_NOT_CONFIGURED", None, False,
            f"No policy version exists for tool '{tool_name}'; failing closed.",
        )
    try:
        config = RefundPolicyConfig.model_validate(latest.rules_json)
    except ValidationError:
        return SimulateResult(
            "DENY", "POLICY_CONFIG_INVALID", latest.version, latest.activated_at is None,
            f"Policy version {latest.version} configuration is invalid; failing closed.",
        )

    facts = _order_facts(db, arguments.get("order_id"))
    outcome = evaluate_refund(
        args=arguments, facts=facts, tool_registered=True, config=config
    )
    return SimulateResult(
        outcome.outcome,
        outcome.reason_code,
        latest.version,
        latest.activated_at is None,
        outcome.explanation,
    )
