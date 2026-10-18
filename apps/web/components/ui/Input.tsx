"use client";

import type { InputHTMLAttributes, ReactNode } from "react";

/**
 * Input — a labeled text input with optional help text and error.
 *
 * Props:
 * - label: visible label text (required)
 * - id: required so the label is programmatically associated
 * - description: help text rendered under the input
 * - error: error text; when set, the input gets aria-invalid and the error
 *   is exposed via aria-describedby with role="alert"
 * - All native <input> props (type, value, onChange, placeholder, ...) pass through.
 */
export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: ReactNode;
  id: string;
  description?: ReactNode;
  error?: string | null;
}

export default function Input({
  label,
  id,
  description,
  error,
  className = "",
  ...rest
}: InputProps) {
  const descriptionId = description ? `${id}-description` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [descriptionId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-text-1">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={[
          "rounded-md border bg-surface px-3 py-2 text-sm text-text-1",
          "placeholder:text-text-3",
          error ? "border-deny-border" : "border-border",
          className,
        ].join(" ")}
        {...rest}
      />
      {description && (
        <p id={descriptionId} className="text-xs text-text-3">
          {description}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-xs font-medium text-deny-text">
          {error}
        </p>
      )}
    </div>
  );
}
