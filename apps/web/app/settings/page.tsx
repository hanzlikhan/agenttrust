"use client";

import { useCallback, useEffect, useState } from "react";
import {
  API_BASE,
  apiFetch,
  useDashboardKey,
} from "@/lib/api";
import { useAdminToken } from "@/lib/admin";
import { formatDateTime } from "@/lib/format";
import PageHeader from "@/components/PageHeader";
import AdminTokenCard from "@/components/AdminTokenCard";
import { StateBadge } from "@/components/badges";
import {
  Badge,
  Button,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  Input,
  Spinner,
} from "@/components/ui";

const ENV_LABEL = process.env.NEXT_PUBLIC_ENV_LABEL ?? "Local demo";

const SCOPES = [
  "agent:run",
  "agent:authorize",
  "agent:execute",
  "approvals:read",
  "approvals:decide",
  // Phase 8 audit C2: without these, no key issued through this UI can
  // ever list incidents or evaluation runs (both pages 403).
  "incidents:read",
  "evaluations:read",
];

const SDK_SNIPPET = `# Install (from the repo root)
pip install -e packages/agenttrust-python

# Use
from agenttrust import AgentTrust

trust = AgentTrust(api_key="YOUR_API_KEY", base_url="http://localhost:8000")

@trust.protect(tool="refund_payment")
def refund_payment(order_id: str, amount_minor: int, currency: str = "USD"):
    # NOTE: this body is never executed by the SDK. The real side effect
    # happens server-side in the trusted gateway after authorization.
    raise NotImplementedError

with trust.run(agent="refund-support-agent", version="0.1.0"):
    refund_payment(order_id="ORD-100", amount_minor=4000)`;

interface ApiKeyItem {
  id: string;
  project_id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

interface IssuedKey {
  id: string;
  name: string;
  key_prefix: string;
  api_key: string;
  scopes: string[];
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [text]);
  return (
    <Button type="button" variant="secondary" size="sm" onClick={copy}>
      {copied ? "Copied ✓" : label}
    </Button>
  );
}

function DashboardKeyCard() {
  const [key, saveKey, forgetKey] = useDashboardKey();
  const [input, setInput] = useState("");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const save = () => {
    const trimmed = input.trim();
    if (trimmed === "") return;
    saveKey(trimmed);
    setInput("");
  };

  return (
    <Card
      title="Dashboard API key"
      description="Read-only key for the dashboard. Stored in sessionStorage (this tab only); drives the stream badge in the header."
    >
      {!mounted || key === null ? (
        <form
          className="flex max-w-md flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <Input
            id="dashboard-key"
            label="Dashboard API key"
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="at_…"
            autoComplete="off"
            description="Needs dashboard read access. Never use a privileged key here."
          />
          <div>
            <Button type="submit" variant="primary" disabled={input.trim() === ""}>
              Connect
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="allow">Connected</Badge>
          <code className="font-mono text-sm text-text-2">
            {key.slice(0, 8)}…
          </code>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={forgetKey}
          >
            Disconnect
          </Button>
        </div>
      )}
    </Card>
  );
}

function KeyManagementCard() {
  const [dashboardKey] = useDashboardKey();
  const [adminToken] = useAdminToken();
  const [projectId, setProjectId] = useState<string | null>(null);
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["agent:run"]);
  const [issuing, setIssuing] = useState(false);
  const [issueError, setIssueError] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedKey | null>(null);

  const [revoking, setRevoking] = useState<ApiKeyItem | null>(null);
  const [revokingBusy, setRevokingBusy] = useState(false);

  const fetchKeys = useCallback(async () => {
    if (adminToken === null) return;
    setLoading(true);
    setError(null);
    try {
      const body = await apiFetch<{ keys: ApiKeyItem[] }>(
        "/api/v1/keys?limit=100",
        adminToken,
      );
      setKeys(body.keys);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load keys.");
    } finally {
      setLoading(false);
    }
  }, [adminToken]);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  useEffect(() => {
    if (dashboardKey === null) {
      setProjectId(null);
      return;
    }
    apiFetch<{ project_id: string }>("/api/v1/me", dashboardKey)
      .then((me) => setProjectId(me.project_id))
      .catch(() => setProjectId(null));
  }, [dashboardKey]);

  const toggleScope = (scope: string) => {
    setScopes((prev) =>
      prev.includes(scope)
        ? prev.filter((s) => s !== scope)
        : [...prev, scope],
    );
  };

  const issueKey = useCallback(async () => {
    if (adminToken === null || projectId === null) return;
    setIssueError(null);
    setIssued(null);
    if (name.trim() === "") {
      setIssueError("Key name is required.");
      return;
    }
    if (scopes.length === 0) {
      setIssueError("Select at least one scope.");
      return;
    }
    setIssuing(true);
    try {
      const body = await apiFetch<IssuedKey>("/api/v1/keys", adminToken, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          name: name.trim(),
          scopes,
        }),
      });
      setIssued(body);
      setName("");
      fetchKeys();
    } catch (err) {
      setIssueError(err instanceof Error ? err.message : "Issuance failed.");
    } finally {
      setIssuing(false);
    }
  }, [adminToken, projectId, name, scopes, fetchKeys]);

  const revokeKey = useCallback(async () => {
    if (revoking === null || adminToken === null) return;
    setRevokingBusy(true);
    try {
      await apiFetch(`/api/v1/keys/${revoking.id}/revoke`, adminToken, {
        method: "POST",
      });
      setRevoking(null);
      fetchKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revocation failed.");
    } finally {
      setRevokingBusy(false);
    }
  }, [revoking, adminToken, fetchKeys]);

  const keyState = (item: ApiKeyItem): "active" | "revoked" | "expired" => {
    if (item.revoked_at !== null) return "revoked";
    if (
      item.expires_at !== null &&
      new Date(item.expires_at).getTime() <= Date.now()
    )
      return "expired";
    return "active";
  };

  return (
    <Card
      title="API key management"
      description="Issue and revoke project API keys. Requires the dev-only admin token; secrets are redacted by the API after issuance."
    >
      <div className="flex flex-col gap-6">
        <AdminTokenCard description="Dev only: gates key issuance, listing, and revocation. Kept in sessionStorage." />

        {adminToken === null ? (
          <p className="text-sm text-text-3">
            Set the dev-only admin token above to manage API keys.
          </p>
        ) : (
          <>
            <div>
              <h3 className="mb-2 text-sm font-semibold text-text-1">Issue a key</h3>
              {projectId === null ? (
                <p className="text-sm text-text-3">
                  Connect a dashboard API key above first — the project id comes
                  from it.
                </p>
              ) : (
                <div className="flex max-w-2xl flex-col gap-3">
                  <Input
                    id="issue-key-name"
                    label="Key name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="ci-runner"
                    maxLength={128}
                  />
                  <fieldset>
                    <legend className="text-sm font-medium text-text-1">Scopes</legend>
                    <div className="mt-1.5 flex flex-wrap gap-3">
                      {SCOPES.map((scope) => (
                        <label
                          key={scope}
                          className="flex items-center gap-1.5 text-sm text-text-2"
                        >
                          <input
                            type="checkbox"
                            checked={scopes.includes(scope)}
                            onChange={() => toggleScope(scope)}
                            className="h-4 w-4 accent-[var(--at-brand)]"
                          />
                          <code className="font-mono text-xs">{scope}</code>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                  {issueError !== null && (
                    <p role="alert" className="text-sm font-medium text-deny-text">
                      {issueError}
                    </p>
                  )}
                  <div>
                    <Button
                      type="button"
                      variant="primary"
                      loading={issuing}
                      onClick={issueKey}
                    >
                      Issue key
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {issued !== null && (
              <div
                role="alert"
                className="rounded-md border border-review-border bg-review-bg p-4"
              >
                <p className="text-sm font-semibold text-review-text">
                  Key issued — copy it now. It will never be shown again.
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <code className="break-all rounded bg-surface px-2 py-1 font-mono text-sm text-text-1">
                    {issued.api_key}
                  </code>
                  <CopyButton text={issued.api_key} label="Copy secret" />
                </div>
                <p className="mt-1 text-xs text-text-3">
                  {issued.name} · prefix {issued.key_prefix} · scopes{" "}
                  {issued.scopes.join(", ")}
                </p>
              </div>
            )}

            <div>
              <h3 className="mb-2 text-sm font-semibold text-text-1">Issued keys</h3>
              {loading ? (
                <div className="flex justify-center py-6">
                  <Spinner label="Loading keys…" />
                </div>
              ) : error !== null ? (
                <p role="alert" className="text-sm font-medium text-deny-text">
                  {error}
                </p>
              ) : (
                <DataTable<ApiKeyItem>
                  columns={[
                    {
                      key: "name",
                      header: "Name",
                      render: (item) => (
                        <span className="font-medium">{item.name || "(unnamed)"}</span>
                      ),
                    },
                    {
                      key: "prefix",
                      header: "Prefix",
                      render: (item) => (
                        <code className="font-mono text-xs text-text-2">
                          {item.key_prefix}…
                        </code>
                      ),
                    },
                    {
                      key: "scopes",
                      header: "Scopes",
                      render: (item) => (
                        <span className="flex flex-wrap gap-1">
                          {item.scopes.map((s) => (
                            <Badge key={s} variant="neutral">
                              {s}
                            </Badge>
                          ))}
                        </span>
                      ),
                    },
                    {
                      key: "created",
                      header: "Created",
                      render: (item) => (
                        <span className="whitespace-nowrap text-text-2">
                          {formatDateTime(item.created_at)}
                        </span>
                      ),
                    },
                    {
                      key: "expires",
                      header: "Expires",
                      render: (item) => (
                        <span className="whitespace-nowrap text-text-2">
                          {formatDateTime(item.expires_at)}
                        </span>
                      ),
                    },
                    {
                      key: "state",
                      header: "State",
                      render: (item) => <StateBadge state={keyState(item)} />,
                    },
                    {
                      key: "action",
                      header: "Action",
                      render: (item) =>
                        keyState(item) === "active" ? (
                          <Button
                            type="button"
                            variant="danger"
                            size="sm"
                            onClick={() => setRevoking(item)}
                          >
                            Revoke
                          </Button>
                        ) : (
                          <span className="text-xs text-text-3">—</span>
                        ),
                    },
                  ]}
                  rows={keys}
                  rowKey={(item) => item.id}
                  caption="Issued API keys"
                  page={0}
                  pageSize={Math.max(keys.length, 1)}
                  total={keys.length}
                  onPageChange={() => {}}
                  empty={
                    <EmptyState
                      title="No keys issued"
                      description="Issue a key above to get started."
                    />
                  }
                />
              )}
            </div>
          </>
        )}
      </div>

      <Dialog
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        title="Revoke this key?"
        actions={
          <>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setRevoking(null)}
              disabled={revokingBusy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="danger"
              loading={revokingBusy}
              onClick={revokeKey}
            >
              Revoke permanently
            </Button>
          </>
        }
      >
        <p className="text-sm text-text-2">
          Revoke the key{" "}
          <span className="font-medium text-text-1">
            {revoking?.name || "(unnamed)"}
          </span>{" "}
          <span className="font-mono text-xs text-text-3">
            ({revoking?.key_prefix}…)
          </span>
          ? Revoked keys are rejected on next use. This cannot be undone.
        </p>
      </Dialog>
    </Card>
  );
}

function HealthCard() {
  const [live, setLive] = useState<{ status: string; timestamp?: string } | null>(
    null,
  );
  const [ready, setReady] = useState<{
    status: string;
    database: string;
    timestamp?: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const check = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [liveRes, readyRes] = await Promise.all([
        fetch(`${API_BASE}/health/live`, { cache: "no-store" }),
        fetch(`${API_BASE}/health/ready`, { cache: "no-store" }),
      ]);
      if (!liveRes.ok) throw new Error(`live: HTTP ${liveRes.status}`);
      if (!readyRes.ok) throw new Error(`ready: HTTP ${readyRes.status}`);
      setLive(await liveRes.json());
      setReady(await readyRes.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Health check failed.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  return (
    <Card
      title="Connection health"
      description="Liveness and readiness of the configured API."
      actions={
        <Button type="button" variant="secondary" size="sm" onClick={check}>
          Refresh
        </Button>
      }
    >
      {loading ? (
        <div className="flex justify-center py-6">
          <Spinner label="Checking health…" />
        </div>
      ) : error !== null ? (
        <p role="alert" className="text-sm font-medium text-deny-text">
          {error}
        </p>
      ) : (
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium text-text-3">Liveness</dt>
            <dd className="mt-1 flex items-center gap-2">
              <Badge variant={live?.status === "ok" ? "allow" : "deny"}>
                {live?.status === "ok" ? "Live" : (live?.status ?? "Down")}
              </Badge>
              {live?.timestamp !== undefined && (
                <span className="text-xs text-text-3">
                  {formatDateTime(live.timestamp)}
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Readiness</dt>
            <dd className="mt-1 flex items-center gap-2">
              <Badge variant={ready?.status === "ready" ? "allow" : "deny"}>
                {ready?.status === "ready" ? "Ready" : (ready?.status ?? "Not ready")}
              </Badge>
              {ready?.database !== undefined && (
                <span className="text-xs text-text-3">db: {ready.database}</span>
              )}
            </dd>
          </div>
        </dl>
      )}
    </Card>
  );
}

export default function SettingsPage() {
  useEffect(() => {
    document.title = "Settings · AgentTrust";
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Dashboard connection, API keys, SDK setup, and environment."
      />

      <DashboardKeyCard />

      <KeyManagementCard />

      <Card
        title="SDK setup"
        description="Install and instrument an agent with the Python SDK."
        actions={<CopyButton text={SDK_SNIPPET} label="Copy snippet" />}
      >
        <pre className="overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-xs text-text-2">
          {SDK_SNIPPET}
        </pre>
      </Card>

      <Card title="Environment" description="Read-only deployment facts.">
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium text-text-3">API base URL</dt>
            <dd className="mt-0.5 font-mono text-sm text-text-1">{API_BASE}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Environment</dt>
            <dd className="mt-0.5 text-sm text-text-1">{ENV_LABEL}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-3">Event retention</dt>
            <dd className="mt-0.5 text-sm text-text-1">
              14 days{" "}
              <span className="text-text-3">
                (AGENTTRUST_EVENT_RETENTION_DAYS documented default)
              </span>
            </dd>
          </div>
        </dl>
      </Card>

      <HealthCard />
    </div>
  );
}
