# AgentTrust

**The security layer for AI agents — it decides what an AI is allowed to do _before_ it does it.**

🔗 **Live demo:** `https://<your-vercel-url>` — paste the demo key from below on the Settings page.

When an AI agent can take real actions — issuing refunds, deleting records, sending emails — you can't rely on its judgment. AgentTrust sits between the agent and its tools as a policy gate:

- **Small actions** (under $100) → auto-approved, executed immediately
- **Risky actions** ($100–$500) → paused for **human approval** on the dashboard
- **Dangerous actions** (over $500) → blocked outright, never executed
- **Tampered or replayed calls** → caught by the incident detector

Every decision is logged, every execution is traceable, and nothing runs without a single-use, 5-minute execution grant.

## The 3-minute demo

1. Open the dashboard. An AI support agent with refund power is already running.
2. Ask it for a **$35 refund** → approved and executed instantly.
3. Ask for a **$900 refund** → denied by policy. The agent has to tell the customer no.
4. Ask for a **$150 refund (damaged item)** → paused. **You** approve it on the Approvals page — and watch the refund complete live.

That last step is the whole product: a human gate in the loop, enforced by infrastructure, not by asking the AI nicely.

## How it works

```
Customer message
      │
      ▼
┌──────────┐   tool call    ┌─────────────┐
│  LLM     │ ─────────────▶ │  AgentTrust │
│ (Groq)   │   refund($150) │  authorize  │
└──────────┘                └──────┬──────┘
                                  │ policy check
                    ┌─────────────┼──────────────┐
                    ▼             ▼              ▼
                 ALLOW         REVIEW          DENY
              (< $100)      ($100–$500)      (> $500)
                    │             │              │
                    ▼             ▼              ▼
              single-use    human approves    never
              grant (5m)    on dashboard     executes
                    │             │
                    └──────┬──────┘
                           ▼
                   gateway re-verifies:
                   grant · args hash · no replay
                           │
                           ▼
                      executed once,
                      effect recorded
```

The `@trust.protect` decorator wraps any tool function. The SDK handles authorize → wait-for-approval → execute; the gateway re-verifies the grant, the argument hash, and replay protection transactionally. Fail-closed everywhere: any doubt, nothing executes.

Beyond the gate: a real-time SSE event stream per project, a deterministic incident detector (tamper / replay / overflow / pattern scans) with an AI investigator that writes incident reports, and a 100-case evaluation benchmark that proves the security properties.

## Features

| Area | What's inside |
|---|---|
| Policy engine | Deterministic thresholds, per-tool policies, dry-run simulation |
| Approvals | Durable queue, reviewer-key auth with separation of duties, optimistic-concurrency decisions, lazy expiry |
| Execution grants | Single-use, 5-minute TTL, argument-hash binding, replay protection |
| Observability | Per-project event sequencing, SSE stream with reconnect backfill, analytics dashboard |
| Incidents | Deterministic detector + LangGraph investigator (works without an LLM via template fallback) |
| Evaluations | 100-case benchmark runner against an isolated DB, honest metrics report |
| SDK | `pip install agenttrust` — `protect`, `wait_for_approval`, typed fail-closed errors |
| Dashboard | 13 pages: overview, executions, approvals, policies, agents, analytics, incidents, evaluations, settings — dark-first design system |

## Tech stack

- **API:** Python 3.12, FastAPI, PostgreSQL 16, SQLAlchemy, Alembic (8 migrations, 24 tables), LangGraph (investigator)
- **SDK:** `agenttrust` pip package (httpx, pydantic)
- **Web:** Next.js 15, React 19, TypeScript (strict), Tailwind CSS v3, Recharts, SSE
- **Infra:** Docker, docker-compose, Render + Neon + Vercel for the public demo

## Project structure

```
apps/api/            FastAPI service (src layout) — policy, approvals, grants,
                     events/SSE, incidents, evaluations, key management
apps/web/            Next.js dashboard (13 pages)
packages/
  agenttrust-python/ the `agenttrust` SDK
examples/
  refund-support-agent/  scripted demo (5 scenarios, all live API calls)
  llm-refund-agent/      Groq-powered agent — the LLM decides, AgentTrust governs
evals/               100-case benchmark suite
docs/                architecture, decisions (56 ADRs), API reference,
                     executive summary, audit log
DEPLOY.md            public deployment guide (Neon → Render → Vercel)
```

## Run it locally

Prerequisites: Python 3.12+, Node 20+, PostgreSQL 16+.

```powershell
# Backend
python -m venv apps\api\.venv
apps\api\.venv\Scripts\Activate.ps1
pip install -r apps\api\requirements.txt
psql -U postgres -c "CREATE DATABASE agenttrust;"
psql -U postgres -c "CREATE USER agenttrust WITH PASSWORD 'agenttrust' SUPERUSER;"
$env:DATABASE_URL = "postgresql+psycopg://agenttrust:agenttrust@localhost:5432/agenttrust"
cd apps\api
$env:PYTHONPATH = "src"
python -m alembic upgrade head
python -m agenttrust_api.seed_demo   # save the printed API keys
python -m uvicorn agenttrust_api.main:app --port 8000
```

```powershell
# Dashboard (second terminal)
cd apps\web
npm install
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
npm run dev   # → http://localhost:3000
```

```powershell
# Groq agent (third terminal, optional)
pip install -e packages\agenttrust-python
pip install openai
$env:GROQ_API_KEY = "<from console.groq.com/keys>"
$env:AGENTTRUST_API_KEY = "<requester key from seed_demo>"
cd examples\llm-refund-agent
python groq_agent.py
```

(Linux/macOS: replace `$env:X = "y"` with `export X=y`, `\` with `/`, and
activate with `source apps/api/.venv/bin/activate`.)

## Deploy it publicly

See **[DEPLOY.md](DEPLOY.md)** — Neon database → Render API → Vercel dashboard,
all free tiers, ~30–45 minutes.

## Verification

This project was built verification-first and then **independently audited**:

- **140/140** pytest passing on real PostgreSQL (including 8 audit regression tests)
- `ruff` clean, frontend `lint` / `typecheck` / `build` green (13/13 routes)
- 100-case security benchmark: accuracy 1.0, 0 unauthorized executions, 0 duplicate effects
- Post-release audit by three independent reviewers found 2 HIGH / 4 MEDIUM / 6 LOW findings — all fixed and verified (migrations 0007–0008; full log in `docs/PROGRESS.md`)

## License

MIT — see [LICENSE](LICENSE).
