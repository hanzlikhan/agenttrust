"use client";

import type { ReactNode } from "react";

/**
 * Consistent page header: title, optional description, optional actions.
 */
export default function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-text-1">
          {title}
        </h1>
        {description !== undefined && (
          <p className="mt-1 max-w-2xl text-sm text-text-2">{description}</p>
        )}
      </div>
      {actions !== undefined && (
        <div className="flex items-center gap-2">{actions}</div>
      )}
    </div>
  );
}
