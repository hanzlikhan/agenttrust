# AgentTrust — Test Strategy

**Status:** Phase 0 — strategy only. No tests are written yet.
**Spec refs:** §13 (layers, targets, reporting), §12 (scenarios S1–S8), §5.4 (failure table).
**Date:** 2026-10-17 (UTC).

## 0. Ground rules

- A test is green only when it ran and passed. Never present unexecuted tests as passing.
- Benchmark numbers are *measured and reported*, never asserted (spec §13.3: "Do not fabricate benchmark
  numbers in README or résumé").
- All §13.2 items below are **targets**, not results.
- Money in fixtures: integer minor units only. Timestamps: UTC.

## 1. The seven test layers (spec §13.1)

1. **Unit** — threshold rules and reason codes; Pydantic schema validation (valid/invalid/malformed);
   canonical JSON hashing incl. cross-client consistency; approval state transitions (incl. illegal ones);
   redaction (seeded secrets must not survive); permission checks (role/scope/project).
2. **Integration** — policy API + PostgreSQL + gateway in real transactions: authorize → approve → execute
   chains; outbox → worker → SSE ordering; multi-client SSE fan-out; worker retry and lease expiry;
   Alembic migration up/down on a fresh database.
3. **Security** — cross-project access (403/404, no leakage, audit entry); expired/revoked credentials;
   changed argument hash after approval; forged or replayed grants; oversized payloads (413); injection
   strings (S4); concurrent duplicate execution (S5); self-approval attempt when separation of duties is on.
4. **End-to-end (Playwright)** — run the sample refund agent; watch Overview/Live Runs update; approve a
   pending $150 refund from the dashboard; kill SSE for 10 s and verify zero-gap backfill (S7); keyboard-only
   walkthrough of the approval flow.
5. **Performance** — decision latency p50/p95 at low load; SSE delivery lag (committed event → browser
   receipt); backfill correctness under load; system behavior while an evaluation run executes. Report
   measured values from the actual test machine; claim no fixed real-world latency.
6. **Recovery** — database outage mid-authorization (fail-closed, 503); worker kill/restart (lease expiry
   → retry → no lost events); lost client response (idempotent retry returns prior outcome); backup restore
   (expired grants stay expired; balances consistent).
7. **AI quality (optional, Phase 7)** — on human-labeled incidents: evidence citation correctness (every
   cited ID exists), factuality of the summary, uncertainty statements present where evidence is thin.

## 2. The 100-case benchmark (M12, spec §3/S03-29)

Composition, with expected outcomes labeled **independently of any model**:

| Category | Cases | Expected outcome |
|---|---|---|
| Eligible automatic ALLOW | 25 | ALLOW + exactly one execution |
| Valid REVIEW | 20 | REVIEW + no execution before approval |
| Limit DENY | 20 | DENY + no execution, no balance change |
| Missing/invalid context DENY | 15 | DENY (fail-closed) |
| Tamper/replay DENY | 10 | DENY at gateway; no duplicate effect |
| Malformed/injection DENY | 10 | DENY; untrusted text changes nothing |

Execution rules: isolated test database or rollback-safe fixtures; one command; fixed random seed;
dataset version + policy version + code version recorded; per-case latency captured. **The verdict asserts
whether the protected tool actually executed**, not only what the policy said.

## 3. Quality gates — targets (spec §13.2, not results)

- Correct outcome for 100/100 initial deterministic labeled scenarios.
- Zero execution of known-denied actions in the fixed suite.
- No duplicated synthetic refund effects in concurrent idempotency tests.
- 100% of sampled committed authorization decisions represented in the audit/event store.
- All browser SSE replays correctly backfill after reconnect in the scripted test.
- Policy errors default to no execution.
- 0 secret values surfaced in test trace/log scans using seeded synthetic credentials.
- Performance metrics reported from measured local hardware; no fixed real-world latency claimed.

## 4. `benchmark-report.json` contents (spec §13.3)

git commit · OS · CPU/RAM · dataset hash/version · policy version · total tests · pass/fail counts ·
timing distribution (p50/p95 per case category) · model identifier if any (else `none`, with the
deterministic-fallback note) · known limitations. The README and any résumé may quote this file and
nothing else.

## 5. Phase-by-phase test obligations

- **Phase 1:** migration tests (fresh DB up/down), health endpoint tests, key issuance/revocation tests.
- **Phase 2:** policy oracle unit tests for every reason code; idempotency-key tests; fail-closed tests.
- **Phase 3:** gateway enforcement tests (S3/S4/S5); concurrency race tests; SDK typed-error tests.
- **Phase 4:** SSE contract tests (resume, backfill, project scoping); Playwright live-timeline tests.
- **Phase 5:** approval state-machine tests (expiry, tamper, double-decide 409, SoD); hardening tests.
- **Phase 6:** the full 100-case benchmark; `benchmark-report.json` generation; export tests.
- **Phase 7:** incident pipeline tests; citation-correctness tests; fallback-parity tests.
- **Phase 8:** fresh-install reproduction; full suite green; CI (lint, typecheck, build, pytest, Playwright)
  passing on a clean checkout.

## 6. What Phase 0 delivers

This document. No test files, fixtures, or harnesses exist yet. The first tests are written in Phase 1.
