"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, useDashboardKey } from "@/lib/api";
import { useAdminToken } from "@/lib/admin";
import { formatDateTime } from "@/lib/format";
import RequireDashboardKey from "@/components/RequireDashboardKey";
import PageHeader from "@/components/PageHeader";
import AdminTokenCard from "@/components/AdminTokenCard";
import { OutcomeBadge } from "@/components/badges";
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

interface PolicyVersion {
  id: string;
  version: number;
  rules_json: Record<string, unknown>;
  created_by: string;
  activated_at: string | null;
  created_at: string;
}

interface Policy {
  id: string;
  project_id: string;
  name: string;
  active_version_id: string | null;
  versions: PolicyVersion[];
  created_at: string;
}

interface SimulateResult {
  outcome: "ALLOW" | "DENY" | "REVIEW";
  reason_code: string;
  policy_version: number | null;
  evaluated_with_draft: boolean;
  explanation: string;
}

const TEXTAREA_CLASSES = [
  "rounded-md border border-border bg-surface px-3 py-2 font-mono text-sm text-text-1",
  "placeholder:text-text-3",
  "focus:outline-none focus:ring-2 focus:ring-brand",
].join(" ");

function parseJsonObject(raw: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (trimmed === "") return { ok: false, error: "JSON is required." };
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { ok: false, error: "JSON must be an object." };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? `Invalid JSON: ${err.message}` : "Invalid JSON.",
    };
  }
}

function PoliciesContent() {
  const [key] = useDashboardKey();
  const [adminToken] = useAdminToken();
  const [projectId, setProjectId] = useState<string | null>(null);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Activate dialog
  const [activating, setActivating] = useState<Policy | null>(null);
  const [activatingBusy, setActivatingBusy] = useState(false);

  // New policy form
  const [newName, setNewName] = useState("");
  const [newRules, setNewRules] = useState("");
  const [newError, setNewError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  // Simulate form
  const [simTool, setSimTool] = useState("");
  const [simArgs, setSimArgs] = useState("");
  const [simError, setSimError] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [simResult, setSimResult] = useState<SimulateResult | null>(null);

  useEffect(() => {
    document.title = "Policies · AgentTrust";
  }, []);

  const fetchPolicies = useCallback(async () => {
    if (key === null) return;
    setLoading(true);
    setError(null);
    try {
      const [me, list] = await Promise.all([
        apiFetch<{ project_id: string }>("/api/v1/me", key),
        apiFetch<{ policies: Policy[] }>("/api/v1/policies", key),
      ]);
      setProjectId(me.project_id);
      setPolicies(list.policies);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load policies.");
    } finally {
      setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    fetchPolicies();
  }, [fetchPolicies]);

  const activatePolicy = useCallback(async () => {
    if (activating === null || adminToken === null) return;
    setActivatingBusy(true);
    try {
      // The API activates the policy's latest draft version; there is no
      // version selector on the endpoint.
      await apiFetch(`/api/v1/policies/${activating.id}/activate`, adminToken, {
        method: "POST",
      });
      setNotice(`Policy "${activating.name}" activated.`);
      setActivating(null);
      fetchPolicies();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Activation failed.");
    } finally {
      setActivatingBusy(false);
    }
  }, [activating, adminToken, fetchPolicies]);

  const createPolicy = useCallback(async () => {
    if (adminToken === null || projectId === null) return;
    setNewError(null);
    if (newName.trim() === "") {
      setNewError("Policy name is required.");
      return;
    }
    const parsed = parseJsonObject(newRules);
    if (!parsed.ok) {
      setNewError(parsed.error);
      return;
    }
    setCreating(true);
    try {
      await apiFetch("/api/v1/policies", adminToken, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          name: newName.trim(),
          rules_json: parsed.value,
        }),
      });
      setNotice(`Draft policy "${newName.trim()}" created.`);
      setNewName("");
      setNewRules("");
      fetchPolicies();
    } catch (err) {
      setNewError(err instanceof Error ? err.message : "Creation failed.");
    } finally {
      setCreating(false);
    }
  }, [adminToken, projectId, newName, newRules, fetchPolicies]);

  const simulate = useCallback(async () => {
    if (adminToken === null || projectId === null) return;
    setSimError(null);
    setSimResult(null);
    if (simTool.trim() === "") {
      setSimError("Tool name is required.");
      return;
    }
    const parsed = parseJsonObject(simArgs);
    if (!parsed.ok) {
      setSimError(parsed.error);
      return;
    }
    setSimulating(true);
    try {
      const body = await apiFetch<SimulateResult>(
        "/api/v1/policies/simulate",
        adminToken,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            tool_name: simTool.trim(),
            arguments: parsed.value,
          }),
        },
      );
      setSimResult(body);
    } catch (err) {
      setSimError(err instanceof Error ? err.message : "Simulation failed.");
    } finally {
      setSimulating(false);
    }
  }, [adminToken, projectId, simTool, simArgs]);

  const activatingVersion =
    activating !== null && activating.versions.length > 0
      ? Math.max(...activating.versions.map((v) => v.version))
      : null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Policies"
        description="Policy versions, activation, and dry-run simulation. Creating, activating, and simulating require the dev-only admin token."
      />

      {notice !== null && (
        <p role="status" className="text-sm text-text-2">
          {notice}
        </p>
      )}

      <AdminTokenCard />

      <div>
        <h2 className="mb-3 text-lg font-semibold text-text-1">Policies</h2>
        {loading ? (
          <div className="flex justify-center py-10">
            <Spinner label="Loading policies…" />
          </div>
        ) : error !== null ? (
          <div role="alert" className="rounded-lg border border-deny-border bg-deny-bg p-4">
            <p className="text-sm font-medium text-deny-text">{error}</p>
            <div className="mt-3">
              <Button type="button" variant="secondary" size="sm" onClick={fetchPolicies}>
                Retry
              </Button>
            </div>
          </div>
        ) : policies.length === 0 ? (
          <EmptyState
            title="No policies yet"
            description="Create a draft policy below, then activate it."
          />
        ) : (
          <div className="flex flex-col gap-4">
            {policies.map((policy) => {
              const latestVersion =
                policy.versions.length > 0
                  ? Math.max(...policy.versions.map((v) => v.version))
                  : null;
              return (
                <Card
                  key={policy.id}
                  title={policy.name}
                  description={`Created ${formatDateTime(policy.created_at)} · ${
                    policy.active_version_id !== null
                      ? `active version ${
                          policy.versions.find((v) => v.id === policy.active_version_id)
                            ?.version ?? "?"
                        }`
                      : "no active version"
                  }`}
                >
                  <DataTable<PolicyVersion>
                    columns={[
                      {
                        key: "version",
                        header: "Version",
                        render: (v) => (
                          <span className="font-mono tabular-nums">v{v.version}</span>
                        ),
                      },
                      {
                        key: "created",
                        header: "Created",
                        render: (v) => (
                          <span className="whitespace-nowrap text-text-2">
                            {formatDateTime(v.created_at)}
                          </span>
                        ),
                      },
                      {
                        key: "status",
                        header: "Status",
                        render: (v) =>
                          v.id === policy.active_version_id ? (
                            <Badge variant="allow">Active</Badge>
                          ) : (
                            <Badge variant="neutral">Draft</Badge>
                          ),
                      },
                      {
                        key: "action",
                        header: "Action",
                        render: (v) =>
                          v.version === latestVersion &&
                          v.id !== policy.active_version_id ? (
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              disabled={adminToken === null}
                              title={
                                adminToken === null
                                  ? "Set the admin token to activate"
                                  : "Activate this draft version"
                              }
                              onClick={() => setActivating(policy)}
                            >
                              Activate
                            </Button>
                          ) : (
                            <span className="text-xs text-text-3">—</span>
                          ),
                      },
                    ]}
                    rows={[...policy.versions].sort((a, b) => a.version - b.version)}
                    rowKey={(v) => v.id}
                    caption={`Versions of policy ${policy.name}`}
                    page={0}
                    pageSize={Math.max(policy.versions.length, 1)}
                    total={policy.versions.length}
                    onPageChange={() => {}}
                  />
                </Card>
              );
            })}
          </div>
        )}
      </div>

      <Card
        title="New policy"
        description="Creates a draft version. Activate it from the list above when ready."
      >
        {adminToken === null ? (
          <p className="text-sm text-text-3">
            Set the dev-only admin token above to create policies.
          </p>
        ) : (
          <div className="flex max-w-2xl flex-col gap-3">
            <Input
              id="new-policy-name"
              label="Policy name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="refund-policy"
              maxLength={128}
            />
            <div className="flex flex-col gap-1.5">
              <label htmlFor="new-policy-rules" className="text-sm font-medium text-text-1">
                Rules JSON
              </label>
              <textarea
                id="new-policy-rules"
                rows={8}
                value={newRules}
                onChange={(e) => setNewRules(e.target.value)}
                placeholder='{"tool_name": "refund_payment", "currency": "USD", "auto_approve_max_minor": 10000, "review_max_minor": 50000}'
                className={TEXTAREA_CLASSES}
                aria-describedby="new-policy-rules-description"
              />
              <p id="new-policy-rules-description" className="text-xs text-text-3">
                Validated against the refund policy config schema on receipt.
              </p>
            </div>
            {newError !== null && (
              <p role="alert" className="text-sm font-medium text-deny-text">
                {newError}
              </p>
            )}
            <div>
              <Button
                type="button"
                variant="primary"
                loading={creating}
                onClick={createPolicy}
              >
                Create draft policy
              </Button>
            </div>
          </div>
        )}
      </Card>

      <Card
        title="Simulate"
        description="Preview the decision a policy version would make for a tool call. Writes nothing to the database."
      >
        {adminToken === null ? (
          <p className="text-sm text-text-3">
            Set the dev-only admin token above to run simulations.
          </p>
        ) : (
          <div className="flex max-w-2xl flex-col gap-3">
            <p className="text-sm text-text-3">
              Simulates against this project&apos;s latest policy version
              (including an unactivated draft, so you can preview before
              activating).
            </p>
            <Input
              id="simulate-tool"
              label="Tool name"
              value={simTool}
              onChange={(e) => setSimTool(e.target.value)}
              placeholder="refund_payment"
              maxLength={128}
            />
            <div className="flex flex-col gap-1.5">
              <label htmlFor="simulate-args" className="text-sm font-medium text-text-1">
                Arguments JSON
              </label>
              <textarea
                id="simulate-args"
                rows={5}
                value={simArgs}
                onChange={(e) => setSimArgs(e.target.value)}
                placeholder='{"order_id": "ORD-100", "amount_minor": 4000, "currency": "USD"}'
                className={TEXTAREA_CLASSES}
              />
            </div>
            {simError !== null && (
              <p role="alert" className="text-sm font-medium text-deny-text">
                {simError}
              </p>
            )}
            <div>
              <Button
                type="button"
                variant="primary"
                loading={simulating}
                onClick={simulate}
              >
                Simulate
              </Button>
            </div>

            {simResult !== null && (
              <div
                role="status"
                className="rounded-md border border-border bg-surface-2 p-4"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <OutcomeBadge outcome={simResult.outcome} />
                  <span className="text-sm text-text-2">
                    This is the decision the policy would make (dry run).
                  </span>
                  <span className="font-mono text-xs text-text-3">
                    {simResult.reason_code}
                  </span>
                </div>
                <p className="mt-2 text-sm text-text-2">{simResult.explanation}</p>
                <p className="mt-2 text-xs text-text-3">
                  Policy version:{" "}
                  {simResult.policy_version !== null
                    ? `v${simResult.policy_version}`
                    : "none"}
                  {simResult.evaluated_with_draft &&
                    " · evaluated with the latest draft version (not yet active)"}
                </p>
              </div>
            )}
          </div>
        )}
      </Card>

      <Dialog
        open={activating !== null}
        onClose={() => setActivating(null)}
        title="Activate policy version?"
        actions={
          <>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setActivating(null)}
              disabled={activatingBusy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              loading={activatingBusy}
              onClick={activatePolicy}
            >
              Activate
            </Button>
          </>
        }
      >
        <p className="text-sm text-text-2">
          Activate draft version{" "}
          <span className="font-mono">v{activatingVersion ?? "?"}</span> of policy{" "}
          <span className="font-medium text-text-1">{activating?.name}</span>?
          The policy will evaluate against the new rules immediately. Activated
          versions are never mutated.
        </p>
      </Dialog>
    </div>
  );
}

export default function PoliciesPage() {
  return (
    <RequireDashboardKey>
      <PoliciesContent />
    </RequireDashboardKey>
  );
}
