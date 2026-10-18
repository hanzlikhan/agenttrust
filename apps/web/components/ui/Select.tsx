"use client";

import type { ReactNode, SelectHTMLAttributes } from "react";

/**
 * Select — a labeled native select with optional help text and error.
 *
 * Props:
 * - label: visible label text (required)
 * - id: required so the label is programmatically associated
 * - options: [{ value, label }] rendered as <option> elements
 * - description: help text rendered under the select
 * - error: error text; when set, the select gets aria-invalid and the error
 *   is exposed via aria-describedby with role="alert"
 * - All native <select> props (value, onChange, disabled, ...) pass through.
 */
export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: ReactNode;
  id: string;
  options: SelectOption[];
  description?: ReactNode;
  error?: string | null;
}

export default function Select({
  label,
  id,
  options,
  description,
  error,
  className = "",
  ...rest
}: SelectProps) {
  const descriptionId = description ? `${id}-description` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [descriptionId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-text-1">
        {label}
      </label>
      <select
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={[
          "rounded-md border bg-surface px-3 py-2 text-sm text-text-1",
          error ? "border-deny-border" : "border-border",
          className,
        ].join(" ")}
        {...rest}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
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
