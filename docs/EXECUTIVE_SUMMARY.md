# AgentTrust — Executive Summary (v1.0, 2026-10-17)

## What it is

AgentTrust is a self-hosted developer toolkit for safe, observable AI agent
tool execution. It sits between an agent and any real-world effect:
deterministic pre-execution policies (ALLOW / DENY / REVIEW), a durable
human-approval queue, and a trusted execution gateway with single-use
grants, tamper detection, and idempotency — all streamed live to a
dashboard and proven by a 100-case benchmark.

## What shipped

| Dimension | Count |
|---|---|
| API endpoints (FastAPI) | 38 across 13 routers (`/api/v1/*`) |
| Database tables (Alembic) | 24 (migrations 0001–0006, fresh-DB verified) |
| Pytest tests | 132, all green on real PostgreSQL 16 |
| Dashboard routes (Next.js) | 13 routes, 11 full pages |
| SDK | `agenttrust` package: `protect`, `wait_for_approval`, typed fail-closed errors |
| Benchmark cases | 100 (25 allow / 20 review / 20 limit-deny / 15 invalid-deny / 10 tamper-replay / 10 malformed) |
| Architecture decision records | 56 in `docs/DECISIONS.md` |

Modules: policy engine with immutable versions · trusted gateway (single-use
5-min grants, FOR UPDATE transactional execute) · approvals (reviewer-key
auth, separation of duties, optimistic concurrency, lazy expiry, fact
revalidation) · per-project event sequencing + SSE with reconnect backfill ·
deterministic incident detector + LangGraph investigator (Ollama-optional,
deterministic fallback, validated reports) · evaluation runner with
`benchmark-report.json` · analytics, agents directory, and built-in
`GET /api/v1/metrics`.

## Measured results (not claims)

From `evals/benchmark-report-2026-10-17.json`, reproduced by re-running the
one-command CLI against an isolated database:

- **100/100 cases passed**, accuracy 1.0
- **0** false allows · **0** false denials · **0** unauthorized executions · **0** duplicate side effects
- Latency p50 11 ms / p95 25 ms (gate target: p95 ≤ 500 ms)
- Concurrency: 8 threads racing one grant → exactly one balance effect
- SSE: reconnect with `Last-Event-ID` backfills exactly the missed events

Scope of the numbers: single host, seeded refund-policy v1, synthetic
dataset. They prove the machinery works; they are not a guarantee against
real-world fraud. The report discloses this in its `limitations` field.

## Honest limitations

- One active policy at a time; no multi-policy routing.
- Incident analysis and benchmark runs execute synchronously in the HTTP
  request — no background worker yet.
- Rate limiting is in-memory (single process); production needs Redis.
- Dashboard auth is a dev API key; cookie sessions are future work.
- No Docker daemon in the build environment: `docker-compose.yml` ships and
  was parse-validated, but containers were never started here.
- No demo video was recorded (no screen capture in this environment);
  `docs/DEMO_SCRIPT.md` is the exact narrated script instead.

## What comes next (production hardening)

From spec §14, in order: background worker for analysis/benchmark jobs ·
Redis-backed rate limiting · cookie-session dashboard auth · multi-policy
routing and policy DSL beyond the refund reference · event retention
enforcement · Prometheus text exposition alongside JSON metrics ·
Playwright dashboard smoke suite (attempted in Phase 8; browser install
infeasible in this environment) · external messaging integrations (stretch).

## Verification

```bash
cd apps/api && pytest -q && ruff check src tests        # 132 green, clean
cd apps/web && npm run lint && npm run typecheck && npm run build
python -m agenttrust_api.evaluation.run --db "$DATABASE_URL" --eval-db agenttrust_eval
```

Full evidence trail: `docs/PROGRESS.md` (dated log), `docs/REQUIREMENTS_TRACEABILITY.md`
(requirement → evidence matrix + §17 definition-of-done), `docs/THREAT_MODEL.md`
(residual risks).
