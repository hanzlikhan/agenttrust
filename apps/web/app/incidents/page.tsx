"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { API_BASE, apiFetch, useDashboardKey } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { useEventSource, type StreamEvent } from "@/hooks/useEventSource";
import ConnectionBadge from "@/components/ConnectionBadge";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import PageHeader from "@/components/PageHeader";
import { IncidentSeverityBadge, IncidentStatusBadge } from "@/components/badges";
import {
  Badge,
  Button,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  Input,
  Select,
  Spinner,
} from "@/components/ui";
import { IconInfo } from "@/components/icons";

/* Response shapes mirrored from the Phase 7 API contract. */

interface IncidentListItem {
  incident_id: string;
  category: string;
  severity: string;
  status: string;
  opened_at: string;
  resolved_at: string | null;
  summary: string;
  evidence_count: number;
}

interface IncidentListResponse {
  incidents: IncidentListItem[];
  total: number;
  limit: number;
  offset: number;
}

interface PossibleCause {
  cause: string;
  confidence: string;
  evidence_refs: string[];
}

interface AnalysisReport {
  analyzer_kind: string;
  classification: string;
  summary: string;
  possible_causes: PossibleCause[];
  evidence_refs: string[];
  uncertainty: string;
  recommended_checks: string[];
  analyzed_at: string;
}

interface EvidenceEvent {
  event_id: string;
  kind: string;
  project_seq: number;
  received_at: string;
  payload: unknown;
}

interface IncidentDetail {
  incident_id: string;
  project_id: string;
  category: string;
  severity: string;
  status: string;
  opened_at: string;
  resolved_at: string | null;
  summary: string;
  analysis: AnalysisReport | null;
  evidence: EvidenceEvent[];
}

interface AnalyzeResponse {
  report: AnalysisReport;
}

interface ScanResponse {
  incidents_created: number;
  checked: { deny_windows: number; tamper_windows: number };
}

type TransitionTarget = "investigating" | "resolved" | "dismissed";

const PAGE_SIZE = 20;

/** Human label for analyzer_kind; AI-assisted reports are non-authoritative. */
function analyzerLabel(kind: string): { text: string; variant: "review" | "info" | "neutral" } {
  if (kind.startsWith("ollama:")) {
    const model = kind.slice("ollama:".length);
    return {
      text: model !== "" ? `AI-assisted (${model}) — non-authoritative` : "AI-assisted — non-authoritative",
      variant: "review",
    };
  }
  if (kind === "template") {
    return { text: "Deterministic template", variant: "info" };
  }
  return { text: kind, variant: "neutral" };
}

function confidencePct(confidence: string): string {
  // Backend sends confidence as a descriptive string (e.g. "high").
  return confidence;
}

function TransitionDialog({
  target,
  onClose,
  onConfirm,
  confirming,
}: {
  target: TransitionTarget | null;
  onClose: () => void;
  onConfirm: (target: TransitionTarget) => void;
  confirming: boolean;
}) {
  const copy: Record<TransitionTarget, { title: string; body: string }> = {
    investigating: {
      title: "Start investigating?",
      body: "The incident moves to INVESTIGATING. It stays open and keeps its evidence and analysis.",
    },
    resolved: {
      title: "Mark resolved?",
      body: "The incident moves to RESOLVED with a resolution timestamp. The finding and its evidence are kept for audit.",
    },
    dismissed: {
      title: "Dismiss incident?",
      body: "The incident moves to DISMISSED. The record is kept for audit but will no longer appear in the open queue.",
    },
  };
  const active = target === null ? null : copy[target];
  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      title={active?.title ?? ""}
      actions={
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={confirming}>
            Cancel
          </Button>
          <Button
            type="button"
            variant={target === "dismissed" ? "danger" : "primary"}
            loading={confirming}
            onClick={() => target !== null && onConfirm(target)}
          >
            Confirm
          </Button>
        </>
      }
    >
      <p className="text-sm text-text-2">{active?.body}</p>
    </Dialog>
  );
}

function IncidentsContent() {
  const searchParams = useSearchParams();
  const [key] = useDashboardKey();
  const [statusFilter, setStatusFilter] = useState("all");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [incidents, setIncidents] = useState<IncidentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState<TransitionTarget | null>(null);
  const [transitioning, setTransitioning] = useState(false);
  // Phase 8 audit H2: scan + status transitions require the reviewer scope
  // (approvals:decide), so they use a separately-connected reviewer key.
  const [reviewerKey, setReviewerKey] = useState<string | null>(null);
  const [reviewerInput, setReviewerInput] = useState("");

  useEffect(() => {
    const raw = sessionStorage.getItem("agenttrust_reviewer_key");
    setReviewerKey(raw !== null && raw.trim() !== "" ? raw : null);
  }, []);

  const connectReviewer = useCallback(() => {
    const trimmed = reviewerInput.trim();
    if (trimmed === "") return;
    sessionStorage.setItem("agenttrust_reviewer_key", trimmed);
    setReviewerKey(trimmed);
    setReviewerInput("");
  }, [reviewerInput]);

  const disconnectReviewer = useCallback(() => {
    sessionStorage.removeItem("agenttrust_reviewer_key");
    setReviewerKey(null);
  }, []);

  useEffect(() => {
    document.title = "Incidents · AgentTrust";
  }, []);

  // Deep link: /incidents?selected=<id>.
  useEffect(() => {
    const selected = searchParams.get("selected");
    if (selected !== null && selected !== "") setSelectedId(selected);
  }, [searchParams]);

  const fetchList = useCallback(
    async (pageNum: number, statusF: string, severityF: string) => {
      if (key === null) return;
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(pageNum * PAGE_SIZE),
        });
        if (statusF !== "all") params.set("status", statusF);
        if (severityF !== "all") params.set("severity", severityF);
        const body = await apiFetch<IncidentListResponse>(
          `/api/v1/incidents?${params.toString()}`,
          key,
        );
        setIncidents(body.incidents);
        setTotal(body.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load incidents.");
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
      setAnalyzeError(null);
      try {
        const body = await apiFetch<IncidentDetail>(`/api/v1/incidents/${id}`, key);
        setDetail(body);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load incident.");
      } finally {
        setDetailLoading(false);
      }
    },
    [key],
  );

  // Refetch on filter/page changes; reset to the first page on filter change.
  useEffect(() => {
    if (key === null) return;
    fetchList(page, statusFilter, severityFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, page]);

  useEffect(() => {
    setPage(0);
    if (key !== null) fetchList(0, statusFilter, severityFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, severityFilter]);

  useEffect(() => {
    if (selectedId !== null && key !== null) fetchDetail(selectedId);
    else setDetail(null);
  }, [selectedId, key, fetchDetail]);

  // Live updates: any incident.* event refreshes the list and the open panel.
  const handleEvent = useCallback(
    (event: StreamEvent) => {
      if (event.kind.startsWith("incident.")) {
        fetchList(page, statusFilter, severityFilter);
        if (selectedId !== null) fetchDetail(selectedId);
      }
    },
    [fetchList, fetchDetail, page, statusFilter, severityFilter, selectedId],
  );

  const streamUrl =
    key !== null ? `${API_BASE}/api/v1/events/stream?api_key=${encodeURIComponent(key)}` : "";
  const { status, lastSync } = useEventSource({
    url: streamUrl,
    onEvent: handleEvent,
    enabled: key !== null,
  });

  const scanNow = useCallback(async () => {
    if (key === null) return;
    setScanning(true);
    setNotice(null);
    try {
      const body = await apiFetch<ScanResponse>("/api/v1/incidents/scan", key, {
        method: "POST",
      });
      setNotice(
        `Scan complete: ${body.incidents_created} new incident(s) — checked ` +
          `${body.checked.deny_windows} deny window(s), ${body.checked.tamper_windows} tamper window(s).`,
      );
      fetchList(0, statusFilter, severityFilter);
      setPage(0);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Scan failed.");
    } finally {
      setScanning(false);
    }
  }, [reviewerKey, fetchList, statusFilter, severityFilter]);

  const analyze = useCallback(async () => {
    if (key === null || selectedId === null) return;
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      const body = await apiFetch<AnalyzeResponse>(
        `/api/v1/incidents/${selectedId}/analyze`,
        key,
        { method: "POST" },
      );
      setDetail((prev) =>
        prev !== null && prev.incident_id === selectedId
          ? { ...prev, analysis: body.report }
          : prev,
      );
    } catch (err) {
      setAnalyzeError(
        err instanceof Error ? err.message : "Analysis failed.",
      );
    } finally {
      setAnalyzing(false);
    }
  }, [key, selectedId]);

  const transition = useCallback(
    async (target: TransitionTarget) => {
      const rkey = reviewerKey ?? sessionStorage.getItem("agenttrust_reviewer_key");
      if (rkey === null || rkey === "" || detail === null) {
        setNotice("Connect a reviewer key (approvals:decide scope) to change incident status.");
        return;
      }
      setTransitioning(true);
      try {
        await apiFetch<{ id: string; status: string; resolved_at: string | null }>(
          `/api/v1/incidents/${detail.incident_id}`,
          rkey,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: target }),
          },
        );
        setConfirmTarget(null);
        setNotice(`Incident moved to ${target}.`);
        fetchList(page, statusFilter, severityFilter);
        fetchDetail(detail.incident_id);
      } catch (err) {
        setNotice(
          err instanceof Error ? err.message : "Status change failed.",
        );
        setConfirmTarget(null);
      } finally {
        setTransitioning(false);
      }
    },
    [reviewerKey, detail, fetchList, fetchDetail, page, statusFilter, severityFilter],
  );

  const detailStatus = detail?.status.toLowerCase() ?? "";
  // Phase 8 audit M2: the backend forbids DISMISSED -> INVESTIGATING (409), so it is not offered.
  const canInvestigate = detailStatus === "open" || detailStatus === "resolved";
  const canResolve = detailStatus === "open" || detailStatus === "investigating";
  const canDismiss = detailStatus === "open" || detailStatus === "investigating";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Incidents"
        description="Deterministic detector findings on the event stream. Each incident cites the exact events that fired it; analysis reports are evidence-linked and never invented."
        actions={<ConnectionBadge status={status} lastSync={lastSync} />}
      />

      <Card
        title="Reviewer key"
        description="Scan and status changes require the reviewer scope (approvals:decide). Connect a reviewer key — it stays in sessionStorage, like the Approvals page."
      >
        {reviewerKey === null ? (
          <form
            className="flex max-w-md flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              connectReviewer();
            }}
          >
            <Input
              id="incident-reviewer-key"
              label="Reviewer key"
              type="password"
              value={reviewerInput}
              onChange={(e) => setReviewerInput(e.target.value)}
              placeholder="reviewer key value"
              autoComplete="off"
            />
            <div>
              <Button type="submit" variant="secondary" disabled={reviewerInput.trim() === ""}>
                Connect reviewer key
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-text-2">
              Reviewer key connected{" "}
              <span className="font-mono text-text-3">({reviewerKey.slice(0, 4)}&hellip;)</span>
            </p>
            <Button type="button" variant="ghost" size="sm" onClick={disconnectReviewer}>
              Disconnect
            </Button>
          </div>
        )}
      </Card>

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

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-44">
          <Select
            id="incident-status-filter"
            label="Status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            options={[
              { value: "all", label: "All statuses" },
              { value: "open", label: "Open" },
              { value: "investigating", label: "Investigating" },
              { value: "resolved", label: "Resolved" },
              { value: "dismissed", label: "Dismissed" },
            ]}
          />
        </div>
        <div className="w-44">
          <Select
            id="incident-severity-filter"
            label="Severity"
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            options={[
              { value: "all", label: "All severities" },
              { value: "critical", label: "Critical" },
              { value: "high", label: "High" },
              { value: "medium", label: "Medium" },
              { value: "low", label: "Low" },
            ]}
          />
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() => fetchList(page, statusFilter, severityFilter)}
            disabled={loading}
          >
            Refresh
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={scanNow}
            loading={scanning}
            title="Run the deterministic detector scan now (synchronous)"
          >
            Scan now
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Incidents (${total})`}>
          <DataTable<IncidentListItem>
            columns={[
              {
                key: "severity",
                header: "Severity",
                render: (item) => <IncidentSeverityBadge severity={item.severity} />,
              },
              {
                key: "finding",
                header: "Finding",
                render: (item) => (
                  <button
                    type="button"
                    onClick={() => setSelectedId(item.incident_id)}
                    className="text-left"
                  >
                    <span className="font-medium text-brand hover:underline">
                      {item.category}
                    </span>
                    <span
                      className="block max-w-xs truncate text-xs text-text-3"
                      title={item.summary}
                    >
                      {item.summary === "" ? "—" : item.summary}
                    </span>
                    <span className="block text-xs text-text-3">
                      {item.evidence_count} evidence event{item.evidence_count === 1 ? "" : "s"}
                    </span>
                  </button>
                ),
              },
              {
                key: "status",
                header: "Status",
                render: (item) => <IncidentStatusBadge status={item.status} />,
              },
              {
                key: "opened",
                header: "Opened",
                render: (item) => (
                  <span
                    className="whitespace-nowrap text-text-2"
                    title={formatDateTime(item.opened_at)}
                  >
                    {formatRelative(item.opened_at)}
                  </span>
                ),
              },
            ]}
            rows={incidents}
            rowKey={(item) => item.incident_id}
            caption="Detected incidents"
            loading={loading}
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={setPage}
            empty={
              <EmptyState
                title="No incidents found"
                description="No incidents match these filters. Press “Scan now” to run the deterministic detector over recent event windows."
              />
            }
          />
        </Card>

        <div>
          {selectedId === null && (
            <Card title="Incident detail">
              <p className="text-sm text-text-3">
                Select an incident from the list to inspect its evidence and analysis.
              </p>
            </Card>
          )}
          {selectedId !== null && detailLoading && (
            <Card title="Incident detail">
              <div className="flex justify-center py-8">
                <Spinner label="Loading incident…" />
              </div>
            </Card>
          )}
          {selectedId !== null && !detailLoading && detail !== null && (
            <div className="flex flex-col gap-4">
              <Card
                title={`${detail.category}`}
                description={`${detail.incident_id}`}
                headingLevel={2}
                actions={
                  <Button type="button" variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
                    Close
                  </Button>
                }
              >
                <div className="mb-3 flex flex-wrap gap-2">
                  <IncidentSeverityBadge severity={detail.severity} />
                  <IncidentStatusBadge status={detail.status} />
                </div>
                <dl className="grid gap-x-6 gap-y-2.5 text-sm">
                  <div>
                    <dt className="text-xs font-medium text-text-3">Summary</dt>
                    <dd className="text-text-1">{detail.summary === "" ? "—" : detail.summary}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-text-3">Opened</dt>
                    <dd className="text-text-2">{formatDateTime(detail.opened_at)}</dd>
                  </div>
                  {detail.resolved_at !== null && (
                    <div>
                      <dt className="text-xs font-medium text-text-3">Resolved</dt>
                      <dd className="text-text-2">{formatDateTime(detail.resolved_at)}</dd>
                    </div>
                  )}
                </dl>

                <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-3">
                  {canInvestigate && (
                    <Button type="button" variant="secondary" size="sm" onClick={() => setConfirmTarget("investigating")}>
                      {detailStatus === "open" ? "Mark investigating" : "Reopen as investigating"}
                    </Button>
                  )}
                  {canResolve && (
                    <Button type="button" variant="secondary" size="sm" onClick={() => setConfirmTarget("resolved")}>
                      Resolve
                    </Button>
                  )}
                  {canDismiss && (
                    <Button type="button" variant="danger" size="sm" onClick={() => setConfirmTarget("dismissed")}>
                      Dismiss
                    </Button>
                  )}
                </div>
              </Card>

              <Card
                title="Analysis"
                description="Evidence-linked investigation report. Re-running analysis replaces the stored report."
                actions={
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    loading={analyzing}
                    onClick={analyze}
                    title="Run the investigator synchronously (can take up to ~60 seconds)"
                  >
                    {detail.analysis === null ? "Analyze" : "Re-analyze"}
                  </Button>
                }
              >
                {analyzing && (
                  <p role="status" className="flex items-center gap-2 text-sm text-text-2">
                    <Spinner size="sm" label="Analyzing incident" />
                    Analysis is running on the server — this can take up to about
                    a minute. The page waits without retrying; do not close it.
                  </p>
                )}
                {analyzeError !== null && (
                  <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-3">
                    <p className="text-sm font-medium text-deny-text">{analyzeError}</p>
                  </div>
                )}
                {detail.analysis === null && !analyzing && analyzeError === null && (
                  <p className="text-sm text-text-3">
                    No analysis yet. Run the investigator to produce an evidence-linked report.
                  </p>
                )}
                {detail.analysis !== null && (
                  <AnalysisPanel analysis={detail.analysis} />
                )}
              </Card>

              <Card
                title={`Evidence (${detail.evidence.length})`}
                description="The exact events that fired this incident. Payloads are redacted before display."
              >
                {detail.evidence.length === 0 ? (
                  <p className="text-sm text-text-3">No evidence events linked.</p>
                ) : (
                  <ol className="flex flex-col gap-3">
                    {detail.evidence.map((ev) => (
                      <li
                        key={ev.event_id}
                        className="rounded-md border border-border bg-surface-2 p-3"
                      >
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                          <span className="font-mono text-xs text-text-1">{ev.kind}</span>
                          <span className="text-xs text-text-3">seq {ev.project_seq}</span>
                          <span className="text-xs text-text-3" title={formatDateTime(ev.received_at)}>
                            {formatRelative(ev.received_at)}
                          </span>
                        </div>
                        <details className="mt-2">
                          <summary className="cursor-pointer text-xs font-medium text-brand hover:underline">
                            Redacted payload
                          </summary>
                          <pre className="mt-1 max-h-56 overflow-auto rounded-md border border-border bg-surface p-2 font-mono text-xs text-text-2">
                            {JSON.stringify(ev.payload, null, 2)}
                          </pre>
                        </details>
                      </li>
                    ))}
                  </ol>
                )}
              </Card>
            </div>
          )}
        </div>
      </div>

      <TransitionDialog
        target={confirmTarget}
        onClose={() => setConfirmTarget(null)}
        onConfirm={transition}
        confirming={transitioning}
      />
    </div>
  );
}

function AnalysisPanel({ analysis }: { analysis: AnalysisReport }) {
  const analyzer = analyzerLabel(analysis.analyzer_kind);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={analyzer.variant}>{analyzer.text}</Badge>
        <span className="text-xs text-text-3">
          analyzed {formatDateTime(analysis.analyzed_at)}
        </span>
      </div>

      <div>
        <h3 className="text-xs font-medium text-text-3">Classification</h3>
        <p className="mt-0.5 font-mono text-sm text-text-1">{analysis.classification}</p>
      </div>

      <div>
        <h3 className="text-xs font-medium text-text-3">Summary</h3>
        <p className="mt-0.5 text-sm text-text-2">{analysis.summary}</p>
      </div>

      {analysis.possible_causes.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-text-3">Possible causes</h3>
          <ul className="mt-1 flex flex-col gap-2">
            {analysis.possible_causes.map((c, i) => (
              <li
                key={`${c.cause}-${i}`}
                className="rounded-md border border-border bg-surface-2 p-3"
              >
                <p className="text-sm text-text-1">{c.cause}</p>
                <p className="mt-1 text-xs text-text-3">
                  Confidence {confidencePct(c.confidence)}
                  {c.evidence_refs.length > 0 && (
                    <>
                      {" "}· cited evidence:{" "}
                      <code className="font-mono text-text-2">
                        {c.evidence_refs.join(", ")}
                      </code>
                    </>
                  )}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {analysis.uncertainty !== "" && (
        <div
          role="note"
          className="rounded-lg border border-info-border bg-info-bg p-3"
        >
          <p className="flex items-center gap-2 text-sm font-semibold text-info-text">
            <IconInfo width={14} height={14} /> Uncertainty
          </p>
          <p className="mt-1 text-sm text-text-2">{analysis.uncertainty}</p>
        </div>
      )}

      {analysis.recommended_checks.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-text-3">Recommended checks</h3>
          <ul className="mt-1 list-disc pl-5 text-sm text-text-2">
            {analysis.recommended_checks.map((check, i) => (
              <li key={`${check}-${i}`}>{check}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function IncidentsPage() {
  return (
    <RequireDashboardKey>
      <Suspense
        fallback={
          <div className="flex justify-center py-16">
            <Spinner label="Loading…" />
          </div>
        }
      >
        <IncidentsContent />
      </Suspense>
    </RequireDashboardKey>
  );
}
