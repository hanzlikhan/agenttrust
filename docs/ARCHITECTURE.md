# AgentTrust — Architecture

**Status:** Phase 0 — documented intent only; nothing implemented.
**Spec refs:** §§3–8. **Date:** 2026-10-17 (UTC).

## 1. System shape: modular monolith

One deployable backend (`apps/api`) with strict internal module boundaries, one Next.js frontend
(`apps/web`), one Python SDK package (`packages/agenttrust-python`), one example agent, one evaluation
suite, and shared infrastructure — all in one monorepo. No microservices, no Redis, no Kubernetes, no
message broker for the MVP (spec §4.1, §10, ADR-004).

### 1.1 Module boundaries

| Boundary | Owns | Must NOT depend on |
|---|---|---|
| HTTP transport (`apps/api`) | Routing, serialization, auth middleware, SSE feed, OpenAPI | Business rules, policy logic, gateway internals |
| Authentication & authorization | Credential verification, project scoping, scopes, reviewer roles | Any single domain module |
| Business logic / domain | Runs, tool calls, approvals, incidents, evaluations | HTTP framework objects, frontend code |
| Policy evaluation | Deterministic rule functions + Pydantic configs; version pinning | LLM output, untrusted agent data, UI |
| Protected tool execution | Mock payment gateway; grant verification; balance mutation | SDK client, agent process |
| Persistence | SQLAlchemy models, Alembic migrations, transactions | HTTP handlers (handlers call repositories/services, not vice versa) |
| Event publishing | Outbox writes in the same transaction; worker reads and pushes to SSE | Browser state |
| AI investigation | LangGraph graph over redacted evidence; Pydantic-validated, citation-checked output | Policy tables (read-only access to evidence views) |
| Background processing | Worker jobs: outbox publish, approval expiry, eval runs, incident analysis, retention cleanup | Request/response cycle (long jobs never hold HTTP open) |
| User interface | Next.js pages; REST snapshot then SSE patch; optimistic updates only where safe | Decision authority (the dashboard never authorizes execution) |

Dependency rule: transport → domain services → persistence. The policy engine and the gateway sit behind
the domain layer and never import HTTP or UI code. The AI investigator is read-only against evidence views
and writes only incident-report rows.

## 2. Policy evaluation pipeline (spec §8 directive / M05–M06)

```
Incoming tool call
  → Authentication (scoped API token → project identity from the credential)
  → Request schema validation (Pydantic; registered tool schema wins over requester claims)
  → Project and tool authorization (tool allowlist, key scopes, role checks)
  → Trusted business context retrieval (server-owned records: eligibility, refundable balance;
     NEVER agent-supplied claims)
  → Policy evaluation (deterministic rules on canonicalized args + trusted context;
     models play no role in the verdict)
  → ALLOW / DENY / REVIEW
  → Enforced execution or suspension
  → Durable event recording (tool_call + policy_decision + outbox row, one transaction)
```

Each decision carries: unique decision ID, tool call ID, outcome, reason code, applicable policy version,
UTC timestamp, safe explanation.

## 3. End-to-end event pipeline (spec §4.2)

```
Agent execution → Python SDK → Backend ingestion → Single DB transaction
  → Durable event (+ transactional outbox row) → Publisher worker
  → Project-scoped SSE stream → Next.js dashboard → visible execution timeline
```

1. SDK sends authorization request with trace/run IDs and an idempotency key.
2. API authenticates, validates schemas, resolves trusted facts.
3. Policy engine decides ALLOW / DENY / REVIEW.
4. API commits `tool_call`, `policy_decision`, and `outbox` rows in **one** database transaction.
5. Worker (PostgreSQL `SKIP LOCKED` lease) reads the committed outbox row and publishes a project-scoped
   SSE message with a per-project monotonic server sequence.
6. Browser applies the message, deduplicated by event ID.
7. On disconnect: exponential-backoff reconnect, then `Last-Event-ID` backfill from the database; the
   cursor is validated inside the authenticated project.
8. The dashboard is eventually consistent with committed events — never the authority for executing tools.

Consistency guarantee (stated, not overstated): within a project, events are ordered by server sequence;
across projects, no ordering claim. Duplicates are possible; consumers dedupe by event ID. The UI is
event-driven near-real-time, **not** hard real-time.

## 4. Secure execution model (M07, ADR-002)

The gateway — a backend endpoint inaccessible to the agent except through authorization — performs, at
execution time, inside one transaction:

- identity and operation re-verification
- canonical argument hash equality against the authorized call (mismatch → reject)
- approval/policy validity and version re-check (policy changed since grant → revalidate or invalidate)
- authorization expiry and single-use grant claim (consumed grant → reject; replay returns prior outcome
  or a conflict — never a second side effect)
- row lock on the synthetic order; balance updated once; business effect + execution result committed durably

The SDK's authorization response alone is never sufficient. Fail-closed on policy-service unavailability.

## 5. Data model summary

Full table list, columns, and constraints: spec §6 (summarized in REQUIREMENTS_TRACEABILITY.md S06-01–S06-27).
Key invariants:

- `api_keys`: store `key_hash` + `key_prefix`; never the raw key.
- `tool_calls`: unique `(project_id, idempotency_key)` — the idempotency anchor.
- `policy_versions`: immutable once active; decisions pin the exact version.
- `approvals`: one active approval per tool call; `row_version` for optimistic concurrency.
- `execution_grants`: unique, single-use, expiring; consumed atomically with the effect.
- `tool_executions`: unique successful execution per call.
- `mock_orders`: money as integer minor units (`total_minor`, `refundable_remaining_minor`); transactionally locked.
- `events` / `outbox`: append-only logical events; unique event ID in the outbox.
- `audit_events`: append-only at the application level (privileged DB admin is out of scope — see THREAT_MODEL.md).
- Hashing: canonical JSON (stable property order, defined numeric representation); cross-client consistency tested.
- Timestamps: UTC ISO-8601 with timezone. IDs: UUIDv7/UUID4.

## 6. State machines (spec §4.4)

- **Tool call:** `REQUESTED → POLICY_CHECKED → DENIED | APPROVAL_PENDING | AUTHORIZED → EXECUTING → SUCCEEDED | FAILED`.
  Approvals may become `APPROVED | REJECTED | EXPIRED`; `APPROVED → AUTHORIZED` only after renewed checks.
  Terminal states never regress.
- **Run:** `CREATED → RUNNING → COMPLETED | FAILED | TIMED_OUT`.
- **Incident:** `OPEN → INVESTIGATING → RESOLVED | DISMISSED`; reopening is an audited transition.
- **Worker job:** `QUEUED → CLAIMED → SUCCEEDED | RETRY_WAIT | DEAD_LETTER`.

All transitions are validated; illegal transitions return structured errors and audit events.

## 7. Why these choices

- **Modular monolith over microservices:** one developer, one deployable unit, in-process calls for the
  security-critical path (fewer network hops on the decision path, fewer failure modes). Boundaries are
  module-level so services can be extracted later if a real scaling requirement appears.
- **PostgreSQL as database + outbox + job store:** the outbox pattern gives durable exactly-once-ish
  delivery semantics without a broker; `SKIP LOCKED` worker leases are proven and need no extra process
  (ADR-004).
- **SSE over WebSockets:** updates are one-way (server → dashboard); SSE gives HTTP auth, proxies, and
  automatic reconnect semantics for free. Approval commands are normal POSTs (ADR-003).
- **Deterministic policy engine:** security decisions must be explainable, versioned, and testable; model
  judgment cannot provide any of those (ADR-001).
- **Trusted gateway:** client-side (SDK) interception is cooperative and bypassable; only server-side
  verification at execution time is an enforcement boundary (ADR-002).
- **Zero required paid services:** localhost PostgreSQL + FastAPI + Next.js + optional Ollama keeps the
  entire demo and test suite runnable on a modest laptop (spec §10).
