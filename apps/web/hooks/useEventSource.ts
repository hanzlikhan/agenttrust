"use client";

import { useEffect, useRef, useState } from "react";

export type StreamStatus = "live" | "reconnecting" | "offline";

export interface StreamEvent {
  event_id: string;
  kind: string;
  project_id: string;
  run_id: string | null;
  project_seq: number;
  received_at: string;
  payload: unknown;
}

interface UseEventSourceOptions {
  /** Stream URL WITHOUT the cursor (api_key etc. already included). */
  url: string;
  /** Cursor to resume from on first connect. */
  initialCursor?: number;
  /** Called for every new, deduplicated event. */
  onEvent: (event: StreamEvent) => void;
  /** Set false to tear the connection down. */
  enabled?: boolean;
}

const MAX_BACKOFF_MS = 30000;
// After this many consecutive failures with no successful open, stop
// retrying: a revoked/invalid key would otherwise show "Reconnecting"
// forever (Phase 8 audit M4). EventSource does not expose the HTTP status,
// so we use "never opened" as the signal.
const MAX_FAILED_ATTEMPTS = 5;
// Bound the at-least-once dedup set: entries at or below the confirmed
// cursor can never be redelivered as new (the server only sends
// project_seq > cursor), so they are safe to forget.
const MAX_SEEN_IDS = 5000;

function isStreamEvent(value: unknown): value is StreamEvent {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.event_id === "string" &&
    typeof v.kind === "string" &&
    typeof v.project_seq === "number"
  );
}

/**
 * Browser EventSource wrapper for the AgentTrust SSE stream.
 *
 * - Resumes with ?cursor= (a fresh EventSource does not resend
 *   Last-Event-ID, so the hook tracks the cursor itself).
 * - Deduplicates by event_id (delivery is at-least-once).
 * - Reconnects with exponential backoff and reports
 *   live / reconnecting / offline status.
 */
export function useEventSource({
  url,
  initialCursor = 0,
  onEvent,
  enabled = true,
}: UseEventSourceOptions): { status: StreamStatus; lastSync: string | null } {
  const [status, setStatus] = useState<StreamStatus>(enabled ? "reconnecting" : "offline");
  const [lastSync, setLastSync] = useState<string | null>(null);

  const cursorRef = useRef<number>(initialCursor);
  const seenRef = useRef<Set<string>>(new Set());
  const attemptRef = useRef<number>(0);
  const everOpenedRef = useRef<boolean>(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!enabled || url === "") {
      setStatus("offline");
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let source: EventSource | null = null;

    const connect = () => {
      if (cancelled) return;
      setStatus("reconnecting");
      const separator = url.includes("?") ? "&" : "?";
      source = new EventSource(`${url}${separator}cursor=${cursorRef.current}`);

      source.onopen = () => {
        if (cancelled) return;
        attemptRef.current = 0;
        everOpenedRef.current = true;
        setStatus("live");
        setLastSync(new Date().toISOString());
      };

      source.onmessage = (message: MessageEvent) => {
        if (cancelled) return;
        let parsed: unknown;
        try {
          parsed = JSON.parse(message.data);
        } catch {
          return; // ignore malformed frames; the stream continues
        }
        if (!isStreamEvent(parsed)) return;
        if (seenRef.current.has(parsed.event_id)) return; // at-least-once dedup
        seenRef.current.add(parsed.event_id);
        if (seenRef.current.size > MAX_SEEN_IDS) {
          // Forget the oldest entries; the cursor (below) still guards
          // redelivery of anything at or below it.
          const ids = seenRef.current.values();
          for (let i = 0; i < MAX_SEEN_IDS / 2; i++) {
            const next = ids.next();
            if (next.done) break;
            seenRef.current.delete(next.value);
          }
        }
        if (parsed.project_seq > cursorRef.current) {
          cursorRef.current = parsed.project_seq;
        }
        setLastSync(new Date().toISOString());
        onEventRef.current(parsed);
      };

      source.onerror = () => {
        if (cancelled) return;
        source?.close();
        source = null;
        attemptRef.current += 1;
        if (!everOpenedRef.current && attemptRef.current >= MAX_FAILED_ATTEMPTS) {
          // Never managed to open the stream: likely a bad/revoked key.
          // Stop retrying and surface offline with guidance.
          setStatus("offline");
          return;
        }
        setStatus("reconnecting");
        const backoff = Math.min(1000 * 2 ** attemptRef.current, MAX_BACKOFF_MS);
        timer = setTimeout(connect, backoff);
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
      source?.close();
    };
    // `onEvent` is intentionally read through a ref so the connection is
    // not torn down when the parent re-renders.
  }, [url, enabled]);

  return { status, lastSync };
}
