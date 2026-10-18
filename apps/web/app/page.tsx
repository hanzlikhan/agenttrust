"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch, useDashboardKey } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import PageHeader from "@/components/PageHeader";
import { ApprovalStateBadge, OutcomeBadge } from "@/components/badges";
import { runColumns, type RunRowData } from "@/components/runColumns";
import {
  Button,
  Card,
  DataTable,
  EmptyState,
  Spinner,
} from "@/components/ui";

/* Response shapes mirrored from the API schemas (dashboard + approvals). */

interface DashboardSummary {
  project_id: string;
  runs_total: number;
  runs_by_state: Record<string, number>;
  tool_calls_total: number;
  decisions_total: number;
  decisions_by_outcome: Record<string, number>;
  executions_total: number;
  events_total: number;
  outbox_pending: number;
}

interface AnalyticsDay {
  day: string;
  ALLOW: number;
  DENY: number;
  REVIEW: number;
}

interface RunListResponse {
  runs: RunRowData[];
  total: number;
  limit: number;
  offset: number;
}

interface PendingApproval {
  approval_id: string;
  tool_name: string;
  state: string;
  reason_code: string;
  order_id: string | null;
  amount_minor: number | null;
  currency: string | null;
  expires_at: string;
}

const REVIEWER_KEY_STORAGE = "agenttrust_reviewer_key";

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <p className="text-sm font-medium text-text-2">{label}</p>
      <p className="mt-1 text-3xl font-bold tabular-nums text-text-1">{value}</p>
    </Card>
  );
}

/** Tiny labeled sparkline of total decisions per day (real data, inline SVG). */
function DecisionSparkline({ days }: { days: AnalyticsDay[] }) {
  const points = useMemo(
    () => days.map((d) => d.ALLOW + d.DENY + d.REVIEW),
    [days],
  );
  if (points.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-text-3">
        No decision activity in the selected window.
      </p>
    );
  }
  const W = 600;
  const H = 120;
  const PAD = 8;
  const max = Math.max(...points, 1);
  const xy = points.map((v, i) => {
    const x =
      points.length === 1
        ? W / 2
        : PAD + (i * (W - 2 * PAD)) / (points.length - 1);
    const y = H - PAD - (v / max) * (H - 2 * PAD);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <figure>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-28 w-full"
        role="img"
        aria-label={`Decisions per day over ${points.length} days, peaking at ${max} decisions in a day`}
      >
        <polyline
          points={xy.join(" ")}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          className="text-brand"
        />
        {xy.map((pt, i) => {
          const [cx, cy] = pt.split(",");
          return (
            <circle key={i} cx={cx} cy={cy} r={3} className="fill-brand" />
          );
        })}
      </svg>
      <figcaption className="mt-1 flex justify-between text-xs text-text-3">
        <span>{days[0].day}</span>
        <span>max {max}/day</span>
        <span>{days[days.length - 1].day}</span>
      </figcaption>
    </figure>
  );
}

function OverviewContent() {
  const [key] = useDashboardKey();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [days, setDays] = useState<AnalyticsDay[]>([]);
  const [recentRuns, setRecentRuns] = useState<RunRowData[]>([]);
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [reviewerPresent, setReviewerPresent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Overview · AgentTrust";
  }, []);

  const load = useCallback(async () => {
    if (key === null) return;
    setLoading(true);
    setError(null);
    try {
      const [summaryBody, analyticsBody, runsBody] = await Promise.all([
        apiFetch<DashboardSummary>("/api/v1/dashboard/summary", key),
        apiFetch<{ decisions_by_day: AnalyticsDay[] }>(
          "/api/v1/dashboard/analytics?window_days=14",
          key,
        ),
        apiFetch<RunListResponse>("/api/v1/dashboard/runs?limit=5", key),
      ]);
      setSummary(summaryBody);
      setDays(analyticsBody.decisions_by_day);
      setRecentRuns(runsBody.runs);

      // Pending approvals preview uses the reviewer's own key (ADR-034);
      // the approvals page owns that flow — here we only read it.
      const reviewerKey = sessionStorage.getItem(REVIEWER_KEY_STORAGE);
      setReviewerPresent(reviewerKey !== null);
      if (reviewerKey !== null) {
        try {
          const queue = await apiFetch<{ approvals: PendingApproval[] }>(
            "/api/v1/approvals?state=PENDING&limit=5",
            reviewerKey,
          );
          setPending(queue.approvals);
        } catch {
          setPending(null);
        }
      } else {
        setPending(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load overview.");
    } finally {
      setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading overview…" />
      </div>
    );
  }

  if (error !== null) {
    return (
      <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-4">
        <p className="text-sm font-medium text-deny-text">{error}</p>
        <div className="mt-3">
          <Button type="button" variant="secondary" size="sm" onClick={load}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const isEmpty =
    summary !== null &&
    summary.runs_total === 0 &&
    summary.decisions_total === 0 &&
    summary.tool_calls_total === 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Overview"
        description="Live project activity across runs, policy decisions, and approvals."
        actions={
          <Button type="button" variant="secondary" size="sm" onClick={load}>
            Refresh
          </Button>
        }
      />

      {isEmpty ? (
        <EmptyState
          title="No activity yet"
          description="Start the refund demo agent to see runs, decisions, and approvals appear here."
          action={
            <Link
              href="/runs"
              className="inline-flex items-center rounded-md border border-transparent bg-brand px-3 py-1.5 text-sm font-medium text-brand-text hover:bg-brand-hover"
            >
              View executions
            </Link>
          }
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Kpi label="Runs" value={summary?.runs_total ?? 0} />
            <Kpi label="Tool calls" value={summary?.tool_calls_total ?? 0} />
            <Kpi label="Executions" value={summary?.executions_total ?? 0} />
            <Kpi label="Outbox pending" value={summary?.outbox_pending ?? 0} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card
              title="Policy decisions"
              description={`${summary?.decisions_total ?? 0} total decisions`}
            >
              <div className="flex flex-wrap items-center gap-3">
                {(["ALLOW", "DENY", "REVIEW"] as const).map((outcome) => (
                  <span key={outcome} className="flex items-center gap-2">
                    <OutcomeBadge outcome={outcome} />
                    <span className="text-lg font-semibold tabular-nums text-text-1">
                      {summary?.decisions_by_outcome[outcome] ?? 0}
                    </span>
                  </span>
                ))}
              </div>
              {summary !== null && Object.keys(summary.runs_by_state).length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
                  <span className="text-xs text-text-3">Runs by state:</span>
                  {Object.entries(summary.runs_by_state).map(([state, count]) => (
                    <span key={state} className="text-xs text-text-2">
                      <span className="font-mono">{state}</span>{" "}
                      <span className="tabular-nums">{count}</span>
                    </span>
                  ))}
                </div>
              )}
            </Card>

            <Card
              title="Decision activity"
              description="Total policy decisions per day, last 14 days"
            >
              <DecisionSparkline days={days} />
            </Card>
          </div>

          <Card
            title="Recent runs"
            actions={
              <Link
                href="/runs"
                className="text-sm font-medium text-brand hover:underline"
              >
                View all →
              </Link>
            }
          >
            <DataTable<RunRowData>
              columns={runColumns()}
              rows={recentRuns}
              rowKey={(row) => row.run_id}
              caption="Five most recent agent runs"
              page={0}
              pageSize={5}
              total={recentRuns.length}
              onPageChange={() => {}}
              empty={
                <EmptyState
                  title="No runs yet"
                  description="Runs will appear here once an agent starts executing."
                />
              }
            />
          </Card>

          <Card
            title="Pending approvals"
            actions={
              <Link
                href="/approvals"
                className="text-sm font-medium text-brand hover:underline"
              >
                Open approval center →
              </Link>
            }
          >
            {!reviewerPresent ? (
              <p className="text-sm text-text-3">
                Connect a reviewer key on the{" "}
                <Link href="/approvals" className="text-brand hover:underline">
                  approvals page
                </Link>{" "}
                to preview the pending queue here.
              </p>
            ) : pending === null ? (
              <p className="text-sm text-text-3">
                Could not load the pending queue with the stored reviewer key.
              </p>
            ) : pending.length === 0 ? (
              <p className="text-sm text-text-3">
                No pending approvals. REVIEW decisions will appear here.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {pending.map((item) => (
                  <li
                    key={item.approval_id}
                    className="flex flex-wrap items-center gap-3 rounded-md border border-border px-3 py-2"
                  >
                    <ApprovalStateBadge state={item.state} />
                    <span className="font-mono text-sm text-text-1">
                      {item.tool_name}
                    </span>
                    <span className="text-xs text-text-3">{item.reason_code}</span>
                    <span className="ml-auto text-sm tabular-nums text-text-2">
                      {formatMoney(item.amount_minor, item.currency)}
                    </span>
                    <span className="text-xs text-text-3" title={formatDateTime(item.expires_at)}>
                      expires {formatDateTime(item.expires_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

export default function OverviewPage() {
  return (
    <RequireDashboardKey>
      <OverviewContent />
    </RequireDashboardKey>
  );
}
