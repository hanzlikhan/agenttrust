"""Deterministic refund policy rules (M05).

Pure functions: no database, no network, no LLM. Every decision is a pure
function of (registered tool, canonical arguments, trusted order facts, active
policy version). Money is integer minor units throughout.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Outcome = Literal["ALLOW", "DENY", "REVIEW"]

# Explicit mapping of governed tool -> owning policy name. A tool with no entry
# here cannot be authorized: the service fails closed (POLICY_NOT_CONFIGURED).
POLICY_FOR_TOOL: dict[str, str] = {
    "refund_payment": "refund-policy",
}

# JSON Schema for refund_payment v1. Note: amount bounds are enforced by the
# *policy rules* (INVALID_AMOUNT / thresholds), not by the schema, so that
# out-of-range amounts produce auditable DENY decisions rather than 422s.
# Floats are rejected by "type": "integer" (jsonschema excludes bool/float).
REFUND_PAYMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "amount_minor": {"type": "integer"},
        "currency": {"type": "string", "minLength": 3, "maxLength": 3},
    },
    "required": ["order_id", "amount_minor", "currency"],
    "additionalProperties": False,
}


class RefundPolicyConfig(BaseModel):
    """Validated policy configuration for the refund tool."""

    tool_name: str = "refund_payment"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    auto_approve_max_minor: int = Field(default=10000, ge=0)
    review_max_minor: int = Field(default=50000, ge=0)

    @model_validator(mode="after")
    def _caps_ordered(self) -> "RefundPolicyConfig":
        if self.review_max_minor < self.auto_approve_max_minor:
            raise ValueError("review_max_minor must be >= auto_approve_max_minor")
        return self


@dataclass(frozen=True)
class OrderFacts:
    """Trusted business facts from the server-owned order record — never from
    agent claims."""

    order_ref: str
    total_minor: int
    remaining_minor: int
    currency: str
    eligible: bool


@dataclass(frozen=True)
class PolicyOutcome:
    outcome: Outcome
    reason_code: str
    explanation: str


def _minor(amount: int) -> str:
    return f"{amount} minor units"


def evaluate_refund(
    *,
    args: dict[str, Any],
    facts: OrderFacts | None,
    tool_registered: bool,
    config: RefundPolicyConfig,
) -> PolicyOutcome:
    """Deterministically decide a refund_payment call.

    Rule order is deliberate and fail-closed: structural problems first, then
    trust problems, then amount problems, then the allow/review split.
    """
    order_ref = str(args.get("order_id", "?"))

    if not tool_registered:
        return PolicyOutcome(
            "DENY",
            "UNKNOWN_TOOL",
            "Tool 'refund_payment' is not registered for this project; failing closed.",
        )
    if facts is None:
        return PolicyOutcome(
            "DENY",
            "MISSING_CONTEXT",
            f"No trusted order record for '{order_ref}'; cannot evaluate eligibility.",
        )

    currency = args.get("currency")
    if currency != config.currency:
        return PolicyOutcome(
            "DENY",
            "INVALID_CURRENCY",
            f"Currency '{currency}' is not governed by this policy (requires {config.currency}).",
        )

    amount = args.get("amount_minor")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
        return PolicyOutcome(
            "DENY",
            "INVALID_AMOUNT",
            f"Amount must be a positive integer of minor units; got {amount!r}.",
        )

    if amount > config.review_max_minor:
        return PolicyOutcome(
            "DENY",
            "AMOUNT_EXCEEDS_MAX",
            f"{_minor(amount)} exceeds the policy maximum of "
            f"{_minor(config.review_max_minor)}.",
        )
    if not facts.eligible:
        return PolicyOutcome(
            "DENY",
            "INELIGIBLE_ORDER",
            f"Order '{order_ref}' is not eligible for refunds.",
        )
    if amount > facts.remaining_minor:
        return PolicyOutcome(
            "DENY",
            "INSUFFICIENT_BALANCE",
            f"{_minor(amount)} exceeds the remaining refundable balance of "
            f"{_minor(facts.remaining_minor)} on order '{order_ref}'.",
        )
    if amount <= config.auto_approve_max_minor:
        return PolicyOutcome(
            "ALLOW",
            "AUTO_APPROVED",
            f"Auto-approved: {_minor(amount)} within the auto-approve limit of "
            f"{_minor(config.auto_approve_max_minor)} for eligible order '{order_ref}'.",
        )
    return PolicyOutcome(
        "REVIEW",
        "APPROVAL_REQUIRED",
        f"{_minor(amount)} exceeds the auto-approve limit of "
        f"{_minor(config.auto_approve_max_minor)}; human review required before execution.",
    )
