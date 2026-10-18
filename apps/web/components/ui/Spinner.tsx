"use client";

/**
 * Spinner — an indeterminate progress indicator.
 *
 * Props:
 * - size: "sm" | "md" | "lg" (default "md")
 * - label: accessible name (default "Loading"); the spinner announces
 *   itself as a status region.
 */
export type SpinnerSize = "sm" | "md" | "lg";

export interface SpinnerProps {
  size?: SpinnerSize;
  label?: string;
}

const SIZE_PX: Record<SpinnerSize, number> = { sm: 14, md: 20, lg: 32 };

export default function Spinner({ size = "md", label = "Loading" }: SpinnerProps) {
  const px = SIZE_PX[size];
  return (
    <svg
      role="status"
      aria-label={label}
      className="animate-spin text-text-3"
      width={px}
      height={px}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="3"
      />
      <path
        d="M21 12a9 9 0 00-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
