"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { API_BASE, apiFetch } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { useEventSource, type StreamEvent } from "@/hooks/useEventSource";
import ConnectionBadge from "@/components/ConnectionBadge";
import PageHeader from "@/components/PageHeader";
import { ApprovalStateBadge, OutcomeBadge } from "@/components/badges";
import {
  Button,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  Input,
  Spinner,
} from "@/components/ui";

// Dev-only reviewer credential. The reviewer pastes a key holding the
// approvals:decide scope and it lives only in sessionStorage, never in the
// bundle or in logs.
const STORAGE_KEY = "agenttrust_reviewer_key";

interface QueueItem {
  approval_id: string;
  tool_call_id: string;
  tool_name: string;
  state: string;
  reason_code: string;
  order_id: string | null;
  amount_minor: number | null;
  currency: string | null;
  expires_at: string;
  row_version: number;
  created_at: string;
}

interface ApprovalDetail {
  approval_id: string;
  tool_call_id: string;
  state: string;
  reason: string | null;
  expires_at: string;
  decided_at: string | null;
  row_version: number;
  created_at: string;
  tool_call: {
    tool_name: string;
    args_redacted: Record<string, unknown>;
    args_hash: string;
    idempotency_key: string;
    state: string;
  };
  decision: {
    outcome: string;
    reason_code: string;
    explanation: string;
    policy_version: number | null;
  };
  order_facts: {
    order_ref: string;
    eligible: boolean;
    remaining_minor: number;
    currency: string;
  } | null;
  requester: { key_name: string; key_prefix: string };
  reviewer_key_prefix: string | null;
  events: Array<{ event_id: string; kind: string; received_at: string }>;
}

interface DecisionResponse {
  approval_id: string;
  state: string;
  decided_at: string | null;
  row_version: number;
  reason: string | null;
}

function formatCountdown(expiresAt: string): string {
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return "expired";
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
}

function getReviewerKey(): string | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  return raw !== null && raw.trim() !== "" ? raw : null;
}

function ApprovalsContent() {
  const searchParams = useSearchParams();
  const [reviewerKey, setReviewerKey] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [queuePage, setQueuePage] = useState(0);
  const QUEUE_PAGE_SIZE = 50;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ApprovalDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reason, setReason] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmVerdict, setConfirmVerdict] = useState<
    "approved" | "rejected" | null
  >(null);

  useEffect(() => {
    document.title = "Approvals · AgentTrust";
  }, []);

  useEffect(() => {
    setReviewerKey(getReviewerKey());
  }, []);

  // Deep link: /approvals?selected=<id> (e.g. from a run timeline).
  useEffect(() => {
    const selected = searchParams.get("selected");
    if (selected !== null && selected !== "") setSelectedId(selected);
  }, [searchParams]);

  const fetchQueue = useCallback(async (pageNum: number) => {
    const key = getReviewerKey();
    if (key === null) return;
    setLoading(true);
    setError(null);
    try {
      const body = await apiFetch<{ approvals: QueueItem[]; total: number }>(
        `/api/v1/approvals?state=PENDING&limit=${QUEUE_PAGE_SIZE}&offset=${pageNum * QUEUE_PAGE_SIZE}`,
        key,
      );
      setQueue(body.approvals);
      setTotal(body.total);
      setQueuePage(pageNum);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load approvals.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (reviewerKey !== null) fetchQueue(queuePage);
  }, [reviewerKey, fetchQueue]);

  const fetchDetail = useCallback(async (id: string) => {
    const key = getReviewerKey();
    if (key === null) return;
    setDetailLoading(true);
    setNotice(null);
    try {
      const body = await apiFetch<ApprovalDetail>(
        `/api/v1/approvals/${id}`,
        key,
      );
      setDetail(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load approval.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId !== null) fetchDetail(selectedId);
    else setDetail(null);
  }, [selectedId, fetchDetail]);

  // Live updates: any approval.* event refreshes the queue and the open panel.
  const handleEvent = useCallback(
    (event: StreamEvent) => {
      if (event.kind.startsWith("approval.")) {
        fetchQueue(queuePage);
        if (selectedId !== null) fetchDetail(selectedId);
      }
    },
    [fetchQueue, fetchDetail, selectedId],
  );

  const streamUrl =
    reviewerKey !== null
      ? `${API_BASE}/api/v1/events/stream?api_key=${encodeURIComponent(reviewerKey)}`
      : "";
  const { status, lastSync } = useEventSource({
    url: streamUrl,
    onEvent: handleEvent,
    enabled: reviewerKey !== null,
  });

  const decide = useCallback(
    async (verdict: "approved" | "rejected") => {
      const key = getReviewerKey();
      if (detail === null || key === null) return;
      setDeciding(true);
      setNotice(null);
      try {
        const body = await apiFetch<DecisionResponse>(
          `/api/v1/approvals/${detail.approval_id}/decision`,
          key,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              decision: verdict,
              reason: reason.trim() === "" ? null : reason.trim(),
              expected_row_version: detail.row_version,
            }),
          },
        );
        setNotice(
          `Decision recorded: ${body.state} (row version ${body.row_version}).`,
        );
        setReason("");
        setConfirmVerdict(null);
        fetchQueue(queuePage);
        fetchDetail(detail.approval_id);
      } catch (err) {
        setNotice(err instanceof Error ? err.message : "Decision failed.");
      } finally {
        setDeciding(false);
      }
    },
    [detail, reason, fetchQueue, fetchDetail],
  );

  const saveKey = useCallback(() => {
    const trimmed = keyInput.trim();
    if (trimmed === "") return;
    sessionStorage.setItem(STORAGE_KEY, trimmed);
    setReviewerKey(trimmed);
    setKeyInput("");
    setSelectedId(null);
  }, [keyInput]);

  const clearKey = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    setReviewerKey(null);
    setQueue([]);
    setSelectedId(null);
    setDetail(null);
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Approval Center"
        description="Human review for REVIEW decisions. Approving mints a single-use execution grant; it never executes the tool."
        actions={<ConnectionBadge status={status} lastSync={lastSync} />}
      />

      {reviewerKey === null ? (
        <Card
          title="Reviewer key"
          description="Dev only: the key is kept in sessionStorage and never leaves your browser except in API calls."
        >
          <form
            className="flex max-w-md flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              saveKey();
            }}
          >
            <Input
              id="reviewer-key"
              label="Reviewer API key"
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="at_…"
              autoComplete="off"
              description="Needs the approvals:decide scope."
            />
            <div>
              <Button type="submit" variant="primary" disabled={keyInput.trim() === ""}>
                Connect
              </Button>
            </div>
          </form>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-text-2">
              Reviewing as key{" "}
              <code className="font-mono text-text-3">
                {reviewerKey.slice(0, 12)}…
              </code>
            </p>
            <div className="ml-auto flex gap-2">
              <Button type="button" variant="secondary" size="sm" onClick={() => fetchQueue(queuePage)}>
                Refresh
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={clearKey}>
                Disconnect
              </Button>
            </div>
          </div>

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
            <Card title={`Pending queue (${total})`}>
              {loading ? (
                <div className="flex justify-center py-8">
                  <Spinner label="Loading approvals…" />
                </div>
              ) : (
                <DataTable<QueueItem>
                  columns={[
                    {
                      key: "action",
                      header: "Action",
                      render: (item) => (
                        <button
                          type="button"
                          onClick={() => setSelectedId(item.approval_id)}
                          className="text-left"
                        >
                          <span className="font-mono text-sm font-medium text-brand hover:underline">
                            {item.tool_name}
                          </span>
                          <span className="block text-xs text-text-3">
                            {item.reason_code} · {item.order_id ?? "—"}
                          </span>
                        </button>
                      ),
                    },
                    {
                      key: "amount",
                      header: "Amount",
                      render: (item) => (
                        <span className="tabular-nums">
                          {formatMoney(item.amount_minor, item.currency)}
                        </span>
                      ),
                    },
                    {
                      key: "expires",
                      header: "Expires in",
                      render: (item) => (
                        <span className="whitespace-nowrap text-text-2">
                          {formatCountdown(item.expires_at)}
                        </span>
                      ),
                    },
                  ]}
                  rows={queue}
                  rowKey={(item) => item.approval_id}
                  caption="Pending approvals awaiting human review"
                  page={queuePage}
                  pageSize={QUEUE_PAGE_SIZE}
                  total={total}
                  onPageChange={(nextPage) => fetchQueue(nextPage)}
                  empty={
                    <EmptyState
                      title="No pending approvals"
                      description="Trigger a REVIEW decision (e.g. a $150 refund) to see one here."
                    />
                  }
                />
              )}
            </Card>

            <div>
              {selectedId === null && (
                <Card title="Review">
                  <p className="text-sm text-text-3">
                    Select an approval from the queue to review it.
                  </p>
                </Card>
              )}
              {selectedId !== null && detailLoading && (
                <Card title="Review">
                  <div className="flex justify-center py-8">
                    <Spinner label="Loading approval…" />
                  </div>
                </Card>
              )}
              {selectedId !== null && !detailLoading && detail !== null && (
                <Card title={`Review: ${detail.tool_call.tool_name}`}>
                  <div className="mb-3">
                    <ApprovalStateBadge state={detail.state} />
                  </div>
                  <dl className="grid gap-x-6 gap-y-2.5 text-sm">
                    <div>
                      <dt className="text-xs font-medium text-text-3">Requested by</dt>
                      <dd className="text-text-1">
                        {detail.requester.key_name || "(unnamed)"}{" "}
                        <span className="font-mono text-xs text-text-3">
                          {detail.requester.key_prefix}…
                        </span>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-medium text-text-3">Policy decision</dt>
                      <dd className="flex flex-wrap items-center gap-2">
                        <OutcomeBadge outcome={detail.decision.outcome} />
                        <span className="font-mono text-xs text-text-3">
                          {detail.decision.reason_code}
                        </span>
                        <span className="text-xs text-text-3">
                          policy v{detail.decision.policy_version ?? "?"}
                        </span>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-medium text-text-3">Explanation</dt>
                      <dd className="text-text-2">{detail.decision.explanation}</dd>
                    </div>
                    <div>
                      <dt className="text-xs font-medium text-text-3">Order facts</dt>
                      <dd className="text-text-2">
                        {detail.order_facts !== null ? (
                          <>
                            <span className="font-mono">{detail.order_facts.order_ref}</span>{" "}
                            · eligible: {detail.order_facts.eligible ? "yes" : "no"} ·
                            remaining:{" "}
                            {formatMoney(
                              detail.order_facts.remaining_minor,
                              detail.order_facts.currency,
                            )}
                          </>
                        ) : (
                          "unavailable"
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-medium text-text-3">Expires</dt>
                      <dd className="text-text-2">
                        {new Date(detail.expires_at).toLocaleString()} (
                        {formatCountdown(detail.expires_at)})
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-medium text-text-3">Argument hash</dt>
                      <dd className="font-mono text-xs text-text-3">
                        {detail.tool_call.args_hash.slice(0, 16)}…
                      </dd>
                    </div>
                  </dl>

                  <h3 className="mt-4 text-xs font-medium text-text-3">
                    Canonical arguments
                  </h3>
                  <pre className="mt-1 max-h-64 overflow-auto rounded-md border border-border bg-surface-2 p-2 font-mono text-xs text-text-2">
                    {JSON.stringify(detail.tool_call.args_redacted, null, 2)}
                  </pre>

                  {detail.state === "PENDING" ? (
                    <div className="mt-4 flex gap-2">
                      <Button
                        type="button"
                        variant="primary"
                        disabled={deciding}
                        onClick={() => setConfirmVerdict("approved")}
                      >
                        Approve
                      </Button>
                      <Button
                        type="button"
                        variant="danger"
                        disabled={deciding}
                        onClick={() => setConfirmVerdict("rejected")}
                      >
                        Reject
                      </Button>
                    </div>
                  ) : (
                    <p className="mt-4 text-sm text-text-3">
                      Decided
                      {detail.decided_at !== null
                        ? ` at ${new Date(detail.decided_at).toLocaleString()}`
                        : ""}
                      {detail.reason !== null ? ` — ${detail.reason}` : ""}.
                    </p>
                  )}

                  <div className="mt-4 border-t border-border pt-3">
                    <h3 className="text-xs font-medium text-text-3">History</h3>
                    <ul className="mt-1 flex flex-col gap-1">
                      {detail.events.map((e) => (
                        <li key={e.event_id} className="text-xs text-text-2">
                          <span className="text-text-3">
                            {new Date(e.received_at).toLocaleTimeString()}
                          </span>{" "}
                          <span className="font-mono">{e.kind}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </>
      )}

      <Dialog
        open={confirmVerdict !== null}
        onClose={() => setConfirmVerdict(null)}
        title={
          confirmVerdict === "approved" ? "Approve this call?" : "Reject this call?"
        }
        actions={
          <>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setConfirmVerdict(null)}
              disabled={deciding}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={confirmVerdict === "approved" ? "primary" : "danger"}
              loading={deciding}
              onClick={() =>
                confirmVerdict !== null && decide(confirmVerdict)
              }
            >
              Confirm {confirmVerdict === "approved" ? "approval" : "rejection"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-text-2">
          {confirmVerdict === "approved"
            ? "Approving mints a single-use execution grant for this tool call. It does not execute the tool."
            : "Rejecting permanently blocks this tool call."}
        </p>
        <div className="mt-3">
          <Input
            id="decision-reason"
            label="Reason (optional)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="reviewer note"
            maxLength={256}
          />
        </div>
      </Dialog>
    </div>
  );
}

export default function ApprovalsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-16">
          <Spinner label="Loading…" />
        </div>
      }
    >
      <ApprovalsContent />
    </Suspense>
  );
}
