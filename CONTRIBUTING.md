# Contributing to AgentTrust

Thanks for your interest — contributions are welcome, from typo fixes to new
policy primitives. This guide keeps the bar clear so your PR gets merged fast.

## Ground rules

1. **Verify, don't claim.** Every PR that touches behavior must include the
   test run that proves it (`pytest`, `ruff`, frontend `lint`/`typecheck`/
   `build` — see below). CI runs the same checks; a red CI blocks merge.
2. **Fail closed.** AgentTrust is security infrastructure. When in doubt, the
   system must deny / refuse / do nothing — never guess, never silently allow.
3. **No hype in code or docs.** If a number is in the README or a docstring,
   it was measured. Label estimates as estimates.

## Local setup

Follow [README.md](README.md#run-it-locally) (Windows PowerShell and
Linux/macOS variants included). The short version:

```bash
# API + database
python -m venv apps/api/.venv && source apps/api/.venv/bin/activate
pip install -r apps/api/requirements.txt
createdb agenttrust
DATABASE_URL=<redacted> \
PYTHONPATH=src python -m alembic upgrade head
DATABASE_URL=<redacted> \
PYTHONPATH=src python -m agenttrust_api.seed_demo

# Dashboard
cd apps/web && npm install && npm run dev
```

## Checks (run before every PR)

```bash
# Backend — from apps/api, venv active
ruff check src packages/agenttrust-python 2>/dev/null || ruff check src
python -m pytest tests/ -q        # ~2.5 min, needs local PostgreSQL

# Frontend — from apps/web
npm run lint && npx tsc --noEmit && npm run build
```

## How to contribute

1. **Fork** the repo and create a branch: `git checkout -b feat/<what>` or
   `fix/<what>`.
2. Make the change. Add/extend tests for behavior changes; update docs if the
   behavior is user-visible (`docs/`, `README.md`, `DEPLOY.md`).
3. Run the checks above. Paste the results in the PR description.
4. Open the PR against `main`. Small, focused PRs get reviewed fastest.

### Good first contributions

- Additional policy primitives in the deterministic engine
- New incident detector scans (tamper / replay / overflow / pattern)
- Dashboard UX polish, accessibility fixes, light-theme coverage
- Docs, examples, translations of the demo script
- Benchmark cases in `evals/` (must be deterministic — no network, no LLM)

### What won't be merged

- Changes that weaken fail-closed behavior without a security rationale
- Features that require paid APIs in the default path (keep the core
  runnable on free tiers; the Groq example is opt-in)
- Unverifiable performance claims

## Decisions

Significant design choices are recorded as ADRs in `docs/DECISIONS.md`
(56 and counting). If your PR changes architecture, add one — copy the
format of the most recent entry.

## Security issues

Don't open a public issue for vulnerabilities. Email the maintainer
privately (see the repo profile) with details and a reproduction; you'll
get credit in the fix release.

## License

By contributing, you agree your work is licensed under the MIT License
([LICENSE](LICENSE)).
