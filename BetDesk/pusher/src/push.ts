// BetDesk pusher: reads the DeepSports read API on this Mac and pushes snapshots to the BetDesk Worker.
// Runs every minute from launchd (../tools/launchd); decides itself whether there is anything to push.
//
//   node --experimental-strip-types pusher/src/push.ts [--dry-run] [--full]
//
// Env: DEEPSPORTS_API (default http://localhost:8787), BETDESK_URL, BETDESK_INGEST_TOKEN,
//      CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET, BETDESK_STATE (state file path).
// Secrets come from the Keychain via tools/pusher.sh; never put them in files.

import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import {
  chunk,
  clampRefresh,
  decide,
  easternDate,
  gameKeys,
  isLive,
  LEAGUES,
  scoreboardKey,
  scoreboardKeys,
  type Entry,
  type League,
  type State,
} from "./plan.ts";

const args = new Set(process.argv.slice(2));
const DRY = args.has("--dry-run");
const FORCE = args.has("--full");
const API = (process.env.DEEPSPORTS_API ?? "http://localhost:8787").replace(/\/+$/, "");
const STATE_FILE = process.env.BETDESK_STATE ?? join(homedir(), "Library/Application Support/BetDesk/pusher-state.json");

type Got = { key: string; status: number; body: string | null };

async function get(key: string): Promise<Got> {
  try {
    const res = await fetch(API + key, { headers: { Accept: "application/json" }, signal: AbortSignal.timeout(20_000) });
    return { key, status: res.status, body: res.ok ? await res.text() : null };
  } catch {
    return { key, status: 0, body: null };
  }
}

/** Fetch keys a few at a time (the local server talks to ESPN for live endpoints). */
async function getAll(keys: string[], concurrency = 4): Promise<Got[]> {
  const out: Got[] = [];
  let i = 0;
  await Promise.all(
    Array.from({ length: concurrency }, async () => {
      while (i < keys.length) out.push(await get(keys[i++]));
    }),
  );
  return out;
}

const parse = <T>(s: string | null): T | null => {
  if (s == null) return null;
  try {
    return JSON.parse(s) as T;
  } catch {
    return null;
  }
};

async function loadState(): Promise<State> {
  try {
    return JSON.parse(await readFile(STATE_FILE, "utf8")) as State;
  } catch {
    return {};
  }
}

async function saveState(s: State): Promise<void> {
  await mkdir(dirname(STATE_FILE), { recursive: true });
  const tmp = `${STATE_FILE}.tmp`;
  await writeFile(tmp, JSON.stringify(s));
  await rename(tmp, STATE_FILE);
}

async function main(): Promise<number> {
  const now = new Date();
  const state = await loadState();

  const health = await get("/api/health");
  if (health.status !== 200) {
    console.log(`push: skipped, DeepSports API unreachable at ${API} (status ${health.status})`);
    return 1;
  }

  // Cheap first look: is anything live? (yesterday covers games past midnight Eastern)
  const firstKeys = [...scoreboardKeys(now, false), "/api/bets"];
  const first = await getAll(firstKeys);
  const lists = first.filter((g) => g.key !== "/api/bets").map((g) => parse<{ games?: never[]; live?: boolean }>(g.body) ?? {});
  const betsBody = parse<{ games?: never[]; live?: boolean }>(first.find((g) => g.key === "/api/bets")?.body ?? null);
  const live = isLive([...lists, betsBody ?? {}]);

  const { push, full } = decide(state, now, live, FORCE);
  if (!push) {
    console.log(state.lastFailAt && !full ? "push: backing off after a failed push" : "push: idle (nothing live, full push not due)");
    return 0;
  }

  const fetched = new Map<string, Got>(first.map((g) => [g.key, g]));
  const more: string[] = [];
  if (full) {
    more.push(...scoreboardKeys(now, true).filter((k) => !fetched.has(k)));
    more.push("/api/standings", "/api/followed", "/api/predictions/record?league=nba&days=30");
  }
  for (const g of await getAll(more)) fetched.set(g.key, g);

  if (full) {
    const standings = parse<{ conferences?: { teams?: { abbr: string }[] }[] }>(fetched.get("/api/standings")?.body ?? null);
    const teamKeys = (standings?.conferences ?? []).flatMap((c) => (c.teams ?? []).map((t) => `/api/teams/${encodeURIComponent(t.abbr)}`));
    for (const g of await getAll(teamKeys)) fetched.set(g.key, g);
  }

  // Game pages, from yesterday's to tomorrow's scoreboards (with their league) plus open bets.
  const pageDates = new Set([-1, 0, 1].map((o) => easternDate(now, o)));
  const boards: { league: League; body: { games?: never[] } }[] = [];
  for (const [key, g] of fetched) {
    if (!key.startsWith("/api/scoreboard")) continue;
    const date = new URLSearchParams(key.split("?")[1]).get("date");
    if (date && !pageDates.has(date)) continue;
    const league = (LEAGUES.find((l) => key.includes(`league=${l}`)) ?? "nba") as League;
    const body = parse<{ games?: never[] }>(g.body);
    if (body) boards.push({ league, body });
  }
  const finals = new Set(state.finalsPushed ?? []);
  const gks = gameKeys(boards, betsBody, full, finals);
  const games = await getAll(gks);
  for (const g of games) fetched.set(g.key, g);

  let warehouse: "ok" | "busy" = "ok";
  const entries: Entry[] = [];
  const failed: string[] = [];
  for (const g of fetched.values()) {
    if (g.body != null) entries.push({ key: g.key, body: clampRefresh(g.body) });
    else {
      if (g.status === 503) warehouse = "busy"; // keep the mirror's last good copy
      failed.push(`${g.key} (${g.status})`);
    }
  }
  // Mirror today's no-date scoreboard under the dated key too, so both URLs the app may use exist.
  for (const l of LEAGUES) {
    const today = fetched.get(scoreboardKey(l));
    const date = parse<{ date?: string }>(today?.body ?? null)?.date;
    if (today?.body && date && !fetched.get(scoreboardKey(l, date))?.body) entries.push({ key: scoreboardKey(l, date), body: clampRefresh(today.body) });
  }

  const chunks = chunk(entries);
  const chars = entries.reduce((n, e) => n + e.body.length, 0);
  const summary = `full=${full} live=${live} entries=${entries.length} games=${gks.length} kb=${Math.round(chars / 1024)} chunks=${chunks.length} warehouse=${warehouse}`;
  if (DRY) {
    for (const e of entries) console.log(`  ${e.key}  ${Math.round(e.body.length / 1024)} KB`);
    if (failed.length) console.log(`  not available: ${failed.join(", ")}`);
    console.log(`push: dry run, ${summary}`);
    return 0;
  }

  const url = process.env.BETDESK_URL?.replace(/\/+$/, "");
  const token = process.env.BETDESK_INGEST_TOKEN;
  if (!url || !token) {
    console.log("push: FAILED, BETDESK_URL and BETDESK_INGEST_TOKEN must be set (see BetDesk/docs/SETUP.md)");
    return 2;
  }
  const headers: Record<string, string> = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  if (process.env.CF_ACCESS_CLIENT_ID && process.env.CF_ACCESS_CLIENT_SECRET) {
    headers["CF-Access-Client-Id"] = process.env.CF_ACCESS_CLIENT_ID;
    headers["CF-Access-Client-Secret"] = process.env.CF_ACCESS_CLIENT_SECRET;
  }
  const generated_at = now.toISOString();
  for (const [i, c] of chunks.entries()) {
    let res: Response;
    try {
      res = await fetch(`${url}/ingest`, {
        method: "POST",
        headers,
        body: JSON.stringify({ generated_at, warehouse, final: i === chunks.length - 1, entries: c }),
        redirect: "manual",
        signal: AbortSignal.timeout(30_000),
      });
    } catch (e) {
      console.log(`push: FAILED chunk ${i + 1}/${chunks.length}: ${(e as Error).message}`);
      await saveState({ ...state, lastFailAt: generated_at });
      return 1;
    }
    if (!res.ok) {
      const hint = res.status >= 300 && res.status < 400 ? " (redirected to login: check the Access service token)" : "";
      console.log(`push: FAILED chunk ${i + 1}/${chunks.length}: HTTP ${res.status}${hint} ${(await res.text()).slice(0, 200)}`);
      await saveState({ ...state, lastFailAt: generated_at });
      return 1;
    }
  }

  for (const g of games) {
    const body = parse<{ game?: { state?: string } }>(g.body);
    if (body?.game?.state === "post") finals.add(g.key);
  }
  await saveState({
    lastPushAt: generated_at,
    lastFullAt: full ? generated_at : state.lastFullAt,
    finalsPushed: [...finals].slice(-300),
  });
  console.log(`push: ok, ${summary}${failed.length ? ` skipped=${failed.length}` : ""}`);
  return 0;
}

main().then(
  (code) => process.exit(code),
  (e) => {
    console.log(`push: FAILED, ${(e as Error).stack ?? e}`);
    process.exit(1);
  },
);
