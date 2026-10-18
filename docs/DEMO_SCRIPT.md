# AgentTrust — 3-minute narrated demo script

**No video was recorded for this release** — this environment has no screen
capture. This script is the precise narration: every command, click, and
expected audience-visible beat, verified against the live build on
2026-10-17.

**Setup (before the clock starts):** API migrated + `seed_demo` run
(`README.md` quickstart), API on `:8000`, dashboard on `:3000`,
`http://localhost:3000` open in a browser, terminal visible. Save the
copy-once keys from `seed_demo` as `REQ` (requester) and `REV` (reviewer).

---

## Beat 1 — The problem and the SDK (0:00–0:25)

**Say:** "Agents with tools are powerful and dangerous. A customer-support
agent that can refund money needs a bouncer in front of every call — not
hope. AgentTrust is that bouncer: deterministic policy checks, human
approvals, and a tamper-proof execution gateway, all observable live."

**Do:** open `examples/refund-support-agent/demo.py`; point at the
`@trust.protect(tool="refund_payment")` decorator.

**Audience sees:** one decorator between the agent's function and the real
money movement. **Say:** "The agent's code never touches the balance. The
gateway does — once, and only after authorization."

## Beat 2 — A safe refund flows through (0:25–0:50)

**Do (terminal):**

```bash
curl -s -X POST http://localhost:8000/api/v1/tool-calls/authorize \
  -H "Authorization: Bearer $REQ" -H "Content-Type: application/json" \
  -d "{\"run_id\":\"$RUN\",\"tool_name\":\"refund_payment\",\"arguments\":{\"order_id\":\"ORD-100\",\"amount_minor\":4000,\"currency\":\"USD\"},\"idempotency_key\":\"demo-live-1\"}"
```

**Audience sees:** `"outcome":"ALLOW"`, `reason_code`, `policy_version: 1`,
a human-readable `explanation`. **Say:** "Forty dollars, eligible order,
under the auto-approve limit — allowed, and the decision is persisted with
the exact policy version that made it."

Execute it (same call id); **audience sees** `"state":"SUCCEEDED"`,
`remaining_minor` decreased by exactly 4000. **Click** `/runs` → the run →
timeline shows `tool.requested → policy.allow → tool.executed` in order.

## Beat 3 — A sensitive refund goes to a human (0:50–1:20)

**Do:** authorize $150 (`amount_minor: 15000`, new idempotency key).

**Audience sees:** `"outcome":"REVIEW"`, `approval_id`. **Say:** "Over the
$100 auto-approve limit — the agent is now waiting on a human."

**Click** `/approvals` — the request is there with the order, amount,
policy reason, and a countdown to expiry. **Do:** approve it with the
*reviewer* key (different credential):

**Audience sees:** `APPROVED` + a single-use `grant_id`. **Say:** "Notice
the reviewer can't be the same key that asked — separation of duties is
enforced by the API, and a racing second reviewer would lose on optimistic
concurrency." Execute with the grant — succeeds.

## Beat 4 — An unsafe refund is denied (1:20–1:40)

**Do:** authorize $900 (`amount_minor: 90000`).

**Audience sees:** `"outcome":"DENY"`, `reason_code: "AMOUNT_EXCEEDS_MAX"`,
`approval_id: null`. **Say:** "Nine hundred dollars exceeds the $500
policy maximum. No grant exists — there is no code path that executes a
denied call. The benchmark suite asserts exactly this, 100 out of 100
cases."

## Beat 5 — Tampering is caught at the gateway (1:40–2:05)

**Do:** authorize $50 on ORD-300, then execute with `amount_minor: 900000`.

**Audience sees:** HTTP 409 `arguments_tampered`. **Say:** "The gateway
re-hashes the arguments at execution time. They don't match the authorized
hash — rejected, nothing moved." **Click** `/incidents`: a **high**
`authorization_tamper` incident is OPEN, with the tampered attempt linked
as evidence. Click it → evidence timeline.

## Beat 6 — The live nervous system (2:05–2:25)

**Click** the connection badge in the header (green: "live"). **Do:**

```bash
curl -N "http://localhost:8000/api/v1/events/stream?api_key=$REQ" | head -8
```

**Audience sees:** ordered `id:` cursors and `project_seq` numbers.
**Say:** "Every beat you just saw was also a sequenced event. If the
browser drops, it reconnects with the last id and backfills exactly what
it missed — we test that." Optionally trigger another authorize in a
second terminal and watch the dashboard update without refresh.

## Beat 7 — Measured, not claimed (2:25–2:45)

**Do:**

```bash
DATABASE_URL="postgresql+psycopg://agenttrust:agenttrust@localhost:5432/agenttrust" \
PYTHONPATH=apps/api/src python -m agenttrust_api.evaluation.run \
  --db "$DATABASE_URL" --eval-db agenttrust_eval --out /tmp/demo-report.json
```

**Audience sees:** `passed: 100/100 (accuracy 1.0000)`, `false_allow=0
false_deny=0 unauthorized_executions=0 duplicate_effects=0`, latency
p50/p95. **Open** `/evaluations` → the same run with the expected-vs-actual
matrix. **Say:** "Twenty-five allows, twenty reviews, twenty limit-denies,
fifteen invalid-denies, ten tamper/replay, ten malformed — each asserting
not just the decision but whether anything actually executed."

## Beat 8 — Honest limits (2:45–3:00)

**Say:** "What this doesn't do yet: one policy at a time; analysis and
benchmarks run synchronously — no job queue; rate limits are in-memory;
the dashboard uses a dev key, not sessions. The threat model documents the
rest. And if the policy service dies, the SDK fails closed — the agent
gets an error, never a silent refund."

---

**After the demo:** hand over the README quickstart — everything above is
reproducible from it on the reviewer's own machine.
