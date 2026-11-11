import type { BetsResponse, GameDetailResponse, League, PredictionRecordResponse, ScoreboardResponse, StandingsResponse, TeamResponse } from "./types";

export class ApiError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, code: string | null) {
    super(code ?? `HTTP ${status}`);
    this.status = status;
    this.code = code;
  }
}

// "busy" = a data job is writing; "unavailable" = the stats drive isn't reachable right now.
// Both are temporary from the user's point of view, so they share the friendly "refreshing" state.
export const isWarehouseBusy = (e: unknown): boolean =>
  e instanceof ApiError &&
  e.status === 503 &&
  (e.code === "warehouse_busy" || e.code === "warehouse_unavailable");

const MOCK = import.meta.env.VITE_MOCK === "1";

async function doFetch(path: string, signal?: AbortSignal): Promise<Response> {
  if (MOCK) {
    // Only bundled when VITE_MOCK=1; tree-shaken from production builds.
    const { mockFetch } = await import("../mocks");
    return mockFetch(path, signal);
  }
  try {
    return await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store", signal });
  } catch (e) {
    if (!signal?.aborted) await reloadIfSignedOut();
    throw e;
  }
}

// Cloudflare Access answers an expired session with a redirect to its login page on another origin,
// which a fetch() can't follow (it fails like a network error). Probe once without following
// redirects; if Access is redirecting, reload the page so the browser shows the login.
let probing = false;
async function reloadIfSignedOut(): Promise<void> {
  if (probing || (typeof navigator !== "undefined" && !navigator.onLine)) return;
  probing = true;
  try {
    const res = await fetch("/api/health", { redirect: "manual", cache: "no-store" });
    if (res.type === "opaqueredirect" || res.status === 401 || res.status === 403) window.location.reload();
  } catch {
    /* really offline or unreachable: let the normal error state show */
  } finally {
    probing = false;
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await doFetch(path, signal);
  if (!res.ok) {
    let code: string | null = null;
    try {
      const body = await res.json();
      if (body && typeof body.error === "string") code = body.error;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code);
  }
  return (await res.json()) as T;
}

function qs(params: Record<string, string | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const api = {
  scoreboard: (date?: string, league: League = "nba") => `/api/scoreboard${qs({ league, date })}`,
  game: (id: string, league: League = "nba") => `/api/games/${encodeURIComponent(id)}${qs({ league })}`,
  predictionRecord: (league: League = "nba", days = 30) =>
    `/api/predictions/record${qs({ league, days: String(days) })}`,
  bets: () => `/api/bets`,
  standings: () => `/api/standings`,
  team: (abbr: string) => `/api/teams/${encodeURIComponent(abbr)}`,
};

export type { BetsResponse, GameDetailResponse, PredictionRecordResponse, ScoreboardResponse, StandingsResponse, TeamResponse };
