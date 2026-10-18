# AgentTrust — Threat Model

**Status:** Phase 0 — documented analysis only; mitigations not yet implemented.
**Spec refs:** §5 (incl. §5.4 failure table). **Date:** 2026-10-17 (UTC).

## 1. Assets

Per spec §5.1: protected external actions, synthetic refund balances, API keys, trace metadata, approval
identities, project data, policy versions, local model inputs, and audit events.

## 2. Adversaries and failure sources

Per spec §5.2: untrusted user prompts, agent hallucinations, malicious document text, compromised SDK
keys, unauthorized dashboard users, tool argument tampering, stale approvals, concurrent duplicate calls,
a compromised developer environment, and ordinary outages.

**Out of scope by design:** a malicious server administrator is outside the strong integrity guarantees of
the local demo. A privileged operator can alter a single-host database; the audit trail is append-only at
the *application* level only. Do not promise tamper-evidence against a privileged operator.

## 3. Trust boundaries and defenses

| # | Boundary | Defense |
|---|---|---|
| B1 | Untrusted prompt vs tool | Natural-language instructions never override deterministic backend policy. The policy engine reads only canonicalized tool arguments and server-owned trusted facts. Prompt-injection strings are test inputs (S12-04), never inputs to the verdict. |
| B2 | SDK vs protected service | The SDK is cooperative and bypassable. Enforcement lives in the gateway, which independently re-verifies identity, canonical arg hash, approval/policy validity, expiry, and single-use status at execution time (ADR-002). |
| B3 | Browser vs API | All authorization is server-side. Hidden UI controls, disabled buttons, or client-side flags never grant authority; the dashboard cannot execute tools. |
| B4 | Agent data vs trusted facts | Eligibility and refundable balance are fetched from server-owned records (`mock_orders`), never accepted as agent claims. |
| B5 | Model vs evaluator | The incident-analysis LLM has zero tool, policy, or approval permissions. It produces analysis text only; a validator checks Pydantic shape and that cited evidence IDs exist. |
| B6 | Tenant vs tenant | Project identity comes from verified credentials (scoped token / session), never from request JSON. Every query is project-scoped; cross-project access returns 403/404 without existence leakage and writes an audit entry. |
| B7 | Telemetry vs secrets | Redaction and field allowlists run *before* ingestion. Raw payloads are not captured by default (`AGENTTRUST_CAPTURE_RAW_PAYLOADS=false`); sensitive fields require explicit opt-in. Seeded-credential scans are a quality gate (S13-14). |
| B8 | Retries vs external effect | Idempotency keys (`unique(project_id, idempotency_key)`) plus transactional claim of the single-use grant and row-locked balance updates make replay safe: the second attempt returns the prior outcome or a conflict, never a second effect. |

## 4. Failure behavior table (spec §5.4)

| Failure | Required safe result | User-facing evidence |
|---|---|---|
| Policy API unreachable | Do not execute protected tool | SDK `PolicyServiceUnavailable`; local error record |
| SSE interrupted | UI shows reconnecting; fetches missed events | Connection status + last sync timestamp |
| Database temporarily unavailable | Reject sensitive operation | API 503 + structured error (`error_code`, `request_id`, `retryable`) |
| Approval expires | Reject execution; require new review | Approval-expired event |
| Tool arguments change after approval | Reject mismatched hash | Authorization-conflict event |
| Same request repeated | Return prior result, no second effect | Replay/idempotency indicator |
| Worker dies | Job lease expires; retry occurs | Backlog / failed-job status in admin view |
| LLM unavailable | Provide deterministic incident details | "Analysis unavailable" status |
| Policy changes after grant | Revalidate or invalidate grant | Stale-policy error |
| Event arrives out of order | Reorder or backfill via server sequence | Stable timeline |
| Unauthorized project access | 403/404 without data leakage | Security audit entry |
| Invalid or oversized payload | 422/413 rejection | Validation error |

## 5. Mitigations (cross-cutting controls, M15)

- Store API key hashes, never plaintext; scoped keys; revocation effective immediately on subsequent
  authorization requests.
- Least-privilege DB user; secrets from environment only; no real `.env` committed; dev ports bound to
  127.0.0.1.
- CSRF protection for cookie-authenticated mutations; constrained CORS; rate limits on sensitive
  endpoints; input size limits; strict Pydantic request validation.
- Integer minor units for all money (never float). Canonical JSON hashing for argument identity.
- Optimistic concurrency (`row_version`) on approval decisions; one active approval per tool call.
- Structured JSON logs with correlation IDs and sanitized error details; no secrets in logs or traces.

## 6. Residual risks — stated honestly

1. **No universal prompt-injection immunity.** The boundary (B1) holds for the *governed* refund tool path:
   untrusted text cannot change a deterministic decision. It says nothing about tools outside the
   trusted boundary or about models used elsewhere.
2. **The SDK alone secures nothing unwrapped.** Any tool an agent can invoke without going through the
   trusted gateway is outside this system's enforcement. This is the documented "SDK security theater" risk.
3. **Privileged local operator can alter audit data.** Append-only is an application-level discipline, not a
   cryptographic guarantee against a database administrator.
4. **Local demo auth is intentionally weak.** Passwordless single-owner mode is for loopback demos only;
   it must not be presented as a production identity story.
5. **The dashboard is not a control plane.** A stale or disconnected UI showing old data is a display
   issue, not a security control — but it can mislead a reviewer; hence the explicit Live/Reconnecting/Offline
   indicator and last-sync timestamps.
6. **Evaluation results are bounded claims.** The 100-case benchmark measures the *fixed suite* on the
   tested hardware; it does not prove security against novel attacks or different configurations.
7. **Never "guaranteed secure."** This platform reduces specific, enumerated risks through deterministic
   pre-execution enforcement. Any communication (docs, demo, résumé) that implies more is a defect in
   documentation, not a feature.
