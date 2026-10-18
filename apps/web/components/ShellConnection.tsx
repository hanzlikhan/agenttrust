"use client";

import { useCallback } from "react";
import ConnectionBadge from "./ConnectionBadge";
import { API_BASE, useDashboardKey } from "@/lib/api";
import { useEventSource } from "@/hooks/useEventSource";

/**
 * ShellConnection — the header's live stream indicator.
 *
 * Uses the dashboard (read) key from sessionStorage (`agenttrust_api_key`,
 * separate from the approvals reviewer key per ADR-034). With no key set the
 * badge reads Offline and the hook never connects. The key is used only to
 * construct the EventSource URL — it is never rendered or logged.
 */
export default function ShellConnection() {
  const [key] = useDashboardKey();
  const noop = useCallback(() => {}, []);
  const url =
    key !== null
      ? `${API_BASE}/api/v1/events/stream?api_key=${encodeURIComponent(key)}`
      : "";
  const { status, lastSync } = useEventSource({
    url,
    enabled: key !== null,
    onEvent: noop,
  });

  return (
    <span
      title={
        key !== null
          ? "Dashboard stream (dashboard key)"
          : "No dashboard key set — stream offline"
      }
    >
      <ConnectionBadge status={key !== null ? status : "offline"} lastSync={lastSync} />
    </span>
  );
}
