// What to push and when. Pure functions (no I/O), unit-tested in ../test/plan.test.ts.

export type League = "nba" | "ncaab";
export const LEAGUES: League[] = ["nba", "ncaab"];

export const FULL_EVERY_MS = 15 * 60_000;
/** The app polls the mirror no faster than this; the mirror only changes about once a minute. */
export const MIN_REFRESH_SECONDS = 30;
/** Per request: stays under the Worker's 40-entry limit and keeps its JSON parse cheap. */
export const CHUNK_ENTRIES = 35;
export const CHUNK_CHARS = 300_000; // free plan: ~10 ms CPU per request; keep JSON.parse small

export type State = { lastPushAt?: string; lastFullAt?: string; lastFailAt?: string; finalsPushed?: string[] };

/** After a failed push, wait this long before trying again (no full refetch every minute during an outage). */
export const FAIL_BACKOFF_MS = 5 * 60_000;
export type Entry = { key: string; body: string };

type Card = { id: string; state: string; followed?: boolean; league?: string; bets?: string[] };
type GameList = { games?: Card[]; live?: boolean };

/** YYYY-MM-DD in US/Eastern, `offsetDays` from `now` (the app's and DeepSports' game-day convention). */
export function easternDate(now: Date, offsetDays = 0): string {
  const d = new Date(now.getTime() + offsetDays * 86400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

/** Should this run push, and is it a full push (everything) or a live one (scores only)? */
export function decide(state: State, now: Date, live: boolean, force: boolean): { push: boolean; full: boolean } {
  const lastFail = state.lastFailAt ? Date.parse(state.lastFailAt) : NaN;
  if (!force && now.getTime() - lastFail < FAIL_BACKOFF_MS) return { push: false, full: false };
  const lastFull = state.lastFullAt ? Date.parse(state.lastFullAt) : NaN;
  const full = force || Number.isNaN(lastFull) || now.getTime() - lastFull >= FULL_EVERY_MS;
  return { push: full || live, full };
}

export const scoreboardKey = (league: League, date?: string) =>
  date ? `/api/scoreboard?league=${league}&date=${date}` : `/api/scoreboard?league=${league}`;
export const gameKey = (id: string, league: string) => `/api/games/${encodeURIComponent(id)}?league=${league}`;

/** Scoreboard dates: live runs cover yesterday + today; full runs the app's whole reachable window. */
export function scoreboardKeys(now: Date, full: boolean): string[] {
  const offsets = full ? [-2, -1, 0, 1, 2, 3] : [-1, 0];
  const keys: string[] = [];
  for (const league of LEAGUES) {
    keys.push(scoreboardKey(league)); // the app's "Today" asks without a date
    for (const o of offsets) keys.push(scoreboardKey(league, easternDate(now, o)));
  }
  return keys;
}

export function isLive(lists: GameList[]): boolean {
  return lists.some((l) => l.live === true || (l.games ?? []).some((g) => g.state === "in"));
}

/**
 * Game pages to mirror: every NBA game, plus college games that are followed or carry a bet.
 * Live games every run; finals once; upcoming games on full runs only.
 */
export function gameKeys(lists: { league: League; body: GameList }[], bets: GameList | null, full: boolean, finalsPushed: Set<string>): string[] {
  const out = new Set<string>();
  const consider = (g: Card, league: string) => {
    if (league !== "nba" && !g.followed && !(g.bets && g.bets.length)) return;
    const key = gameKey(g.id, league);
    if (g.state === "in") out.add(key);
    else if (g.state === "post" && !finalsPushed.has(key)) out.add(key);
    else if (g.state === "pre" && full) out.add(key);
  };
  for (const { league, body } of lists) for (const g of body.games ?? []) consider(g, g.league ?? league);
  for (const g of bets?.games ?? []) consider({ ...g, bets: g.bets ?? ["bet"] }, g.league ?? "nba");
  return [...out];
}

/** Never let the app poll the mirror faster than MIN_REFRESH_SECONDS. */
export function clampRefresh(body: string): string {
  try {
    const obj = JSON.parse(body) as Record<string, unknown>;
    if (typeof obj.refresh_seconds === "number" && obj.refresh_seconds < MIN_REFRESH_SECONDS) {
      obj.refresh_seconds = MIN_REFRESH_SECONDS;
      return JSON.stringify(obj);
    }
  } catch {
    /* not JSON: leave as is */
  }
  return body;
}

export function chunk(entries: Entry[], maxEntries = CHUNK_ENTRIES, maxChars = CHUNK_CHARS): Entry[][] {
  const out: Entry[][] = [];
  let cur: Entry[] = [];
  let size = 0;
  for (const e of entries) {
    const n = e.key.length + e.body.length;
    if (cur.length && (cur.length >= maxEntries || size + n > maxChars)) {
      out.push(cur);
      cur = [];
      size = 0;
    }
    cur.push(e);
    size += n;
  }
  if (cur.length) out.push(cur);
  return out;
}
