"use client";

import type { ReactNode } from "react";

/**
 * Card — a titled content panel.
 *
 * Props:
 * - title: heading content (rendered as <h2> when a string; use headingLevel
 *   to change — default 2)
 * - headingLevel: 1 | 2 | 3 (default 2)
 * - description: secondary text under the title
 * - actions: right-aligned slot in the header (e.g. buttons)
 * - children: card body
 * - className: extra classes
 */
export interface CardProps {
  title?: ReactNode;
  headingLevel?: 1 | 2 | 3;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export default function Card({
  title,
  headingLevel = 2,
  description,
  actions,
  children,
  className = "",
}: CardProps) {
  const Heading = `h${headingLevel}` as "h1" | "h2" | "h3";
  const hasHeader = title !== undefined || actions !== undefined;
  return (
    <section
      className={[
        "rounded-lg border border-border bg-surface shadow-card",
        "p-4 sm:p-6",
        className,
      ].join(" ")}
    >
      {hasHeader && (
        <header className="mb-4 flex items-start justify-between gap-4">
          <div>
            {title !== undefined && (
              <Heading className="text-base font-semibold text-text-1">
                {title}
              </Heading>
            )}
            {description !== undefined && (
              <p className="mt-1 text-sm text-text-2">{description}</p>
            )}
          </div>
          {actions !== undefined && (
            <div className="flex shrink-0 items-center gap-2">{actions}</div>
          )}
        </header>
      )}
      {children}
    </section>
  );
}
