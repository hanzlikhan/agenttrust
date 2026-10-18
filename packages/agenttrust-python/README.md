# agenttrust — Python SDK

Pre-execution authorization for tool-using AI agents. The SDK asks the
AgentTrust API whether a tool call may run **before** it runs; the trusted
gateway — not the SDK — performs the side effect.

```python
from agenttrust import AgentTrust, AuthorizationDenied, ApprovalRequired

trust = AgentTrust(api_key="YOUR_API_KEY", base_url="http://localhost:8000")

@trust.protect(tool="refund_payment")
def refund_payment(order_id: str, amount_minor: int, currency: str = "USD"):
    # NOTE: this body is never executed by the SDK. The real side effect
    # happens server-side in the trusted gateway after authorization.
    raise NotImplementedError

with trust.run(agent="refund-support-agent", version="0.1.0"):
    try:
        result = refund_payment(order_id="ORD-100", amount_minor=4000)
    except AuthorizationDenied as exc:
        print("denied:", exc.reason_code)
    except ApprovalRequired:
        print("sent to human review")
```

## Failure semantics (fail closed)

| Situation | Result |
|---|---|
| Policy says DENY | `AuthorizationDenied`; the execute endpoint is never called |
| Policy says REVIEW | `ApprovalRequired`; nothing executes |
| API unreachable / timeout / 5xx | `PolicyServiceUnavailable`; nothing executes |
| Bad API key | `ConfigurationError` |

`protect()`ed functions must be called inside a `trust.run(...)` block.
Calls are synchronous only. Every request carries a client-generated
`X-Correlation-ID` and a per-call idempotency key. Environment proxy variables
are ignored (`trust_env=False`): the SDK talks to the configured `base_url`
only, so auth-bearing traffic is never silently rerouted. Retries happen only
for safe, idempotent requests:
authorize retries reuse the same idempotency key, and execute is retried at
most once after a network failure because the server makes it idempotent
(single-use grant claim + one execution row per call in a single transaction).

## Install

```bash
pip install -e packages/agenttrust-python   # from the repo root
```
