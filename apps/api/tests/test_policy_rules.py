"""Unit tests for the deterministic refund policy rules.

Pure functions only — no database, no network, no LLM. This file is the
hand-written test oracle for every reason code.
"""

import pytest
from pydantic import ValidationError

from agenttrust_api.policy.canonical import args_hash, canonical_json, redact_args
from agenttrust_api.policy.rules import (
    OrderFacts,
    RefundPolicyConfig,
    evaluate_refund,
)

CONFIG = RefundPolicyConfig()  # auto 10000, review 50000, USD

ELIGIBLE_RICH = OrderFacts(
    order_ref="ORD-100", total_minor=40000, remaining_minor=40000, currency="USD",
    eligible=True,
)
ELIGIBLE_POOR = OrderFacts(
    order_ref="ORD-300", total_minor=20000, remaining_minor=5000, currency="USD",
    eligible=True,
)
INELIGIBLE = OrderFacts(
    order_ref="ORD-200", total_minor=100000, remaining_minor=100000, currency="USD",
    eligible=False,
)


def _args(order_id: str = "ORD-100", amount_minor: int = 4000, currency: str = "USD"):
    return {"order_id": order_id, "amount_minor": amount_minor, "currency": currency}


def _decide(args, facts=ELIGIBLE_RICH, registered=True, config=CONFIG):
    return evaluate_refund(args=args, facts=facts, tool_registered=registered, config=config)


def test_auto_approve_boundary():
    assert _decide(_args(amount_minor=10000)).outcome == "ALLOW"
    assert _decide(_args(amount_minor=10000)).reason_code == "AUTO_APPROVED"
    assert _decide(_args(amount_minor=10001)).outcome == "REVIEW"
    assert _decide(_args(amount_minor=10001)).reason_code == "APPROVAL_REQUIRED"


def test_review_cap_boundary():
    rich = OrderFacts(
        order_ref="ORD-100", total_minor=100000, remaining_minor=100000,
        currency="USD", eligible=True,
    )
    assert _decide(_args(amount_minor=50000), facts=rich).outcome == "REVIEW"
    assert _decide(_args(amount_minor=50001), facts=rich).outcome == "DENY"
    assert _decide(_args(amount_minor=50001), facts=rich).reason_code == "AMOUNT_EXCEEDS_MAX"


def test_ineligible_order_denied():
    outcome = _decide(_args(amount_minor=4000), facts=INELIGIBLE)
    assert outcome.outcome == "DENY"
    assert outcome.reason_code == "INELIGIBLE_ORDER"


def test_insufficient_balance_denied():
    outcome = _decide(_args(amount_minor=15000), facts=ELIGIBLE_POOR)
    assert outcome.outcome == "DENY"
    assert outcome.reason_code == "INSUFFICIENT_BALANCE"


def test_missing_order_denied():
    outcome = _decide(_args(order_id="ORD-999"), facts=None)
    assert outcome.outcome == "DENY"
    assert outcome.reason_code == "MISSING_CONTEXT"


def test_invalid_currency_denied():
    outcome = _decide(_args(currency="EUR"))
    assert outcome.outcome == "DENY"
    assert outcome.reason_code == "INVALID_CURRENCY"


@pytest.mark.parametrize("amount", [0, -1, -100000])
def test_invalid_amount_denied(amount):
    outcome = _decide(_args(amount_minor=amount))
    assert outcome.outcome == "DENY"
    assert outcome.reason_code == "INVALID_AMOUNT"


def test_unknown_tool_denied_fail_closed():
    outcome = _decide(_args(), registered=False)
    assert outcome.outcome == "DENY"
    assert outcome.reason_code == "UNKNOWN_TOOL"


def test_amount_cap_beats_other_reasons():
    # 90000 on an ineligible, zero-balance order: the cap violation is reported.
    facts = OrderFacts(
        order_ref="ORD-X", total_minor=0, remaining_minor=0, currency="USD", eligible=False
    )
    outcome = _decide(_args(amount_minor=90000), facts=facts)
    assert (outcome.outcome, outcome.reason_code) == ("DENY", "AMOUNT_EXCEEDS_MAX")


def test_deterministic_same_input_same_outcome():
    first = _decide(_args(amount_minor=15000))
    second = _decide(_args(amount_minor=15000))
    assert first == second


def test_explanations_are_safe_strings():
    outcome = _decide(_args(amount_minor=4000))
    assert isinstance(outcome.explanation, str) and outcome.explanation
    assert "sk-" not in outcome.explanation  # no secret-shaped content


def test_config_rejects_inverted_caps():
    with pytest.raises(ValidationError):
        RefundPolicyConfig(auto_approve_max_minor=50000, review_max_minor=10000)


def test_config_defaults():
    config = RefundPolicyConfig()
    assert config.auto_approve_max_minor == 10000
    assert config.review_max_minor == 50000
    assert config.currency == "USD"


def test_canonical_hash_stable_across_key_order():
    a = {"order_id": "ORD-100", "amount_minor": 4000, "currency": "USD"}
    b = {"currency": "USD", "amount_minor": 4000, "order_id": "ORD-100"}
    assert args_hash(a) == args_hash(b)
    assert canonical_json(a) == canonical_json(b)


def test_canonical_hash_changes_with_values():
    a = {"order_id": "ORD-100", "amount_minor": 4000, "currency": "USD"}
    b = {"order_id": "ORD-100", "amount_minor": 4001, "currency": "USD"}
    assert args_hash(a) != args_hash(b)


def test_redact_args_allowlist():
    args = {"order_id": "ORD-100", "amount_minor": 4000, "currency": "USD", "ssn": "x"}
    assert redact_args("refund_payment", args) == {
        "order_id": "ORD-100",
        "amount_minor": 4000,
        "currency": "USD",
    }


def test_redact_args_unknown_tool_drops_everything():
    assert redact_args("mystery_tool", {"a": 1}) == {}
