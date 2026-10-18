"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch, useDashboardKey } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import { runColumns, type RunRowData } from "@/components/runColumns";
import {
  Button,
  Card,
  DataTable,
  EmptyState,
  Spinner,
} from "@/components/ui";

interface AgentDetail {
  agent_id: string;
  name: string;
  version: string;
  environment: string;
  created_at: string;
  recent_runs: RunRowData[];
  total_runs: number;
}

function AgentDetailContent() {
  const params = useParams();
  const rawId = params.id;
  const agentId = Array.isArray(rawId) ? rawId[0] : (rawId ?? "");

  const [key] = useDashboardKey();
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAgent = useCallback(async () => {
    if (key === null || agentId === "") return;
    setLoading(true);
    setError(null);
    try {
      const body = await apiFetch<AgentDetail>(`/api/v1/agents/${agentId}`, key);
      setAgent(body);
      document.title = `${body.name} · AgentTrust`;
    } catch (err) {
      setError(
        err instanceof Error && err.message.includes("404")
          ? "Agent not found."
          : err instanceof Error
            ? err.message
            : "Failed to load agent.",
      );
    } finally {
      setLoading(false);
    }
  }, [key, agentId]);

  useEffect(() => {
    fetchAgent();
  }, [fetchAgent]);

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading agent…" />
      </div>
    );
  }

  if (error !== null) {
    return (
      <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-4">
        <p className="text-sm font-medium text-deny-text">{error}</p>
        <div className="mt-3 flex gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={fetchAgent}>
            Retry
          </Button>
          <Link
            href="/agents"
            className="inline-flex items-center rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm font-medium text-text-1 hover:bg-surface"
          >
            Back to agents
          </Link>
        </div>
      </div>
    );
  }

  if (agent === null) return null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href="/agents"
          className="text-sm font-medium text-brand hover:underline"
        >
          ← Agents
        </Link>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-text-1">
          {agent.name}
        </h1>
      </div>

      <Card title="Agent details">
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-xs font-medium text-text-3">Version</dt>
            <dd className="mt-0.5 font-mono text-sm text-text-1">{agent.version}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Environment</dt>
            <dd className="mt-0.5 text-sm text-text-1">{agent.environment}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Registered</dt>
            <dd className="mt-0.5 text-sm text-text-1">
              {formatDateTime(agent.created_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Total runs</dt>
            <dd className="mt-0.5 text-sm tabular-nums text-text-1">
              {agent.total_runs}
            </dd>
          </div>
        </dl>
      </Card>

      <Card
        title="Recent runs"
        description={`Newest ${agent.recent_runs.length} of ${agent.total_runs} runs`}
      >
        <DataTable<RunRowData>
          columns={runColumns({ showAgent: false, sortStartedAt: false })}
          rows={agent.recent_runs}
          rowKey={(row) => row.run_id}
          caption={`Recent runs for agent ${agent.name}`}
          page={0}
          pageSize={Math.max(agent.recent_runs.length, 1)}
          total={agent.recent_runs.length}
          onPageChange={() => {}}
          empty={
            <EmptyState
              title="No runs yet"
              description="This agent has not executed any runs."
            />
          }
        />
      </Card>
    </div>
  );
}

export default function AgentDetailPage() {
  return (
    <RequireDashboardKey>
      <AgentDetailContent />
    </RequireDashboardKey>
  );
}
