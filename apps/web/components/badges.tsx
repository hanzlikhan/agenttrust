"use client";

import type { ReactNode } from "react";
import { Badge, type BadgeVariant } from "./ui";
import {
  IconCheck,
  IconClock,
  IconDot,
  IconIncidents,
  IconInfo,
} from "./icons";

/**
 * Status badges with a fixed semantic mapping, used across pages.
 * Status is always icon + text (the Badge component), never color alone.
 */

function outcomeVariant(outcome: string): BadgeVariant {
  switch (outcome) {
    case "ALLOW":
      return "allow";
    case "DENY":
      return "deny";
    case "REVIEW":
      return "review";
    default:
      return "neutral";
  }
}

/** Policy decision outcome: ALLOW / DENY / REVIEW. */
export function OutcomeBadge({ outcome }: { outcome: string }) {
  return <Badge variant={outcomeVariant(outcome)}>{outcome}</Badge>;
}

function runStateVariant(state: string): BadgeVariant {
  switch (state) {
    case "COMPLETED":
      return "allow";
    case "FAILED":
      return "deny";
    case "RUNNING":
      return "info";
    default:
      return "neutral";
  }
}

/** Agent run state: RUNNING / COMPLETED / FAILED. */
export function RunStateBadge({ state }: { state: string }) {
  return <Badge variant={runStateVariant(state)}>{state}</Badge>;
}

function approvalStateVariant(state: string): BadgeVariant {
  switch (state) {
    case "PENDING":
      return "review";
    case "APPROVED":
      return "allow";
    case "REJECTED":
      return "deny";
    case "EXPIRED":
      return "neutral";
    default:
      return "neutral";
  }
}

/** Approval state: PENDING / APPROVED / REJECTED / EXPIRED. */
export function ApprovalStateBadge({ state }: { state: string }) {
  return <Badge variant={approvalStateVariant(state)}>{state}</Badge>;
}

/** Generic active/draft/revoked state badge. */
export function StateBadge({
  state,
  activeLabel = "Active",
}: {
  state: "active" | "draft" | "revoked" | "expired";
  activeLabel?: string;
}) {
  const variant: BadgeVariant =
    state === "active"
      ? "allow"
      : state === "revoked"
        ? "deny"
        : state === "expired"
          ? "review"
          : "neutral";
  const label =
    state === "active" ? activeLabel : state === "draft" ? "Draft" : state === "revoked" ? "Revoked" : "Expired";
  return <Badge variant={variant}>{label}</Badge>;
}

function incidentSeverityMeta(severity: string): {
  variant: BadgeVariant;
  icon: ReactNode;
  label: string;
} {
  switch (severity.toLowerCase()) {
    case "critical":
      return {
        variant: "deny",
        icon: <IconIncidents width={12} height={12} />,
        label: "Critical",
      };
    case "high":
      return {
        variant: "review",
        icon: <IconIncidents width={12} height={12} />,
        label: "High",
      };
    case "medium":
      return {
        variant: "info",
        icon: <IconInfo width={12} height={12} />,
        label: "Medium",
      };
    case "low":
      return {
        variant: "neutral",
        icon: <IconDot width={12} height={12} />,
        label: "Low",
      };
    default:
      return {
        variant: "neutral",
        icon: <IconDot width={12} height={12} />,
        label: severity,
      };
  }
}

/** Incident severity: low / medium / high / critical (icon + text). */
export function IncidentSeverityBadge({ severity }: { severity: string }) {
  const { variant, icon, label } = incidentSeverityMeta(severity);
  return (
    <Badge variant={variant} icon={icon}>
      {label}
    </Badge>
  );
}

function incidentStatusMeta(status: string): {
  variant: BadgeVariant;
  icon: ReactNode;
  label: string;
} {
  switch (status.toLowerCase()) {
    case "open":
      return {
        variant: "review",
        icon: <IconClock width={12} height={12} />,
        label: "Open",
      };
    case "investigating":
      return {
        variant: "info",
        icon: <IconIncidents width={12} height={12} />,
        label: "Investigating",
      };
    case "resolved":
      return {
        variant: "allow",
        icon: <IconCheck width={12} height={12} />,
        label: "Resolved",
      };
    case "dismissed":
      return {
        variant: "neutral",
        icon: <IconDot width={12} height={12} />,
        label: "Dismissed",
      };
    default:
      return {
        variant: "neutral",
        icon: <IconDot width={12} height={12} />,
        label: status,
      };
  }
}

/** Incident status: open / investigating / resolved / dismissed. */
export function IncidentStatusBadge({ status }: { status: string }) {
  const { variant, icon, label } = incidentStatusMeta(status);
  return (
    <Badge variant={variant} icon={icon}>
      {label}
    </Badge>
  );
}

function evalRunStateMeta(state: string): {
  variant: BadgeVariant;
  icon: ReactNode;
  label: string;
} {
  switch (state.toLowerCase()) {
    case "completed":
      return {
        variant: "allow",
        icon: <IconCheck width={12} height={12} />,
        label: "Completed",
      };
    case "running":
      return {
        variant: "info",
        icon: <IconClock width={12} height={12} />,
        label: "Running",
      };
    case "failed":
      return {
        variant: "deny",
        icon: <IconDot width={12} height={12} />,
        label: "Failed",
      };
    default:
      return {
        variant: "neutral",
        icon: <IconDot width={12} height={12} />,
        label: state,
      };
  }
}

/** Evaluation run state: running / completed / failed. */
export function EvalRunStatusBadge({ state }: { state: string }) {
  const { variant, icon, label } = evalRunStateMeta(state);
  return (
    <Badge variant={variant} icon={icon}>
      {label}
    </Badge>
  );
}
