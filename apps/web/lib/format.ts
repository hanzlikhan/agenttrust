/**
 * Pure formatting helpers. No I/O, no secrets, no locale assumptions beyond
 * the browser defaults.
 */

/**
 * Format integer minor units as a decimal amount, e.g. 10000 / "USD" ->
 * "100.00 USD". Returns an em dash when either argument is missing.
 */
export function formatMoney(
  minor: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (minor === null || minor === undefined) return "—";
  if (currency === null || currency === undefined || currency === "") return "—";
  const sign = minor < 0 ? "-" : "";
  const abs = Math.abs(minor);
  const whole = Math.floor(abs / 100);
  const frac = String(abs % 100).padStart(2, "0");
  return `${sign}${whole}.${frac} ${currency}`;
}

/** Format an ISO timestamp as a local date-time string. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}

/** Format an ISO timestamp as a date-only string. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString();
}

/**
 * Relative time, e.g. "5m ago", "2h ago", "3d ago". Future timestamps read
 * "in Xs". Anything under 5s reads "just now".
 */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const deltaMs = Date.now() - then;
  const future = deltaMs < 0;
  const abs = Math.abs(deltaMs);
  if (abs < 5000) return "just now";
  const s = Math.floor(abs / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  const unit =
    d > 0 ? `${d}d` : h > 0 ? `${h}h` : m > 0 ? `${m}m` : `${s}s`;
  return future ? `in ${unit}` : `${unit} ago`;
}

/**
 * Human duration for a millisecond span, e.g. 90000 -> "1m 30s".
 * Negative or non-finite input returns an em dash.
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0)
    return "—";
  const totalS = Math.floor(ms / 1000);
  const s = totalS % 60;
  const m = Math.floor(totalS / 60) % 60;
  const h = Math.floor(totalS / 3600);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
