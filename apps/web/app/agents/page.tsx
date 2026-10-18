"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, useDashboardKey } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import PageHeader from "@/components/PageHeader";
import {
  Button,
  Card,
  DataTable,
  EmptyState,
  Spinner,
} from "@/components/ui";

const PAGE_SIZE = 20;

interface AgentItem {
  agent_id: string;
  name: string;
  version: string;
  environment: string;
  run_count: number;
  last_run_at: string | null;
}

interface AgentListResponse {
  agents: AgentItem[];
  total: number;
  limit: number;
  offset: number;
}

function AgentsContent() {
  const [key] = useDashboardKey();
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Agents · AgentTrust";
  }, []);

  const fetchAgents = useCallback(async () => {
    if (key === null) return;
    setLoading(true);
    setError(null);
    try {
      const body = await apiFetch<AgentListResponse>(
        `/api/v1/agents?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`,
        key,
      );
      setAgents(body.agents);
      setTotal(body.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load agents.");
    } finally {
      setLoading(false);
    }
  }, [key, page]);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Agents"
        description="Registered agents with run counts and last activity."
        actions={
          <Button type="button" variant="secondary" size="sm" onClick={fetchAgents}>
            Refresh
          </Button>
        }
      />

      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner label="Loading agents…" />
        </div>
      ) : error !== null ? (
        <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-4">
          <p className="text-sm font-medium text-deny-text">{error}</p>
          <div className="mt-3">
            <Button type="button" variant="secondary" size="sm" onClick={fetchAgents}>
              Retry
            </Button>
          </div>
        </div>
      ) : (
        <Card>
          <DataTable<AgentItem>
            columns={[
              {
                key: "name",
                header: "Name",
                render: (agent) => (
                  <Link
                    href={`/agents/${agent.agent_id}`}
                    className="font-medium text-brand hover:underline"
                  >
                    {agent.name}
                  </Link>
                ),
              },
              {
                key: "version",
                header: "Version",
                render: (agent) => (
                  <span className="font-mono text-xs text-text-2">{agent.version}</span>
                ),
              },
              {
                key: "environment",
                header: "Environment",
                render: (agent) => (
                  <span className="text-text-2">{agent.environment}</span>
                ),
              },
              {
                key: "run_count",
                header: "Runs",
                render: (agent) => (
                  <span className="tabular-nums">{agent.run_count}</span>
                ),
              },
              {
                key: "last_run_at",
                header: "Last run",
                render: (agent) => (
                  <span className="whitespace-nowrap text-text-2">
                    {formatRelative(agent.last_run_at)}
                  </span>
                ),
              },
            ]}
            rows={agents}
            rowKey={(agent) => agent.agent_id}
            caption="Registered agents"
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={setPage}
            empty={
              <EmptyState
                title="No agents registered"
                description="Agents appear here once they register with the API."
              />
            }
          />
        </Card>
      )}
    </div>
  );
}

export default function AgentsPage() {
  return (
    <RequireDashboardKey>
      <AgentsContent />
    </RequireDashboardKey>
  );
}
