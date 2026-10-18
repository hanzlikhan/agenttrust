"use client";

/**
 * Bespoke AgentTrust component library (Tailwind-based, NOT shadcn).
 *
 * Why bespoke instead of shadcn/radix: the dashboard needs a tiny,
 * security-signaling-focused set of primitives (status badges that always
 * pair icon + text, server-driven tables) wired directly to our design
 * tokens and dark-by-default theme. Pulling in shadcn would add a second
 * theming layer (CSS-var conventions of its own), a CLI-generated component
 * tree to maintain, and Radix primitives whose accessibility we would still
 * need to verify — for ten small components, hand-rolled Tailwind code with
 * deliberate ARIA is cheaper to audit and keeps the dependency list at
 * Tailwind alone.
 */

export { default as Button } from "./Button";
export type { ButtonProps, ButtonVariant, ButtonSize } from "./Button";
export { default as Badge } from "./Badge";
export type { BadgeProps, BadgeVariant } from "./Badge";
export { default as Card } from "./Card";
export type { CardProps } from "./Card";
export { default as DataTable } from "./DataTable";
export type {
  DataTableProps,
  DataTableColumn,
  SortDirection,
} from "./DataTable";
export { default as Input } from "./Input";
export type { InputProps } from "./Input";
export { default as Select } from "./Select";
export type { SelectProps, SelectOption } from "./Select";
export { default as Dialog } from "./Dialog";
export type { DialogProps } from "./Dialog";
export { default as EmptyState } from "./EmptyState";
export type { EmptyStateProps } from "./EmptyState";
export { default as Spinner } from "./Spinner";
export type { SpinnerProps, SpinnerSize } from "./Spinner";
export { default as Skeleton } from "./Skeleton";
export type { SkeletonProps } from "./Skeleton";
