# Refund support agent — live demo

A synthetic customer-support agent that issues refunds through the AgentTrust
SDK. Every call in this demo hits the real API: nothing is mocked.

## Run it

```bash
# 1. From apps/api: migrate and seed (prints a copy-once API key)
PYTHONPATH=src alembic upgrade head
PYTHONPATH=src python -m agenttrust_api.seed

# 2. Start the API
PYTHONPATH=src uvicorn agenttrust_api.main:app --port 8000

# 3. Install the SDK (from the repo root)
pip install -e packages/agenttrust-python

# 4. Run the demo
export AGENTTRUST_API_KEY='<key printed by the seed>'
python examples/refund-support-agent/demo.py
```

## What it shows

- **S1** — `$40` refund on `ORD-100`: policy says ALLOW, the gateway executes,
  the balance drops by exactly 4000 minor units.
- **S3** — `$900` refund: policy says DENY (`AMOUNT_EXCEEDS_MAX`); the SDK
  raises `AuthorizationDenied` and the execute endpoint is never called. A
  follow-up probe proves the balance did not move.
- **S5** — the same authorize request sent twice returns one decision
  (201 then 200 replay); the same execute sent twice returns one execution
  (201 then 200 replayed). The balance moves exactly once.

Each run consumes synthetic balance on `ORD-100` (40000 minor units seeded);
re-running works until the balance is exhausted.
