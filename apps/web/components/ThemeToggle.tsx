"use client";

import { useCallback, useEffect, useState } from "react";
import { IconMoon, IconSun } from "./icons";

/**
 * ThemeToggle — switches between dark (default) and light themes.
 *
 * The choice persists to localStorage under `agenttrust_theme`; a pre-paint
 * script in the root layout applies the stored value so there is no flash.
 */
const STORAGE_KEY = "agenttrust_theme";

export default function ThemeToggle() {
  // Default matches the statically rendered <html class="dark">.
  const [dark, setDark] = useState(true);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = useCallback(() => {
    setDark((wasDark) => {
      const next = !wasDark;
      document.documentElement.classList.toggle("dark", next);
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "dark" : "light");
      } catch {
        // Storage may be unavailable (private mode); the toggle still works
        // for this session.
      }
      return next;
    });
  }, []);

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={dark}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Switch to light theme" : "Switch to dark theme"}
      className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface-2 text-text-2 hover:text-text-1"
    >
      {dark ? (
        <IconSun width={18} height={18} />
      ) : (
        <IconMoon width={18} height={18} />
      )}
    </button>
  );
}
