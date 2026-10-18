"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useDashboardKey } from "@/lib/api";
import { EmptyState, Spinner } from "./ui";

/**
 * Gate for pages that need the dashboard (read) API key. Shows a spinner
 * until sessionStorage is readable, then either the children or an
 * EmptyState pointing at Settings where the key is entered.
 */
export default function RequireDashboardKey({
  children,
  description,
}: {
  children: ReactNode;
  description?: ReactNode;
}) {
  const [key] = useDashboardKey();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading…" />
      </div>
    );
  }

  if (key === null) {
    return (
      <EmptyState
        title="No dashboard API key"
        description={
          description ??
          "Connect a read-only dashboard API key to view live data from the API."
        }
        action={
          <Link
            href="/settings"
            className="inline-flex items-center rounded-md border border-transparent bg-brand px-3 py-1.5 text-sm font-medium text-brand-text hover:bg-brand-hover"
          >
            Go to Settings
          </Link>
        }
      />
    );
  }

  return <>{children}</>;
}
