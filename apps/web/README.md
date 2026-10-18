# AgentTrust Web (Phase 1 — Foundation)

Frontend slice of AgentTrust. A single status page that fetches the backend
API's `GET /health/live` endpoint and displays the **real** result — never a
hard-coded status.

- Stack: Next.js 15 (App Router), TypeScript (`strict`), React 19.
- No Tailwind CSS in this phase (deferred); styling is a plain CSS module.

## Prerequisites

- Node.js v24.x and npm 10.x
- The AgentTrust backend API running and reachable (defaults to
  `http://localhost:8000`)

## Setup

```bash
cd apps/web
npm install
```

## Run

```bash
npm run dev      # start the dev server on http://localhost:3000
npm run build    # production build
npm run start    # serve the production build
```

## Configuration

| Env var              | Default                 | Purpose                                       |
| -------------------- | ----------------------- | --------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the backend API (no trailing `/`) |

Example:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Verification

```bash
npm run lint       # ESLint (flat config)
npm run typecheck  # tsc --noEmit
npm run build      # production build
```

## How the status page works

`app/page.tsx` is a client component. On mount (and on every Retry click) it
fetches `${NEXT_PUBLIC_API_URL}/health/live` with `cache: "no-store"` and
renders one of three honest states:

- **Loading…** while the request is in flight.
- **API: Live** (green) plus the returned JSON and timestamp when the fetch
  succeeds and the response body has `status: "ok"`.
- **API: Down** (red) with the actual error message when the fetch fails, the
  HTTP status is not 2xx, or the response body's `status` is not `"ok"`.

A **Retry** button re-fetches on demand.

## Live dashboard (Phase 4)

Copy `.env.example` to `.env.local` and set `NEXT_PUBLIC_API_KEY` to a
project API key (dev only — session auth arrives in Phase 5/6):

```bash
cp .env.example .env.local
npm run dev
```

- `/` — API health status.
- `/runs` — live run list: REST snapshot first, then Server-Sent Events
  deltas (new runs prepend, state changes update in place). The
  `ConnectionBadge` shows Live / Reconnecting / Offline.
- `/runs/[id]` — run detail with a vertical event timeline fed by the same
  SSE stream; reconnects resume from the last seen `project_seq` cursor and
  deduplicate by `event_id`.
