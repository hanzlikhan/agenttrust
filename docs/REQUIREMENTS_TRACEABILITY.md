# AgentTrust — Requirements Traceability Matrix

**Spec:** `AgentTrust_Complete_Technical_Documentation__1.md` v1.0 (2026-10-17).
**Matrix date:** 2026-10-17 (UTC). **Matrix version:** 1.0.

## Standing values (apply to every row except where overridden below)

- **Implementation status:** Pending — Phase 0. No requirement below is implemented.
- **Test coverage:** None yet.
- **Verification evidence:** None yet.

Non-goals (§1.3) are tracked as constraints that future implementation must honor; "Pending — Phase 0" means
"not yet demonstrated or honored in code/tests."

Rows completed in later phases are recorded under "Phase 1 status overrides" (and subsequent phase
sections); those rows carry their own status and evidence, everything else keeps the standing values.

Monetary values below are expressed in integer minor units (e.g. 4000 minor units = USD 40.00).

---

## Phase 1 status overrides (2026-10-17 — backend verified; frontend slice in progress)

| Req ID | Status | Evidence |
|---|---|---|
| S03-01 | Implemented | `POST /api/v1/keys` issues copy-once secrets; list endpoint redacts; SHA-256 hash storage asserted in `test_issue_key_returns_secret_once`; live smoke test confirmed. Scope *enforcement* (not just storage) arrives in Phase 5. |
| S03-02 | Implemented | `test_revoke_key_disables_it`: `/api/v1/me` returns 403 `key_revoked` immediately after revocation; confirmed live. |
| S06-01 | Implemented | `users` table via Alembic `0001`; `test_upgrade_head_creates_expected_tables`. |
| S06-02 | Implemented | `projects` table (owner FK, unique owner/name) via Alembic `0001`; same test. |
| S06-03 | Implemented | `memberships` table (unique user/project) via Alembic `0001`; same test. |
| S06-04 | Implemented | `api_keys` table (prefix index, hash, scopes, expiry, revocation) via Alembic `0001`; never-stores-plaintext asserted in tests. |
| S07-23 | Partial | `GET /health/live` and `GET /health/ready` (real DB ping) implemented and tested (`test_live_returns_ok`, `test_ready_reports_database_up`, live curl). `/metrics` not yet implemented (Phase 8). |
| S07-25 | Partial | Structured error envelope (`error_code`, `message`, `request_id`, `retryable`) implemented for all Phase 1 routes; 201/401/403/404/409/422/503 paths covered by tests (`test_unknown_route_returns_structured_error`). Full code table applies as routes are added. |
| S10-04 | Implemented | SQLAlchemy 2.1.5 + Alembic 1.20.0 operational: `alembic upgrade head` / `downgrade base` verified on real PostgreSQL 16 (`test_migrations.py`). |
| S10-05 | Implemented | PostgreSQL 16.15 is the data store; all tests run against real databases. |
| S11-04 | Partial | `apps/api/README.md` documents the verified setup sequence (venv → install → Postgres → `alembic upgrade head` → seed → uvicorn → pytest). Compose `up` not yet executed (no Docker in build env). |
| S14-01 | Partial | Health + migration tests pass (13/13 pytest); ruff clean; frontend slice pending; `docker compose up` not run (no Docker engine) — gate not fully closed. |

## Phase 2 status overrides (2026-10-17 — policy engine verified)

| Req ID | Status | Evidence |
|---|---|---|
| S02-02 | Implemented | `test_authorize_deny_over_cap` (90000 → DENY AMOUNT_EXCEEDS_MAX) + live smoke S3; unauthorized amounts never reach execution (no gateway exists yet — Phase 3). |
| S02-03 | Implemented | Eligibility/balance read from server-owned `mock_orders` via `_order_facts`; `test_authorize_deny_ineligible`, `test_authorize_deny_missing_order`. |
| S02-04 | Implemented | Live smoke S4 + M12 attack suite: injected extra field → DENY MALFORMED_ARGUMENTS; 90000 attempt → DENY AMOUNT_EXCEEDS_MAX regardless; injection-shaped order_ids/currencies → DENY as data (malformed-006…010 in the 100-case dataset, all passing 2026-10-17). |
| S02-06 | Partial | Authorize-level idempotency done (`test_idempotent_replay_returns_same_decision`, 409 on changed payload). Execution-effect idempotency is Phase 3 (gateway). |
| S02-12 | Implemented | `agenttrust_api/policy/rules.py`: pure functions, no I/O, no LLM; `test_policy_rules.py` oracle (17 unit tests). |
| S03-08 | Implemented | `POST /api/v1/tools` (versioned, 409 on duplicate slug/version, JSON Schema validated at registration); `GET /api/v1/tools` project-scoped. |
| S03-09 | Implemented | `test_authorize_deny_unknown_tool_persisted`: unregistered tool → persisted DENY UNKNOWN_TOOL (tool_id NULL, args fully redacted). Server schemas authoritative. |
| S03-10 | Implemented | Canonical JSON hashing (`test_canonical_hash_stable_across_key_order`); integer minor units; floats rejected → DENY MALFORMED_ARGUMENTS (`test_authorize_float_amount_rejected`). |
| S03-11 | Implemented | `RefundPolicyConfig` (Pydantic) + `evaluate_refund` returning outcome/reason_code/explanation/policy version; full oracle in `test_policy_rules.py`. |
| S03-12 | Implemented | `test_policy_activation_immutability`: drafts don't affect authorize; activate bumps version; old decisions keep version 1; re-activate without draft → 409. |
| S03-13 | Implemented | Boundary oracle: 10000 ALLOW / 10001 REVIEW / 50000 REVIEW / 50001 DENY; ineligible/over-balance/missing-order/bad-currency/zero-amount all DENY; live smoke S1–S3. |
| S03-14 | Implemented | `POST /api/v1/tool-calls/authorize`; tool_call + policy_decision persisted in ONE transaction (`test_authorize_allow_persists_atomically`); 201 new / 200 replay. |
| S03-15 | Implemented | Same key + same args hash → identical stored decision (200); same key + different hash → 409 `idempotency_conflict`; race handled via unique constraint + re-read. |
| S03-16 | Partial | Fail-closed verified for policy paths (UNKNOWN_TOOL, POLICY_NOT_CONFIGURED, DB-down → 503). SDK timeout mapping is Phase 3 (M02). |
| S04-08 | Partial | tool_call + policy_decision commit atomically; outbox row joins the transaction in Phase 3. |
| S04-16 | Partial | Tool-call states DENIED / APPROVAL_PENDING / AUTHORIZED implemented and tested; EXECUTING → SUCCEEDED / FAILED transitions are Phase 3 (gateway). |
| S06-05 | Implemented | `agents` table (project/name index) via Alembic `0002`; covered by `test_upgrade_head_creates_expected_tables`. |
| S06-06 | Implemented | `agent_runs` table (project/time + trace indexes) via Alembic `0002`; run creation tested (`test_authorize_*` fixtures). |
| S06-07 | Implemented | `tool_definitions` table (unique project/slug/version) via Alembic `0002`; registration tested. |
| S06-08 | Implemented | `tool_calls` table (unique project/idempotency_key; args_redacted, args_hash, state) via Alembic `0002`; redaction allowlist asserted in tests. |
| S06-09 | Implemented | `policies` + `policy_versions` (unique policy/version; immutable once active) via Alembic `0002`; immutability tested. |
| S06-10 | Implemented | `policy_decisions` (unique tool_call FK; outcome, reason_code, decided_at, pinned version) via Alembic `0002`. |
| S06-14 | Partial | `mock_orders` table created via Alembic `0002` with seed data; transactional locking of balances is Phase 3 (gateway). |
| S07-01 | Implemented | `POST /api/v1/runs` creates run (agent get-or-create), returns run_id + trace_id; tested in every authorize test. |
| S07-04 | Implemented | `POST /api/v1/tool-calls/authorize` → ALLOW/DENY/REVIEW; 16 integration tests in `test_authorize.py`; live smoke verified. |
| S07-14 | Implemented | `GET/POST /api/v1/policies` — draft creation with Pydantic-validated rules_json; tested. |
| S07-15 | Implemented | `POST /api/v1/policies/{id}/activate` — activates latest draft only; 409 when no draft; tested. |
| S07-16 | Implemented | `POST /api/v1/policies/simulate` — non-mutating preview (row counts unchanged in test); evaluates latest version incl. drafts. |
| S12-01 | Partial | Decision half verified: $40 → ALLOW AUTO_APPROVED, atomic persistence, live smoke. Balance mutation + stream + execution are Phases 3/4. |
| S12-02 | Partial | Decision half verified: $150 → REVIEW APPROVAL_REQUIRED, approval_id null (deferred to Phase 5). Approval workflow is Phase 5. |
| S12-03 | Implemented | $900 → DENY AMOUNT_EXCEEDS_MAX; nothing executes; balance provably unchanged. M11 incident trigger live: anomalous amounts (>2× review_max) open `amount_overflow` incidents (tested). |
| S12-04 | Implemented | Deterministic denial of injected content verified in the 100-case benchmark (10 malformed/injection cases, all passing 2026-10-17). |

---

## Phase 3 status overrides (2026-10-17 — trusted gateway + SDK verified)

| Req ID | Status | Evidence |
|---|---|---|
| S01-08 | Implemented | `POST /api/v1/tool-calls/{id}/execute` verifies grant (unconsumed, unexpired, args-hash-bound) in one transaction before mutating `mock_orders`; `test_allow_execute_moves_balance_once`. |
| S02-06 | Implemented | Was Partial: execution-effect idempotency now done — replay execute → 200 with original result, balance moves once (`test_replay_execute_returns_original_result`, 8-thread `test_concurrent_executes_single_side_effect`). |
| S02-10 | Implemented | `test_sdk_unavailable_fails_closed`: unreachable API → `PolicyServiceUnavailable`, zero execution rows, balance untouched. |
| S02-11 | Implemented | OBJ-1: `test_deny_decision_never_executes_no_grant` + `test_review_decision_never_executes` — DENY/REVIEW mint no grant and execute returns 409. |
| S02-16 | Implemented | OBJ-6: unique execution row per call + grant claim + row locks in one transaction; concurrency test proves single effect. |
| S03-04 | Implemented | `packages/agenttrust-python`: `AgentTrust`, `@trust.protect(tool=...)`, `trust.run(...)` context manager, typed `AuthorizationDenied`/`ApprovalRequired`/`PolicyServiceUnavailable`/`ConfigurationError`; `pip install -e` verified. |
| S03-05 | Implemented | `test_sdk_deny_raises_and_never_executes` (execute never called, no execution row); `test_sdk_review_raises_approval_required`. |
| S03-06 | Implemented | Timeouts on every SDK request; `test_sdk_unavailable_fails_closed`; execute retried at most once after network failure only (server-side idempotent) — documented in SDK README and ADR-025. |
| S03-16 | Implemented | Was Partial: SDK timeout/unavailable mapping now covered (`test_sdk_unavailable_fails_closed`). |
| S03-17 | Implemented | `test_tampered_arguments_rejected` (409, grant survives), `test_expired_grant_rejected` (410), `test_execute_unknown_call_404`. |
| S03-18 | Implemented | `test_allow_execute_moves_balance_once` + `test_concurrent_executes_single_side_effect`: exactly one SUCCEEDED row, balance decremented once, grant CONSUMED. |
| S03-19 | Partial | Envelope core persisted (event_id, project_id, run_id, seq, kind, redacted payload, received_at). Per-project monotonic seq, trace/parent IDs, schema version → Phase 4 (ADR-024). |
| S03-20 | Partial | Append-only `events` + transactional `outbox` persisted in the decision/execution transactions. Publisher worker → SSE is Phase 4. |
| S04-08 | Implemented | Was Partial: authorize now persists tool_call + policy_decision + `tool.requested`/`policy.*` events + outbox rows + ALLOW grant in ONE transaction. |
| S04-16 | Implemented | Was Partial: `EXECUTING → SUCCEEDED` now real — `tool_call.state` → SUCCEEDED with `tool_executions` row; `tool.executing`/`tool.succeeded` events recorded. |
| S05-04 | Implemented | Boundary SDK vs gateway: SDK cannot execute — only `POST .../execute` with a live grant mutates state; tamper/expiry/consumed all rejected server-side. |
| S05-10 | Implemented | Retries vs effects: idempotent replay from persisted execution state + `FOR UPDATE` grant locking; 8-thread race → one effect. |
| S05-11 | Implemented | Policy API unreachable → SDK `PolicyServiceUnavailable`, nothing executes (`test_sdk_unavailable_fails_closed`). |
| S05-15 | Implemented | Args changed after authorization → 409 `arguments_tampered`, balance unchanged, grant left ACTIVE (`test_tampered_arguments_rejected`). |
| S05-16 | Implemented | Same execute repeated → 200 with original `execution_id`, no second effect (`test_replay_execute_returns_original_result`). |
| S06-12 | Implemented | `execution_grants` (unique tool_call, args_hash, policy_version_id, expires_at, consumed_at, status) via Alembic `0003`. |
| S06-13 | Implemented | `tool_executions` (unique call_id, state, redacted result) via Alembic `0003`. |
| S06-14 | Implemented | Was Partial: `mock_orders` row locked `FOR UPDATE` at execution; balance re-checked at execution time (S2-relevant revalidation). |
| S12-01 | Partial | Was Partial: decision + execution halves now verified live (demo.py S1: 5/5). Live dashboard stream remains Phase 4. |
| S12-03 | Implemented | Was Partial: DENY + provably-no-execution verified live (demo.py S3); M11 incident trigger for anomalous amounts implemented and tested (Phase 7). |

## Phase 4 status overrides (2026-10-17 — real-time observability verified)

| Req ID | Status | Evidence |
|---|---|---|
| S02-13 | Implemented | OBJ-3: live event timeline on `/runs` and `/runs/[id]` fed by SSE; `test_live_event_arrives_within_deadline` proves <2 s committed-event-to-stream delivery over real HTTP. |
| S03-19 | Partial | Was Partial: per-project monotonic `project_seq` now assigned atomically (`record_event`, migration `0004`) and carried as the SSE `id:` cursor; `trace_id` rides in `run.started` payloads. Tool-call/parent IDs and schema version in the envelope remain open. |
| S03-20 | Implemented | Was Partial: append-only `events` + transactional `outbox` feed the SSE stream via in-API polling of the durable table (no separate publisher worker — ADR-028); outbox rows still written for backlog metrics and the future worker. |
| S03-21 | Implemented | `GET /api/v1/events/stream`: project-scoped SSE, `Last-Event-ID` resume (+ `?cursor=` fallback), backfill, `: ping` heartbeats, 300 s bounded subscriptions; dashboard documented as eventually consistent, never a security control (`test_backfill_respects_cursor_and_order`, `test_heartbeat_received`, `test_stream_is_bounded`). |
| S03-22 | Partial | M09 slice done: Live Runs + Run Detail pages (real data, honest states). Overview, Tool Call Detail, Policies, Approvals, Evaluations, Incidents, Integration/Settings pages remain Phase 6. |
| S03-23 | Partial | Live/Reconnecting/Offline indicator + run status/agent filters implemented (`ConnectionBadge`, `test_runs_pagination_and_filters`). Redacted args/policy code/durations per tool-call page remain Phase 6. |
| S04-07 | Partial | Event path SDK → API → single DB transaction → outbox → SSE → dashboard is live; the worker hop is skipped by design in Phase 4 (ADR-028). |
| S04-09 | Implemented | Dashboard pairs REST snapshot with SSE deltas; `useEventSource` dedups by `event_id`; run detail appends in `project_seq` order (`test_run_detail_includes_ordered_events`). |
| S04-12 | Partial | Live delivery measured <2 s in `test_live_event_arrives_within_deadline` (localhost, real HTTP); no p95 SLO claim made — that measurement is Phase 8. |
| S04-13 | Implemented | `useEventSource` reconnects with exponential backoff (1 s → 30 s cap) and resumes from the last seen cursor; gap recovery proven by `test_backfill_respects_cursor_and_order` + `test_backfill_repeat_is_byte_identical`. |
| S05-12 | Implemented | SSE interruption → `reconnecting` badge + missed-event backfill on resume; connection status always visible (`ConnectionBadge`). |
| S05-20 | Implemented | Events reordered by `project_seq` on backfill and on live append; run detail asserts ascending order. |
| S06-15 | Implemented | `events` indexed on `(project_id, project_seq)` (migration `0004`); payloads redacted before storage (unchanged from Phase 2/3). |
| S06-16 | Implemented | Was Pending: `outbox` (unique `event_id`, `published_at`, `retries`, `next_attempt_at`) via Alembic `0003`; `dashboard/summary.outbox_pending` exposes the backlog. Publisher worker still deferred. |
| S07-03 | Implemented | `POST /api/v1/runs/{run_id}/events` ingests SDK telemetry in one transaction (kind allowlist, 100-item cap); `test_ingest_endpoint_validates_input`. |
| S07-09 | Implemented | `GET /api/v1/dashboard/summary` — counters from committed rows only (`test_summary_counts_come_from_committed_rows`). |
| S07-10 | Implemented | `GET /api/v1/dashboard/runs` — server-side pagination + status/agent filters (`test_runs_pagination_and_filters`). |
| S07-11 | Implemented | `GET /api/v1/dashboard/runs/{id}` — run + events in `project_seq` order, project-scoped 404 (`test_run_detail_includes_ordered_events`). |
| S07-13 | Implemented | `GET /api/v1/events/stream` — project-scoped SSE with resume cursor. Note: served under the versioned `/api/v1` namespace rather than the spec's unversioned `/dashboard/events/stream` shorthand (§7 requires versioned routes). |
| S12-07 | Implemented | S7 reconnect scenario: cursor-based backfill loses nothing, `event_id` dedup duplicates nothing, byte-identical repeat backfills; live delivery over real HTTP; `ConnectionBadge` shows reconnect state. |

## Phase 5 status overrides (2026-10-17 — human approvals verified)

| Req ID | Status | Evidence |
|---|---|---|
| S01-04 | Implemented | A pending REVIEW action is decided by a human via `POST /api/v1/approvals/{id}/decision` (reviewer key, SoD-guarded); `test_approve_execute_moves_balance_once` proves the full loop. |
| S02-05 | Implemented | Durable `approvals` table (migration `0005`) with `expires_at` deadlines (default 15 min); `GET /api/v1/approvals` queue with state filter + pagination; lazy expiry applied on every read (`test_lazy_expiry_visible_in_queue`). |
| S02-14 | Implemented | OBJ-4: approvals are DB rows (survive reload/restart) carrying requester/reviewer key identity, expiry, and a full `approval.*` event audit trail (`test_approval_events_recorded`). |
| S03-01 | Implemented | Was Partial: scope *enforcement* now live — `require_scopes` dependency on all routes; SDK keys (`agent:run`/`agent:authorize`/`agent:execute`), reviewer keys (`approvals:read`/`approvals:decide`); `"*"` wildcard still grants everything (`test_reviewer_key_cannot_authorize`, `test_agent_key_cannot_decide`). |
| S03-03 | Implemented | M01/M10: reviewer identity is a scoped API key; separation of duties enforced at credential level — the requesting key can never decide (403 `sod_violation`, `test_sod_self_approval_forbidden`); dashboard cookie sessions deferred to Phase 6 (ADR-034/035). |
| S03-24 | Implemented | M10: state machine PENDING → APPROVED/REJECTED/EXPIRED with terminal-state stability; `require_reviewer` auth; optimistic concurrency on `row_version` (409 `approval_conflict`); idempotent same-reviewer re-decision (200) (`test_racing_double_decisions_single_execution`, `test_idempotent_redecision`, `test_stale_row_version_conflict`). |
| S03-25 | Implemented | M07/M10: approval mints a single-use grant (never executes); execute requires a linked APPROVED, unexpired approval and rechecks args hash + business facts; replays return the original result; tampered args → 409 `arguments_tampered` (`test_tampered_args_post_approval_rejected`). |
| S03-38 | Partial | Was Partial: rate limits now enforced — in-memory token bucket per key (default 60/min, `AGENTTRUST_RATE_LIMIT_PER_MINUTE`), 429 with `retryable: true` on POST authorize/execute/decision (`test_rate_limit_429`); single-process only, documented (ADR-039). Remaining M15 hardening (CSRF, CORS allowlist, dependency scanning) still open. |
| S04-14 | Implemented | Suspended approval is a durable DB row (never held in an HTTP request); `wait_for_approval` polls `GET /approvals/{id}/status` with a timeout and never auto-executes. |
| S05-14 | Implemented | Expired approval → 410 `approval_expired` on decision (auto-transitions to EXPIRED + event), 409 `approval_required` on execute; a fresh review is required (`test_expired_approval_rejected`). |
| S05-15 | Implemented | Args changed after approval → gateway hash mismatch → 409 `arguments_tampered`; the legitimate grant survives the attempt (`test_tampered_args_post_approval_rejected`). |
| S07-08 | Implemented | `GET /api/v1/approvals/{approval_id}/status` — lightweight durable-approval query for SDK polling; visible to the requesting key and `approvals:read` keys. |
| S07-17 | Implemented | `GET /api/v1/approvals` — approval queue with state filter + pagination, lazy expiry on read. |
| S07-18 | Implemented | `POST /api/v1/approvals/{approval_id}/decision` — authenticated approve/reject with SoD, lazy expiry, optimistic concurrency, idempotent re-decision, decision-time business revalidation (409 `approval_stale`, REJECTED `facts_changed`), and grant minting. |
| S07-25 | Partial | Structured envelope unchanged; 429 (rate limits) and 410 (expired approvals) added to the documented code table. |
| S12-02 | Implemented | Was Partial: REVIEW now returns a real `approval_id` (approval row created in the same transaction as the decision + `approval.created` event + outbox); `ApprovalRequired` carries it in the SDK. |

## Phase 6 status overrides (2026-10-17 — premium frontend verified)

| Req ID | Status | Evidence |
|---|---|---|
| S03-22 | Partial | M09 pages now real: Overview, Live Runs, Run Detail, Policies, Approvals, Agents, Analytics, Settings — all with live data, honest states, `npm run lint/typecheck/build` green. Tool Details has no standalone page (tool-call evidence lives in the run-detail timeline + approvals review panel). Incidents/Evaluations became real in Phase 7 (see Phase 7 overrides). |
| S07-27 | Implemented | NEW: `GET /api/v1/agents` — project-scoped paginated agent directory with run_count/last_run_at (`routers/agents.py`; `test_agents_analytics.py`: pagination, isolation, 404 leak check). |
| S07-28 | Implemented | NEW: `GET /api/v1/agents/{agent_id}` — identity + 20 newest runs with tool_call_count; 404 `agent_not_found` leaks nothing (same tests). |
| S07-29 | Implemented | NEW: `GET /api/v1/dashboard/analytics?window_days=` — decisions/day, execution latency p50/p95, top denied tools, approval turnaround, all from committed rows; empty data → empty arrays/nulls, never invented (seeded-analytics test asserts exact counts/percentiles; ADR-041). |
| S08-01 | Implemented | Overview page: KPI cards from `GET /dashboard/summary`, decision outcome badges + counts, real SVG sparkline from analytics decisions_by_day, recent-runs table, pending-approvals preview (reviewer key only, else muted hint); zero-state EmptyState. |
| S08-02 | Implemented | Live Runs: search (run/trace prefix), status/agent/date-range filters (server-side; `started_after`/`started_before`/`order` added additively with `test_runs_date_range_and_order_filters`), sortable started_at, pagination, SSE live-prepend, all states. |
| S08-03 | Implemented | Run Detail: header card, project_seq-ordered timeline with kind badges + payload summaries, approval deep-links (`/approvals?selected=`), redacted metadata `<details>`, live SSE append. |
| S08-04 | Partial | No standalone Tool Details page; registered schema, redacted args, args hash, trusted facts, policy version/reason, approval state and gateway result are shown in the run-detail timeline and the approvals review panel. |
| S08-05 | Implemented | Policies page: policy cards with version table, activate-with-confirm (bodiless POST matches backend semantics — activates latest draft), new-policy form with JSON validation, simulate card showing the WOULD-BE decision (outcome badge, reason_code, explanation, version, draft note). |
| S08-06 | Implemented | Approvals page restyled into the design system with all Phase 5 logic intact (reviewer-key flow, SSE refresh, approve/reject via confirm Dialog, 409 handling, `?selected=` deep link). |
| S08-07 | Implemented | Incidents page is real (Phase 7): filter bar, scan button, sortable table, detail with evidence timeline and analyzer-kind-labeled report panel (uncertainty + recommended checks). |
| S08-08 | Implemented | Evaluations page is real (Phase 7): suite info, Run button, run history, metrics cards, expected-vs-actual matrix with expandable failures, export JSON. Post-release audit (2026-10-17): tenant isolation added — `evaluation_runs.project_id` (migration 0007), all four endpoints scoped by caller project (HIGH-1); `POST /evaluations/run` no longer performs DDL, uses shared truncated eval DB under single-flight lock (HIGH-2). |
| S08-09 | Partial | Settings page: dashboard-key management (drives header badge), admin-gated API key issue/list/revoke with confirm + copy-once secret, SDK instructions copied verbatim from the package README, read-only environment card, live health card. Missing: registered-tools list, retention-config UI, telemetry preview, local-LLM status. |
| S08-10 | Implemented | UX acceptance: destructive actions behind Dialog confirms, consistent timestamp/currency formatting (`lib/format.ts`), status always icon+text via Badge (never color alone), full keyboard navigation (focus-visible rings, WAI-ARIA tabs, dialog focus trap), dark-first + light theme with persisted toggle, responsive sidebar. |
| S09-01 | Implemented | NEW (design system): Tailwind v3 + `app/tokens.css` (`:root`/`.dark` CSS variables), documented in `docs/DESIGN_TOKENS.md`; bespoke `components/ui/` library (ADR-043/044). No hard-coded statistics anywhere (verified by grep). |

---

## Phase 7 status overrides (2026-10-17 — evaluations + AI incident analysis verified)

| Req ID | Status | Evidence |
|---|---|---|
| S09-02 | Implemented | LangGraph Evidence Collector (`incidents/investigator.py`): loads incident, its evidence events (redacted, project_seq order), tool call + policy decision + policy version snapshot; read-only, no tools bound (node set asserted in `test_analyzer_binds_no_tools`). |
| S09-03 | Implemented | LangGraph Incident Analyzer: tries local Ollama (`AGENTTRUST_OLLAMA_MODEL`, default `qwen2.5:3b`, 30s timeout, JSON-only prompt over redacted evidence) with deterministic template fallback; `analyzer_kind` labels every report. No approval/execution/policy powers by construction. |
| S09-04 | Implemented | Evidence Validator: Pydantic schema; every cited evidence_ref must exist in the incident's evidence set (fabricated refs rejected in tests); uncertainty required non-empty; claims of approval/execution/policy change rejected by pattern denylist. |
| S09-05 | Implemented | Stored report carries `analyzer_kind` (`ollama:<model>` \| `template`); `/incidents` UI labels reports "AI-assisted" vs "deterministic"; uncertainty and recommended checks always shown. |
| S09-06 | Implemented | `incident.created`, `incident.analyzed`, `incident.status_changed` events stream via the event system/SSE. No `analysis_queued` state: analysis is synchronous (ADR-047); queue states arrive with a background worker. |
| S13-08 | Implemented | Gate: 100/100 deterministic labeled scenarios pass — measured 2026-10-17 via CLI and API (accuracy 1.0000). Reported as a measurement with gate targets beside it (ADR-051), not a universal guarantee. |
| S13-09 | Implemented | Gate: zero executions of known-denied actions — measured `unauthorized_executions: 0` across the 100-case suite; tamper cases assert balance unchanged and no execution row. |
| S13-10 | Implemented | Gate: no duplicated effects — measured `duplicate_effects: 0`; replay cases assert exactly one balance mutation across double executes. |
| S13-16 | Implemented | `benchmark-report.json` carries code version (git commit or honest "unknown"), OS/CPU/RAM, dataset hash + version, policy version, totals, pass/fail, latency p50/p95/max, model ("none"), and limitations. |

---

## Phase 8 status overrides (2026-10-17 — integration, metrics, traceability audit)

This section records (a) Phase 8 implementation evidence and (b) the final
traceability audit (2026-10-17): all 127 override rows from Phases 1–7 were
re-checked against the executed evidence in `docs/PROGRESS.md`; stale rows are
flipped below with their evidence. Nothing is marked Implemented without
executed evidence (a test file, a measured number, or a doc produced by a run).

| Req ID | Status | Evidence |
|---|---|---|
| S03-42 | Implemented | Was Pending: `GET /api/v1/metrics` (`routers/metrics.py`) returns project-scoped JSON counters — `decisions_by_outcome`, `executions_total`, `active_approvals`, `incidents_by_status` — counted from committed rows only. `test_metrics.py`: 4/4 passed on real PostgreSQL (re-run foreground 2026-10-17). Human-readable JSON by design (ADR-056), not Prometheus text. |
| S07-23 | Implemented | Was Partial ("`/metrics` not yet implemented"). Now: `/health/live`, `/health/ready` (real DB ping, `test_health.py`) and `/metrics` (`test_metrics.py`, 4 tests, re-run 2026-10-17) all live; metrics endpoint is project-key authenticated. |
| S06-11 | Implemented | Was Pending (no override existed): `approvals` table via Alembic `0005` — one active approval per tool call (unique tool_call FK), `row_version` optimistic concurrency — verified by fresh-DB `upgrade head` → 19 tables and the Phase 5 approval tests (`test_racing_double_decisions_single_execution`, `test_stale_row_version_conflict`). |
| S06-17 | Implemented | Was Pending (no override existed): `incidents` + `incident_evidence` via Alembic `0006` — project/status index, unique (incident_id, event_id) — verified by fresh-DB `upgrade head` → 24 tables (PROGRESS Phase 7). |
| S06-18 | Implemented | Was Pending (no override existed): `evaluation_cases` (unique case_key) via Alembic `0006`; fresh-DB → 24 tables (PROGRESS Phase 7). |
| S06-19 | Implemented | Was Pending (no override existed): `evaluation_runs` (suite/time index, code_version, policy_version) via Alembic `0006` (PROGRESS Phase 7). |
| S06-20 | Implemented | Was Pending (no override existed): `evaluation_results` (unique run/case, actual_outcome, passed, latency_ms) via Alembic `0006` (PROGRESS Phase 7). |
| S03-26 | Implemented | Was Pending (no override existed): deterministic incident triggers — discrete request-path triggers (`arguments_tampered` → high, consumed-grant replay → medium, amount overflow > 2× review_max → medium, dedup one OPEN per (category, tool_call)) + on-demand `POST /incidents/scan`; 8 detector/API tests in `test_incidents.py` (PROGRESS Phase 7). |
| S03-27 | Implemented | Was Pending (no override existed): LangGraph `collect_evidence → analyze → validate` over redacted evidence; node set asserted structurally (`test_analyzer_binds_no_tools`); citations verified, policy/execution claims rejected (PROGRESS Phase 7). |
| S03-28 | Implemented | Was Pending (no override existed): zero-cost deterministic template fallback when no local model — the tested path in this environment (no Ollama here); UI labels reports "AI-assisted"/"deterministic" via `analyzer_kind`; uncertainty + recommended checks always shown (PROGRESS Phase 7). |
| S03-29 | Implemented | Was Pending (no override existed): 100-case dataset — 25 allow / 20 review / 20 limit-deny / 15 invalid-deny / 10 tamper-replay / 10 malformed (injection-shaped inputs treated as data) (PROGRESS Phase 7). |
| S03-30 | Implemented | Was Pending (no override existed): one-command runner `python -m agenttrust_api.evaluation.run --db <url>` against an isolated DB (fresh per run, migrated, seeded, orders reset per case); CLI and synchronous API agree, both 100/100 (PROGRESS Phase 7). |
| S07-05 | Implemented | Was Pending (no override existed): `POST /api/v1/tool-calls/{call_id}/execute` — trusted gateway performs the authorized synthetic action; same evidence as S01-08 (Phase 3: single-use grants, tamper/expiry/replay rejection, `test_allow_execute_moves_balance_once`). |
| S07-19 | Implemented | Was Pending (no override existed): `GET /api/v1/incidents` — status/severity filters, pagination, cross-project 404 (PROGRESS Phase 7 API list). |
| S07-20 | Implemented | Was Pending (no override existed): `POST /api/v1/incidents/{id}/analyze` — synchronous analysis in-request, no queued state (ADR-047); reviewer/project-key auth (PROGRESS Phase 7). |
| S07-21 | Implemented | Was Pending (no override existed): `POST /api/v1/evaluations/run` — synchronous benchmark run, reviewer-key gated (ADR-052) (PROGRESS Phase 7). |
| S07-22 | Implemented | Was Pending (no override existed): `GET /api/v1/evaluations/runs`, `/runs/{id}`, `/runs/{id}/report` (JSON download) (PROGRESS Phase 7 API list). |
| S07-26 | Implemented | Was Pending (no override existed): SSE stream emits valid `data:` + `id:` (cursor) lines; the spec's `event:` named lines are dropped by documented deviation (ADR-029 — browsers cannot wildcard-subscribe named SSE events); event kind travels in the data envelope. |
| S12-01 | Implemented | Was Partial ("Live dashboard stream remains Phase 4"). Now: `demo.py` S1 5/5 live (Phase 3) + SSE live timeline with <2 s committed-event-to-stream delivery + cursor backfill (Phase 4). |
| S12-05 | Implemented | Was Pending (no override existed): 8-thread `test_concurrent_executes_single_side_effect` — exactly one balance mutation; replay execute → 200 with original result (PROGRESS Phase 3). |
| S12-06 | Implemented | Was Pending (no override existed): `test_sdk_unavailable_fails_closed` — unreachable API → typed `PolicyServiceUnavailable`, zero execution rows, balance untouched (PROGRESS Phase 3). |
| S12-08 | Implemented | Was Pending (no override existed): investigator offline path = deterministic template with the exact policy reason + evidence/policy snapshot; synchronous, no queue states (ADR-047); the template path is what is tested here (PROGRESS Phase 7). |
| S04-11 | Implemented | Was Pending (no override existed): measured decision p95 19 ms (builder) / 53 ms (independent verifier) vs the ~200 ms target on the 100-case benchmark, 2026-10-17 (PROGRESS Phase 7); reported as a measurement, not a real-world guarantee (ADR-051). |
| S04-18 | Implemented | Was Pending (no override existed): incident state machine OPEN → INVESTIGATING → RESOLVED/DISMISSED via `PATCH /incidents/{id}`; reopening to INVESTIGATING is tested as the audited path (`test_incidents.py`, PROGRESS Phase 7). |
| S05-18 | Implemented | Was Pending (no override existed): Ollama failure → deterministic template; "analysis unavailable" posture is the tested path here — no Ollama in this environment (PROGRESS Phase 7). |
| S05-21 | Partial | Was Pending (no override existed): cross-project access → 404 without data leakage, verified in tests (Phases 2–4). The "audit entry" half is not separately implemented — there is no `audit_events` table (S06-22 still Pending); events ride the event store instead. |
| S07-24 | Partial | Was Pending (no override existed): scoped API tokens (SDK keys `agent:run`/`agent:authorize`/`agent:execute`, reviewer keys `approvals:read`/`approvals:decide`) implemented and scope-enforced (Phases 1/5). Secure dashboard browser session is NOT implemented — reviewer key in sessionStorage remains the dev-only posture (ADR-034, Phase 6 limitations). |
| S14-01 | Implemented | Was Partial ("frontend slice pending"). The Week 1 gate — health + migration tests pass — is satisfied; the frontend is now fully real (Phase 6). The `docker compose up` caveat is tracked under S11-04, not this row. |
| S03-03 | Implemented | Status unchanged; evidence amended: credential-level reviewer identity + SoD enforced (403 `sod_violation`); dashboard cookie sessions are still NOT implemented — sessionStorage key remains dev-only posture (Phase 6 deliberate limitation, ADR-034). |
| S03-31 | Partial | Was Pending (no override existed): evaluation report JSON export implemented (`GET /evaluations/runs/{id}/report`, PROGRESS Phase 7). CSV trace exports and Markdown incident reports are not implemented. |
| S16-20 | Partial | Was Pending: no demo video was recorded — this environment has no screen capture. `docs/DEMO_SCRIPT.md` is provided instead as the exact narrated script with commands (ADR-055); `docs/EXECUTIVE_SUMMARY.md` states this explicitly. |
| S16-23 | Implemented | Was Pending: MIT `LICENSE` is present at the repo root (ADR-053). |
| S14-08 | Partial | Was Pending (no override existed): packaging + docs + demo script + measured benchmarks delivered (README, `docs/DEMO_SCRIPT.md`, `docs/EXECUTIVE_SUMMARY.md`, `evals/benchmark-report-2026-10-17.json`). CI is not yet wired (no `.github/workflows`) and a from-scratch fresh-install run has not been executed. |

Rows deliberately left at their standing values (verified, no evidence found): S07-06, S07-07,
S07-12 (endpoints not built — tool-call evidence lives in the run-detail timeline and
approvals review panel); S06-22, S03-35/36/37 (no `audit_events` table, no M15 audit
module); S03-32 (scheduled digests/PDF), S03-39/40/41, S04-19, S06-21 (no background
worker — deferred by design, ADR-028/047); S03-43 (no structured-JSON log pipeline;
OpenTelemetry not yet wired); S04-17 (run status column exists but COMPLETED/FAILED/
TIMED_OUT transitions are not driven — completion rides events); S05-13 (DB-down 503
tested only on `/health/ready`, not on sensitive ops); S05-17 (no worker to kill);
S05-22 (422 tested; 413 oversized-payload rejection not implemented); S10-12
(Playwright e2e deferred; Hypothesis not used); S16-19 (no screenshots committed).

---

## §1 — Executive overview

| Req ID | Requirement | Owner |
|---|---|---|
| S01-01 | Developer can clone repo and start the stack locally with no paid account | M18 / infra |
| S01-02 | Sample agent runs and produces observable decisions on the dashboard | M02 / examples |
| S01-03 | ALLOW, REVIEW, DENY outcomes are all demonstrable | M06 / M07 |
| S01-04 | A pending action can be approved by a human reviewer | M10 |
| S01-05 | An incident can be inspected with recorded evidence | M11 |
| S01-06 | Reproducible evaluation suite runs with one command | M12 |
| S01-07 | Synthetic refund agent enforces rules from trusted business records, not LLM reasoning | M05 / M07 |
| S01-08 | Mock payment service verifies single-use authorization before changing refund state | M07 |
| S01-09 | No guarantee of universal prompt-injection prevention is claimed | M11 / M18 |
| S01-10 | No automatic interception of arbitrary agents, OS operations, or unwrapped network calls | M02 / M18 |
| S01-11 | No real financial/medical operations; refund system is synthetic only | M07 / M18 |
| S01-12 | No enterprise compliance certification, billing, multi-region uptime, SaaS tenancy, or public SLA | M18 |
| S01-13 | No autonomous policy modification by an LLM | M11 |
| S01-14 | No claims that model-generated incident analysis is infallible | M11 / M18 |

## §2 — Real-world problems and product objectives

| Req ID | Requirement | Owner |
|---|---|---|
| S02-01 | Consolidated live timeline of agent tool actions (trace completeness) | M08 / M09 |
| S02-02 | Pre-execution rule blocks refunds outside allowed amounts (unauthorized executions = 0) | M05 / M06 |
| S02-03 | Policy fetches eligibility from trusted source of truth, not model claims | M05 |
| S02-04 | Untrusted prompt text cannot change a deterministic decision (attack suite) | M05 / M12 |
| S02-05 | Durable review queue with deadlines for legitimate large refunds | M10 |
| S02-06 | Idempotency keys + transactional claim prevent duplicate effects on retry | M06 / M07 |
| S02-07 | Evidence-linked policy result explains each denial | M06 / M11 |
| S02-08 | Static policy-case replay for regression after prompt/policy change | M12 |
| S02-09 | Redaction + field allowlists keep secrets out of traces (secret-leakage tests) | M08 / M15 |
| S02-10 | Policy API outage fails closed for sensitive tools | M06 / M02 |
| S02-11 | OBJ-1 Block before effect: authorization precedes any protected side-effect invocation | M06 / M07 |
| S02-12 | OBJ-2 Deterministic security: versioned, schema-validated code — never model judgment | M05 |
| S02-13 | OBJ-3 Transparency: stable correlation IDs and live event timeline | M08 |
| S02-14 | OBJ-4 Durable reviews: approval survives reload/restart with identity, expiry, auditability | M10 |
| S02-15 | OBJ-5 Least privilege: API key scopes, tool allowlists, role checks | M01 / M04 |
| S02-16 | OBJ-6 No repeat side effects: idempotent execution + uniqueness constraints | M06 / M07 |
| S02-17 | OBJ-7 Proven behavior: reproducible benchmarks, security scenarios, CI tests | M12 / M17 |
| S02-18 | OBJ-8 Accessible: complete local experience with zero paid dependencies | M18 / infra |

## §3 — Functional modules (MVP vs Stretch)

| Req ID | Requirement | Owner |
|---|---|---|
| S03-01 | M01 (MVP): project-scoped auth; API key issuance/revocation, copy-once display, hashed storage | M01 |
| S03-02 | M01 (MVP): key revocation affects subsequent authorizations immediately | M01 / M06 |
| S03-03 | M01 (MVP): separate reviewer identity for approval demos; no self-approval when SoD enabled | M01 / M10 |
| S03-04 | M02 (MVP): SDK `AgentTrustClient`, `protect(tool=...)`, run context, typed exceptions | M02 |
| S03-05 | M02 (MVP): DENY never invokes the protected function; REVIEW returns pending reference, no execution | M02 |
| S03-06 | M02 (MVP): timeouts, bounded retries only for safe/idempotent requests; timeouts never become permissive | M02 |
| S03-07 | M03 (MVP): agent registry + run lifecycle (UUID run, trace ID, states, server sequence numbers) | M03 |
| S03-08 | M04 (MVP): tool registry with versioned JSON schema, risk class, redaction config | M04 |
| S03-09 | M04 (MVP): unknown tool names fail closed; requester schemas never override server schemas | M04 |
| S03-10 | M04 (MVP): canonicalized input hashing; integer minor units or Decimal for money — never float | M04 |
| S03-11 | M05 (MVP): Pydantic-validated configs + deterministic rule functions returning ALLOW/DENY/REVIEW with code, explanation, policy version | M05 |
| S03-12 | M05 (MVP): policies immutable after activation; edits create new versions; decisions pin exact version | M05 |
| S03-13 | M05 (MVP): refund thresholds — ≤10000 minor units + eligible → ALLOW; 10001–50000 → REVIEW; above cap/balance → DENY | M05 |
| S03-14 | M06 (MVP): central decision API; atomic `tool_call` + `policy_decision` persistence | M06 |
| S03-15 | M06 (MVP): idempotent authorize — same key + payload hash → stable response; changed payload → 409 | M06 |
| S03-16 | M06 (MVP): local ~2s decision target; timeout/unavailable never authorizes sensitive side effects | M06 |
| S03-17 | M07 (MVP): gateway rechecks identity, canonical arg hash, approval/policy validity, expiry, single-use at execution time | M07 |
| S03-18 | M07 (MVP): transactional claim of execution token + idempotency key; row-locked balance update exactly once | M07 |
| S03-19 | M08 (MVP): event envelope (ID, project, run, trace, tool-call/parent IDs, server sequence, source+receipt time, type, redacted payload, schema version) | M08 |
| S03-20 | M08 (MVP): append-only logical events in PostgreSQL; transactional outbox; worker → SSE publish | M08 / M16 |
| S03-21 | M08 (MVP): SSE subscription, Last-Event-ID reconnect, backfill; dashboard eventually consistent, never a security control | M08 |
| S03-22 | M09 (MVP): Overview, Live Runs, Run Detail, Tool Call Detail, Policies, Approvals, Evaluations, Incidents, Integration/Settings pages | M09 |
| S03-23 | M09 (MVP): redacted args, policy code, decision reason, durations, filters; explicit Live/Reconnecting/Offline state | M09 |
| S03-24 | M10 (MVP): approval state machine PENDING → APPROVED/REJECTED/EXPIRED; authenticated reviewer; optimistic concurrency | M10 |
| S03-25 | M10 (MVP): post-approval execution requires fresh authorization bound to same args hash + idempotency key, with business-fact revalidation | M07 / M10 |
| S03-26 | M11 (MVP basic): deterministic incident triggers (repeated denials, amount overflow, tool errors, policy failure, duplicate token, grant tamper) | M11 |
| S03-27 | M11 (Stretch AI): LangGraph Collector → Analyzer → Validator over redacted evidence; citations verified; model cannot act | M11 |
| S03-28 | M11 (Stretch AI): zero-cost fallback — deterministic templates when no local model; UI labels AI text non-authoritative | M11 |
| S03-29 | M12 (MVP): 100-case dataset (25 ALLOW / 20 REVIEW / 20 limit-DENY / 15 invalid-context-DENY / 10 tamper-DENY / 10 malformed-DENY), independently labeled | M12 |
| S03-30 | M12 (MVP): one-command seeded runner on isolated DB; verdict includes whether the tool actually executed | M12 |
| S03-31 | M13 (MVP minimal): CSV/JSON trace exports, eval results, decisions, Markdown incident reports — redacted, authorized | M13 |
| S03-32 | M13 (Stretch): scheduled digests, PDF reports, incident bundles, report comparison | M13 |
| S03-33 | M14 (MVP local): in-app/SSE alerts for pending approvals, denial spikes, incidents, worker failures | M14 |
| S03-34 | M14 (Stretch): external email/SMS/WhatsApp explicitly out of required MVP | M14 |
| S03-35 | M15 (MVP): audit of logins, key lifecycle, policy activation, approvals, execution attempts, security-setting changes | M15 |
| S03-36 | M15 (MVP): append-only application permissions + ordered event IDs; no immutability promise against privileged DB admin | M15 |
| S03-37 | M15 (MVP): configurable 14–30 day retention; project export/delete; differential retention for incident aggregates | M15 |
| S03-38 | M15 (MVP): no default public admin, least-privilege DB user, env secrets, CSRF, rate limits, input size limits, CORS allowlist, dependency scanning | M15 |
| S03-39 | M16 (MVP): PostgreSQL-backed worker (SKIP LOCKED leases) for outbox publish, approval expiry, run summaries, eval runs, incident reports, retention cleanup | M16 |
| S03-40 | M16 (MVP): lease expiry + retry + exponential backoff + dead-letter + idempotent handlers + admin reprocess | M16 |
| S03-41 | M16 (MVP): worker heartbeat, backlog count, retries, dead-letter list visible in admin status | M16 |
| S03-42 | M17 (MVP basics): built-in metrics endpoint (API rate, decision latency, authz failures, DB errors, outbox backlog, SSE clients, worker stats) | M17 |
| S03-43 | M17 (MVP basics): structured JSON logs with correlation IDs, sanitized errors; OpenTelemetry SDK for future export | M17 |
| S03-44 | M18 (MVP): install guide, quickstart, SDK docs, OpenAPI, FAQ, security model, ADRs, failure table, eval method, dev workflow, license, contributing, demo scripts | M18 |
| S03-45 | M18 (MVP): success criterion — another engineer reproduces the protected refund flow from the README | M18 |

## §4 — End-to-end architecture

| Req ID | Requirement | Owner |
|---|---|---|
| S04-01 | Container `web`: Next.js dashboard server and browser assets | infra |
| S04-02 | Container `api`: FastAPI endpoints, policy evaluation, SSE feed | infra |
| S04-03 | Container `db`: PostgreSQL source of truth | infra |
| S04-04 | Container `worker`: outbox publisher, evaluator, incident worker, cleanup | infra |
| S04-05 | Container `demo-agent`: controlled sample agent invoking protected tools | examples |
| S04-06 | Container `local-llm` (optional): Ollama/local inference, not required | infra |
| S04-07 | Event path: SDK → API → single DB transaction → outbox → worker → SSE → dashboard | M08 / M16 |
| S04-08 | Commit tool-call + decision + outbox row in ONE database transaction | M06 / M08 |
| S04-09 | Dashboard uses REST snapshot then SSE patch; dedup by event ID; never the authority for execution | M09 |
| S04-10 | Gateway checks persisted authorization; browser reconnect never grants authority | M07 |
| S04-11 | SLO target (not guarantee): local deterministic decision p95 < ~200 ms at low load, excluding expensive trusted lookups | M06 |
| S04-12 | SLO target (not guarantee): committed-event-to-browser visibility < 1 s on localhost | M08 / M16 |
| S04-13 | SSE reconnect uses exponential backoff + gap recovery | M08 |
| S04-14 | Suspended approval durable indefinitely until configured expiry; never hold an HTTP request open | M10 |
| S04-15 | SDK on policy outage: typed failure, no tool execution | M02 |
| S04-16 | Tool-call state machine: REQUESTED → POLICY_CHECKED → DENIED / APPROVAL_PENDING / AUTHORIZED → EXECUTING → SUCCEEDED / FAILED; APPROVED → AUTHORIZED only after renewed checks; terminal states never regress | M06 / M10 |
| S04-17 | Run state machine: CREATED → RUNNING → COMPLETED / FAILED / TIMED_OUT | M03 |
| S04-18 | Incident state machine: OPEN → INVESTIGATING → RESOLVED / DISMISSED; reopening is an audited transition | M11 |
| S04-19 | Worker-job state machine: QUEUED → CLAIMED → SUCCEEDED / RETRY_WAIT / DEAD_LETTER | M16 |

## §5 — Threat model

| Req ID | Requirement | Owner |
|---|---|---|
| S05-01 | Assets protected: protected actions, synthetic refund balances, API keys, trace metadata, approval identities, project data, policy versions, local model inputs, audit events | THREAT_MODEL.md / all |
| S05-02 | Adversaries modeled: untrusted prompts, hallucinations, malicious documents, compromised SDK keys, unauthorized dashboard users, arg tampering, stale approvals, duplicate calls, compromised dev environment, outages; malicious server admin out of scope | THREAT_MODEL.md |
| S05-03 | Boundary: untrusted prompt vs tool — natural language never overrides deterministic backend policy | M05 |
| S05-04 | Boundary: SDK vs protected service — gateway independently enforces single-use authorization | M07 |
| S05-05 | Boundary: browser vs API — authorization server-side, never via hidden UI controls | M09 / M10 |
| S05-06 | Boundary: agent data vs trusted facts — eligibility/balance from server-owned records | M05 |
| S05-07 | Boundary: model vs evaluator — incident LLM offers analysis only, zero execution permissions | M11 |
| S05-08 | Boundary: tenant vs tenant — project identity from verified credentials, not request JSON | M01 |
| S05-09 | Boundary: telemetry vs secrets — redact before ingestion; opt-in for sensitive fields | M08 / M15 |
| S05-10 | Boundary: retries vs external effect — idempotent replay from persisted execution state + transactional locking | M06 / M07 |
| S05-11 | Failure: policy API unreachable → no execution; SDK raises PolicyServiceUnavailable | M02 / M06 |
| S05-12 | Failure: SSE interrupted → reconnecting UI + missed-event fetch; connection status visible | M08 / M09 |
| S05-13 | Failure: DB unavailable → sensitive ops rejected with 503 + structured error | M06 |
| S05-14 | Failure: approval expires → execution rejected; new review required | M10 |
| S05-15 | Failure: args change after approval → hash mismatch rejected | M07 |
| S05-16 | Failure: same request repeated → prior result returned, no second effect | M06 / M07 |
| S05-17 | Failure: worker dies → lease expires, retry occurs; backlog visible | M16 |
| S05-18 | Failure: LLM unavailable → deterministic incident details; "analysis unavailable" status | M11 |
| S05-19 | Failure: policy changes after grant → revalidate or invalidate grant | M07 |
| S05-20 | Failure: events arrive out of order → reorder/backfill by server sequence | M08 |
| S05-21 | Failure: unauthorized project access → 403/404 without data leakage + audit entry | M01 |
| S05-22 | Failure: invalid/oversized payload → 422/413 rejection | M04 |

## §6 — Data model and constraints

| Req ID | Requirement | Owner |
|---|---|---|
| S06-01 | `users`: unique account ID | M01 |
| S06-02 | `projects`: owner FK | M01 |
| S06-03 | `memberships`: unique (user_id, project_id) | M01 |
| S06-04 | `api_keys`: key_prefix, key_hash, scopes, expiry, revocation; never store raw key | M01 |
| S06-05 | `agents`: project/name index | M03 |
| S06-06 | `agent_runs`: project/time/status indexes | M03 |
| S06-07 | `tool_definitions`: unique project/slug/version; schema_json, risk_class | M04 |
| S06-08 | `tool_calls`: unique (project_id, idempotency_key); args_redacted, args_hash, state | M06 |
| S06-09 | `policies`: unique project/name; `policy_versions` immutable once active | M05 |
| S06-10 | `policy_decisions`: decision → tool_call FK; outcome, reason_code, decided_at, version pinned | M06 |
| S06-11 | `approvals`: one active approval per tool call; row_version for optimistic concurrency | M10 |
| S06-12 | `execution_grants`: unique single-use grant (high-entropy secret hash if tokenized); expiry | M07 |
| S06-13 | `tool_executions`: unique successful execution per call | M07 |
| S06-14 | `mock_orders`: total_minor, refundable_remaining_minor, currency, status; transactionally locked | M07 |
| S06-15 | `events`: indexed project/seq/time; redacted payloads | M08 |
| S06-16 | `outbox`: unique event ID; published_at, retries, next_attempt_at | M08 / M16 |
| S06-17 | `incidents` + `incident_evidence`: project/status index; unique (incident_id, event_id) | M11 |
| S06-18 | `evaluation_cases`: dataset version; input_json, expected_outcome, case_type | M12 |
| S06-19 | `evaluation_runs`: suite/time index; code_version, policy_version | M12 |
| S06-20 | `evaluation_results`: unique (run_id, case_id); actual_outcome, passed, latency_ms | M12 |
| S06-21 | `worker_jobs`: due/status index; state, lease_until, attempts | M16 |
| S06-22 | `audit_events`: restricted, append-only at application level | M15 |
| S06-23 | Currency: integer minor units + verified currency; never Python float for enforcement | all |
| S06-24 | Timestamps: UTC ISO-8601 with timezone | all |
| S06-25 | IDs: UUIDv7/UUID4 acceptable | all |
| S06-26 | Canonical JSON hashing with stable property order and defined numeric representation; cross-client consistency tested | M04 |
| S06-27 | Deletion: careful cascades; regulatory-grade audit preservation out of scope | M15 |

## §7 — API contracts

| Req ID | Requirement | Owner |
|---|---|---|
| S07-01 | POST /api/v1/runs — create run, return run_id + trace_id | M03 |
| S07-02 | PATCH /api/v1/runs/{run_id} — finish/fail run with validated state | M03 |
| S07-03 | POST /api/v1/runs/{run_id}/events — batch redacted telemetry | M08 |
| S07-04 | POST /api/v1/tool-calls/authorize — ALLOW/DENY/REVIEW decision | M06 |
| S07-05 | POST /api/v1/tool-calls/{call_id}/execute — trusted gateway performs authorized synthetic action | M07 |
| S07-06 | GET /api/v1/tool-calls/{call_id} — project-scoped outcome read | M06 |
| S07-07 | POST /api/v1/tool-calls/{call_id}/result — cooperative external-tool result report (non-authoritative) | M07 |
| S07-08 | GET /api/v1/approvals/{approval_id}/status — durable approval query | M10 |
| S07-09 | GET /api/v1/dashboard/summary — initial counters and health | M09 |
| S07-10 | GET /api/v1/dashboard/runs — paginated/filterable runs | M09 |
| S07-11 | GET /api/v1/dashboard/runs/{id} — run detail with ordered events | M09 |
| S07-12 | GET /api/v1/dashboard/tool-calls/{id} — policy decision and evidence | M09 |
| S07-13 | GET /api/v1/dashboard/events/stream — project-scoped SSE with resume cursor | M08 |
| S07-14 | GET/POST /api/v1/policies — list/create policy draft | M05 |
| S07-15 | POST /api/v1/policies/{id}/activate — activate immutable version | M05 |
| S07-16 | POST /api/v1/policies/simulate — non-mutating policy preview | M05 |
| S07-17 | GET /api/v1/approvals — pending/decided approval queue | M10 |
| S07-18 | POST /api/v1/approvals/{id}/decision — authenticated approve/reject, optimistic concurrency | M10 |
| S07-19 | GET /api/v1/incidents — incident list | M11 |
| S07-20 | POST /api/v1/incidents/{id}/analyze — queue optional local analysis | M11 |
| S07-21 | POST /api/v1/evaluations/run — enqueue benchmark run | M12 |
| S07-22 | GET /api/v1/evaluations/runs/{id} — read results | M12 |
| S07-23 | GET /api/v1/health/live, /health/ready, /metrics (protected or local-only) | M17 |
| S07-24 | Auth: scoped API token (SDK), secure browser session (dashboard), service credential (gateway/worker), reviewer role (approval mutation) | M01 |
| S07-25 | Status codes: 201/200/202/400/401/403/404-no-leak/409/413/422/429/503; consistent error_code, message, request_id, retryable | all |
| S07-26 | SSE message contract: valid `event:`/`data:` lines; Last-Event-ID validated within authenticated project; project-scoped cursor | M08 |
## §8 — UI information architecture

| Req ID | Requirement | Owner |
|---|---|---|
| S08-01 | Overview page: header (product/project/env/connection), KPI panels, recent events, failed/blocked calls, activity chart; REST snapshot + SSE patch | M09 |
| S08-02 | Live Runs page: search, filter by agent/version/status/time, expandable rows, loading/empty/live/disconnected/error states | M09 |
| S08-03 | Run Detail page: header, vertical event timeline, tool sequence, latency, decision reason, approval/incident links, masked metadata; ordered by server sequence | M09 |
| S08-04 | Tool Details page: registered schema, redacted args, args hash, trusted evaluated attributes, policy version, decision reasoning, approval state, gateway result, retry chain | M09 |
| S08-05 | Policy Builder page: numeric thresholds, tool allowlists, version list, draft editing, activation confirmation, preview simulator; no arbitrary source-code editor | M05 / M09 |
| S08-06 | Approvals page: pending queue, severity, requester, trusted context, exact params, expiry; approve/reject with reason; 409 on double-decide | M10 / M09 |
| S08-07 | Incidents page: category, severity, facts/evidence refs, timeline, AI summary labeled non-authoritative, proposal recommendations, analyst notes, resolved/dismissed | M11 / M09 |
| S08-08 | Evaluations page: suite, case count, policy version, executed date, expected/actual matrix, failing cases, replay, export, run comparison | M12 / M09 |
| S08-09 | Integration & Settings page: SDK install instructions, key lifecycle, registered tools, retention settings, telemetry preview, connection health, local-LLM status | M01 / M09 |
| S08-10 | UX acceptance: explicit feedback for sensitive states, confirmation for destructive actions, consistent timestamp/currency formatting, text+color status, full keyboard navigability, ARIA labels | M09 |

## §9 — Agent and AI workflows

| Req ID | Requirement | Owner |
|---|---|---|
| S09-01 | Baseline: sample agent is deterministic scripted or local open-weight; security/testing never depend on model performance; policies stay deterministic | examples / M05 |
| S09-02 | LangGraph Evidence Collector: fetch only authorized redacted events + policy snapshot + gateway results | M11 |
| S09-03 | LangGraph Incident Analyzer: local model proposes causes with citations, confidence, uncertainty; no tool/policy/approval powers | M11 |
| S09-04 | Evidence Validator: Pydantic-validated output; cited IDs must exist; unsourced assertions rejected where feasible | M11 |
| S09-05 | Presentation: stored summary carries model/version + data refs; UI labels AI-assisted text | M11 |
| S09-06 | Analysis progress events (analysis_queued/started/completed/failed) streamed via the event system | M11 / M08 |
| S09-07 | Stretch agents (Pattern Analyzer, Regression Case Proposer, Policy Recommendation Assistant) — not required for MVP | M11 |

## §10 — Free and open-source stack

| Req ID | Requirement | Owner |
|---|---|---|
| S10-01 | Frontend: Next.js + React + TypeScript + Tailwind CSS, self-hosted | infra |
| S10-02 | Backend: Python + FastAPI + Pydantic | infra |
| S10-03 | SDK: httpx + stdlib (+ Pydantic as needed) | M02 |
| S10-04 | ORM/migrations: SQLAlchemy + Alembic | M01–M16 |
| S10-05 | Data store: PostgreSQL (free/open license) | infra |
| S10-06 | Real-time push: SSE from FastAPI (no paid messaging vendor) | M08 |
| S10-07 | Work queue: PostgreSQL outbox + worker (no Redis/queue hosting) | M16 |
| S10-08 | Policy engine: plain Python functions + validated JSON (no OPA for MVP) | M05 |
| S10-09 | Agent workflow: LangGraph OSS package (optional incident analysis) | M11 |
| S10-10 | Language model: Ollama/local appropriately licensed open-weight model; optional | M11 |
| S10-11 | Observability: OpenTelemetry SDK; simple built-in metrics endpoint initially | M17 |
| S10-12 | Tests: pytest, Hypothesis, Playwright | M12 / TEST_STRATEGY |
| S10-13 | Documentation: Markdown in repo | M18 |
| S10-14 | Containers: Docker/Podman Compose, local only; verify desktop product license terms | infra |
| S10-15 | CI: GitHub Actions quotas/terms noted; no CI vendor dependency | .github |
| S10-16 | Source control: Git; public GitHub repo optional | infra |
| S10-17 | Hosting: localhost; $0 recurring software/cloud fee (hardware and power not free) | infra |
| S10-18 | Alerts: in-app/SSE only | M14 |
| S10-19 | Hard boundary honored: everything in this stack runs locally with no external bills | all |

## §11 — Local setup and operational runbook

| Req ID | Requirement | Owner |
|---|---|---|
| S11-01 | Prerequisites documented: Git, Python 3.12+ (compatibility verified), Node.js current LTS, PostgreSQL, Docker/Podman optional, Ollama optional | M18 / infra |
| S11-02 | Configuration via environment: DATABASE_URL, AGENTTRUST_ENV, AGENTTRUST_ENFORCEMENT_FAIL_CLOSED, AGENTTRUST_AUTH_MODE, AGENTTRUST_CAPTURE_RAW_PAYLOADS, AGENTTRUST_EVENT_RETENTION_DAYS, AGENTTRUST_ENABLE_LOCAL_AI, AGENTTRUST_SSE_HEARTBEAT_SECONDS | infra |
| S11-03 | `.env.example` with empty placeholders; no real `.env` or credentials committed; dev ports bound to 127.0.0.1 | infra |
| S11-04 | Documented startup sequence (clone → .env → Postgres → migrations+seed → API/worker health → web → sample agent → dashboard review → pytest/eval run) with commands verified by execution | M18 |
| S11-05 | Backup/recovery: local pg_dump, no secret-bearing dumps in repo, restore + migration/health checks, expired grants never revalidate on restore | M15 |

## §12 — End-to-end live scenarios

| Req ID | Requirement | Owner |
|---|---|---|
| S12-01 | S1 — Safe automatic refund: $40 of $400 verified balance → ALLOW; balance moves to $360 exactly once; stream shows approval, execution start, success | M05 / M06 / M07 / M09 |
| S12-02 | S2 — Human-reviewed refund: $150 with $100 auto threshold → REVIEW; reviewer approves; rechecks state + arg hash; executes exactly once; balance consumed meanwhile → deny + fresh review | M06 / M10 / M07 |
| S12-03 | S3 — Denied excessive refund: $900 vs $500 cap → DENY; gateway never called; incident trigger records attempt; balance unchanged | M05 / M06 / M11 |
| S12-04 | S4 — Prompt injection: "ignore the refund policy…" → only normalized args + trusted facts decide; deny regardless of model compliance | M05 / M12 |
| S12-05 | S5 — Duplicate/race: concurrent identical executions → transactional lock + idempotency → exactly one effect; second gets prior outcome or conflict | M07 |
| S12-06 | S6 — Policy service outage: typed unavailable error, local log, no gateway execution; deliberate retry on same idempotency key later | M02 / M06 |
| S12-07 | S7 — Dashboard reconnect: 10 s SSE disconnect mid-decisions → Reconnecting indicator, backfill by last sequence, zero timeline gaps | M08 / M09 |
| S12-08 | S8 — Incident investigator offline: evidence + policy snapshot fetched; LangGraph draft if model enabled, else deterministic template with exact policy reason; queued→running→complete statuses | M11 |

## §13 — Evaluation and acceptance

| Req ID | Requirement | Owner |
|---|---|---|
| S13-01 | Layer 1 Unit: threshold rules, schema validation, canonical hashing, approval transitions, redaction, permissions | M12 |
| S13-02 | Layer 2 Integration: policy API + Postgres + gateway transactions, outbox, multi-client streaming, worker retry | M12 |
| S13-03 | Layer 3 Security: cross-project access, expired credentials, changed arg hashes, forged grants, oversized payloads, injection strings, concurrency | M12 |
| S13-04 | Layer 4 E2E: browser runs/approvals, SDK sample, live status/reconnect (Playwright) | M12 |
| S13-05 | Layer 5 Performance: decision p50/p95 latency, SSE lag, backfill correctness, load during evaluations | M12 |
| S13-06 | Layer 6 Recovery: DB outage, worker kill/restart, lost response, partial failure and restore | M12 |
| S13-07 | Layer 7 AI quality (optional): evidence citation correctness, report factuality on human-labeled incidents | M11 / M12 |
| S13-08 | Gate: correct outcome for 100/100 initial deterministic labeled scenarios | M12 |
| S13-09 | Gate: zero execution of known-denied actions in fixed suite | M12 |
| S13-10 | Gate: no duplicated synthetic refund effects in concurrent idempotency tests | M12 |
| S13-11 | Gate: 100% of sampled committed authorization decisions represented in audit/event store | M12 |
| S13-12 | Gate: all browser SSE replays correctly backfill after reconnect in scripted test | M12 |
| S13-13 | Gate: policy errors default to no execution | M12 |
| S13-14 | Gate: 0 secret values surfaced in test trace/log scans using seeded synthetic credentials | M12 |
| S13-15 | Performance reported from measured local hardware; no fixed real-world latency claimed | M12 / M18 |
| S13-16 | `benchmark-report.json`: git commit, OS, CPU/RAM, dataset hash/version, policy version, totals, pass/fail, timing distribution, model if any, known limitations | M12 |

## §14 — Development plan (solo developer)

| Req ID | Requirement | Owner |
|---|---|---|
| S14-01 | Week 1: validated problem, threat model, monorepo, API, DB, mock orders — gate: health + migration tests pass | Phase 1 |
| S14-02 | Week 2: tool registry, trusted facts, deterministic policy engine, simulation — gate: unit policies match test oracle | Phase 2 |
| S14-03 | Week 3: Python SDK, gateway, idempotency, outbox/event persistence — gate: unsafe call provably never executes | Phase 3 |
| S14-04 | Week 4: Next.js dashboard, run explorer, tool details, SSE reconnect — gate: live run timeline works | Phase 4 |
| S14-05 | Week 5: approval queue, reviewers, security hardening — gate: changed/expired approval rejected | Phase 5 |
| S14-06 | Week 6: 100-case evaluation runner, failure/replay tests, reporting — gate: reproducible suite runs locally | Phase 6 |
| S14-07 | Week 7: optional local LangGraph investigator, fallback templates, incident page — gate: evidence-linked report or accurate fallback | Phase 7 |
| S14-08 | Week 8: packaging, documentation, CI, recorded demo, measured benchmarks — gate: fresh install works from instructions | Phase 8 |
| S14-09 | Scope control honored: M01–M10, M12, M15–M18 first; M11-advanced AI, external messaging, PDF reports second priority | IMPLEMENTATION_PLAN |

## §15 — Risks, limitations, and decisions

| Req ID | Requirement | Owner |
|---|---|---|
| S15-01 | Risk: generic tracing instead of useful security → start with protected refunds; demonstrate pre-execution enforcement | Phase 2–3 |
| S15-02 | Risk: SDK security theater → gateway validates grants server-side | M07 |
| S15-03 | Risk: exploding scope → one language, one demo tool, one project initially | Phase 0–1 |
| S15-04 | Risk: local model resource needs → all security/reporting usable with no model | M11 |
| S15-05 | Risk: too many containers → PostgreSQL outbox/worker, SSE, built-in metrics | infra |
| S15-06 | Risk: opaque LLM claims → evidence-linked analysis + deterministic fallback | M11 |
| S15-07 | Risk: secret leakage into traces → allowlisted metadata + redaction before collection | M08 / M15 |
| S15-08 | Risk: changing cloud free tiers → no core third-party deployment dependency | infra |
| S15-09 | Risk: lost events on reconnect → durable events + sequence-based backfill | M08 |
| S15-10 | Risk: approval races → transactional state transition + single-use grant | M10 / M07 |
| S15-11 | Risk: misleading "real-time" claim → documented as event-driven near-real-time, not hard real-time | M18 |
| S15-12 | Risk: overpromising security → published threat model + explicit bypass/privileged-admin limitations | THREAT_MODEL / M18 |
| S15-13 | Record ADR-001: deterministic, model-independent policy decisions | DECISIONS.md |
| S15-14 | Record ADR-002: trusted gateway necessity | DECISIONS.md |
| S15-15 | Record ADR-003: SSE over WebSockets for the MVP | DECISIONS.md |
| S15-16 | Record ADR-004: PostgreSQL as database + job/outbox store initially | DECISIONS.md |
| S15-17 | Record ADR-005: raw prompt contents not stored by default | DECISIONS.md |
| S15-18 | Record ADR-006: local LLM incident investigation is optional | DECISIONS.md |
| S15-19 | Record ADR-007: project-scoped event IDs and idempotency keys | DECISIONS.md |

## §16 — Public portfolio demonstration

| Req ID | Requirement | Owner |
|---|---|---|
| S16-01 | Demo step 1: Python SDK integration and sample agent | examples / M02 |
| S16-02 | Demo step 2: safe $40 refund allowed | M06 / M07 |
| S16-03 | Demo step 3: $150 refund sent to dashboard for reviewer | M10 |
| S16-04 | Demo step 4: $900 refund denied | M05 |
| S16-05 | Demo step 5: argument-tampering/replay blocked at gateway | M07 |
| S16-06 | Demo step 6: live events and incident evidence | M08 / M11 |
| S16-07 | Demo step 7: run evaluation suite and show actual measured outcome | M12 |
| S16-08 | Demo step 8: explain limitations and policy-outage behavior | M18 |
| S16-09 | Repo deliverable: source code | all |
| S16-10 | Repo deliverable: local setup instructions | M18 |
| S16-11 | Repo deliverable: SDK example | M02 / examples |
| S16-12 | Repo deliverable: architecture diagram | M18 |
| S16-13 | Repo deliverable: ERD | M18 |
| S16-14 | Repo deliverable: OpenAPI schema | M17 |
| S16-15 | Repo deliverable: state machines | M18 |
| S16-16 | Repo deliverable: threat model | THREAT_MODEL |
| S16-17 | Repo deliverable: evaluation cases | M12 |
| S16-18 | Repo deliverable: test result JSON (benchmark-report.json) | M12 |
| S16-19 | Repo deliverable: screenshots | M18 |
| S16-20 | Repo deliverable: demo video | M18 |
| S16-21 | Repo deliverable: performance report | M17 |
| S16-22 | Repo deliverable: security disclosures | M15 |
| S16-23 | Repo deliverable: license | M18 |
| S16-24 | Repo deliverable: contributing guide | M18 |
| S16-25 | Repo deliverable: issue backlog | M18 |
| S16-26 | README first sentence (verbatim): "AgentTrust is a self-hosted developer toolkit for safe, observable AI agent tool execution: deterministic pre-execution policies, approval workflows, live trace streaming and reproducible evaluations." | README |

## §17 — Definition of done (acceptance evidence)

| Req ID | Requirement | Acceptance evidence (target) | Owner |
|---|---|---|---|
| S17-01 | Zero required SaaS bills | Clean installation without commercial API keys | infra / M18 |
| S17-02 | Agent onboarding | Working SDK import and sample execution | M02 / examples |
| S17-03 | Live traces | Run timeline updates and reconnect test | M08 / M09 |
| S17-04 | Deny unsafe actions | No side effect in deny tests | M05 / M07 |
| S17-05 | Approve sensitive actions | Expiry, identity, and tamper tests | M10 |
| S17-06 | Explain decisions | Trace links to exact policy version | M06 |
| S17-07 | Investigate incidents | Evidence-backed incident report | M11 |
| S17-08 | Reproduce failures | Repeatable versioned benchmark | M12 |
| S17-09 | Avoid duplicates | Race-condition test passes | M06 / M07 |
| S17-10 | Protect credentials | Token and leakage tests | M01 / M15 |
| S17-11 | Recover from outages | Injected-failure test evidence | M02 / M16 |
| S17-12 | Portfolio ready | Outside engineer follows README | M18 |

## §18 — References and maintenance

| Req ID | Requirement | Owner |
|---|---|---|
| S18-01 | OpenTelemetry docs consulted for instrumentation design | M17 |
| S18-02 | PostgreSQL license terms noted (free/open) | infra |
| S18-03 | LangGraph Python + interrupt references consulted for investigator design (note: resumed nodes may rerun code — requires idempotency) | M11 |
| S18-04 | Next.js self-hosting guide consulted for web deployment | infra |
| S18-05 | FastAPI documentation consulted for API/OpenAPI | all |
| S18-06 | OWASP GenAI Security Project reviewed (independently, versioned guidance) before release | M15 |
| S18-07 | Spec maintained as living design: exact installed versions, license compatibility, host requirements, verified scripts, executed eval results, discovered limitations reconciled before release | M18 |

---

## Coverage summary

- 18/18 spec sections covered.
- 0 requirements marked implemented; 0 tests written; 0 verification evidence produced (Phase 0 rule).
- This matrix is updated in every subsequent phase: status, test coverage, and evidence columns are filled
  per requirement as work completes — never in advance.
- Phase 8 note (2026-10-17): the "0 requirements" line above is the Phase-0 standing
  snapshot; current status lives in the "Phase N status overrides" sections. 127 override
  rows were re-audited against `docs/PROGRESS.md` in the Phase 8 audit; flips are recorded
  in the Phase 8 overrides section. The §17 acceptance checklist below is the final
  evidence mapping.

---

## §17 — Definition of done: acceptance checklist (Phase 8, 2026-10-17)

Every status below is grounded in executed evidence (test files, measured numbers,
or produced docs) — never in memory or assertion. "Partial" marks a row whose core
acceptance is demonstrated but which carries a documented caveat or an untested half.

| Req ID | Requirement | Status | Acceptance evidence | Caveats |
|---|---|---|---|---|
| S17-01 | Zero required SaaS bills | Implemented | Local-only stack: PostgreSQL, FastAPI, Next.js, SSE (no paid messaging); Ollama optional and never downloaded — the 100-case benchmark reports `model: "none"` (`evals/benchmark-report-2026-10-17.json`). | Hardware and power are not free (spec §10.17 says so); eval DB drop/create needs a privileged local role. |
| S17-02 | Agent onboarding | Implemented | SDK `agenttrust` 0.1.0 installed editable (`packages/agenttrust-python`); `AgentTrust`, `@trust.protect(tool=...)`, `trust.run(...)` typed exceptions; `examples/refund-support-agent/demo.py` ran 5/5 live against a real API (PROGRESS Phase 3). | — |
| S17-03 | Live traces | Implemented | SSE stream with `Last-Event-ID` resume; run timeline updates live; `test_live_event_arrives_within_deadline` (<2 s committed→stream over real HTTP); backfill byte-identical (`test_backfill_repeat_is_byte_identical`) (PROGRESS Phase 4). | Dashboard is eventually consistent, never a security control (ADR-028). |
| S17-04 | Deny unsafe actions | Implemented | 100-case benchmark: `unauthorized_executions: 0`; DENY/REVIEW mint no grant and execute → 409 (`test_deny_decision_never_executes_no_grant`); tampered/expired/consumed grants rejected; balances provably unchanged (PROGRESS Phases 3, 7). | — |
| S17-05 | Approve sensitive actions | Implemented | Expiry → 410, SoD → 403, stale facts → 409 `approval_stale`, tamper → 409, racing double-decision → exactly one winner/one grant/one execution (17 approval tests + 5 SDK approval tests, PROGRESS Phase 5). | SoD is credential-level (no user model on keys); rate limiter is single-process (ADR-039). |
| S17-06 | Explain decisions | Implemented | `policy_decisions` pin the exact policy version; run-detail timeline shows reason_code + redacted args; policy simulate returns the WOULD-BE decision with explanation (PROGRESS Phases 2, 6). | No standalone Tool Details page — tool-call evidence lives in the run-detail timeline + approvals review panel (S08-04 Partial). |
| S17-07 | Investigate incidents | Implemented | Deterministic detector + `POST /incidents/scan`; evidence timeline in project_seq order; LangGraph investigator with Pydantic-validated, evidence-cited reports labeled by `analyzer_kind` (PROGRESS Phase 7). | Analysis is synchronous in-request (no worker, ADR-047); no Ollama in this environment — the deterministic template is the tested path. |
| S17-08 | Reproduce failures | Implemented | One command `python -m agenttrust_api.evaluation.run --db <url>` on an isolated DB; `benchmark-report.json` carries dataset hash, code/policy versions, host info, gate targets, limitations (PROGRESS Phase 7; file at `evals/benchmark-report-2026-10-17.json`). | Measurements are single-host / seeded-policy / synthetic-dataset — not real-world guarantees (ADR-051). |
| S17-09 | Avoid duplicates | Implemented | 8-thread `test_concurrent_executes_single_side_effect`; replay execute → 200 with the original result; unique execution row + `FOR UPDATE` grant locking (PROGRESS Phase 3). | — |
| S17-10 | Protect credentials | Partial | Token tests: key secrets never persisted (prefix + SHA-256 asserted), copy-once display, revocation immediate 403, scope enforcement both directions (`test_api_keys.py`, Phase 1/5); redaction allowlists before ingestion; 404-no-leak tests. | No S13-14-style trace/log scan test exists (0-secret-values scan not implemented); there is no separate `audit_events` table (S06-22). |
| S17-11 | Recover from outages | Partial | Policy outage → typed `PolicyServiceUnavailable`, zero execution rows (`test_sdk_unavailable_fails_closed`, Phase 3); SSE reconnect + backfill (Phase 4); DB-down → `/health/ready` 503 (Phase 1). | Worker kill/restart untested (no worker exists); DB-down 503 on sensitive ops not explicitly tested; failover/restore not exercised. |
| S17-12 | Portfolio ready | Partial | README quickstart, `docs/DEMO_SCRIPT.md` (exact narrated demo), `docs/EXECUTIVE_SUMMARY.md`, `apps/api/src/agenttrust_api/seed_demo.py` (idempotent demo dataset, verified on a fresh DB), `docker-compose.yml` present. | No outside engineer has yet followed the README from scratch; `docker compose up` not run here (no Docker engine); CI not wired; no demo video (ADR-055). |
