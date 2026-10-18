"""Synthetic customer-support refund agent demo (REAL API calls, no mocks).

Demonstrates three spec scenarios end to end against a running AgentTrust API:
  S1 — a safe $40 refund is ALLOWed and executed exactly once.
  S3 — a $900 refund is DENied; the gateway provably never executes it.
  S5 — a duplicated request (same idempotency key, repeated execute) moves the
       balance exactly once.

Prerequisites (see README.md): API migrated + seeded, then:
    export AGENTTRUST_API_KEY='<key printed by the seed>'
    python demo.py

Note: each run consumes real synthetic balance on ORD-100 (40000 minor units
seeded). Re-running the demo keeps working until the balance is exhausted.
"""

import os
import sys
import uuid

import httpx
from agenttrust import (
    AgentTrust,
    ApprovalRequired,
    AuthorizationDenied,
    PolicyServiceUnavailable,
)

API_URL = os.environ.get("AGENTTRUST_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("AGENTTRUST_API_KEY", "")
ORDER = "ORD-100"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    if not API_KEY:
        print("error: set AGENTTRUST_API_KEY (the key printed by the seed).", file=sys.stderr)
        return 2

    trust = AgentTrust(api_key=API_KEY, base_url=API_URL, timeout=10.0)

    @trust.protect(tool="refund_payment")
    def refund_payment(order_id: str, amount_minor: int, currency: str = "USD"):
        # Never executed by the SDK — the gateway performs the real effect.
        raise NotImplementedError

    try:
        with trust.run(agent="refund-support-agent", version="0.1.0") as run_id:
            # ---- S1: safe refund is allowed and executed exactly once ----
            r1 = refund_payment(order_id=ORDER, amount_minor=4000, currency="USD")
            remaining_s1 = r1["remaining_minor"]
            check(
                "S1 ALLOW+execute",
                r1["amount_minor"] == 4000 and r1["order_id"] == ORDER,
                f"refunded 4000, remaining={remaining_s1}",
            )

            # ---- S3: excessive refund is denied and never executes ----
            try:
                refund_payment(order_id=ORDER, amount_minor=90000, currency="USD")
                check("S3 DENY", False, "expected AuthorizationDenied, call succeeded")
            except AuthorizationDenied as exc:
                check(
                    "S3 DENY",
                    exc.reason_code == "AMOUNT_EXCEEDS_MAX",
                    f"reason={exc.reason_code}; execute endpoint never called",
                )
            except (ApprovalRequired, PolicyServiceUnavailable) as exc:
                check("S3 DENY", False, f"wrong exception: {type(exc).__name__}")

            # Prove S3 moved no money: a $1 probe must see the exact S1 balance.
            probe = refund_payment(order_id=ORDER, amount_minor=100, currency="USD")
            check(
                "S3 no side effect",
                probe["remaining_minor"] == remaining_s1 - 100,
                f"remaining={probe['remaining_minor']} (expected {remaining_s1 - 100})",
            )
            balance = probe["remaining_minor"]

            # ---- S5: duplicate requests cause a single balance change ----
            http = httpx.Client(
                base_url=API_URL,
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=10.0,
                # Same rationale as the SDK: talk to the configured URL only.
                trust_env=False,
            )
            key = f"demo-s5-{uuid.uuid4().hex}"
            body = {
                "run_id": run_id,
                "tool_name": "refund_payment",
                "arguments": {"order_id": ORDER, "amount_minor": 2000, "currency": "USD"},
                "idempotency_key": key,
            }
            a1 = http.post("/api/v1/tool-calls/authorize", json=body)
            a2 = http.post("/api/v1/tool-calls/authorize", json=body)
            check(
                "S5 idempotent authorize",
                a1.status_code == 201
                and a2.status_code == 200
                and a1.json()["tool_call_id"] == a2.json()["tool_call_id"],
                f"first={a1.status_code}, replay={a2.status_code}",
            )
            call_id = a1.json()["tool_call_id"]
            e1 = http.post(f"/api/v1/tool-calls/{call_id}/execute", json={"arguments": body["arguments"]})
            e2 = http.post(f"/api/v1/tool-calls/{call_id}/execute", json={"arguments": body["arguments"]})
            r_after_1 = e1.json()["result"]["remaining_minor"]
            r_after_2 = e2.json()["result"]["remaining_minor"]
            check(
                "S5 single execution",
                e1.status_code == 201
                and e2.status_code == 200
                and e2.json()["replayed"] is True
                and e1.json()["execution_id"] == e2.json()["execution_id"]
                and r_after_1 == balance - 2000
                and r_after_2 == r_after_1,
                f"exec1={e1.status_code}, exec2={e2.status_code}, "
                f"remaining {balance} -> {r_after_1} -> {r_after_2}",
            )
    except PolicyServiceUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} scenarios passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
