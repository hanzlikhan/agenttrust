"use client";

import { useEffect, useState } from "react";
import { useAdminToken } from "@/lib/admin";
import { Button, Card, Input } from "./ui";

/**
 * Dev-only admin token entry, shared by the Policies and Settings pages.
 * The token gates admin endpoints (key issuance, policy create/activate/
 * simulate) via the Authorization header; it lives only in sessionStorage.
 */
export default function AdminTokenCard({
  description,
}: {
  description?: string;
}) {
  const [token, saveToken, clearToken] = useAdminToken();
  const [input, setInput] = useState("");
  const [mounted, setMounted] = useState(false);

  // Render the form until the hook has synced from sessionStorage.
  useEffect(() => {
    setMounted(true);
  }, []);

  const save = () => {
    const trimmed = input.trim();
    if (trimmed === "") return;
    saveToken(trimmed);
    setInput("");
  };

  return (
    <Card
      title="Admin token"
      description={
        description ??
        "Dev only: required for admin-gated actions. Kept in sessionStorage; never leaves your browser except in API calls."
      }
    >
      {!mounted || token === null ? (
        <form
          className="flex max-w-md flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <Input
            id="admin-token"
            label="Admin token"
            type="password"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="admin token value"
            autoComplete="off"
            description="Dev only. Sent as the Authorization bearer for admin endpoints."
          />
          <div>
            <Button type="submit" variant="secondary" disabled={input.trim() === ""}>
              Save admin token
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-text-2">
              Admin token set{" "}
              <span className="font-mono text-text-3">
                ({token.slice(0, 4)}&hellip;)
              </span>{" "}
              &mdash; dev only, sessionStorage.
            </p>
            <Button type="button" variant="ghost" size="sm" onClick={clearToken}>
              Disconnect
            </Button>
          </div>
          <p
            role="note"
            className="max-w-2xl rounded-md border border-review-border bg-review-bg px-3 py-2 text-xs text-review-text"
          >
            Security note: this token is a cross-project superuser credential
            held in browser sessionStorage. Use it only on a trusted local
            deployment, and disconnect it when finished. Never paste a
            production admin token here.
          </p>
        </div>
      )}
    </Card>
  );
}
