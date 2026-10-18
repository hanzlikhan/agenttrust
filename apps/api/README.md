# AgentTrust API (Phase 2 — policy engine)

FastAPI service providing health probes, project API-key management, and the
deterministic pre-execution policy engine (no LLM anywhere in the decision path).
Database: PostgreSQL, managed with Alembic migrations.

## Setup

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

PostgreSQL (local):

```bash
sudo apt-get install -y postgresql
sudo -u postgres psql -c "CREATE ROLE agenttrust WITH LOGIN PASSWORD 'agenttrust';"
sudo -u postgres psql -c "CREATE DATABASE agenttrust OWNER agenttrust;"
```

Configure (`.env` is gitignored — never commit it):

```bash
cp .env.example .env
# then fill in DATABASE_URL and ADMIN_TOKEN
```

Migrate and seed:

```bash
alembic upgrade head
PYTHONPATH=src python -m agenttrust_api.seed   # prints one API key, copy-once
```

Run:

```bash
PYTHONPATH=src uvicorn agenttrust_api.main:app --reload --port 8000
```

## Checks

```bash
ruff check .
pytest
```

Tests use a real PostgreSQL test database (`agenttrust_test` by default;
override with `DATABASE_URL_TEST`). Migration tests use a scratch database
(`agenttrust_migtest`, override with `DATABASE_URL_MIGTEST`).

## Endpoints (Phase 1)

- `GET /health/live` — liveness, no auth
- `GET /health/ready` — readiness, pings PostgreSQL, no auth
- `POST /api/v1/keys` — issue a key (admin token required; secret shown once)
- `GET /api/v1/keys` — list keys, redacted (admin token required)
- `POST /api/v1/keys/{id}/revoke` — revoke a key (admin token required)
- `GET /api/v1/me` — project identity for a presented API key

## Endpoints (Phase 2 — policy engine)

All SDK routes authenticate with a project API key (`Authorization: Bearer at_…`);
tool/policy administration requires the admin token.

- `POST /api/v1/runs` — open a run (agent get-or-create); returns `run_id` + `trace_id`
- `POST /api/v1/tools` — register a tool version (slug, JSON Schema, risk class)
- `GET /api/v1/tools` — list this project's tool versions
- `POST /api/v1/policies` — create a policy draft (rules validated on receipt)
- `POST /api/v1/policies/{id}/activate` — activate the latest draft (immutable after)
- `GET /api/v1/policies` — list policies with versions
- `POST /api/v1/policies/simulate` — non-mutating decision preview (writes nothing)
- `POST /api/v1/tool-calls/authorize` — deterministic ALLOW/DENY/REVIEW decision;
  persists `tool_call` + `policy_decision` atomically; idempotent on
  `(project_id, idempotency_key)` (200 replay / 409 on changed payload)

Seeded demo (via `python -m agenttrust_api.seed`): `refund_payment` v1,
`refund-policy` v1 active (auto-approve ≤ 10000, review ≤ 50000 minor units, USD),
mock orders `ORD-100` (eligible, 40000 remaining), `ORD-200` (ineligible),
`ORD-300` (eligible, 5000 remaining).
