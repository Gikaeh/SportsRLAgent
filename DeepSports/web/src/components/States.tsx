import type { ReactNode } from "react";
import { ApiError, isWarehouseBusy } from "../api/client";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

export function Skeleton({ rows = 3, height = 104 }: { rows?: number; height?: number }) {
  return (
    <div role="status" aria-label="Loading" className="skeleton-list">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ height }} />
      ))}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <p className="state-title">{title}</p>
      {children && <div className="state-body">{children}</div>}
    </div>
  );
}

function describe(error: unknown): { title: string; body: string } {
  if (isWarehouseBusy(error)) {
    return {
      title: "Stats refreshing, try again shortly",
      body: "The stats database is being updated right now. This usually takes a few minutes; we'll retry automatically.",
    };
  }
  if (error instanceof ApiError) {
    if (error.status === 404) return { title: "Not found", body: "We couldn't find that. It may not exist yet." };
    if (error.status === 502 || error.status === 504) {
      return { title: "Couldn't reach the server", body: "Check that DeepSports is running and you're on the same Wi-Fi." };
    }
    return { title: "Something went wrong", body: `The server returned an error (${error.status}). Try again in a moment.` };
  }
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    return { title: "You're offline", body: "Reconnect to the internet to see scores." };
  }
  return { title: "Couldn't reach the server", body: "Check that DeepSports is running and you're on the same Wi-Fi." };
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { title, body } = describe(error);
  const busy = isWarehouseBusy(error);
  return (
    <div className={`state ${busy ? "state-busy" : "state-error"}`} role="alert">
      <span className="state-icon" aria-hidden="true">{busy ? "⟳" : "!"}</span>
      <p className="state-title">{title}</p>
      <p className="state-body">{body}</p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** Thin banner when a background refresh fails but older data is still on screen. */
export function StaleBanner({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const msg = isWarehouseBusy(error) ? "Stats refreshing, showing the last update" : "Couldn't refresh, showing the last update";
  return (
    <div className="banner" role="status">
      <span>{msg}</span>
      <button type="button" className="btn-link" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
