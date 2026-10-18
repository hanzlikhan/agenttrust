# AgentTrust API Reference

> **Generated from the live OpenAPI schema** (`GET /openapi.json`) fetched from a
> locally running API (`AgentTrust API 0.1.0`, uvicorn, real PostgreSQL) on
> 2026-10-17. Field names, required flags, and enums below come from the schema,
> not from memory. Items explicitly marked **unverified in this pass** were read
> from code/schema but not exercised with a live request.

Base URL (dev): `http://localhost:8000` · All API routes are prefixed `/api/v1`.
Schema completeness check in this pass: **34 paths / 38 operations, all 13 v1
routers represented** (health, keys, runs, tools, policies, toolcalls,
approvals, incidents, evaluations, events, dashboard, agents, metrics) — nothing missing.

## Authentication

- **Project API keys** — `Authorization: Bearer <key>` header on every `/api/v1`
  route except key issuance itself. Verified live in this pass (real key created
  in DB, used for requests, then deleted).
  - Bad/missing key → `401 {"error_code":"invalid_api_key","message":"Invalid API key.",...}`
    (verified live).
- **SSE stream** — `GET /api/v1/events/stream` takes the key as the **`api_key`
  query parameter** instead of the header (code-verified in `routers/events.py`,
  ADR-027; browsers' `EventSource` cannot send headers) — *unverified in this pass*.
- **Admin bearer <redacted>** — `POST /api/v1/keys` (issue), `GET /api/v1/keys` (list),
  `POST /api/v1/keys/{key_id}/revoke` require the configured admin token
  (`AGENTTRUST_ADMIN_TOKEN`); key issuance is admin-only. Code-verified in
  `deps.py` (`require_admin`) — *unverified in this pass* (no admin token set in
  this environment).
- **Reviewer keys** — `POST /api/v1/approvals/{approval_id}/decision` requires a
  key holding the `approvals:decide` scope; separation of duties (requester key
  ≠ reviewer key) is enforced. Code-verified in `deps.py` (`require_reviewer`) —
  *unverified in this pass*.
- Rate limiting is applied per key (per-key minute buckets); scope violations
  return `403 {"error_code":"insufficient_scope",...}` (code-verified, *unverified
  in this pass*).

## Standard error envelope

Every error response (verified live via an unauthenticated request) has this shape:

```json
{
  "error_code": "invalid_api_key",
  "message": "Invalid API key.",
  "request_id": "c875836a560c471e",
  "retryable": false
}
```

Every response also carries an `X-Request-ID` header.

## Endpoints

### POST /api/v1/runs — start an agent run ✅ live-verified

Request (`RunCreateRequest`):

```json
{ "agent_name": "support-bot", "agent_version": "1.2.0", "environment": "prod" }
```

`agent_name` required; `agent_version`/`environment` optional. Live `201` response:

```json
{
  "run_id": "e03576d1-7758-4372-8c33-fb95989a7812",
  "trace_id": "55b4d17f-4c16-4e54-b652-ead646df307f",
  "agent_name": "docs-smoke",
  "agent_version": "0.1",
  "state": "RUNNING",
  "started_at": "2026-10-17T17:37:31.427910+05:00"
}
```

### POST /api/v1/tool-calls/authorize — pre-execution policy check ✅ live-verified

Request (`AuthorizeRequest`; all four required):

```json
{
  "run_id": "<uuid>",
  "tool_name": "refund_payment",
  "arguments": { "order_id": "ORD-1", "amount_minor": 500, "currency": "PKR" },
  "idempotency_key": "unique-per-attempt"
}
```

Response (`AuthorizeResponse`) — live example (outcome `DENY`):

```json
{
  "tool_call_id": "54433e5f-896a-4dc0-9dbc-4e26f0c31483",
  "decision_id": "67fa6f84-6956-4a60-a7be-075176fad03b",
  "outcome": "ALLOW | DENY | REVIEW",
  "reason_code": "MISSING_CONTEXT",
  "policy_version": 1,
  "decided_at": "2026-10-17T12:37:44.476744Z",
  "explanation": "No trusted order record for 'ORD-1'; cannot evaluate eligibility.",
  "approval_id": "<uuid, only when outcome=REVIEW>"
}
```

### POST /api/v1/tool-calls/{call_id}/execute — consume a grant *(unverified in this pass)*

Request (`ExecuteRequest`): `arguments` (optional — must hash-match the
authorized arguments when supplied). Response (`ExecuteResponse`):
`tool_call_id`, `execution_id`, `state`, `result` (object), `replayed`
(boolean — `true` when the idempotency key replayed a prior execution).

### GET /api/v1/approvals — pending queue *(unverified in this pass)*

Paginated list (`ApprovalQueueResponse`): `approvals[]`, `total`, `limit`,
`offset`. Detail: `GET /api/v1/approvals/{approval_id}`;
`GET /api/v1/approvals/{approval_id}/status` (lightweight state poll).

### POST /api/v1/approvals/{approval_id}/decision — reviewer decision *(unverified in this pass)*

Requires `approvals:decide` scope. Request (`ApprovalDecisionRequest`):

```json
{ "decision": "approved", "reason": "verified with customer", "expected_row_version": 3 }
```

`decision` required, enum `["approved","rejected"]`; `expected_row_version`
required for optimistic concurrency (stale → `409`).

### GET /api/v1/metrics — project-scoped operational counters ✅ live-verified

Response (`MetricsResponse`) — live example:

```json
{
  "project_id": "8c8188d2-9c81-4cdc-a0c7-00cd6319b6ce",
  "decisions_by_outcome": { "ALLOW": 4, "DENY": 2, "REVIEW": 1 },
  "executions_total": 4,
  "active_approvals": 0,
  "incidents_by_status": { "OPEN": 1 },
  "generated_at": "2026-10-17T12:37:31.408776Z"
}
```

Counts come only from committed rows for the caller's project — never fabricated.

### GET /api/v1/incidents · POST /api/v1/incidents/scan · POST /api/v1/incidents/{id}/analyze *(unverified in this pass)*

List (`incidents[]`, `total`, `limit`, `offset`); `scan` runs the deterministic
detector → `{"incidents_created": n, "checked": {...}}`; `analyze` returns
`{"incident_id", "report": {...}}`; `PATCH /api/v1/incidents/{id}` updates status.

### POST /api/v1/evaluations/run · GET /api/v1/evaluations/runs · GET .../report *(unverified in this pass)*

Run the benchmark suite → `EvaluationRunDetailResponse` (`run`, `metrics`,
`results[]`); `GET /api/v1/evaluations/runs/{run_id}/report` returns the report
document.

### GET /api/v1/events/stream — SSE telemetry *(unverified in this pass)*

Query params: `api_key=<key>` (required, since headers can't be sent by
`EventSource`), `cursor` (optional, for reconnect backfill). Per ADR-029 there
is **no** `event:` SSE line — the event kind is in the data envelope.

### Other routes (from schema; *unverified in this pass*)

- `GET /health/live`, `GET /health/ready` — liveness/readiness (no auth).
- `POST /api/v1/keys`, `GET /api/v1/keys`, `POST /api/v1/keys/{key_id}/revoke`
  (admin token); `GET /api/v1/me` — caller's project/scopes.
- `POST /api/v1/tools`, `GET /api/v1/tools` — tool registration/listing.
- `POST /api/v1/policies`, `GET /api/v1/policies`,
  `POST /api/v1/policies/{policy_id}/activate`, `POST /api/v1/policies/simulate`
  — policy management and dry-run simulation.
- `POST /api/v1/runs/{run_id}/events` — SDK telemetry ingestion (batch).
- `GET /api/v1/dashboard/summary|/runs|/runs/{id}|/analytics` — dashboard reads.
- `GET /api/v1/agents`, `GET /api/v1/agents/{agent_id}` — agent registry.

## Regenerating

```bash
cd apps/api
DATABASE_URL="postgresql+psycopg://agenttrust:agenttrust@localhost:5432/agenttrust" \
PYTHONPATH=src .venv/bin/python -m uvicorn agenttrust_api.main:app --port 8000 &
sleep 4
curl -s http://localhost:8000/openapi.json | python3 -m json.tool > /tmp/openapi.json
# diff against a previously saved copy, then update this doc's verified sections
```
