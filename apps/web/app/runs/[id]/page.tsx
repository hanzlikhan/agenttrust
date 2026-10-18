"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { API_BASE, apiFetch, useDashboardKey } from "@/lib/api";
import {
  formatDateTime,
  formatDuration,
} from "@/lib/format";
import { useEventSource, type StreamEvent } from "@/hooks/useEventSource";
import ConnectionBadge from "@/components/ConnectionBadge";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import { RunStateBadge } from "@/components/badges";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Spinner,
  type BadgeVariant,
} from "@/components/ui";

interface TimelineEvent {
  event_id: string;
  kind: string;
  project_seq: number;
  run_id: string | null;
  received_at: string;
  payload: unknown;
}

interface RunDetail {
  run_id: string;
  trace_id: string;
  agent_name: string;
  agent_version: string;
  state: string;
  started_at: string;
  ended_at: string | null;
  tool_call_count: number;
  events: TimelineEvent[];
}

function kindVariant(kind: string): BadgeVariant {
  if (kind === "policy.allowed" || kind.endsWith(".approved")) return "allow";
  if (
    kind === "policy.denied" ||
    kind.endsWith(".rejected") ||
    kind === "run.failed"
  )
    return "deny";
  if (kind === "policy.review" || kind.startsWith("approval.")) return "review";
  if (
    kind.startsWith("run.") ||
    kind.startsWith("tool.") ||
    kind.startsWith("execution.")
  )
    return "info";
  return "neutral";
}

/** Short human summary of the interesting fields in an event payload. */
function summarizePayload(payload: unknown): string {
  if (typeof payload !== "object" || payload === null) return "—";
  const p = payload as Record<string, unknown>;
  const parts: string[] = [];
  for (const key of [
    "outcome",
    "state",
    "reason_code",
    "tool",
    "decision",
    "order_id",
  ]) {
    const v = p[key];
    if (typeof v === "string" && v !== "") parts.push(`${key}: ${v}`);
  }
  const amount = p["amount_minor"];
  if (typeof amount === "number") parts.push(`amount_minor: ${amount}`);
  if (parts.length === 0) {
    const keys = Object.keys(p);
    return keys.length > 0 ? `fields: ${keys.slice(0, 5).join(", ")}` : "—";
  }
  return parts.join(" · ");
}

/** Pull an approval_id out of an event payload when present. */
function approvalIdOf(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const v = (payload as Record<string, unknown>)["approval_id"];
  return typeof v === "string" && v !== "" ? v : null;
}

function durationMs(run: RunDetail): number | null {
  if (run.ended_at === null) return null;
  const ms = new Date(run.ended_at).getTime() - new Date(run.started_at).getTime();
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

function RunDetailContent() {
  const params = useParams();
  const rawId = params.id;
  const runId = Array.isArray(rawId) ? rawId[0] : (rawId ?? "");

  const [key] = useDashboardKey();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = `Run ${runId.slice(0, 8)} · AgentTrust`;
  }, [runId]);

  const fetchDetail = useCallback(async () => {
    if (key === null || runId === "") return;
    setLoading(true);
    setError(null);
    try {
      const body = await apiFetch<RunDetail>(
        `/api/v1/dashboard/runs/${runId}`,
        key,
      );
      setRun(body);
      setEvents(body.events);
    } catch (err) {
      setError(
        err instanceof Error && err.message.includes("404")
          ? "Run not found."
          : err instanceof Error
            ? err.message
            : "Failed to load run.",
      );
    } finally {
      setLoading(false);
    }
  }, [key, runId]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  const handleEvent = useCallback(
    (event: StreamEvent) => {
      if (event.run_id !== runId) return;
      setEvents((prev) => {
        if (prev.some((e) => e.event_id === event.event_id)) return prev;
        const next = [
          ...prev,
          {
            event_id: event.event_id,
            kind: event.kind,
            project_seq: event.project_seq,
            run_id: event.run_id,
            received_at: event.received_at,
            payload: event.payload,
          },
        ];
        next.sort((a, b) => a.project_seq - b.project_seq);
        return next;
      });
      if (event.kind === "run.completed" || event.kind === "run.failed") {
        setRun((prev) =>
          prev === null
            ? prev
            : {
                ...prev,
                state:
                  event.kind === "run.completed" ? "COMPLETED" : "FAILED",
              },
        );
      }
    },
    [runId],
  );

  const streamUrl =
    key === null
      ? ""
      : `${API_BASE}/api/v1/events/stream?api_key=${encodeURIComponent(key)}`;
  const { status, lastSync } = useEventSource({
    url: streamUrl,
    onEvent: handleEvent,
    enabled: key !== null && runId !== "",
  });

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading run…" />
      </div>
    );
  }

  if (error !== null) {
    return (
      <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-4">
        <p className="text-sm font-medium text-deny-text">{error}</p>
        <div className="mt-3 flex gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={fetchDetail}>
            Retry
          </Button>
          <Link
            href="/runs"
            className="inline-flex items-center rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm font-medium text-text-1 hover:bg-surface"
          >
            Back to runs
          </Link>
        </div>
      </div>
    );
  }

  if (run === null) return null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link
            href="/runs"
            className="text-sm font-medium text-brand hover:underline"
          >
            ← Executions
          </Link>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-text-1">
            Run <span className="font-mono">{run.run_id.slice(0, 8)}…</span>
          </h1>
        </div>
        <ConnectionBadge status={status} lastSync={lastSync} />
      </div>

      <Card title="Run summary">
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <dt className="text-xs font-medium text-text-3">Agent</dt>
            <dd className="mt-0.5 text-sm text-text-1">
              {run.agent_name} <span className="text-text-3">v{run.agent_version}</span>
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">State</dt>
            <dd className="mt-1">
              <RunStateBadge state={run.state} />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Run id</dt>
            <dd className="mt-0.5 break-all font-mono text-xs text-text-2">
              {run.run_id}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Trace id</dt>
            <dd className="mt-0.5 break-all font-mono text-xs text-text-2">
              {run.trace_id}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Started</dt>
            <dd className="mt-0.5 text-sm text-text-1">
              {formatDateTime(run.started_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Ended</dt>
            <dd className="mt-0.5 text-sm text-text-1">
              {run.ended_at !== null ? formatDateTime(run.ended_at) : "—"}
              {durationMs(run) !== null && (
                <span className="text-text-3">
                  {" "}
                  ({formatDuration(durationMs(run))})
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Tool calls</dt>
            <dd className="mt-0.5 text-sm tabular-nums text-text-1">
              {run.tool_call_count}
            </dd>
          </div>
        </dl>
      </Card>

      <Card
        title="Event timeline"
        description="Events in project_seq order. Payloads are redacted server-side before storage."
      >
        {events.length === 0 ? (
          <EmptyState
            title="No events yet"
            description="No events have been recorded for this run."
          />
        ) : (
          <ol className="relative flex flex-col gap-0 border-l border-border pl-0">
            {events.map((event) => {
              const approvalId = approvalIdOf(event.payload);
              return (
                <li
                  key={event.event_id}
                  className="relative pb-5 pl-6 last:pb-0"
                >
                  <span
                    aria-hidden="true"
                    className="absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full bg-text-3"
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={kindVariant(event.kind)}>{event.kind}</Badge>
                    <span className="font-mono text-xs text-text-3">
                      #{event.project_seq}
                    </span>
                    <time className="text-xs text-text-3" dateTime={event.received_at}>
                      {formatDateTime(event.received_at)}
                    </time>
                  </div>
                  <p className="mt-1 text-sm text-text-2">
                    {summarizePayload(event.payload)}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {approvalId !== null && (
                      <Link
                        href={`/approvals?selected=${approvalId}`}
                        className="text-xs font-medium text-brand hover:underline"
                      >
                        Open approval {approvalId.slice(0, 8)}… →
                      </Link>
                    )}
                    <details className="text-xs">
                      <summary className="cursor-pointer text-text-3 hover:text-text-1">
                        Full payload
                      </summary>
                      <pre className="mt-1 max-h-64 overflow-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-[11px] text-text-2">
                        {JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </details>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </Card>

      <details className="rounded-lg border border-border bg-surface p-4">
        <summary className="cursor-pointer text-sm font-medium text-text-1">
          Run metadata (raw)
        </summary>
        <pre className="mt-2 max-h-96 overflow-auto rounded-md bg-surface-2 p-3 font-mono text-xs text-text-2">
          {JSON.stringify(
            {
              run_id: run.run_id,
              trace_id: run.trace_id,
              agent_name: run.agent_name,
              agent_version: run.agent_version,
              state: run.state,
              started_at: run.started_at,
              ended_at: run.ended_at,
              tool_call_count: run.tool_call_count,
              event_count: events.length,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </div>
  );
}

export default function RunDetailPage() {
  return (
    <RequireDashboardKey>
      <RunDetailContent />
    </RequireDashboardKey>
  );
}
