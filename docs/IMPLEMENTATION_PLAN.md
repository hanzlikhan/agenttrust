# AgentTrust — Implementation Plan

**Status:** Phase 0 (this document set) is the only phase in progress. Nothing is implemented yet.
**Source spec:** `AgentTrust_Complete_Technical_Documentation__1.md`, v1.0, dated 2026-10-17 (spec sections cited below).
**Last updated:** 2026-10-17 (UTC).

## How to read this plan

- Modules are cited as **M01–M18** per spec §3.
- Each phase lists a completion gate. A phase is NOT complete until its gate is honestly satisfied; gates
  that require running commands are marked as such, and a gate is never marked green on assertion alone.
- "MVP" follows spec §14 scope control: M01–M10, M12, M15–M18 first; M11 advanced AI, external
  messaging (M14 stretch), PDF reports (M13 stretch) are second priority.

---

## Phase 0 — Repository inspection and architecture (this phase, 2026-10-17)

- **Objective:** Read the full spec, identify every requirement, decide architecture, and record everything
  in writing before implementation code exists.
- **Affected modules:** M18 (documentation assets; nothing else).
- **Dependencies:** None — first phase.
- **Key deliverables:**
  - Repo skeleton `apps/web`, `apps/api`, `packages/agenttrust-python`, `examples/refund-support-agent`,
    `evals`, `infra`, `docs`, `.github`
  - The seven Phase 0 docs (this file + traceability, architecture, threat model, decisions, test strategy, progress)
- **Completion gate:** All seven docs exist, each marked with honest status; requirements traceability covers
  all 18 spec sections; README states plainly that nothing is implemented.

## Phase 1 — Foundation (spec §14, Week 1)

- **Objective:** A running monorepo with API, database, authentication foundation, and synthetic seed data.
- **Affected modules:** M01 (identity, projects, API keys), M15 (audit events, retention config, secrets handling),
  M17 (health endpoints, structured logging), M18 (install README).
- **Dependencies:** Phase 0 complete.
- **Key deliverables:**
  - FastAPI app with versioned router (`/api/v1`), Alembic migrations for `users`, `projects`,
    `memberships`, `api_keys`, `agents`, `mock_orders`, `audit_events`
  - Passwordless single-owner local-demo auth mode (loopback-bound) per M01, or local accounts — see DECISIONS.md open question
  - Docker Compose for `db` (+ `api`/`web` as wiring exists later); `.env.example` with placeholder values only
  - Seed: synthetic orders in integer minor units, demo reviewer, default policy placeholder
- **Completion gate:** `docker compose up` succeeds; Alembic migrates a fresh DB; `/health/live` and
  `/health/ready` return expected responses; audit event recorded for key issuance.

## Phase 2 — Policy engine (spec §14, Week 2)

- **Objective:** Deterministic pre-execution policy decisions on registered tools with trusted business context.
- **Affected modules:** M04 (tool registry, schema contracts, canonicalization), M05 (policy authoring/versioning),
  M06 (decision API), M15 (redaction in stored args).
- **Dependencies:** Phase 1 (DB, auth, projects). No frontend required yet.
- **Key deliverables:**
  - `tool_definitions` table + registration API; canonical JSON hashing (stable order, defined numerics)
  - Pydantic-validated policy configs; immutable policy versions (activation creates a new version)
  - `/tool-calls/authorize` implementing the §8 pipeline: auth → schema validation → project/tool auth →
    trusted context retrieval → rule evaluation → ALLOW / DENY / REVIEW
  - Decision record: decision ID, tool call ID, outcome, reason code, policy version, UTC timestamp, safe explanation
  - Refund rules per §5 example: ≤ 10000 minor units (USD 100.00) + eligible → ALLOW; 10001–50000 → REVIEW;
    above cap or above remaining balance → DENY; missing context / invalid currency / float amount → DENY
- **Completion gate:** Unit tests match a hand-written test oracle for every reason code; retried authorize
  with same idempotency key + payload hash returns the identical stable response; key reuse with changed
  payload returns 409; policy service path demonstrably fails closed.

## Phase 3 — Trusted gateway and SDK (spec §14, Week 3)

- **Objective:** Enforcement that an agent cannot bypass: the gateway, not the SDK, decides what executes.
- **Affected modules:** M02 (Python SDK), M07 (trusted action executor / mock payment gateway), M08 (trace ingestion,
  event store, transactional outbox), M16 (publisher worker consuming the outbox).
- **Dependencies:** Phase 2 (decision API). This is the security-critical phase — do not compress it.
- **Key deliverables:**
  - `agenttrust-python` package: `AgentTrustClient`, `@trust.protect(tool=...)`, run context manager,
    typed `AuthorizationDenied` / `ApprovalRequired` / `PolicyServiceUnavailable`, timeouts, bounded retries
    only for safe requests, client-generated correlation IDs, redaction before reporting
  - Mock payment gateway endpoint `/tool-calls/{call_id}/execute`: re-verifies identity, canonical arg hash,
    approval/policy validity, grant expiry, single-use status — at execution time, in one transaction
  - `execution_grants` (unique single-use grant), `tool_executions` (unique successful execution per call),
    row-locked `mock_orders` balance updates, all in integer minor units
  - Outbox table + worker publishing committed events (PostgreSQL `SKIP LOCKED` leases; no Redis)
- **Completion gate:** "Unsafe call provably never executes": S3/S4/S5 scenario tests pass — denied calls have
  no side effect; tampered args rejected at gateway; concurrent identical requests produce at most one balance
  change; SDK timeout/unavailable maps to a typed error and zero execution.

## Phase 4 — Real-time observability (spec §14, Week 4)

- **Objective:** Live dashboard fed by durable events; the browser is eventually consistent, never authoritative.
- **Affected modules:** M08 (SSE contract, resume cursor, backfill), M09 (dashboard pages), M16 (worker heartbeat
  visibility), M17 (SSE metrics: connected clients, reconnects, delivery lag).
- **Dependencies:** Phases 1–3 (events must exist before they can be streamed).
- **Key deliverables:**
  - `GET /dashboard/events/stream`: project-scoped SSE, `Last-Event-ID` resume, per-project monotonic sequence,
    heartbeats; event envelope per §8 (event ID, project, run, trace, tool-call/parent IDs, server sequence,
    source + receipt timestamps, redacted payload, schema version)
  - Next.js App Router pages (MVP slice): Overview, Live Runs, Run Detail, Tool Call Detail — initial REST
    snapshot then SSE patch, `Live / Reconnecting / Offline` indicator, last-sync timestamp
  - Dashboard counters derived only from committed events; duplicate events deduplicated by event ID
- **Completion gate:** S7 scenario passes — disconnect SSE 10s mid-decisions, reconnect, timeline shows zero gaps;
  no event is delivered to a project the credential cannot access.

## Phase 5 — Human approvals (spec §14, Week 5)

- **Objective:** Durable, authenticated, reviewer-separated approval workflow with concurrency safety.
- **Affected modules:** M01 (reviewer identity + role checks; requester ≠ reviewer when separation of duties is on),
  M10 (approval state machine), M15 (audit of every approval event).
- **Dependencies:** Phases 2–3 (REVIEW outcomes and the gateway's revalidation). Frontend slice from Phase 4.
- **Key deliverables:**
  - `approvals` state machine: `PENDING → APPROVED | REJECTED | EXPIRED` with optimistic concurrency
    (`row_version`); one active approval per tool call
  - Approvals UI page: pending queue, canonical args, trusted eligibility, policy reason, expiry, approve/reject
    with reason, audit history; 409 on double-decide with refreshed status
  - Execute-after-approval: fresh authorization bound to same args hash + idempotency key; revalidation of
    business facts at execution time (e.g. balance consumed while waiting → deny, fresh review required)
  - Security hardening pass: CSRF on cookie mutations, rate limits on sensitive endpoints, input size limits,
    CORS allowlist, API scopes enforced, no keys in frontend JS/logs
- **Completion gate:** S2 passes end-to-end ($150 → REVIEW → approve → exactly one execution); changed args,
  expired approval, and double approval-decide are each rejected with an audit event.

## Phase 6 — Evaluations (spec §14, Week 6)

- **Objective:** Reproducible benchmark proving enforcement, not just policy classification.
- **Affected modules:** M12 (evaluation laboratory), M13 (minimal exports: CSV/JSON/Markdown benchmark report),
  M16 (eval runner as background job), M09 (Evaluations page).
- **Dependencies:** Phases 1–5 complete. This phase cannot be front-loaded — it tests the enforcement path.
- **Key deliverables:**
  - 100-case dataset: 25 eligible automatic ALLOW, 20 valid REVIEW, 20 limit DENY, 15 missing/invalid-context
    DENY, 10 tamper/replay DENY, 10 malformed/injection DENY — expected outcomes labeled independently of any model
  - One-command runner on an isolated test DB (or rollback-safe fixtures): seeded RNG, dataset version,
    policy version, environment metadata, per-case latency; `benchmark-report.json` per §13.3
  - Verdicts include **whether the protected tool actually executed**, not only the policy outcome
  - Evaluations page: suite list, expected/actual matrix, failing cases, replay, run comparison, export
- **Completion gate:** Suite runs locally, reproducibly (same seed → same results); §13.2 targets are *measured
  and reported*, never asserted; no secrets leak into stored events under seeded-credential scans.

## Phase 7 — Incidents and optional AI (spec §14, Week 7)

- **Objective:** Deterministic incident evidence + optional local-LLM explanations that cite their evidence.
- **Affected modules:** M11 (baseline detector + LangGraph investigator + deterministic template fallback),
  M09 (Incidents page), M14 (in-app alerting for incident creation), M16 (analysis as worker job).
- **Dependencies:** Phases 1–6 (evidence must exist). LLM path is optional — do NOT let it gate the phase.
- **Key deliverables:**
  - Deterministic triggers: repeated denials, amount overflow, unexpected tool errors, policy-service failure,
    duplicate token attempt, authorization tamper
  - `incidents` + `incident_evidence` records; state machine `OPEN → INVESTIGATING → RESOLVED | DISMISSED`
  - LangGraph graph (Evidence Collector → Incident Analyzer → Evidence Validator) over redacted evidence;
    Pydantic-validated output; cited IDs verified to exist; model gets NO tool/policy permissions; local-model
    timeout is an analysis failure, never an enforcement failure
  - Zero-cost fallback: deterministic template report with the exact policy reason; UI labels AI text
    "AI-assisted, non-authoritative"; all core functionality works with the model disabled
- **Completion gate:** S8 passes both with and without a local model; incident report references only evidence
  that exists; unresolved-analysis jobs appear in the worker dead-letter/backlog view.

## Phase 8 — Final integration and release (spec §14, Week 8)

- **Objective:** A portfolio-grade release an outside engineer can install and verify.
- **Affected modules:** M13 (README-friendly benchmark summary), M17 (built-in metrics endpoint), M18 (full
  onboarding docs: install, quickstart, SDK docs, OpenAPI, FAQ, security model, ADRs, failure table, license,
  contributing, demo scripts), `infra/` (finalized Compose), `.github/` (CI running lint/typecheck/tests).
- **Dependencies:** Phases 1–7. Nothing new may be added that isn't already tested.
- **Key deliverables:**
  - Fresh-install verification from README commands (no invented commands — §11: document only what was run)
  - Measured benchmark numbers in README/benchmark report; recorded 3-minute demo per §16
  - Verification commands run and honestly reported: `docker compose config`, `pytest`, `ruff check .`,
    `npm run lint`, `npm run typecheck`, `npm run build`, Playwright suite
  - Limitations + residual risks documented (THREAT_MODEL.md, README); security disclosures; issue backlog
- **Completion gate:** §17 definition-of-done rows all have real acceptance evidence; an outside engineer
  reproduces the protected refund flow (S1–S8) from the README on their machine.

---

## Scope control and ordering rules

1. **MVP first:** M01–M10, M12, M15–M18. M11 advanced AI, M13 PDF reports, M14 external messaging are
   stretch — they ship only after the deterministic security core is complete and tested.
2. **Never compress Phase 3.** The gateway is the product's security claim; "SDK security theater" is the
   spec's named #1 risk (§15).
3. **No phase begins before its dependencies' gates are honestly satisfied.** A gate is not satisfied by
   assertion; it is satisfied by a command that was run and produced the stated output.
4. **Do not fabricate.** Benchmark numbers, latency claims, and security claims are reported only after
   measurement (§13.3: "Do not fabricate benchmark numbers in README or résumé").
5. **One language, one demo tool, one project initially** (§15) — resist scope creep into a generic tracing platform.
