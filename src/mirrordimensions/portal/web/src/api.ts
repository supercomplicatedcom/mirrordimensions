// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// Calls to /api/v1. The session cookie set when the portal's address was opened is sent
// automatically; changes also carry X-Mirror-Portal, which the server requires.

import { useCallback, useEffect, useState } from "react";
import type { ApiError } from "./types";

export const API = "/api/v1";

export class PortalError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: ApiError,
  ) {
    super(detail.what);
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let detail: ApiError = { what: `The portal answered ${response.status}.`, why: "", fix: "" };
  try {
    detail = (await response.json()) as ApiError;
  } catch {
    // not JSON: keep the generic message
  }
  throw new PortalError(response.status, detail);
}

export async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(API + path, { credentials: "same-origin" }));
}

export async function send<T>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  return parse<T>(
    await fetch(API + path, {
      method,
      credentials: "same-origin",
      headers: { "X-Mirror-Portal": "1", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
}

export interface Loaded<T> {
  data: T | undefined;
  error: PortalError | undefined;
  loading: boolean;
  reload: () => void;
}

/** Load a path, and again whenever `reload` is called or the path changes. */
export function useApi<T>(path: string | null): Loaded<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<PortalError>();
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    if (path === null) return;
    let live = true;
    setLoading(true);
    get<T>(path)
      .then((value) => {
        if (live) {
          setData(value);
          setError(undefined);
        }
      })
      .catch((err: unknown) => {
        if (live) setError(err instanceof PortalError ? err : new PortalError(0, { what: String(err), why: "", fix: "" }));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [path, tick]);
  return { data, error, loading, reload };
}
