"use client";

import type { ReactNode } from "react";

/**
 * EmptyState — centered placeholder for "nothing here yet".
 *
 * Props:
 * - icon: decorative glyph (aria-hidden by the caller or wrapped here)
 * - title: headline (required)
 * - description: supporting text
 * - action: call-to-action slot (e.g. a Button)
 */
export interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export default function EmptyState({
  icon,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      {icon !== undefined && (
        <span aria-hidden="true" className="text-text-3">
          {icon}
        </span>
      )}
      <p className="text-sm font-semibold text-text-1">{title}</p>
      {description !== undefined && (
        <p className="max-w-sm text-sm text-text-2">{description}</p>
      )}
      {action !== undefined && <div className="mt-2">{action}</div>}
    </div>
  );
}
