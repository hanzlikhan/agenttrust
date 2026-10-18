"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { API_BASE, apiFetch, useDashboardKey } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import PageHeader from "@/components/PageHeader";
import { EvalRunStatusBadge } from "@/components/badges";
import {
  Badge,
  Button,
  Card,
  DataTable,
  EmptyState,
  Spinner,
} from "@/components/ui";

/* Response shapes mirrored from the Phase 7 API contract. */

interface EvalRun {
  run_id: string;
  suite_id: string;
  dataset_version: string;
  policy_version: string | null;
  code_version: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  total: number;
  passed: number;
  failed: number;
}

interface EvalTypeStats {
  total: number;
  passed: number;
}

interface EvalMetrics {
  accuracy: number | null;
  false_allow: number;
  false_deny: number;
  unauthorized_executions: number;
  duplicate_effects: number;
  latency_ms: { p50: number | null; p95: number | null; max: number | null };
  by_type: Record<string, EvalTypeStats>;
}

interface EvalRunStartedResponse {
  run: EvalRun;
  metrics: EvalMetrics;
}

interface EvalResultRow {
  case_key: string;
  case_type: string;
  expected: { outcome: string; executed: boolean };
  actual: { outcome: string; executed: boolean };
  passed: boolean;
  latency_ms: number;
  error: string | null;
}

interface EvalRunDetailResponse {
  run: EvalRun;
  metrics: EvalMetrics;
  results: EvalResultRow[];
}

interface EvalRunsResponse {
  runs: EvalRun[];
  total: number;
}

const PAGE_SIZE = 20;

/* The benchmark suite definition (static metadata, not a measurement). */
const SUITE_NAME = "refund-policy benchmark";
const SUITE_COMPOSITION: Array<{ type: string; label: string; count: number }> = [
  { type: "allow", label: "Allow", count: 25 },
  { type: "review", label: "Review", count: 20 },
  { type: "limit-deny", label: "Limit deny", count: 20 },
  { type: "invalid-deny", label: "Invalid deny", count: 15 },
  { type: "tamper-replay", label: "Tamper / replay", count: 10 },
  { type: "malformed-injection", label: "Malformed / injection", count: 10 },
];
const SUITE_TOTAL = SUITE_COMPOSITION.reduce((sum, c) => sum + c.count, 0);

/** Normalize accuracy to a 0–100 percentage regardless of fraction/percent. */
function accuracyPct(accuracy: number | null): number {
  if (accuracy === null) return 0;
  return accuracy > 1 ? accuracy : accuracy * 100;
}

function EvalContent() {
  const searchParams = useSearchParams();
  const [key] = useDashboardKey();
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvalRunDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [matrixPage, setMatrixPage] = useState(0);
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set());

  useEffect(() => {
    document.title = "Evaluations · AgentTrust";
  }, []);

  // Deep link: /evaluations?selected=<run id>.
  useEffect(() => {
    const selected = searchParams.get("selected");
    if (selected !== null && selected !== "") setSelectedId(selected);
  }, [searchParams]);

  const fetchRuns = useCallback(
    async (pageNum: number) => {
      if (key === null) return;
      setLoading(true);
      setError(null);
      try {
        const body = await apiFetch<EvalRunsResponse>(
          `/api/v1/evaluations/runs?limit=${PAGE_SIZE}&offset=${pageNum * PAGE_SIZE}`,
          key,
        );
        setRuns(body.runs);
        setTotal(body.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load evaluation runs.");
      } finally {
        setLoading(false);
      }
    },
    [key],
  );

  const fetchDetail = useCallback(
    async (id: string) => {
      if (key === null) return;
      setDetailLoading(true);
      setExpandedCases(new Set());
      setMatrixPage(0);
      try {
        const body = await apiFetch<EvalRunDetailResponse>(
          `/api/v1/evaluations/runs/${id}`,
          key,
        );
        setDetail(body);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load run detail.");
      } finally {
        setDetailLoading(false);
      }
    },
    [key],
  );

  useEffect(() => {
    if (key !== null) fetchRuns(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, page]);

  useEffect(() => {
    if (selectedId !== null && key !== null) fetchDetail(selectedId);
    else setDetail(null);
  }, [selectedId, key, fetchDetail]);

  const runBenchmark = useCallback(async () => {
    if (key === null) return;
    setRunning(true);
    setNotice(null);
    try {
      const body = await apiFetch<EvalRunStartedResponse>(
        "/api/v1/evaluations/run",
        key,
        { method: "POST" },
      );
      const acc = accuracyPct(body.metrics.accuracy);
      setNotice(
        `Benchmark finished: run ${body.run.run_id} — ${body.run.passed}/${body.run.total} passed ` +
          `(accuracy ${acc.toFixed(1)}%).`,
      );
      await fetchRuns(0);
      setPage(0);
      setSelectedId(body.run.run_id);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Benchmark run failed.");
    } finally {
      setRunning(false);
    }
  }, [key, fetchRuns]);

  const toggleExpanded = useCallback((caseKey: string) => {
    setExpandedCases((prev) => {
      const next = new Set(prev);
      if (next.has(caseKey)) next.delete(caseKey);
      else next.add(caseKey);
      return next;
    });
  }, []);

  const matrixRows = detail?.results ?? [];
  const matrixSlice = matrixRows.slice(
    matrixPage * PAGE_SIZE,
    (matrixPage + 1) * PAGE_SIZE,
  );

  const exportHref =
    key !== null && detail !== null
      ? `${API_BASE}/api/v1/evaluations/runs/${detail.run.run_id}/report?api_key=${encodeURIComponent(key)}`
      : "";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Evaluations"
        description="100-case benchmark runs against the policy engine. Every value below is measured from a real run — quality gates compare measured values against their targets."
      />

      {error !== null && (
        <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-4">
          <p className="text-sm font-medium text-deny-text">{error}</p>
        </div>
      )}

      {notice !== null && (
        <p role="status" className="text-sm text-text-2">
          {notice}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Benchmark suite"
          description={`${SUITE_NAME} · ${SUITE_TOTAL} cases`}
          actions={
            <Button
              type="button"
              variant="primary"
              loading={running}
              onClick={runBenchmark}
              title="Run the full benchmark on the server (typically 20–60 seconds)"
            >
              Run benchmark
            </Button>
          }
        >
          <h3 className="text-xs font-medium text-text-3">
            Dataset composition (suite definition)
          </h3>
          <div
            className="mt-2 flex h-3 w-full overflow-hidden rounded-full border border-border"
            role="img"
            aria-label={`Suite composition: ${SUITE_COMPOSITION.map((c) => `${c.count} ${c.label}`).join(", ")}`}
          >
            {SUITE_COMPOSITION.map((c) => (
              <div
                key={c.type}
                className={compositionBarClass(c.type)}
                style={{ width: `${(c.count / SUITE_TOTAL) * 100}%` }}
                title={`${c.label}: ${c.count}`}
              />
            ))}
          </div>
          <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
            {SUITE_COMPOSITION.map((c) => (
              <li key={c.type} className="flex items-center gap-2 text-text-2">
                <span
                  aria-hidden="true"
                  className={`h-2.5 w-2.5 rounded-sm ${compositionBarClass(c.type)}`}
                />
                <span>{c.label}</span>
                <span className="ml-auto tabular-nums text-text-1">{c.count}</span>
              </li>
            ))}
          </ul>
          {running ? (
            <p role="status" className="mt-4 flex items-center gap-2 text-sm text-text-2">
              <Spinner size="sm" label="Benchmark running" />
              Running the full {SUITE_TOTAL}-case suite — typically 20–60 seconds.
              The button stays busy while the server works; the run cannot be
              cancelled from here.
            </p>
          ) : (
            <p className="mt-4 text-xs text-text-3">
              The benchmark runs synchronously on the server and typically takes
              20–60 seconds. Leave this page open while it runs.
            </p>
          )}
        </Card>

        <Card
          title={`Run history (${total})`}
          description="Newest runs first."
          actions={
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => fetchRuns(page)}
              disabled={loading}
            >
              Refresh
            </Button>
          }
        >
          <DataTable<EvalRun>
            columns={[
              {
                key: "run",
                header: "Run",
                render: (item) => (
                  <button
                    type="button"
                    onClick={() => setSelectedId(item.run_id)}
                    className="text-left"
                  >
                    <span className="font-mono text-sm font-medium text-brand hover:underline">
                      {item.run_id.slice(0, 8)}
                    </span>
                    <span className="block text-xs text-text-3">
                      {formatDateTime(item.started_at)}
                    </span>
                  </button>
                ),
              },
              {
                key: "versions",
                header: "Versions",
                render: (item) => (
                  <span className="block text-xs text-text-2">
                    <span className="font-mono">dataset {item.dataset_version}</span>
                    <span className="block font-mono">
                      policy {item.policy_version ?? "?"}
                    </span>
                  </span>
                ),
              },
              {
                key: "score",
                header: "Passed",
                render: (item) => (
                  <span className="tabular-nums">
                    {item.passed}/{item.total}
                  </span>
                ),
              },
              {
                key: "status",
                header: "Status",
                render: (item) => <EvalRunStatusBadge state={item.status} />,
              },
            ]}
            rows={runs}
            rowKey={(item) => item.run_id}
            caption="Benchmark run history"
            loading={loading}
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={setPage}
            empty={
              <EmptyState
                title="No benchmark runs yet"
                description="Press “Run benchmark” to execute the 100-case suite against the current policy. Results are stored and appear here."
              />
            }
          />
        </Card>
      </div>

      {selectedId === null && (
        <Card title="Run detail">
          <p className="text-sm text-text-3">
            Select a run from the history to see its metrics, quality gates, and the expected-vs-actual decision matrix.
          </p>
        </Card>
      )}
      {selectedId !== null && detailLoading && (
        <Card title="Run detail">
          <div className="flex justify-center py-8">
            <Spinner label="Loading run…" />
          </div>
        </Card>
      )}
      {selectedId !== null && !detailLoading && detail !== null && (
        <div className="flex flex-col gap-4">
          <Card
            title={`Run ${detail.run.run_id.slice(0, 8)}`}
            description={`${detail.run.suite_id} · dataset ${detail.run.dataset_version} · policy ${detail.run.policy_version ?? "?"} · code ${detail.run.code_version} · started ${formatDateTime(detail.run.started_at)}`}
            actions={
              <div className="flex gap-2">
                <a
                  href={exportHref}
                  download={`benchmark-report-${detail.run.run_id}.json`}
                  className="inline-flex items-center justify-center rounded-md font-semibold transition-colors select-none bg-brand text-brand-text border border-transparent hover:bg-brand-hover text-sm px-4 py-2 gap-2"
                >
                  Export JSON
                </a>
                <Button type="button" variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
                  Close
                </Button>
              </div>
            }
          >
            <div className="mb-2">
              <EvalRunStatusBadge state={detail.run.status} />
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <MetricCard label="Accuracy" value={`${accuracyPct(detail.metrics.accuracy).toFixed(1)}%`} />
              <MetricCard label="False allow" value={String(detail.metrics.false_allow)} />
              <MetricCard label="False deny" value={String(detail.metrics.false_deny)} />
              <MetricCard
                label="Unauthorized executions"
                value={String(detail.metrics.unauthorized_executions)}
              />
              <MetricCard
                label="Duplicate effects"
                value={String(detail.metrics.duplicate_effects)}
              />
              <MetricCard
                label="Latency p50 / p95"
                value={`${detail.metrics.latency_ms.p50} / ${detail.metrics.latency_ms.p95} ms`}
              />
            </div>

            <h3 className="mt-5 text-xs font-medium text-text-3">
              Quality gates — measured value vs target
            </h3>
            <ul className="mt-2 flex flex-col gap-2">
              <QualityGate
                label="Accuracy"
                target="100%"
                measured={`${accuracyPct(detail.metrics.accuracy).toFixed(1)}%`}
                passed={accuracyPct(detail.metrics.accuracy) >= 100}
              />
              <QualityGate
                label="Unauthorized executions"
                target="0"
                measured={String(detail.metrics.unauthorized_executions)}
                passed={detail.metrics.unauthorized_executions === 0}
              />
              <QualityGate
                label="Duplicate effects"
                target="0"
                measured={String(detail.metrics.duplicate_effects)}
                passed={detail.metrics.duplicate_effects === 0}
              />
            </ul>
            <p className="mt-2 text-xs text-text-3">
              Gates are evaluated from this run&apos;s measured metrics only.
            </p>
          </Card>

          <Card
            title={`Expected vs actual (${detail.results.length} cases)`}
            description="Per-case decision matrix from this run."
          >
            <DataTable<EvalResultRow>
              columns={[
                {
                  key: "case",
                  header: "Case",
                  render: (row) => (
                    <span className="block">
                      <span className="font-mono text-sm font-medium text-text-1">
                        {row.case_key}
                      </span>
                      <span className="block font-mono text-xs text-text-3">
                        {row.case_type}
                      </span>
                    </span>
                  ),
                },
                {
                  key: "expected",
                  header: "Expected",
                  render: (row) => (
                    <span className="block text-xs text-text-2">
                      <span className="font-mono">{row.expected.outcome}</span>
                      <span className="block">
                        executed: {row.expected.executed ? "yes" : "no"}
                      </span>
                    </span>
                  ),
                },
                {
                  key: "actual",
                  header: "Actual",
                  render: (row) => (
                    <span className="block text-xs text-text-2">
                      <span className="font-mono">{row.actual.outcome}</span>
                      <span className="block">
                        executed: {row.actual.executed ? "yes" : "no"}
                      </span>
                    </span>
                  ),
                },
                {
                  key: "result",
                  header: "Result",
                  render: (row) => {
                    const expanded = expandedCases.has(row.case_key);
                    return (
                      <span className="block">
                        <Badge variant={row.passed ? "allow" : "deny"}>
                          {row.passed ? "Passed" : "Failed"}
                        </Badge>
                        {!row.passed && (
                          <>
                            <button
                              type="button"
                              onClick={() => toggleExpanded(row.case_key)}
                              className="mt-1 block text-xs font-medium text-brand hover:underline"
                              aria-expanded={expanded}
                            >
                              {expanded ? "Hide error" : "Show error"}
                            </button>
                            {expanded && (
                              <span className="mt-1 block max-w-xs whitespace-pre-wrap rounded-md border border-deny-border bg-deny-bg p-2 font-mono text-xs text-deny-text">
                                {row.error ?? "No error message recorded."}
                              </span>
                            )}
                          </>
                        )}
                      </span>
                    );
                  },
                },
                {
                  key: "latency",
                  header: "Latency",
                  render: (row) => (
                    <span className="whitespace-nowrap tabular-nums text-text-2">
                      {row.latency_ms} ms
                    </span>
                  ),
                },
              ]}
              rows={matrixSlice}
              rowKey={(row) => row.case_key}
              caption="Expected versus actual decision matrix"
              page={matrixPage}
              pageSize={PAGE_SIZE}
              total={detail.results.length}
              onPageChange={setMatrixPage}
              empty={
                <EmptyState
                  title="No results"
                  description="This run recorded no per-case results."
                />
              }
            />
          </Card>
        </div>
      )}
    </div>
  );
}

/** Segment color for a composition type — decorative only, counts are in text. */
function compositionBarClass(type: string): string {
  switch (type) {
    case "allow":
      return "bg-allow-text";
    case "review":
      return "bg-review-text";
    case "limit-deny":
    case "invalid-deny":
      return "bg-deny-text";
    case "tamper-replay":
      return "bg-info-text";
    case "malformed-injection":
      return "bg-text-3";
    default:
      return "bg-text-3";
  }
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-2 p-3">
      <p className="text-xs font-medium text-text-3">{label}</p>
      <p className="mt-1 text-xl font-bold tabular-nums text-text-1">{value}</p>
    </div>
  );
}

function QualityGate({
  label,
  target,
  measured,
  passed,
}: {
  label: string;
  target: string;
  measured: string;
  passed: boolean;
}) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm">
      <span className="font-medium text-text-1">{label}</span>
      <span className="text-text-3">
        measured <span className="tabular-nums text-text-1">{measured}</span>
        {" "}· target <span className="tabular-nums text-text-1">{target}</span>
      </span>
      <span className="ml-auto">
        <Badge variant={passed ? "allow" : "deny"}>
          {passed ? "Met" : "Missed"}
        </Badge>
      </span>
    </li>
  );
}

export default function EvaluationsPage() {
  return (
    <RequireDashboardKey>
      <Suspense
        fallback={
          <div className="flex justify-center py-16">
            <Spinner label="Loading…" />
          </div>
        }
      >
        <EvalContent />
      </Suspense>
    </RequireDashboardKey>
  );
}
