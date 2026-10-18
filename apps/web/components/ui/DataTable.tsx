"use client";

import type { ReactNode } from "react";
import Spinner from "./Spinner";

/**
 * DataTable — a server-driven table with sortable headers and pagination.
 *
 * The table itself never fetches: the parent owns data, sorting, and paging
 * state and re-renders with new props.
 *
 * Props:
 * - columns: [{ key, header, render(row), sortable? }]. A column with
 *   sortable: true renders its header as a button that calls onSortChange(key).
 * - rows: current page rows
 * - rowKey: (row, index) => stable React key (prefer a server id)
 * - caption: accessible table description (visually hidden)
 * - loading: shows a spinner row instead of data
 * - empty: node rendered when rows is empty and not loading
 *   (e.g. <EmptyState .../>)
 * - page: 0-based current page
 * - pageSize, total: drive the "Showing X–Y of Z" label and button state
 * - onPageChange: (nextPage) => void
 * - sortKey / sortDirection: current sort, for aria-sort + arrow indicator
 * - onSortChange: (key) => void — parent toggles direction and refetches
 */
export type SortDirection = "asc" | "desc";

export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  sortable?: boolean;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  caption: string;
  loading?: boolean;
  empty?: ReactNode;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  sortKey?: string;
  sortDirection?: SortDirection;
  onSortChange?: (key: string) => void;
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  loading = false,
  empty,
  page,
  pageSize,
  total,
  onPageChange,
  sortKey,
  sortDirection,
  onSortChange,
}: DataTableProps<T>) {
  const pageCount = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);

  const ariaSort = (col: DataTableColumn<T>): "ascending" | "descending" | "none" => {
    if (!col.sortable || sortKey !== col.key) return "none";
    return sortDirection === "desc" ? "descending" : "ascending";
  };

  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-border bg-surface-2">
              {columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={col.sortable ? ariaSort(col) : undefined}
                  className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-text-2"
                >
                  {col.sortable && onSortChange ? (
                    <button
                      type="button"
                      onClick={() => onSortChange(col.key)}
                      className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-text-1"
                      aria-label={`Sort by ${col.key}${
                        sortKey === col.key
                          ? sortDirection === "desc"
                            ? ", descending"
                            : ", ascending"
                          : ""
                      }`}
                    >
                      {col.header}
                      <span aria-hidden="true" className="text-text-3">
                        {sortKey === col.key
                          ? sortDirection === "desc"
                            ? "▾"
                            : "▴"
                          : "↕"}
                      </span>
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-10">
                  <div className="flex justify-center">
                    <Spinner label="Loading rows" />
                  </div>
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-10">
                  {empty ?? (
                    <p className="text-center text-sm text-text-3">
                      No rows to show.
                    </p>
                  )}
                </td>
              </tr>
            ) : (
              rows.map((row, i) => (
                <tr
                  key={rowKey(row, i)}
                  className="border-b border-border last:border-0 hover:bg-surface-2/60"
                >
                  {columns.map((col) => (
                    <td key={col.key} className="px-4 py-2.5 text-text-1">
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-text-2">
        <p role="status" aria-live="polite">
          Showing {from}–{to} of {total}
        </p>
        <nav aria-label="Table pages" className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 0 || loading}
            className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm font-medium text-text-1 hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-text-3" aria-hidden="true">
            Page {page + 1} of {pageCount}
          </span>
          <button
            type="button"
            onClick={() => onPageChange(page + 1)}
            disabled={page + 1 >= pageCount || loading}
            className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm font-medium text-text-1 hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
          >
            Next
          </button>
        </nav>
      </div>
    </div>
  );
}
