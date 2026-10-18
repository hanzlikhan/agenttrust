"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, apiFetch, useDashboardKey } from "@/lib/api";
import { useEventSource, type StreamEvent } from "@/hooks/useEventSource";
import ConnectionBadge from "@/components/ConnectionBadge";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import PageHeader from "@/components/PageHeader";
import { runColumns, type RunRowData } from "@/components/runColumns";
import {
  Button,
  Card,
  DataTable,
  EmptyState,
  Input,
  Select,
  Spinner,
  type SortDirection,
} from "@/components/ui";

const PAGE_SIZE = 20;

interface RunListResponse {
  runs: RunRowData[];
  total: number;
  limit: number;
  offset: number;
}

interface AgentOption {
  agent_id: string;
  name: string;
  version: string;
}

function payloadString(value: unknown, key: string): string {
  if (typeof value === "object" && value !== null) {
    const v = (value as Record<string, unknown>)[key];
    return typeof v === "string" ? v : "";
  }
  return "";
}

function toIsoOrNull(local: string): string | null {
  if (local === "") return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function RunsContent() {
  const [key] = useDashboardKey();
  const [runs, setRuns] = useState<RunRowData[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [agentFilter, setAgentFilter] = useState("");
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [afterFilter, setAfterFilter] = useState("");
  const [beforeFilter, setBeforeFilter] = useState("");
  const [search, setSearch] = useState("");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Executions · AgentTrust";
  }, []);

  const fetchRuns = useCallback(async () => {
    if (key === null) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
        order: sortDirection,
      });
      if (statusFilter !== "") params.set("status", statusFilter);
      if (agentFilter !== "") params.set("agent_name", agentFilter);
      const after = toIsoOrNull(afterFilter);
      const before = toIsoOrNull(beforeFilter);
      if (after !== null) params.set("started_after", after);
      if (before !== null) params.set("started_before", before);
      const body = await apiFetch<RunListResponse>(
        `/api/v1/dashboard/runs?${params}`,
        key,
      );
      setRuns(body.runs);
      setTotal(body.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs.");
    } finally {
      setLoading(false);
    }
  }, [key, page, statusFilter, agentFilter, afterFilter, beforeFilter, sortDirection]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Agent options for the filter select (one fetch; the list rarely changes).
  useEffect(() => {
    if (key === null) return;
    apiFetch<{ agents: AgentOption[] }>("/api/v1/agents?limit=100", key)
      .then((body) => setAgents(body.agents))
      .catch(() => setAgents([]));
  }, [key]);

  const resetFilters = useCallback(() => {
    setStatusFilter("");
    setAgentFilter("");
    setAfterFilter("");
    setBeforeFilter("");
    setSearch("");
    setPage(0);
  }, []);

  // Live updates: prepend newly started runs, flip state on completion.
  const handleEvent = useCallback((event: StreamEvent) => {
    if (event.kind === "run.started" && event.run_id !== null) {
      const runId = event.run_id;
      setRuns((prev) => {
        if (prev.some((r) => r.run_id === runId)) return prev;
        const row: RunRowData = {
          run_id: runId,
          trace_id: payloadString(event.payload, "trace_id"),
          agent_name: payloadString(event.payload, "agent") || "unknown",
          agent_version: payloadString(event.payload, "version") || "unknown",
          state: "RUNNING",
          started_at: event.received_at,
          ended_at: null,
          tool_call_count: 0,
        };
        return [row, ...prev].slice(0, PAGE_SIZE);
      });
      setTotal((t) => t + 1);
    } else if (
      (event.kind === "run.completed" || event.kind === "run.failed") &&
      event.run_id !== null
    ) {
      const runId = event.run_id;
      const state = event.kind === "run.completed" ? "COMPLETED" : "FAILED";
      setRuns((prev) =>
        prev.map((r) => (r.run_id === runId ? { ...r, state } : r)),
      );
    }
  }, []);

  const streamUrl =
    key === null
      ? ""
      : `${API_BASE}/api/v1/events/stream?api_key=${encodeURIComponent(key)}`;
  const { status, lastSync } = useEventSource({
    url: streamUrl,
    onEvent: handleEvent,
    enabled: key !== null,
  });

  // Page-scoped prefix search over the loaded rows.
  const visibleRuns = useMemo(() => {
    const q = search.trim();
    if (q === "") return runs;
    return runs.filter(
      (r) => r.run_id.startsWith(q) || r.trace_id.startsWith(q),
    );
  }, [runs, search]);

  const onSortChange = useCallback(() => {
    setSortDirection((d) => (d === "desc" ? "asc" : "desc"));
    setPage(0);
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Executions"
        description="Agent runs with server-side pagination, filtering, and live updates."
        actions={<ConnectionBadge status={status} lastSync={lastSync} />}
      />

      <Card title="Filters">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Input
            id="run-search"
            label="Search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="run id or trace id prefix"
            description="Filters the currently loaded page."
          />
          <Select
            id="status-filter"
            label="Status"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(0);
            }}
            options={[
              { value: "", label: "All" },
              { value: "RUNNING", label: "Running" },
              { value: "COMPLETED", label: "Completed" },
              { value: "FAILED", label: "Failed" },
            ]}
          />
          <Select
            id="agent-filter"
            label="Agent"
            value={agentFilter}
            onChange={(e) => {
              setAgentFilter(e.target.value);
              setPage(0);
            }}
            options={[
              { value: "", label: "All agents" },
              ...agents.map((a) => ({
                value: a.name,
                label: `${a.name} v${a.version}`,
              })),
            ]}
          />
          <Input
            id="started-after"
            label="Started after"
            type="datetime-local"
            value={afterFilter}
            onChange={(e) => {
              setAfterFilter(e.target.value);
              setPage(0);
            }}
          />
          <Input
            id="started-before"
            label="Started before"
            type="datetime-local"
            value={beforeFilter}
            onChange={(e) => {
              setBeforeFilter(e.target.value);
              setPage(0);
            }}
          />
          <div className="flex items-end gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={fetchRuns}>
              Refresh
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={resetFilters}>
              Reset filters
            </Button>
          </div>
        </div>
      </Card>

      {loading && (
        <div className="flex justify-center py-10">
          <Spinner label="Loading runs…" />
        </div>
      )}

      {!loading && error !== null && (
        <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-4">
          <p className="text-sm font-medium text-deny-text">{error}</p>
          <div className="mt-3">
            <Button type="button" variant="secondary" size="sm" onClick={fetchRuns}>
              Retry
            </Button>
          </div>
        </div>
      )}

      {!loading && error === null && (
        <DataTable<RunRowData>
          columns={runColumns({ showAgent: true, sortStartedAt: true })}
          rows={visibleRuns}
          rowKey={(row) => row.run_id}
          caption="Agent runs, sortable by start time"
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          onPageChange={setPage}
          sortKey="started_at"
          sortDirection={sortDirection}
          onSortChange={onSortChange}
          empty={
            <EmptyState
              title="No runs found"
              description="No runs match the current filters. Start the refund demo agent or widen the filters."
              action={
                <Button type="button" variant="secondary" size="sm" onClick={resetFilters}>
                  Reset filters
                </Button>
              }
            />
          }
        />
      )}
    </div>
  );
}

export default function RunsPage() {
  return (
    <RequireDashboardKey>
      <RunsContent />
    </RequireDashboardKey>
  );
}
