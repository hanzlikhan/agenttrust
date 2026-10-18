# infra/ — deployment notes (Phase 1)

## Local Docker Compose stack

`../docker-compose.yml` defines three services:

| Service | Image / build | Port (loopback only) | Depends on |
|---|---|---|---|
| `db` | `postgres:16` | `127.0.0.1:5432` | — (healthcheck: `pg_isready`) |
| `api` | `./apps/api` (Dockerfile) | `127.0.0.1:8000` | `db` healthy |
| `web` | `./apps/web` (Dockerfile) | `127.0.0.1:3000` | `api` |

All published ports bind to `127.0.0.1` only — nothing is exposed to the LAN.

The `api` container runs `alembic upgrade head` on startup, then uvicorn.

## Verification status (honest)

- The compose file was **parse-validated** with Python's YAML parser in the
  build environment.
- `docker compose config` and `docker compose up` were **not run** — no Docker
  engine is available in this environment. Run `docker compose config` on a
  Docker host before `up`; record the outcome in `docs/PROGRESS.md`.

## Environment

- `apps/api/.env` (from `.env.example`): `ADMIN_TOKEN` must be set, otherwise
  key-management endpoints return 503 (fail closed).
- `POSTGRES_PASSWORD` (compose): defaults to `agenttrust` for local dev only;
  set a real value for anything beyond a loopback demo.
