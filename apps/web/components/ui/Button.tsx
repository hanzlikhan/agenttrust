"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * Button — the single interactive button for the dashboard.
 *
 * Props:
 * - variant: "primary" | "secondary" | "danger" | "ghost" (default "secondary")
 * - size: "sm" | "md" (default "md")
 * - loading: shows an inline spinner, sets aria-busy, and disables the button
 * - disabled: standard disabled state
 * - All native <button> props (type, onClick, aria-label, ...) pass through.
 */
export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children: ReactNode;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-brand text-brand-text border border-transparent hover:bg-brand-hover",
  secondary:
    "bg-surface-2 text-text-1 border border-border hover:bg-surface hover:border-text-3",
  danger:
    "bg-deny-bg text-deny-text border border-deny-border hover:brightness-95 dark:hover:brightness-125",
  ghost:
    "bg-transparent text-text-2 border border-transparent hover:text-text-1 hover:bg-surface-2",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "text-xs px-2.5 py-1.5 gap-1.5",
  md: "text-sm px-4 py-2 gap-2",
};

export default function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  disabled,
  children,
  type = "button",
  className = "",
  ...rest
}: ButtonProps) {
  const isDisabled = disabled === true || loading;
  return (
    <button
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={[
        "inline-flex items-center justify-center rounded-md font-semibold",
        "transition-colors select-none",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      ].join(" ")}
      {...rest}
    >
      {loading && (
        <svg
          className="animate-spin"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
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
      )}
      {children}
    </button>
  );
}
