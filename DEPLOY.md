# Deploying AgentTrust (public demo)

Goal: a public URL anyone can open — API on Render, PostgreSQL on Neon,
dashboard on Vercel. All free tiers. Takes about 30–45 minutes, most of it
waiting on dashboards.

> Free-tier honesty: Render's free web service sleeps after ~15 minutes of
> inactivity, so the first visit after idle takes ~50 seconds to wake up.
> Fine for a portfolio demo; not for production.

## 0. Put the code on GitHub

Render and Vercel both deploy from a git repo.

```powershell
cd "C:\Users\MUHAMMAD HANZLA\Downloads\agenttrust-v1.1-audited"
git init
git add -A
git commit -m "AgentTrust v1.1-audited"
```

Then on github.com: **New repository** → name it `agenttrust` (public) →
follow the "push an existing repository" instructions:

```powershell
git remote add origin https://github.com/<your-username>/agenttrust.git
git branch -M main
git push -u origin main
```

## 1. Database — Neon (5 min)

1. Sign up at [neon.tech](https://neon.tech) (free, GitHub login works).
2. **New Project** → name `agenttrust`, region closest to you (Singapore is
   usually fastest from Pakistan) → Create.
3. Copy the connection string. It looks like:
   `postgresql://agenttrust_owner:xxxx@ep-xxx.ap-southeast-1.aws.neon.tech/agenttrust?sslmode=require`
4. Change the scheme from `postgresql://` to `postgresql+psycopg://`
   (the API uses the psycopg3 driver). Save this as your `DATABASE_URL`.

## 2. Migrate + seed the cloud database (from your laptop)

Point your local tools at Neon once. In a terminal with the venv active:

```powershell
cd "C:\Users\MUHAMMAD HANZLA\Downloads\agenttrust-v1.1-audited\apps\api"
.venv\Scripts\Activate.ps1
$env:DATABASE_URL = "postgresql+psycopg://<user>:<password>@<host>/agenttrust?sslmode=require"
$env:PYTHONPATH = "src"
python -m alembic upgrade head
python -m agenttrust_api.seed_demo
```

`seed_demo` prints the project API keys — **save them**, same as before.
Your cloud database now has the demo project, the refund scenario, and the
pending approval.

> Afterwards, unset it so you don't accidentally write to prod later:
> remove the `$env:DATABASE_URL` line or just close the terminal.

## 3. API — Render (10 min + deploy wait)

1. Sign up at [render.com](https://render.com) (GitHub login).
2. **New → Blueprint** → connect your `agenttrust` repo.
3. Render reads `render.yaml`. When prompted, paste:
   - `DATABASE_URL` — the Neon string from step 1 (with `postgresql+psycopg://`)
   - `ADMIN_TOKEN` — Render generates one; **copy it somewhere safe**,
     you'll need it in step 6.
   - Leave `AGENTTRUST_CORS_ORIGINS` as `http://localhost:3000` for now —
     you'll update it after Vercel.
4. Deploy. The Dockerfile runs migrations on every start, so the schema is
   always current. First build takes ~5 minutes.
5. When it's live, note the URL: `https://agenttrust-api-xxxx.onrender.com`.
   Check `https://<your-api>/api/v1/health/live` returns `{"timestamp":...}`.

## 4. Dashboard — Vercel (5 min)

1. Sign up at [vercel.com](https://vercel.com) (GitHub login).
2. **Add New → Project** → import your `agenttrust` repo.
3. Set **Root Directory** to `apps/web`.
4. Under **Environment Variables**, add:
   - `NEXT_PUBLIC_API_URL` = `https://<your-render-api-url>` (no trailing slash)
5. Deploy. Note the URL: `https://agenttrust-xxxx.vercel.app`.

## 5. Wire up CORS (2 min)

The API rejects browser calls from unknown origins. Back in Render:

1. Open the `agenttrust-api` service → **Environment**.
2. Change `AGENTTRUST_CORS_ORIGINS` to your Vercel URL
   (`https://agenttrust-xxxx.vercel.app`).
3. **Save** — Render redeploys automatically (~2 min).

## 6. Demo key for visitors

Visitors need an API key to see the dashboard. Issue a read-only one:

```powershell
curl.exe -X POST https://<your-render-api>/api/v1/keys `
  -H "Authorization: Bearer <ADMIN_TOKEN_FROM_RENDER>" `
  -H "Content-Type: application/json" `
  --data "{\"name\":\"public-demo\",\"scopes\":[\"agent:run\",\"approvals:read\",\"incidents:read\",\"evaluations:read\"]}"
```

Save the returned key. Put it in your README (see the Live Demo section)
and/or tell visitors to paste it on the dashboard's Settings page.

> The public key is read-only: visitors can browse runs, approvals,
> incidents, and evaluations, but can't issue refunds or approve anything.
> Approving stays yours, via the reviewer key on the Approvals page.

## 7. Verify the public deployment

1. Open the Vercel URL → Settings → paste the demo key → Overview should
   show the seeded runs and decisions.
2. From your laptop, run the Groq agent against the **cloud** API:
   ```powershell
   $env:AGENTTRUST_API_URL = "https://<your-render-api>"
   $env:AGENTTRUST_API_KEY = "<requester key from step 2>"
   python groq_agent.py
   ```
   Type the `$150` message → approve it on the **public** dashboard →
   the refund completes. That's the whole product, live on the internet.

## If something breaks

| Symptom | Likely cause |
|---|---|
| Vercel page loads but shows connection errors | CORS: check `AGENTTRUST_CORS_ORIGINS` on Render matches the Vercel URL exactly (no trailing slash) |
| Render deploy fails on `alembic upgrade head` | `DATABASE_URL` wrong or Neon project paused (free Neon pauses after inactivity — wake it in the Neon dashboard) |
| First API call takes ~50s | Render free tier cold start — normal |
| `seed_demo` against Neon fails | URL scheme must be `postgresql+psycopg://`, and include `?sslmode=require` |

## Tear-down (optional)

Deleting the Render service, Vercel project, and Neon project stops
everything. Nothing on your laptop is affected.
