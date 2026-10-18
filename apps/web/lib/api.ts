"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Shared API client helpers for the AgentTrust dashboard.
 *
 * Two credentials exist in this app and they are deliberately different:
 * - DASHBOARD key (sessionStorage `agenttrust_api_key`): read-only dashboard
 *   access for the new app shell (Overview, Runs, ...).
 * - REVIEWER key (sessionStorage `agenttrust_reviewer_key`): approvals
 *   scope per ADR-034, managed only by the Approval Center page. This file
 *   does NOT touch it.
 */

export const API_BASE: string =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** sessionStorage slot for the dashboard (read) API key. */
export const DASHBOARD_KEY_STORAGE = "agenttrust_api_key";
/** Window event fired whenever the dashboard key is saved or cleared. */
export const DASHBOARD_KEY_EVENT = "agenttrust:dashboard-key-changed";

function readStoredKey(): string | null {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  const raw = window.sessionStorage.getItem(DASHBOARD_KEY_STORAGE);
  return raw !== null && raw.trim() !== "" ? raw : null;
}

/** Dashboard API key currently in sessionStorage, or null. Safe on the server. */
export function getStoredKey(): string | null {
  return readStoredKey();
}

/** Persist the dashboard API key for this tab only (sessionStorage). */
export function setStoredKey(key: string): void {
  window.sessionStorage.setItem(DASHBOARD_KEY_STORAGE, key);
  // Notify other hook instances in this tab (sessionStorage fires no
  // storage events for same-tab writes, and the app-shell header keeps its
  // own useDashboardKey instance alive across navigations).
  window.dispatchEvent(new Event(DASHBOARD_KEY_EVENT));
}

/** Forget the dashboard API key. */
export function clearStoredKey(): void {
  window.sessionStorage.removeItem(DASHBOARD_KEY_STORAGE);
  window.dispatchEvent(new Event(DASHBOARD_KEY_EVENT));
}

/**
 * React binding for the dashboard key: [key, saveKey, clearKey].
 * Initializes from sessionStorage after mount (avoids SSR mismatch).
 */
export function useDashboardKey(): [
  string | null,
  (key: string) => void,
  () => void,
] {
  // Starts null and syncs from sessionStorage after mount; sessionStorage
  // does not exist during SSR, so the initial null is the safe value.
  // Also re-syncs when another hook instance saves/clears the key (e.g. the
  // Settings page), so the app-shell header's stream badge follows.
  const [key, setKey] = useState<string | null>(null);

  useEffect(() => {
    const resync = () => setKey(readStoredKey());
    resync();
    window.addEventListener(DASHBOARD_KEY_EVENT, resync);
    return () => window.removeEventListener(DASHBOARD_KEY_EVENT, resync);
  }, []);

  const saveKey = useCallback((next: string) => {
    setStoredKey(next);
    setKey(next);
  }, []);

  const forgetKey = useCallback(() => {
    clearStoredKey();
    setKey(null);
  }, []);

  return [key, saveKey, forgetKey];
}

/** The API's error envelope: {error_code, message, request_id}. */
export interface ApiErrorEnvelope {
  error_code?: string;
  message?: string;
  request_id?: string;
}

function isEnvelope(value: unknown): value is ApiErrorEnvelope {
  return typeof value === "object" && value !== null;
}

/**
 * Fetch a JSON API resource with Bearer auth.
 *
 * - `path` is appended to API_BASE (leading "/" optional).
 * - Adds `Authorization: Bearer <key>`; omits the header when key is "".
 * - On non-2xx, parses the {error_code, message, request_id} envelope and
 *   throws Error(message). On network failure, throws the fetch error.
 * - Never logs the key.
 */
export async function apiFetch<T>(
  path: string,
  key: string,
  options: Omit<RequestInit, "headers"> & { headers?: HeadersInit } = {},
): Promise<T> {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };
  if (key !== "") {
    headers.Authorization = `Bearer ${key}`;
  }
  const res = await fetch(`${API_BASE}${normalized}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => null);
    let message = `HTTP ${res.status}`;
    if (isEnvelope(body) && typeof body.message === "string" && body.message !== "") {
      message =
        typeof body.error_code === "string" && body.error_code !== ""
          ? `${body.error_code}: ${body.message}`
          : body.message;
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}
