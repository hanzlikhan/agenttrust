"""CLI: run the 100-case evaluation benchmark.

``python -m agenttrust_api.evaluation.run --db <main-database-url>``

Runs the full suite against an isolated database (created fresh, migrated,
seeded), writes ``evaluation_runs`` / ``evaluation_results`` rows to the
main database, and emits ``benchmark-report.json``.
"""

import argparse
import os
import sys

from .service import run_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AgentTrust evaluation benchmark.")
    parser.add_argument(
        "--db",
        required=False,
        default=os.environ.get("DATABASE_URL"),
        help="Main database URL (default: $DATABASE_URL).",
    )
    parser.add_argument(
        "--eval-db",
        default="agenttrust_eval",
        help="Name of the isolated eval database (default: agenttrust_eval).",
    )
    parser.add_argument(
        "--out",
        default="benchmark-report.json",
        help="Where to write benchmark-report.json.",
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Optional subset of case keys (smoke runs).",
    )
    parser.add_argument(
        "--keep-eval-db",
        action="store_true",
        help="Do not drop the isolated eval database afterwards.",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Project UUID that owns the run's results (tenant isolation). "
        "Omit to store the run unowned (invisible to the project-scoped API).",
    )
    args = parser.parse_args()
    if not args.db:
        print("error: --db or $DATABASE_URL is required", file=sys.stderr)
        return 2
    project_id = None
    if args.project_id:
        from uuid import UUID

        try:
            project_id = UUID(args.project_id)
        except ValueError:
            print("error: --project-id must be a UUID", file=sys.stderr)
            return 2
    report = run_benchmark(
        main_db_url=args.db,
        eval_db_name=args.eval_db,
        case_keys=args.cases,
        out_path=args.out,
        project_id=project_id,
        destructive=True,
    )
    metrics = report["metrics"]
    print(f"run_id:   {report['run_id']}")
    print(f"dataset:  {report['dataset_version']} ({report['dataset_sha256'][:12]}...)")
    print(f"policy:   v{report['policy_version']}  code: {report['code_version'][:12]}")
    print(f"passed:   {metrics['passed']}/{metrics['total']} "
          f"(accuracy {metrics['accuracy']:.4f})")
    print(f"false_allow={metrics['false_allow']} false_deny={metrics['false_deny']} "
          f"unauthorized_executions={metrics['unauthorized_executions']} "
          f"duplicate_effects={metrics['duplicate_effects']}")
    lat = metrics["latency_ms"]
    print(f"latency_ms: p50={lat['p50']} p95={lat['p95']} max={lat['max']}")
    print(f"report:   {args.out}")
    if not args.keep_eval_db:
        from .service import drop_eval_db

        drop_eval_db(args.db, args.eval_db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
