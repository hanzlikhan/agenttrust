"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  IconAgents,
  IconAnalytics,
  IconApprovals,
  IconClose,
  IconEvaluations,
  IconIncidents,
  IconMenu,
  IconOverview,
  IconPolicies,
  IconRuns,
  IconSettings,
  type IconProps,
} from "./icons";
import ThemeToggle from "./ThemeToggle";
import ShellConnection from "./ShellConnection";
import { API_BASE } from "@/lib/api";

/**
 * AppShell — sidebar navigation + header, rendered by the root layout.
 *
 * - Desktop: fixed sidebar. Mobile: hamburger button opens a slide-over
 *   (Esc / overlay / close button dismiss it).
 * - The header carries the stream status badge, environment label, API base
 *   indicator, and theme toggle.
 * - All nav targets (Policies, Agents, Analytics, Incidents, Evaluations,
 *   Settings) have real pages.
 */

interface NavItem {
  href: string;
  label: string;
  Icon: (props: IconProps) => ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Overview", Icon: IconOverview },
  { href: "/runs", label: "Executions", Icon: IconRuns },
  { href: "/approvals", label: "Approvals", Icon: IconApprovals },
  { href: "/policies", label: "Policies", Icon: IconPolicies },
  { href: "/agents", label: "Agents", Icon: IconAgents },
  { href: "/analytics", label: "Analytics", Icon: IconAnalytics },
  { href: "/incidents", label: "Incidents", Icon: IconIncidents },
  { href: "/evaluations", label: "Evaluations", Icon: IconEvaluations },
  { href: "/settings", label: "Settings", Icon: IconSettings },
];

// Build-time labels; never user secrets.
const ENV_LABEL = process.env.NEXT_PUBLIC_ENV_LABEL ?? "Local demo";

function apiBaseLabel(): string {
  try {
    const url = new URL(API_BASE);
    return url.host;
  } catch {
    return API_BASE;
  }
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Primary" className="flex flex-col gap-1 p-3">
      {NAV_ITEMS.map(({ href, label, Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={[
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
              "transition-colors",
              active
                ? "bg-surface-2 text-text-1"
                : "text-text-2 hover:bg-surface-2/60 hover:text-text-1",
            ].join(" ")}
          >
            <span aria-hidden="true" className="inline-flex shrink-0">
              <Icon width={18} height={18} />
            </span>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-4 py-4" aria-label="AgentTrust home">
      <span
        aria-hidden="true"
        className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-brand text-brand-text"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      </span>
      <span className="text-base font-bold tracking-tight text-text-1">
        AgentTrust
      </span>
    </Link>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeMobile = useCallback(() => setMobileOpen(false), []);
  const apiLabel = apiBaseLabel();
  const mobileDialogRef = useRef<HTMLDivElement | null>(null);
  const hamburgerRef = useRef<HTMLButtonElement | null>(null);

  // Esc dismisses the mobile slide-over; Tab is trapped inside it.
  // Phase 8 audit M6: focus moves into the dialog on open and returns to
  // the hamburger button on close.
  useEffect(() => {
    if (!mobileOpen) return;
    const dialog = mobileDialogRef.current;
    // Move focus into the dialog.
    const firstFocusable = dialog?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    (firstFocusable ?? dialog)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMobile();
        return;
      }
      if (event.key !== "Tab" || dialog === null) return;
      const focusables = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (event.shiftKey && (active === first || active === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      // Return focus to the hamburger button.
      hamburgerRef.current?.focus();
    };
  }, [mobileOpen, closeMobile]);

  return (
    <div className="flex min-h-screen bg-bg text-text-1">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r border-border bg-surface md:block">
        <Brand />
        <NavList />
      </aside>

      {/* Mobile slide-over */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/60"
            aria-hidden="true"
            onClick={closeMobile}
          />
          <div
            ref={mobileDialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            tabIndex={-1}
            className="absolute inset-y-0 left-0 w-64 bg-surface shadow-popover"
          >
            <div className="flex items-center justify-between border-b border-border pr-2">
              <Brand />
              <button
                type="button"
                onClick={closeMobile}
                aria-label="Close navigation"
                className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text-2 hover:text-text-1"
              >
                <IconClose width={18} height={18} />
              </button>
            </div>
            <NavList onNavigate={closeMobile} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border bg-surface px-4 py-2.5">
          <button
            ref={hamburgerRef}
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text-2 hover:text-text-1 md:hidden"
          >
            <IconMenu width={20} height={20} />
          </button>

          <span className="hidden items-center gap-2 sm:inline-flex">
            <span
              className="rounded-full border border-info-border bg-info-bg px-2.5 py-0.5 text-xs font-semibold text-info-text"
              title="Deployment environment label"
            >
              {ENV_LABEL}
            </span>
            <span
              className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 font-mono text-xs text-text-2"
              title={`API base URL: ${API_BASE}`}
            >
              {apiLabel}
            </span>
          </span>

          <div className="ml-auto flex items-center gap-2.5">
            <ShellConnection />
            <ThemeToggle />
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 p-4 sm:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
