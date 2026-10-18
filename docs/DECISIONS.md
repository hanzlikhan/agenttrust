# AgentTrust — Architecture Decision Records

**Status:** Phase 0 — decisions recorded from the spec; nothing implemented.
**Date:** 2026-10-17 (UTC).

Conventions: each ADR records context, decision, consequences, and alternatives rejected. Where the spec is
silent, the question is parked under "Open decisions" rather than invented.

---

## ADR-001 — Security decisions are deterministic and model-independent

- **Context:** LLM outputs are stochastic, prompt-sensitive, and manipulable by untrusted text.
- **Decision:** All pre-execution verdicts (ALLOW / DENY / REVIEW) are produced by deterministic,
  Pydantic-validated rule functions over canonicalized arguments and server-owned trusted facts. Models
  play no role in any authorization path.
- **Consequences:** Verdicts are explainable (reason code + policy version), replayable, and unit-testable
  against a hand-written oracle. Prompt-injection strings become ordinary test inputs.
- **Rejected:** LLM-as-judge authorization (untestable, injectable), external policy engines like OPA for
  the MVP (unnecessary dependency for one demo tool).

## ADR-002 — A trusted gateway is necessary; the SDK alone is not enforcement

- **Context:** The Python SDK runs in the agent's process and is cooperative — a bypassing caller can invoke
  the underlying function directly.
- **Decision:** Protected side effects execute only behind a server-side gateway endpoint that, at execution
  time and inside one transaction, re-verifies identity, canonical argument hash, approval/policy validity,
  grant expiry, and single-use status. The SDK's authorization response alone never authorizes execution.
- **Consequences:** Replay, argument tampering, and stale-approval attacks are decided server-side; the
  product's security claim is testable (S3/S4/S5 scenarios).
- **Rejected:** Client-side-only interception (the spec's named "SDK security theater" risk).

## ADR-003 — SSE instead of WebSockets for the MVP

- **Context:** Dashboard updates flow one way (server → browser); approval commands are ordinary POSTs.
- **Decision:** Server-Sent Events for the live stream: project-scoped, `Last-Event-ID` resume, per-project
  monotonic server sequence, heartbeats.
- **Consequences:** HTTP-native auth, proxy-friendly, free reconnect semantics; no socket protocol to secure.
  Limitation: one-way only — all mutations stay REST, which matches the design anyway.
- **Rejected:** WebSockets (bidirectional channel with no consumer), paid realtime vendors (zero-cost boundary).

## ADR-004 — PostgreSQL serves as database, outbox, and job store initially

- **Context:** A broker (Redis/RabbitMQ) would add a process, a client library, and an operational story for
  a solo developer with no documented scaling requirement.
- **Decision:** Transactional outbox + a PostgreSQL-backed worker using `SKIP LOCKED` leases, exponential
  backoff, and dead-letter states. No Redis or distributed orchestration for the MVP.
- **Consequences:** Exactly-once-ish delivery via unique event IDs + idempotent handlers; worker recovery via
  lease expiry. Limitation: polling cadence is seconds/minutes — near-real-time, not hard real-time.
- **Rejected:** Redis/queue hosting (cost + complexity without a justified requirement).

## ADR-005 — Raw prompt contents are not stored by default

- **Context:** Traces can capture passwords, customer details, and other PII (spec §2: "sensitive logging").
- **Decision:** `AGENTTRUST_CAPTURE_RAW_PAYLOADS=false` by default. Ingestion applies redaction and field
  allowlists before storage; capturing sensitive fields requires explicit opt-in. Event payloads store the
  redacted structured form.
- **Consequences:** Incident evidence is safe to display and export; seeded-credential scans (S13-14) verify
  the property. Limitation: some debugging context is unavailable unless opted in.

## ADR-006 — Local LLM incident investigation is optional

- **Context:** Local inference needs substantial CPU/RAM; the developer's hardware is not yet confirmed, and
  a paid model API would violate the zero-cost boundary.
- **Decision:** The LangGraph investigator (Collector → Analyzer → Validator) is optional behind
  `AGENTTRUST_ENABLE_LOCAL_AI=false`. Deterministic template reports with the exact policy reason are the
  always-available fallback; all security functionality works with no model at all.
- **Consequences:** No hardware gate on the MVP; AI text is labeled "AI-assisted, non-authoritative" and
  citation-checked against recorded evidence. Model timeout is an analysis failure, never an enforcement failure.
- **Rejected:** Required cloud LLM (cost), and required local LLM (hardware gate).

## ADR-007 — Project-scoped event IDs and idempotency keys are essential

- **Context:** Retries, duplicate submissions, and multi-tenant streams are the normal case, not edge cases.
- **Decision:** `unique(project_id, idempotency_key)` on tool calls; per-project monotonic server sequence on
  events; `Last-Event-ID` cursors validated inside the authenticated project; deduplication by event ID on
  the client.
- **Consequences:** Replay returns prior outcomes instead of new effects; reconnects backfill without gaps;
  cross-project cursor probing leaks nothing.
- **Rejected:** Global sequences (cross-tenant leakage risk), client-generated ordering (untrusted).

## ADR-008 — Modular monolith, docs-first

- **Context:** One developer, security-critical paths, and a portfolio audience evaluating engineering discipline.
- **Decision:** A modular monolith with explicit layer boundaries (ARCHITECTURE.md §1.1), developed
  docs-first: this Phase 0 record set exists before any implementation code, and the requirements matrix is
  updated in every phase. Nothing is marked implemented without executable evidence.
- **Consequences:** Slower start, but every later claim (benchmarks, security properties) traces to a recorded
  requirement and a gate. Scope stays at "one language, one demo tool, one project initially."

---

## Open decisions (not decided in Phase 0)

1. **Product role:** portfolio piece vs sellable product. The spec names no buyer, price, or sales channel.
   Until this is decided, treat AgentTrust as a portfolio/engineering-demonstration project; do not design
   billing, multi-tenancy beyond project scoping, or a sales motion.
2. **Ollama model choice:** hardware-dependent (user's machine specs unconfirmed). Defer until Phase 7;
   deterministic fallback covers the gap. No paid cloud model without explicit approval.
3. **Auth mode for local demo:** spec M01 allows "passwordless local-demo owner mode (bound only to
   loopback) or open-source local authentication." Default planned: passwordless loopback single-owner for
   the demo, with reviewer identity as a separate local account to demonstrate separation of duties.
   Revisit in Phase 1 before building.
4. **License:** spec lists a license as a deliverable but does not choose one. Candidates: MIT or
   Apache-2.0. Decide in Phase 8 (or earlier if publishing the repo publicly).
5. **Demo currency and thresholds:** spec examples use USD (10000 minor units auto-allow, 10001–50000
   review, cap 50000+) and a $400-balance/$40/$150/$900 scenario set. Keep as the seed defaults unless
   the product-role decision changes the target audience.
6. **Retention default:** spec suggests 14–30 days (`AGENTTRUST_EVENT_RETENTION_DAYS`). Pick the concrete
   default in Phase 1.
7. **Python/Node versions:** spec says Python 3.12+ and Node current LTS "verify library compatibility."
   Pin exact versions in Phase 1 after compatibility checks; record them in the living spec.

---

## Phase 1 decisions (2026-10-17, recorded during implementation)

### ADR-009 — Admin bearer token for key management (Phase 1 auth mode)

- **Context:** Open question #3 allowed "passwordless local-demo owner mode (bound only to loopback) or
  open-source local authentication," to be revisited in Phase 1 before building.
- **Decision:** Key issuance/listing/revocation require a bearer `ADMIN_TOKEN` from the environment
  (`require_admin`); project-scoped SDK routes authenticate via `at_`-prefixed API keys
  (`require_api_key`). If `ADMIN_TOKEN` is empty, key-management endpoints return 503 — fail closed,
  never fail open. API key secrets are shown once on issuance; only prefix + SHA-256 hash persist.
- **Consequences:** Simple, auditable, no password database in Phase 1. Reviewer separation of duties
  still needs a real identity model — revisit before the Phase 5 approval UI.
- **Rejected:** Passwordless loopback-only mode (weaker audit story once the API leaves localhost).

### ADR-010 — Tailwind CSS deferred to Phase 6

- **Context:** Phase 1 frontend is a single API-status page; the design system lands in Phase 6.
- **Decision:** No Tailwind in Phase 1. Minimal CSS only. Recorded so the Phase 6 design-system pass
  is an explicit, planned step — not forgotten scope.
- **Rejected:** Installing Tailwind now for one page (dependency without a consumer).

### ADR-011 — Verification limits of this build environment

- **Context:** The build environment has no Docker engine, so `docker compose config` / `docker compose up`
  cannot be executed here.
- **Decision:** `docker-compose.yml` is parse-validated (Python YAML) with structural assertions
  (services db/api/web, no worker yet, all ports loopback-bound), but `config`/`up` must be run on a
  Docker host and the outcome recorded in PROGRESS.md. PostgreSQL 16 was installed via apt for real
  database tests instead of a container.
- **Consequences:** Honest gate: Phase 1's compose gate is "YAML valid, not yet executed."

### ADR-012 — Python src-layout, venv, and dependency files

- **Context:** Needed a reproducible local layout for the API package, Alembic, seed CLI, and pytest.
- **Decision:** `src/` layout (`src/agenttrust_api/`); `requirements.txt` + `requirements-dev.txt`
  (dependency list per directive); venv at `apps/api/.venv` (gitignored); `PYTHONPATH=src` for
  Alembic/seed/uvicorn; pytest `pythonpath = ["src"]` in `pyproject.toml`; ruff config in
  `pyproject.toml` with B008 ignored (FastAPI `Depends()` idiom) — documented, not hidden.
- **Consequences:** One documented setup path in `apps/api/README.md`.

### ADR-013 — Version pins resolved 2026-10-17

- Python 3.12.3, PostgreSQL 16.15, Node v24.20.0, npm 10.9.4.
- Python packages (pip-resolved): FastAPI 0.143.3, uvicorn 0.54.0, SQLAlchemy 2.1.5, Alembic 1.20.0,
  psycopg[binary] 3.3.6, Pydantic 2.14.1, pydantic-settings 2.16.0, pytest 9.1.1, httpx 0.28.1,
  ruff 0.17.1. Frontend: Next.js 15, React 19 (per web slice).
- **Decision:** Minimum pins in requirements files; exact resolved versions recorded here.

### ADR-014 — Local dev secrets posture

- **Context:** Local demo needs a database credential and an admin token without committing secrets.
- **Decision:** `.env` is gitignored and holds real local values; `.env.example` keeps empty
  placeholders only. The local Postgres role uses a documented loopback-only dev password
  (`agenttrust`); the local `ADMIN_TOKEN` is a generated random value. Compose binds all ports to
  `127.0.0.1`. No secret is committed to the repo.
- **Consequences:** Safe for a local demo; must be replaced before any network-exposed deployment.

### Scope note — tables deferred out of Phase 1

- The Phase 0 plan listed `agents`, `mock_orders`, and `audit_events` tables in Phase 1. The Phase 1
  build directive scoped migrations to the four identity tables (`users`, `projects`, `memberships`,
  `api_keys`) that Phase 1 features actually need.
- **Decision:** `agents` + `mock_orders` land in Phase 3 with the gateway/SDK that first needs them;
  `audit_events` lands with the M15 audit-trail work (key-issuance audit included). The traceability
  matrix keeps those rows Pending until then.

---

## Phase 2 decisions (2026-10-17, recorded during implementation)

### ADR-015 — Unknown tool → persisted DENY (UNKNOWN_TOOL), not 422/404

- **Context:** An authorize request can name a tool with no registered version for the project.
- **Decision:** Return a persisted `DENY` decision with reason `UNKNOWN_TOOL` (`tool_calls.tool_id` NULL, `policy_decisions.version_id` NULL) instead of a 422/404. Rationale: fail-closed *and* auditable — every attempted action leaves evidence, which the M11 incident detector and the M12 benchmark ("unknown tool" cases expect DENY) both rely on.
- **Consequences:** `tool_calls.tool_id` and `policy_decisions.version_id` are nullable by design.

### ADR-016 — REVIEW decisions carry `approval_id: null` until Phase 5

- **Context:** The authorize response schema reserves `approval_id`, but approvals don't exist yet.
- **Decision:** Always return `approval_id: null` in Phase 2 and document it in the schema description and PROGRESS.md, rather than inventing a half-approval workflow. A REVIEW decision records that human review is *required*; issuance happens in Phase 5.
- **Rejected:** Skipping the field (breaks the documented contract) or minting stub approvals (fake workflow).

### ADR-017 — Canonical argument hash scheme

- **Context:** Idempotency and tamper-evidence need a stable argument digest.
- **Decision:** `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)` → SHA-256 hex. Floats are rejected *before* schema validation because JSON Schema 2020-12 treats `4000.0` as an "integer"; money must be integer minor units, so a float is `MALFORMED_ARGUMENTS`, never silently normalized.
- **Consequences:** Same logical arguments hash identically regardless of key order; any value change alters the hash (tested).

### ADR-018 — Malformed arguments → persisted DENY, not 422

- **Context:** Arguments failing the registered tool schema (wrong types, extra fields, floats).
- **Decision:** Persist `DENY` / `MALFORMED_ARGUMENTS` rather than returning 422. The M12 benchmark defines "malformed tool inputs" as a DENY category, and fail-closed auditability (ADR-015) applies equally: the attempt is evidence.
- **Consequences:** 422 is reserved for request-shape errors (non-object arguments, missing fields, oversized payloads).

### ADR-019 — Tool→policy mapping and simulate-vs-authorize version semantics

- **Context:** Authorize must find the governing policy for a tool without the agent choosing it.
- **Decision:** Explicit `POLICY_FOR_TOOL` mapping (`refund_payment` → `refund-policy`); a tool with no mapping or no active version yields persisted `DENY` / `POLICY_NOT_CONFIGURED` (fail closed). `POST /policies/simulate` evaluates the *latest* version (draft preview for authors); `authorize` uses *only* the active version. Both behaviors are tested.
- **Rejected:** Agent-supplied policy selection (privilege escalation by request).

### ADR-020 — Minimal runs/agents in Phase 2

- **Context:** M03 run registry could grow a full lifecycle in Phase 2.
- **Decision:** `POST /api/v1/runs` only (agent get-or-create + run in `RUNNING` state). Run finish/fail (`PATCH /runs/{id}`), heartbeats, and telemetry batching stay in their planned phases (M03 completion / M08).

---

## Phase 3 decisions (2026-10-17, recorded during implementation)

### ADR-021 — Execution grants live 5 minutes, single-use

- **Context:** An ALLOW decision must become a bounded, non-replayable permission to execute.
- **Decision:** `mint_grant` issues a grant with `expires_at = now + 300s`, bound to
  (`tool_call_id`, `args_hash`, `policy_version_id`). The gateway consumes it
  (`status=CONSUMED`, `consumed_at`) inside the execution transaction; expired
  grants are marked `EXPIRED` and rejected with 410.
- **Consequences:** A stolen grant is useful for at most 5 minutes and exactly
  one execution. Clients needing longer must re-authorize (fresh policy check).
- **Rejected:** Long-lived grants (larger replay window), bearer-token-only
  execution (no server-side grant verification — the spec's "inadequate" case).

### ADR-022 — Execute replay returns 200 with the original result

- **Context:** Retried execute requests must not create second effects, but the
  caller still needs an answer.
- **Decision:** If a `tool_executions` row exists for the call, return it with
  200 and `replayed=true` — never a new side effect. The check runs before
  grant locking, and again after acquiring the grant lock (the winner may have
  committed while a concurrent request waited).
- **Consequences:** At-most-once effects with at-least-once answers; the
  8-thread race test proves exactly one `SUCCEEDED` row and one balance change.

### ADR-023 — Tampered arguments are rejected without consuming the grant

- **Context:** An execute request may echo arguments that differ from the
  authorized canonical hash.
- **Decision:** Hash mismatch → 409 `arguments_tampered` + `tool.execute_rejected`
  event; the grant stays `ACTIVE` so the legitimate arguments may still
  execute. Balance and business facts are untouched.
- **Consequences:** Tampering is evidence, not a denial-of-service against the
  legitimate retry. Rejected for the same reason: expired grants (410) and
  consumed grants (409) are terminal.

### ADR-024 — Event `seq` is a database-wide bigserial for now

- **Context:** Phase 4's SSE contract needs per-project monotonic sequencing
  for `Last-Event-ID` resume cursors.
- **Decision:** `events.seq` is a bigserial (database-wide, not per-project)
  for Phase 3. Consumers must deduplicate by `event_id`. Per-project
  monotonic sequencing lands with the Phase 4 SSE cursor work.
- **Consequences:** Honest interim gap, recorded here rather than silently
  claiming the Phase 4 contract early.

### ADR-025 — SDK retry policy: never retry what might have executed

- **Context:** Retries around a non-idempotent boundary can duplicate effects.
- **Decision:** Authorize may be retried only with the same client-generated
  idempotency key. Execute is retried at most once, and only after a
  network-level failure (timeout/connection error) — never after an HTTP
  response — because the server makes execute idempotent (grant claim +
  single execution row in one transaction). DENY/REVIEW paths never call
  execute, so they are never retried.
- **Consequences:** Documented in the SDK README; `test_sdk_unavailable_fails_closed`
  proves fail-closed behavior.

### ADR-026 — SDK ignores environment proxy variables

- **Context:** `httpx.Client()` defaults to `trust_env=True`, which crashed
  client construction in this build environment (proxy env vars with IPv6
  `no_proxy` entries that httpx 0.28 cannot parse: `InvalidURL`).
- **Decision:** The SDK passes `trust_env=False`: it talks to an explicitly
  configured `base_url`, and auth-bearing policy traffic must never be
  silently rerouted by ambient environment variables.
- **Consequences:** Deterministic behavior everywhere; corporate-proxy users
  must configure explicitly (a documented limitation, not a silent behavior).

### ADR-027 — SSE stream authenticates via `api_key` query parameter

- **Context:** The browser `EventSource` API cannot send `Authorization`
  headers, so the SSE stream cannot reuse the header-based API key auth
  (M01). Alternatives were cookie sessions (dashboard auth lands in
  Phase 5/6) and long-lived stream tokens (new credential type, new
  lifecycle — scope creep for Phase 4).
- **Decision:** `GET /api/v1/events/stream` accepts the project API key as
  the `api_key` query parameter. After reading it, the endpoint rewrites
  `scope["query_string"]` with the value redacted, so uvicorn access logs
  do not record the secret. All stream queries remain project-scoped, and a
  forged `Last-Event-ID`/cursor from another project yields nothing.
- **Consequences:** Weaker than header auth (keys can linger in browser
  history); documented as an interim limitation. Dashboard session auth
  (Phase 5/6) replaces it. Tested: `test_stream_requires_valid_key`,
  `test_project_isolation`.

### ADR-028 — SSE reads poll the durable events table in-API (no separate worker)

- **Context:** Phase 3's plan put an outbox publisher worker in Phase 4.
  A separate publisher process adds operational complexity (leases, restarts,
  monitoring) before any fan-out requirement exists.
- **Decision:** For Phase 4, the SSE endpoint polls the durable `events`
  table directly inside the API process (0.5s poll, short-lived sessions).
  The events table — not the outbox — is the source of truth for the
  stream; outbox rows are still written transactionally for the future
  publisher and for backlog metrics (`dashboard/summary.outbox_pending`).
  A dedicated publisher worker remains an option if fan-out or delivery
  SLAs demand it, and the schema already supports it.
- **Consequences:** One fewer moving part for localhost scale; delivery is
  at-least-once with client-side dedup by `event_id` (documented contract).

### ADR-029 — SSE emits plain `message` events; kind travels in the payload

- **Context:** Spec §7.4's example shows typed `event: <kind>` SSE lines.
  The browser `EventSource` API has no wildcard subscription for named
  events — a generic live dashboard cannot consume an unbounded set of
  kinds (including custom SDK kinds like `agent.thinking`) that way.
- **Decision:** The stream sends `id:` + `data:` only (no `event:` line);
  every data payload carries `kind` in its envelope. The `id:` field is the
  per-project `project_seq` resume cursor, unchanged.
- **Consequences:** Typed consumers read `kind` from JSON instead of the
  SSE event type. Documented here as a deliberate, disclosed deviation from
  the §7.4 example.

### ADR-030 — Per-project event sequence via a counter table

- **Context:** ADR-024 recorded the database-wide bigserial as an interim
  gap. The Phase 4 cursor contract needs per-project monotonic sequences.
- **Decision:** New `project_event_seq` table (one row per project);
  `record_event` inserts the counter row idempotently
  (`ON CONFLICT DO NOTHING`), locks it `FOR UPDATE` inside the caller's
  transaction, assigns `project_seq`, and increments. Migration 0004
  backfills existing events per project ordered by `(received_at, seq)`.
  The old `seq` bigserial is kept for diagnostics.
- **Consequences:** Cursors are gap-free per project from the start;
  concurrent recorders in one project serialize on the row lock (localhost
  scale; documented). Tested: backfill order, resume, isolation.

### ADR-031 — Bounded SSE subscriptions

- **Context:** Spec reliability list asks for "bounded subscription
  behavior": an infinite server-held connection is a resource leak vector.
- **Decision:** One stream lives at most `AGENTTRUST_SSE_MAX_SECONDS`
  (default 300s), then the server closes it; heartbeats (`: ping`) go out
  every `AGENTTRUST_SSE_HEARTBEAT_SECONDS` (default 20s) when idle. Clients
  reconnect with the last seen cursor and lose nothing. Both are settings
  so tests can shrink them.
- **Consequences:** Predictable server resource use; reconnects are a
  normal, tested path (`test_stream_is_bounded`, `test_heartbeat_received`).

### ADR-032 — SDK run lifecycle telemetry is best-effort

- **Context:** `trust.run()` now emits `run.started`/`run.completed`/
  `run.failed`, and `client.report_event()` posts to
  `/runs/{run_id}/events`. Telemetry must never break the protected call.
- **Decision:** Auto-emitted lifecycle events swallow `AgentTrustError`
  (network/auth failures); explicit `report_event()` calls surface typed
  errors to the caller. The ingestion endpoint validates kinds
  (`^[a-z][a-z0-9_.]{0,63}$`) and caps batches at 100 items; payloads are
  treated as untrusted and size-limited by the request body limit.
- **Consequences:** A telemetry outage degrades observability, never
  safety. Tested: `test_sdk_run_context_emits_lifecycle_events`,
  `test_sdk_report_event_persists_and_streams`, ingestion validation tests.

## Phase 5 decisions (2026-10-17, recorded during implementation)

### ADR-033 — API key scopes gain teeth

- **Context:** `api_keys.scopes` existed since Phase 1 but was never enforced;
  every key behaved like an admin-issued wildcard.
- **Decision:** Scopes are now enforced: SDK keys carry
  `agent:run` / `agent:authorize` / `agent:execute`; reviewer keys carry
  `approvals:read` / `approvals:decide`. The `"*"` wildcard still grants
  everything (backwards compatible with seed and existing test keys).
  `require_scopes(...)` is a dependency factory combining key auth, scope
  check, and (for mutations) rate limiting.
- **Consequences:** A reviewer key cannot authorize or execute; an agent key
  cannot read the queue or decide. Tested: `test_reviewer_key_cannot_authorize`,
  `test_agent_key_cannot_decide`.

### ADR-034 — Reviewer identity is a scoped API key (local-demo posture)

- **Context:** Spec M01 wants a distinct reviewer identity; dashboard cookie
  sessions land in Phase 6.
- **Decision:** For Phase 5, the reviewer is an API key with
  `approvals:decide` scope, pasted into the Approval Center UI and kept in
  `sessionStorage` (never in the bundle, never logged). The seed issues a
  `demo-reviewer` key with only approval scopes, printed once.
- **Consequences:** Real authentication and authorization today; session UX
  later. Documented as interim in the UI itself.

### ADR-035 — Separation of duties at credential level

- **Context:** M01 requires that a requester cannot silently approve their
  own actions. API keys have no user association (admin-token issuance has
  no user context either).
- **Decision:** The decision endpoint rejects with 403 `sod_violation` when
  the deciding key's id equals the approval's `requester_key_id`. Combined
  with scope separation (agent keys cannot decide at all), the credential
  that requested an action can never approve it.
- **Consequences:** Credential-level SoD is enforced and tested
  (`test_sod_self_approval_forbidden`). User-level SoD (two humans) awaits a
  user model on keys — recorded as future work, not silently claimed.
- **Rejected:** Pretending key-level separation is user-level separation.

### ADR-036 — Lazy approval expiry

- **Context:** Approvals need deadlines without a background sweeper process
  (the worker is still future work).
- **Decision:** `expires_at` (default now + 15 min, `AGENTTRUST_APPROVAL_TTL_SECONDS`)
  is enforced lazily: every read and every decision attempt transitions
  overdue PENDING approvals to EXPIRED, records `approval.expired`, and
  commits. Expired approvals answer 410 on decision and 409
  `approval_required` on execute.
- **Consequences:** No cron/worker needed; expiry is visible in the queue
  listing. Tested: `test_expired_approval_rejected`,
  `test_lazy_expiry_visible_in_queue`.

### ADR-037 — Optimistic concurrency on decisions

- **Context:** Two reviewers (or a double-click) must not both decide, and
  must never cause a double execution.
- **Decision:** `approvals.row_version` guards an atomic
  `UPDATE ... WHERE id AND row_version AND state='PENDING'`. Zero rows →
  409 `approval_conflict`. Clients may send the version they saw
  (`expected_row_version`); omitting it still protects the server's
  read-then-write window. An identical re-decision by the same reviewer is
  idempotent (200, no version bump); anything else on a terminal approval
  is 409.
- **Consequences:** Racing deciders collapse to exactly one winner; the
  winner mints exactly one grant, so at most one execution follows. Tested:
  `test_racing_double_decisions_single_execution`,
  `test_idempotent_redecision`, `test_stale_row_version_conflict`.

### ADR-038 — Revalidation at decision time; stale facts reject the approval

- **Context:** Spec S2: a balance consumed while waiting must deny the
  action and require fresh review — approval is not a blank check.
- **Decision:** On APPROVED, inside the decision transaction, the server
  re-reads trusted facts (order exists, eligible, currency matches,
  remaining balance covers the amount) and confirms the deciding policy
  version is still active. Any change → the approval moves to
  REJECTED (`reason=facts_changed`), an event is recorded, and the endpoint
  answers 409 `approval_stale`. The gateway re-checks the same facts again
  at execution time (defense in depth).
- **Consequences:** Approving a stale review is impossible; the requester
  must re-authorize against current facts. Tested:
  `test_approve_after_balance_consumed_rejected`.

### ADR-039 — In-memory per-key rate limiting (single-process)

- **Context:** Spec M15 asks for rate limits on sensitive endpoints.
- **Decision:** Token bucket per API key id (default 60/min,
  `AGENTTRUST_RATE_LIMIT_PER_MINUTE`), enforced on POST
  authorize/execute/decision; 429 answers carry `retryable: true`. The
  buckets live in process memory behind a lock.
- **Consequences:** Bounds abuse against one API instance. Documented
  limitation: no cross-process coordination — a distributed limiter is
  future work if multi-process deployment demands it. Tested:
  `test_rate_limit_429` (with a monkeypatched limit and bucket reset).

### ADR-040 — SDK `wait_for_approval` semantics

- **Context:** Agents need a blocking path from REVIEW to execution without
  re-implementing polling.
- **Decision:** `trust.wait_for_approval(approval_id, timeout_s=300)`
  polls the lightweight `GET /approvals/{id}/status` (visible to the
  requesting key or `approvals:read` keys). APPROVED → one gateway execute
  call, result returned. REJECTED → `ApprovalRejected`; EXPIRED →
  `ApprovalExpired`; timeout → `ApprovalTimeout`. `ApprovalRequired` now
  carries `approval_id`. Nothing executes on any non-APPROVED outcome.
- **Consequences:** The SDK still never auto-executes on approval — the
  caller explicitly opts into blocking, and the gateway still enforces the
  grant. Tested end-to-end over real HTTP: approved/rejected/expired/
  timeout paths.

## Phase 6 decisions (2026-10-17, recorded during implementation)

### ADR-041 — Analytics metric definitions (M09 read surface)

- **Context:** `GET /api/v1/dashboard/analytics` must aggregate only real
  committed rows over a caller-chosen window (`window_days`, default 14,
  max 90); empty data must yield empty arrays / nulls, never invented
  numbers.
- **Decision:** Each metric and its exact source:
  - `decisions_by_day`: from `policy_decisions.decided_at`, grouped by
    UTC calendar day (`date_trunc('day', ...)`) and `outcome`, joined
    through `tool_calls` for project scoping. Only the three real
    outcomes (`ALLOW`, `DENY`, `REVIEW`) are reported; days that have at
    least one decision list all three with zero-fill for absent outcomes.
  - `execution_latency_ms`: `(tool_executions.finished_at -
    tool_executions.started_at)` in milliseconds, restricted to rows
    with `started_at` inside the window and `finished_at IS NOT NULL`
    (unfinished executions are excluded, not treated as zero). p50/p95
    are nearest-rank percentiles computed in Python.
  - `top_denied_tools`: `tool_calls` joined to `tool_definitions` (by
    `tool_id`) and to `policy_decisions` with `outcome='DENY'` inside
    the window, top 10 by count, ties broken by slug ascending. Calls
    for unregistered tools (`tool_id` NULL) carry no slug and are
    excluded from the per-tool ranking rather than invented.
  - `approval_turnaround_s`: `(approvals.decided_at - created_at)` in
    seconds for non-PENDING approvals with `decided_at` inside the
    window (PENDING approvals have no turnaround yet; lazy expiry
    (ADR-036) keeps terminal states honest).
  - Percentile method: nearest-rank (`rank = ceil(p/100 * n)`), recorded
    so frontend and benchmark consumers can reproduce the numbers.
- **Consequences:** Every number on the analytics page traces to a
  committed row; definitions are testable (window exclusion, zero-fill,
  unfinished-execution exclusion, pending-approval exclusion).
- **Rejected:** Averaging/means (percentiles describe latency better),
  including PENDING approvals as zero turnaround (would fabricate).

### ADR-042 — Agents directory is a read-only project-scoped listing

- **Context:** The dashboard needs an agents page; agent rows already
  exist (M03) but had no read API.
- **Decision:** `GET /api/v1/agents` (paginated, max 100, server-side)
  returns per-agent `run_count` and `last_run_at` derived from
  `agent_runs` in the same transaction; `GET /api/v1/agents/{id}`
  returns identity fields plus the 20 newest runs with per-run
  `tool_call_count` and a `total_runs` counter. Both use
  `require_api_key` (same as the other dashboard reads) and 404 as
  `agent_not_found` without distinguishing "exists elsewhere" from
  "does not exist" — the same no-leak rule as run detail.
- **Consequences:** No new tables, no behavior change to existing
  endpoints; the listing cannot be used to enumerate other projects'
  agents.

### ADR-043 — Tailwind CSS v3 for the Phase 6 design system

- **Context:** ADR-010 deferred Tailwind to Phase 6. The design system needs utility-first styling with a dark-by-default theme driven by CSS variables.
- **Decision:** Tailwind CSS **v3.4** (stable), `darkMode: 'class'`, theme values mapped to CSS variables defined in `apps/web/app/tokens.css` (`:root` light, `.dark` dark, dark is the default via `class="dark"` on `<html>` plus a persisted header toggle). Design tokens documented in `docs/DESIGN_TOKENS.md`.
- **Rejected:** Tailwind v4 (newer engine, less battle-tested with our Next 15 setup at the time of the build); hand-rolled CSS only (would not scale across 11 pages).

### ADR-044 — Bespoke component library instead of shadcn/ui

- **Context:** The directive's recommended stack names shadcn/ui + Radix. The product needs ~10 small primitives centered on security signaling (badges that structurally enforce icon+text, server-driven tables) wired to our own tokens.
- **Decision:** Hand-rolled `components/ui/` (Button, Badge, Card, DataTable, Input, Select, Dialog, EmptyState, Spinner/Skeleton, Tabs) on Tailwind with deliberate ARIA. Rationale recorded in `components/ui/index.ts`: shadcn would add a second theming layer with its own CSS-var conventions, a CLI-generated tree to maintain, and Radix primitives whose accessibility we'd still verify — for this size, bespoke is cheaper to audit and keeps the dependency list at Tailwind alone.
- **Consequences:** We own the accessibility burden; every component was built keyboard-first (focus-visible rings, aria-sort, dialog focus trap, WAI-ARIA tabs).

### ADR-045 — Incidents and Evaluations ship as honest Phase-7 placeholders

- **Context:** Spec §8 lists Incidents and Evaluations pages, but their backends (M11 incident detection, M12 evaluation runner) are Phase 7. The completion gate forbids fake data and dead controls.
- **Decision:** `/incidents` and `/evaluations` render EmptyState-only pages with a "Phase 7 — pending" badge and a paragraph describing the planned shape. No fabricated incidents, no decorative charts, no buttons that do nothing.
- **Consequences:** The nav is complete and honest; the pages become real in Phase 7 without redesign.

### ADR-046 — Recharts for analytics charts

- **Context:** The Analytics page needs a stacked decisions/day chart and a top-denied-tools chart from the new `/dashboard/analytics` endpoint.
- **Decision:** Recharts (client-side, no paid services). Latency and turnaround are shown as stat cards, not charts — a single data point plotted as a chart would be decorative. Every chart binds real endpoint data and renders an EmptyState when its series is empty.

### ADR-047 — Incident analysis runs synchronously in-request (no worker yet)

- **Context:** Spec M11 wants an investigation workflow; the system has no background worker process.
- **Decision:** `POST /incidents/{id}/analyze` runs the LangGraph `collect_evidence → analyze → validate` graph synchronously with the Ollama call bounded by `AGENTTRUST_ANALYZE_TIMEOUT_SECONDS` (30s). The deterministic template fallback keeps the endpoint usable with no model installed. Production would queue this; the sync posture and its blocking implication are documented on the endpoint.
- **Consequences:** Simple and honest for local use; a slow model blocks one HTTP worker. The report is stored on the incident, so re-fetching is free.

### ADR-048 — Discrete triggers in the request path, pattern triggers on demand

- **Context:** M11 needs both immediate and pattern-based detection without a streaming pipeline.
- **Decision:** Cheap discrete checks (`arguments_tampered` → high, consumed-grant replay → medium, `AMOUNT_EXCEEDS_MAX` > 2× review_max → medium) run synchronously in the request path and are total — they can never change an authorization outcome. Expensive pattern checks (≥5 DENYs from one key in 10 min; ≥3 tamper rejections project-wide in 1 h) run on demand via `POST /incidents/scan`. Dedup: one OPEN incident per (category, tool_call) for discrete, per (category, project) for scan.
- **Consequences:** No background scheduling to operate; scans are explicit and auditable. The detector records `incident.created` events like any other domain event.

### ADR-049 — Evaluation runs on an isolated database

- **Context:** The 100-case benchmark must drive the real authorize/execute stack without polluting the main database or depending on its state.
- **Decision:** Each run drops/creates `agenttrust_eval` (name configurable), migrates it to head, seeds the fixed policy stack, and resets mock orders to seed balances before every case. Results are written to the main database's `evaluation_runs` / `evaluation_results`. The CLI is one command: `python -m agenttrust_api.evaluation.run --db <url>`.
- **Consequences:** Runs are reproducible and hermetic; the main database only accumulates run records. The drop/create requires a privileged DB role — documented, local-use only.

### ADR-050 — Ollama-optional investigator with deterministic template fallback

- **Context:** Spec §9 wants AI-assisted incident analysis, but no model may be downloaded or required in any environment.
- **Decision:** The analyzer tries local Ollama (`AGENTTRUST_OLLAMA_URL`, model `AGENTTRUST_OLLAMA_MODEL` default `qwen2.5:3b`, JSON-only prompt over redacted evidence) and falls back to a deterministic template on any failure. `analyzer_kind` (`ollama:<model>` | `template`) labels every report in API and UI. The graph binds no tools — the analyzer can only read its evidence and return JSON; a test asserts the node set structurally. The validator rejects fabricated evidence refs, empty uncertainty, and any claim of approval/execution/policy change.
- **Consequences:** The fallback path is what ships and what is tested here; a real model improves prose, never authority.

### ADR-051 — Quality gates reported as targets beside measured values

- **Context:** Spec §13.2 sets numeric quality gates (accuracy, false-allow/deny, unauthorized executions, duplicate effects, p95 latency).
- **Decision:** The benchmark report carries `gate_targets` next to `metrics` — measured values are never presented as universal guarantees, and gates are never asserted as passed in code. The report also discloses limitations (single host, seeded policy v1, synthetic dataset).
- **Consequences:** Honest numbers: 100/100 on this dataset, on this host, against this policy — not a claim about real-world fraud.

### ADR-052 — Scan, analyze, and benchmark-run are reviewer-gated, not admin-token

- **Context:** The admin bearer token is for cross-project key management; incident and evaluation operations are project-scoped.
- **Decision:** `POST /incidents/scan`, `PATCH /incidents/{id}`, and `POST /evaluations/run` require a project API key with reviewer scope (`approvals:decide`; the `*` wildcard passes). Analysis (`POST /incidents/{id}/analyze`) and all reads require any valid project key. This lets the project dashboard trigger scans and benchmark runs without the admin token.
- **Consequences:** Privilege model stays project-scoped; the heavyweight benchmark run is still restricted to reviewer keys and documented as synchronous.

### ADR-053 — MIT license for the repository

- **Context:** Spec §16 lists "license" as a required repo deliverable but names no license; the Phase 0 open question on license choice was never resolved.
- **Decision:** MIT. Permissive, portfolio-friendly, and compatible with every dependency in the stack (FastAPI, SQLAlchemy, Alembic, Next.js, LangGraph — all permissive or LGPL-adjacent licenses; PostgreSQL uses its own permissive license). The full MIT text is present at the repo root (`LICENSE`).
- **Consequences:** Anyone can use, modify, and distribute the code with attribution; no copyleft obligations attach to the portfolio demo. If the project ever takes a commercial direction, the license choice is revisited explicitly.

### ADR-054 — Demo-seed design: layered, idempotent, determinism-safe

- **Context:** Phase 8 needs a realistic demo dataset (agent, keys, runs, decisions, an execution, a pending approval, an open tamper incident) without disturbing the base seed or making re-runs dangerous.
- **Decision:** `apps/api/src/agenttrust_api/seed_demo.py` layers demo content on top of the base `seed` module: it calls `seed.main()` first, then creates the demo agent and requester/reviewer keys idempotently (existence checks; raw secrets printed copy-once only at creation), resets the synthetic mock-order balances to fixed values for determinism, and runs the scenario (2 runs: $40 ALLOW+execute, $150 REVIEW left PENDING, $900 DENY; run-2 tamper → 409 → OPEN incident) through the real HTTP stack only when no demo runs exist. The base `seed` CLI is untouched.
- **Consequences:** Re-running is safe (scenario skipped when present); demo data is reproducible; the scenario exercises real authorize/execute code paths rather than inserting rows by hand.

### ADR-055 — No recorded demo video; DEMO_SCRIPT.md provided instead

- **Context:** Spec §16.20 asks for a demo video, but this environment has no screen capture.
- **Decision:** No video is recorded or implied. `docs/DEMO_SCRIPT.md` is provided instead: a precise narrated script with the exact commands to run, in order. `docs/EXECUTIVE_SUMMARY.md` states the substitution explicitly. The traceability row S16-20 is marked Partial, not Implemented.
- **Consequences:** The demo is reproducible by reading the script, but there is no recorded artifact for viewers who will not run it.

### ADR-056 — Metrics endpoint: human-readable JSON, project-scoped, committed-rows only

- **Context:** Spec M17 asks for a built-in metrics endpoint; the dashboard and demo scripts need to consume it without a Prometheus parser.
- **Decision:** `GET /api/v1/metrics` returns human-readable JSON (not Prometheus text exposition): `decisions_by_outcome`, `executions_total`, `active_approvals`, `incidents_by_status`, plus `project_id` and `generated_at`. It is project-scoped to the caller's API key like every other read endpoint, and every counter is computed from committed rows only — never invented (empty data yields zeros/empty maps).
- **Consequences:** The dashboard can render metrics directly; the endpoint cannot leak cross-project data or fabricate numbers.
