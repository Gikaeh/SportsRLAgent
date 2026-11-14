import type { BetsResponse, CircaTodayResponse, CircaUploadResponse, GameDetailResponse, League, PredictionRecordResponse, ScoreboardResponse, StandingsResponse, TeamResponse } from "./types";

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
      code = errorCode(await res.json());
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
  circaToday: () => `/api/circa/screenshots/today`,
};

/** Error code from a JSON error body: the Worker sends `error`, DeepSports' 4xx may send `detail`. */
function errorCode(body: unknown): string | null {
  if (body && typeof body === "object") {
    const b = body as { error?: unknown; detail?: unknown };
    if (typeof b.error === "string") return b.error;
    if (typeof b.detail === "string") return b.detail;
  }
  return null;
}

/**
 * Upload Circa screenshots in one multipart POST (field `file`, repeated). Uses XHR, not fetch,
 * because only XHR reports upload progress. `onProgress` gets bytes sent so far.
 */
export async function uploadCircaScreenshots(
  files: File[],
  onProgress: (sent: number) => void,
): Promise<CircaUploadResponse> {
  if (MOCK) {
    const { mockCircaUpload } = await import("../mocks/circa");
    return mockCircaUpload(files, onProgress);
  }
  const form = new FormData();
  for (const f of files) form.append("file", f, f.name);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/circa/screenshots");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON body */
      }
      if (xhr.status >= 200 && xhr.status < 300 && body) resolve(body as CircaUploadResponse);
      else reject(new ApiError(xhr.status || 0, errorCode(body)));
    };
    xhr.onerror = () => {
      void reloadIfSignedOut();
      reject(new TypeError("network"));
    };
    xhr.send(form);
  });
}

export type { BetsResponse, CircaTodayResponse, CircaUploadResponse, GameDetailResponse, PredictionRecordResponse, ScoreboardResponse, StandingsResponse, TeamResponse };
