// Mock Circa screenshot endpoints (VITE_MOCK=1), shaped like DeepSports/docs/API.md.
// Page-URL switches (before the #): `?mock=circa0` no screenshots yet, `?mock=circaread` already read
// at 2 PM, `?mock=circafull` daily limit reached (uploads fail with 429), `?mock=uploadfail` uploads
// fail with "Mac offline". `?mock=error` (every endpoint 500) applies here too.
import type { CircaTodayResponse, CircaUploadResponse } from "../api/types";
import { etToday } from "./scoreboard";

const DAILY_LIMIT = 30;
const mode = () => new URLSearchParams(window.location.search).get("mock");

const atToday = (h: number, m: number) => {
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toISOString();
};

let count: number | null = null;
let latest: string | null = null;

function state(): { count: number; latest: string | null } {
  if (count == null) {
    const m = mode();
    count = m === "circa0" ? 0 : m === "circafull" ? DAILY_LIMIT : 3;
    latest = count ? atToday(11, 42) : null;
  }
  return { count, latest };
}

export function circaToday(): CircaTodayResponse {
  const s = state();
  return {
    date: etToday(),
    count: s.count,
    latest_at: s.latest,
    read: mode() === "circaread" ? { read_at: atToday(14, 2), lines: 46, matched: 41 } : null,
  };
}

/** Fake upload: progress ticks over ~1.5 s, then the same checks the server makes. */
export async function mockCircaUpload(files: File[], onProgress: (sent: number) => void): Promise<CircaUploadResponse> {
  const total = files.reduce((n, f) => n + f.size, 0);
  for (let i = 1; i <= 10; i++) {
    await new Promise((r) => setTimeout(r, 150));
    onProgress((total * i) / 10);
  }
  const { ApiError } = await import("../api/client");
  const m = mode();
  if (m === "error") throw new ApiError(500, "upstream_error");
  if (m === "uploadfail") throw new ApiError(503, "mac_offline");
  const s = state();
  if (s.count + files.length > DAILY_LIMIT) throw new ApiError(429, "daily limit reached (30 screenshots)");
  const big = files.find((f) => f.size > 10 * 1024 * 1024);
  if (big) throw new ApiError(413, `${big.name} is over 10 MB`);
  count = s.count + files.length;
  latest = new Date().toISOString();
  return {
    date: etToday(),
    saved: files.map((f, i) => ({ name: `circa-${String(s.count + i + 1).padStart(2, "0")}.${f.name.split(".").pop() ?? "png"}`, bytes: f.size })),
    today_count: count,
  };
}

