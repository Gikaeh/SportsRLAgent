// Mock Circa screenshot endpoints (VITE_MOCK=1), shaped like DeepSports/docs/API.md.
// Page-URL switches (before the #): `?mock=circa0` no screenshots yet, `?mock=circaread` already read
// at 2 PM, `?mock=circafull` daily limit reached. `?mock=error` (every endpoint 500) applies here too.
import type { CircaTodayResponse } from "../api/types";
import { etToday } from "./scoreboard";

const DAILY_LIMIT = 30;
const mode = () => new URLSearchParams(window.location.search).get("mock");

const atToday = (h: number, m: number) => {
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toISOString();
};

let count: number | null = null;
let latest: string | null = null; // set once, on first read

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
