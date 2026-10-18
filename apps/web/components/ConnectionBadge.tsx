"use client";

import type { StreamStatus } from "@/hooks/useEventSource";

/**
 * ConnectionBadge — stream connection status for the SSE dashboard stream.
 *
 * Props (unchanged from the CSS-modules version):
 * - status: "live" | "reconnecting" | "offline"
 * - lastSync: ISO timestamp of the last received event, or null
 *
 * Status is always an icon (dot) + text label, never color alone.
 */
const LABEL: Record<StreamStatus, string> = {
  live: "Live",
  reconnecting: "Reconnecting",
  offline: "Offline",
};

const VARIANT_CLASSES: Record<StreamStatus, string> = {
  live: "border-allow-border bg-allow-bg text-allow-text",
  reconnecting: "border-review-border bg-review-bg text-review-text",
  offline: "border-deny-border bg-deny-bg text-deny-text",
};

const DOT_CLASSES: Record<StreamStatus, string> = {
  live: "bg-allow-text",
  reconnecting: "bg-review-text animate-pulse",
  offline: "bg-deny-text",
};

export default function ConnectionBadge({
  status,
  lastSync,
}: {
  status: StreamStatus;
  lastSync: string | null;
}) {
  return (
    <span
      className={[
        "inline-flex items-center gap-2 rounded-full border px-3 py-1",
        "text-xs font-semibold",
        VARIANT_CLASSES[status],
      ].join(" ")}
      role="status"
      aria-label={`Stream status: ${LABEL[status]}`}
      title={lastSync ? `Last sync: ${lastSync}` : "No events received yet"}
    >
      <span
        aria-hidden="true"
        className={`inline-block h-2 w-2 rounded-full ${DOT_CLASSES[status]}`}
      />
      {LABEL[status]}
    </span>
  );
}
