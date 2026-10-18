"""Evaluation runner tests (M12) against real PostgreSQL.

The 12-case smoke subset exercises every case type through the real
stack. The FULL 100-case run is executed once during verification (not in
pytest) so the suite stays fast; its measured numbers are recorded in
PROGRESS.md.
"""

from agenttrust_api.evaluation.dataset import (
    SUITE_ID,
    build_dataset,
    dataset_hash,
)
from agenttrust_api.evaluation.service import compute_metrics, run_benchmark

SMOKE_KEYS = [
    "allow-001",
    "allow-025",
    "review-001",
    "review-020",
    "limit-deny-001",
    "limit-deny-012",
    "invalid-deny-001",
    "invalid-deny-014",  # 413 ERROR shape
    "tamper-replay-001",  # tampered execute
    "tamper-replay-006",  # double execute
    "malformed-002",  # injection-shaped extra field
    "malformed-008",  # injection-shaped amount over cap
]


def test_dataset_shape():
    cases = build_dataset()
    assert len(cases) == 100
    assert len({c.case_key for c in cases}) == 100
    assert len(dataset_hash()) == 64
    from collections import Counter

    counts = Counter(c.case_type for c in cases)
    assert counts == {
        "allow": 25,
        "review": 20,
        "limit_deny": 20,
        "invalid_deny": 15,
        "tamper_replay": 10,
        "malformed": 10,
    }


def test_smoke_subset_passes(migrated_db_url):
    report = run_benchmark(
        main_db_url=migrated_db_url,
        eval_db_name="agenttrust_eval_test",
        case_keys=SMOKE_KEYS,
        out_path=None,
    )
    metrics = report["metrics"]
    assert metrics["total"] == len(SMOKE_KEYS)
    failing = [r for r in report["results"] if not r["passed"]]
    assert failing == [], f"smoke cases failed: {failing}"
    assert metrics["false_allow"] == 0
    assert metrics["false_deny"] == 0
    assert metrics["unauthorized_executions"] == 0
    assert metrics["duplicate_effects"] == 0
    assert report["suite_id"] == SUITE_ID
    assert report["model"] == "none"
    assert report["dataset_sha256"] == dataset_hash()
    assert report["limitations"], "limitations must be disclosed"


def test_metrics_detect_regressions():
    rows = [
        {
            "case_type": "allow",
            "passed": False,
            "expected_outcome": "ALLOW",
            "actual_outcome": "DENY",
            "actual_executed": False,
            "actual_side_effects": 0,
            "latency_ms": 10,
        },
        {
            "case_type": "limit_deny",
            "passed": False,
            "expected_outcome": "DENY",
            "actual_outcome": "ALLOW",
            "actual_executed": True,
            "actual_side_effects": 1,
            "latency_ms": 12,
        },
        {
            "case_type": "allow",
            "passed": True,
            "expected_outcome": "ALLOW",
            "actual_outcome": "ALLOW",
            "actual_executed": True,
            "actual_side_effects": 2,
            "latency_ms": 8,
        },
    ]
    metrics = compute_metrics(rows)
    assert metrics["total"] == 3
    assert metrics["passed"] == 1
    assert metrics["false_deny"] == 1
    assert metrics["false_allow"] == 1
    assert metrics["unauthorized_executions"] == 1
    assert metrics["duplicate_effects"] == 1
    assert metrics["latency_ms"]["p50"] == 10.0
    assert metrics["by_type"]["allow"] == {"total": 2, "passed": 1}
