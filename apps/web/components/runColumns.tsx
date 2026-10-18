"use client";

import Link from "next/link";
import type { DataTableColumn } from "./ui";
import { formatDateTime } from "@/lib/format";
import { RunStateBadge } from "./badges";

/**
 * Shared run-table column definitions. Used by the Overview recent-runs
 * preview, the Execution Explorer, and the agent detail page.
 */

export interface RunRowData {
  run_id: string;
  trace_id: string;
  agent_name?: string;
  agent_version?: string;
  state: string;
  started_at: string;
  ended_at?: string | null;
  tool_call_count: number;
}

/**
 * Columns for run summary rows. `showAgent` adds the Agent column
 * (agent detail rows carry no agent fields, so they hide it).
 * `sortStartedAt` wires the Started column to the parent's sort state.
 */
export function runColumns({
  showAgent = true,
  sortStartedAt = false,
}: {
  showAgent?: boolean;
  sortStartedAt?: boolean;
} = {}): DataTableColumn<RunRowData>[] {
  const columns: DataTableColumn<RunRowData>[] = [
    {
      key: "run",
      header: "Run",
      render: (row) => (
        <span>
          <Link
            href={`/runs/${row.run_id}`}
            className="font-mono text-brand hover:underline"
          >
            {row.run_id.slice(0, 8)}…
          </Link>
          <span
            className="block font-mono text-xs text-text-3"
            title={row.trace_id}
          >
            trace {row.trace_id.slice(0, 8)}…
          </span>
        </span>
      ),
    },
  ];
  if (showAgent) {
    columns.push({
      key: "agent",
      header: "Agent",
      render: (row) => (
        <span>
          {row.agent_name ?? "unknown"}
          <span className="text-text-3"> v{row.agent_version ?? "?"}</span>
        </span>
      ),
    });
  }
  columns.push(
    {
      key: "state",
      header: "State",
      render: (row) => <RunStateBadge state={row.state} />,
    },
    {
      key: "tool_calls",
      header: "Tool calls",
      render: (row) => <span className="tabular-nums">{row.tool_call_count}</span>,
    },
    {
      key: "started_at",
      header: "Started",
      sortable: sortStartedAt,
      render: (row) => (
        <span className="whitespace-nowrap text-text-2">
          {formatDateTime(row.started_at)}
        </span>
      ),
    },
  );
  return columns;
}
