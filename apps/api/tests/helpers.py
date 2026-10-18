"""Shared helpers for Phase 3 gateway/SDK tests.

Fixtures live in conftest.py; this module holds plain helper functions and
constants only.
"""

V1_RULES = {
    "tool_name": "refund_payment",
    "currency": "USD",
    "auto_approve_max_minor": 10000,
    "review_max_minor": 50000,
}

REFUND_ARGS = {"order_id": "ORD-100", "amount_minor": 4000, "currency": "USD"}


def authorize(client, key_headers, run_id, tool_name, arguments, idempotency_key):
    headers, _raw = key_headers
    resp = client.post(
        "/api/v1/tool-calls/authorize",
        json={
            "run_id": run_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "idempotency_key": idempotency_key,
        },
        headers=headers,
    )
    return resp


def execute(client, key_headers, call_id, arguments=None):
    headers, _raw = key_headers
    body = {} if arguments is None else {"arguments": arguments}
    return client.post(f"/api/v1/tool-calls/{call_id}/execute", json=body, headers=headers)


def order_balance(db_session, order_ref):
    from agenttrust_api.models import MockOrder

    session, _ = db_session
    order = session.query(MockOrder).filter(MockOrder.order_ref == order_ref).one()
    session.refresh(order)
    return order.refundable_remaining_minor
