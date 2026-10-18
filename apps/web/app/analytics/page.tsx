"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiFetch, useDashboardKey } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import PageHeader from "@/components/PageHeader";
import {
  Button,
  Card,
  EmptyState,
  Select,
  Spinner,
} from "@/components/ui";

interface AnalyticsDay {
  day: string;
  ALLOW: number;
  DENY: number;
  REVIEW: number;
}

interface PercentileStats {
  p50: number | null;
  p95: number | null;
  count: number;
}

interface DeniedTool {
  tool_name: string;
  deny_count: number;
}

interface AnalyticsResponse {
  window_days: number;
  decisions_by_day: AnalyticsDay[];
  execution_latency_ms: PercentileStats;
  top_denied_tools: DeniedTool[];
  approval_turnaround_s: PercentileStats;
}

const WINDOW_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "14", label: "Last 14 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const CHART_COLORS = {
  ALLOW: "#22c55e",
  DENY: "#ef4444",
  REVIEW: "#f59e0b",
  denied: "#ef4444",
};

const TOOLTIP_STYLE = {
  backgroundColor: "var(--at-surface)",
  border: "1px solid var(--at-border)",
  borderRadius: "8px",
  fontSize: "12px",
} as const;

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card>
      <p className="text-sm font-medium text-text-2">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums text-text-1">{value}</p>
      {hint !== undefined && <p className="mt-1 text-xs text-text-3">{hint}</p>}
    </Card>
  );
}

function AnalyticsContent() {
  const [key] = useDashboardKey();
  const [windowDays, setWindowDays] = useState("14");
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Analytics · AgentTrust";
  }, []);

  const fetchAnalytics = useCallback(async () => {
    if (key === null) return;
    setLoading(true);
    setError(null);
    try {
      const body = await apiFetch<AnalyticsResponse>(
        `/api/v1/dashboard/analytics?window_days=${windowDays}`,
        key,
      );
      setData(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analytics.");
    } finally {
      setLoading(false);
    }
  }, [key, windowDays]);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Analytics"
        description="Windowed aggregates over committed rows. Empty windows render as empty states, never invented numbers."
        actions={
          <div className="flex items-end gap-2">
            <Select
              id="analytics-window"
              label="Window"
              value={windowDays}
              onChange={(e) => setWindowDays(e.target.value)}
              options={WINDOW_OPTIONS}
            />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={fetchAnalytics}
              className="mb-0"
            >
              Refresh
            </Button>
          </div>
        }
      />

      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner label="Loading analytics…" />
        </div>
      ) : error !== null ? (
        <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-4">
          <p className="text-sm font-medium text-deny-text">{error}</p>
          <div className="mt-3">
            <Button type="button" variant="secondary" size="sm" onClick={fetchAnalytics}>
              Retry
            </Button>
          </div>
        </div>
      ) : data !== null ? (
        <>
          <Card
            title="Decisions per day"
            description={`Stacked by outcome, UTC calendar days, last ${data.window_days} days`}
          >
            {data.decisions_by_day.length === 0 ? (
              <EmptyState
                title="No decisions in this window"
                description="Policy decisions will appear here once tool calls are authorized."
              />
            ) : (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.decisions_by_day}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--at-border)" />
                    <XAxis dataKey="day" tick={{ fontSize: 12 }} stroke="var(--at-text-3)" />
                    <YAxis
                      allowDecimals={false}
                      tick={{ fontSize: 12 }}
                      stroke="var(--at-text-3)"
                    />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Legend />
                    <Bar dataKey="ALLOW" stackId="decisions" fill={CHART_COLORS.ALLOW} />
                    <Bar dataKey="DENY" stackId="decisions" fill={CHART_COLORS.DENY} />
                    <Bar dataKey="REVIEW" stackId="decisions" fill={CHART_COLORS.REVIEW} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>

          <div>
            <h2 className="mb-3 text-lg font-semibold text-text-1">
              Execution latency
            </h2>
            <div className="grid grid-cols-3 gap-4">
              <StatCard
                label="p50"
                value={
                  data.execution_latency_ms.p50 !== null
                    ? formatDuration(data.execution_latency_ms.p50)
                    : "—"
                }
                hint="median finished execution"
              />
              <StatCard
                label="p95"
                value={
                  data.execution_latency_ms.p95 !== null
                    ? formatDuration(data.execution_latency_ms.p95)
                    : "—"
                }
                hint="95th percentile"
              />
              <StatCard
                label="Executions"
                value={String(data.execution_latency_ms.count)}
                hint="finished in window"
              />
            </div>
          </div>

          <Card
            title="Top denied tools"
            description="Registered tools with the most DENY decisions in the window"
          >
            {data.top_denied_tools.length === 0 ? (
              <EmptyState
                title="No denied tools"
                description="No DENY decisions were recorded in this window."
              />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.top_denied_tools} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--at-border)" />
                    <XAxis
                      type="number"
                      allowDecimals={false}
                      tick={{ fontSize: 12 }}
                      stroke="var(--at-text-3)"
                    />
                    <YAxis
                      type="category"
                      dataKey="tool_name"
                      width={140}
                      tick={{ fontSize: 12 }}
                      stroke="var(--at-text-3)"
                    />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Bar dataKey="deny_count" fill={CHART_COLORS.denied} name="Denies" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>

          <div>
            <h2 className="mb-3 text-lg font-semibold text-text-1">
              Approval turnaround
            </h2>
            <div className="grid grid-cols-3 gap-4">
              <StatCard
                label="p50"
                value={
                  data.approval_turnaround_s.p50 !== null
                    ? formatDuration(data.approval_turnaround_s.p50 * 1000)
                    : "—"
                }
                hint="median time to decision"
              />
              <StatCard
                label="p95"
                value={
                  data.approval_turnaround_s.p95 !== null
                    ? formatDuration(data.approval_turnaround_s.p95 * 1000)
                    : "—"
                }
                hint="95th percentile"
              />
              <StatCard
                label="Decided"
                value={String(data.approval_turnaround_s.count)}
                hint="approvals decided in window"
              />
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <RequireDashboardKey>
      <AnalyticsContent />
    </RequireDashboardKey>
  );
}
