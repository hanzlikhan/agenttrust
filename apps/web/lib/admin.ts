"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Dev-only admin token for admin-gated endpoints (key issuance, policy
 * create/activate/simulate). Stored in sessionStorage, never in the bundle.
 *
 * The backend's `require_admin` expects the token as an
 * `Authorization: Bearer <token>` header — apiFetch(path, token) sends it
 * exactly that way.
 */

/** sessionStorage slot for the dev-only admin token. */
export const ADMIN_TOKEN_STORAGE = "agenttrust_admin_token";

function readStoredAdminToken(): string | null {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  const raw = window.sessionStorage.getItem(ADMIN_TOKEN_STORAGE);
  return raw !== null && raw.trim() !== "" ? raw : null;
}

/** Admin token currently in sessionStorage, or null. Safe on the server. */
export function getStoredAdminToken(): string | null {
  return readStoredAdminToken();
}

/** React binding: [token, saveToken, clearToken]. */
export function useAdminToken(): [
  string | null,
  (token: string) => void,
  () => void,
] {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    setToken(readStoredAdminToken());
  }, []);

  const saveToken = useCallback((next: string) => {
    window.sessionStorage.setItem(ADMIN_TOKEN_STORAGE, next);
    setToken(next);
  }, []);

  const clearToken = useCallback(() => {
    window.sessionStorage.removeItem(ADMIN_TOKEN_STORAGE);
    setToken(null);
  }, []);

  return [token, saveToken, clearToken];
}
