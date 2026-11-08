import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "../api/client";

export type ApiState<T> = {
  data: T | undefined;
  error: unknown;
  loading: boolean; // first load for this path (no data yet)
  refreshing: boolean; // background refresh with data on screen
  updatedAt: number | null;
  refresh: () => Promise<void>;
};

type Options<T> = {
  /** Seconds until the next automatic refresh, or null to stop polling. */
  refreshSeconds?: (data: T) => number | null;
  /** Retry delay (seconds) after an error; null disables auto-retry. */
  retrySeconds?: number | null;
};

const visible = () => document.visibilityState === "visible";

/**
 * Fetch JSON from `path` and keep it fresh. Polls every `refreshSeconds(data)` while
 * the page is visible, pauses when hidden, and refreshes immediately on return if stale.
 */
export function useApi<T>(path: string | null, opts: Options<T> = {}): ApiState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path != null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [attemptAt, setAttemptAt] = useState(0);
  const reqId = useRef(0);
  const ctrl = useRef<AbortController | null>(null);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const load = useCallback(async () => {
    if (!path) return;
    const id = ++reqId.current;
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setRefreshing(true);
    try {
      const body = await apiGet<T>(path, c.signal);
      if (id !== reqId.current) return;
      setData(body);
      setError(null);
      setUpdatedAt(Date.now());
    } catch (e) {
      if (id !== reqId.current || (e instanceof DOMException && e.name === "AbortError")) return;
      setError(e);
    } finally {
      if (id === reqId.current) {
        setLoading(false);
        setRefreshing(false);
        setAttemptAt(Date.now());
      }
    }
  }, [path]);

  // New path: reset and load.
  useEffect(() => {
    setData(undefined);
    setError(null);
    setUpdatedAt(null);
    setLoading(path != null);
    load();
    return () => ctrl.current?.abort();
  }, [path, load]);

  // Schedule the next refresh after each attempt; pause while the tab is hidden.
  useEffect(() => {
    if (!attemptAt) return;
    const o = optsRef.current;
    const seconds = error
      ? o.retrySeconds === undefined ? 30 : o.retrySeconds
      : data !== undefined && o.refreshSeconds ? o.refreshSeconds(data) : null;
    if (seconds == null || seconds <= 0) return;
    const ms = seconds * 1000;
    let timer: number | undefined;
    const schedule = (wait: number) => {
      window.clearTimeout(timer);
      if (visible()) timer = window.setTimeout(load, Math.max(0, wait));
    };
    const onVisibility = () => {
      if (visible()) schedule(ms - (Date.now() - attemptAt));
      else window.clearTimeout(timer);
    };
    schedule(ms);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [attemptAt, data, error, load]);

  return { data, error, loading, refreshing, updatedAt, refresh: load };
}
