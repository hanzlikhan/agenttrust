"use client";

/**
 * Skeleton — a content placeholder shown while data loads.
 *
 * Props:
 * - className: sizing/positioning (e.g. "h-4 w-1/2")
 * - label: accessible name; defaults to aria-hidden because a lone
 *   placeholder conveys no information. Pass a label only when the skeleton
 *   itself needs announcing (rare).
 */
export interface SkeletonProps {
  className?: string;
  label?: string;
}

export default function Skeleton({ className = "", label }: SkeletonProps) {
  return (
    <div
      aria-hidden={label === undefined ? true : undefined}
      aria-label={label}
      role={label === undefined ? undefined : "status"}
      className={`animate-pulse rounded-md bg-surface-2 ${className}`}
    />
  );
}
