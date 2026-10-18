"use client";

import type { ReactNode } from "react";
import {
  IconCheck,
  IconClock,
  IconCross,
  IconDot,
  IconInfo,
} from "@/components/icons";

/**
 * Badge — a status pill. Status is ALWAYS icon + text label; color is never
 * the only signal (see docs/DESIGN_TOKENS.md).
 *
 * Props:
 * - variant: "allow" | "deny" | "review" | "info" | "neutral"
 * - children: the text label (required — e.g. "Allowed", "Denied")
 * - icon: optional override for the default per-variant icon
 * - className: extra classes
 */
export type BadgeVariant = "allow" | "deny" | "review" | "info" | "neutral";

export interface BadgeProps {
  variant: BadgeVariant;
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
}

const DEFAULT_ICONS: Record<BadgeVariant, ReactNode> = {
  allow: <IconCheck width={12} height={12} />,
  deny: <IconCross width={12} height={12} />,
  review: <IconClock width={12} height={12} />,
  info: <IconInfo width={12} height={12} />,
  neutral: <IconDot width={12} height={12} />,
};

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  allow: "bg-allow-bg text-allow-text border-allow-border",
  deny: "bg-deny-bg text-deny-text border-deny-border",
  review: "bg-review-bg text-review-text border-review-border",
  info: "bg-info-bg text-info-text border-info-border",
  neutral: "bg-neutral-bg text-neutral-text border-neutral-border",
};

export default function Badge({
  variant,
  children,
  icon,
  className = "",
}: BadgeProps) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5",
        "text-xs font-semibold whitespace-nowrap",
        VARIANT_CLASSES[variant],
        className,
      ].join(" ")}
    >
      <span aria-hidden="true" className="inline-flex shrink-0">
        {icon ?? DEFAULT_ICONS[variant]}
      </span>
      {children}
    </span>
  );
}
