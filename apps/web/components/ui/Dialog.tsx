"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Dialog — an accessible modal.
 *
 * Props:
 * - open: controls visibility
 * - onClose: called on Esc, overlay click, or an explicit close action
 * - title: dialog heading (rendered as the labelled element)
 * - children: dialog body
 * - actions: footer slot (e.g. confirm/cancel buttons)
 *
 * Behavior:
 * - role="dialog" aria-modal="true", labelled by the title
 * - Focus moves into the dialog on open; Esc closes it
 * - Focus returns to the element that had it before the dialog opened
 * - Tab is trapped inside the dialog while open
 * - Body scroll is locked while open
 */
export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function Dialog({
  open,
  onClose,
  title,
  children,
  actions,
}: DialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    const dialog = dialogRef.current;
    // Focus the dialog container itself on open (it is tabindex=-1).
    dialog?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      // Simple focus trap: keep Tab cycling inside the dialog.
      const focusables = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter((el) => el.offsetParent !== null || el === dialog);
      if (focusables.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      // Return focus to whatever opened the dialog.
      previousFocusRef.current?.focus();
    };
  }, [open ]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onMouseDown={(event) => {
        // Close on overlay click, but not on clicks inside the dialog.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="absolute inset-0 bg-black/60"
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="at-dialog-title"
        tabIndex={-1}
        className="relative w-full max-w-lg rounded-xl border border-border bg-surface shadow-popover"
      >
        <div className="border-b border-border px-5 py-4">
          <h2 id="at-dialog-title" className="text-base font-semibold text-text-1">
            {title}
          </h2>
        </div>
        <div className="max-h-[60vh] overflow-y-auto px-5 py-4 text-sm text-text-1">
          {children}
        </div>
        {actions !== undefined && (
          <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
            {actions}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
