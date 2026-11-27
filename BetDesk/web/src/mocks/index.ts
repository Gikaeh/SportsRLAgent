// Mock API used when VITE_MOCK=1. Responses follow docs/API.md exactly.
//
// Add `?mock=busy` to the page URL (before the #) to make the warehouse endpoints
// (/api/standings, /api/teams/*) return 503 {"error": "warehouse_busy"}.
// Add `?mock=error` to make every endpoint fail with a 500.
// v2: `?mock=busy` also makes /api/predictions/record 503 and every `prediction` null (as the server does).
// `?mock=record0` returns a model record with 0 graded games. `?mock=v1` mimics a pre-v2 server
// (ignores league=, no league/prediction fields, no /api/predictions/record).
// v3: `?mock=noplays` mimics a pre-v3 server: game detail has no `plays`/`possession` fields.
// Picks: `?mock=nopicks` (./picks.ts).
// `?mock=flaky` makes every 4th game-detail poll fail with a 404, as the server does when an ESPN fetch fails.
import type { GameCard, League, ScoreboardResponse, StandingsResponse } from "../api/types";
import { gameDetail } from "./boxscore";
import { picksToday } from "./picks";
import { advanceLive, playsFor, possessionFor } from "./plays";
import { predictionRecord } from "./record";
import { allKnownCards, etToday, nextFollowedGame, slateFor } from "./scoreboard";
import { extraGames, followedAbbrs, teamPage } from "./teamPage";
import { FOLLOWED_NCAAB, TEAMS, standingRows } from "./teams";

/** Apply the mode switches to a card: busy => no predictions; v1 => strip v2 fields. */
function shape(card: GameCard, mode: string | null): GameCard {
  if (mode === "v1") {
    const { league: _l, prediction: _p, ...rest } = card;
    return rest;
  }
  return mode === "busy" ? { ...card, prediction: null } : card;
}

let detailPolls = 0;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const mockMode = () => new URLSearchParams(window.location.search).get("mock");

function delay(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });
}

export async function mockFetch(path: string, signal?: AbortSignal): Promise<Response> {
  await delay(250 + Math.random() * 300, signal);
  const url = new URL(path, window.location.origin);
  const p = url.pathname;
  const mode = mockMode();
  if (mode === "error") return json({ error: "upstream_error" }, 500);
  const warehouse = p === "/api/standings" || p.startsWith("/api/teams/") || p === "/api/predictions/record";
  const lgParam = url.searchParams.get("league");
  if (lgParam && lgParam !== "nba" && lgParam !== "ncaab") return json({ detail: "bad league" }, 422);
  const league: League = mode === "v1" ? "nba" : ((lgParam as League | null) ?? "nba");
  if (warehouse && mode === "busy") return json({ error: "warehouse_busy" }, 503);

  if (p === "/api/picks/today") return json(picksToday());

  if (p === "/api/health") {
    return json({ ok: true, warehouse: mode === "busy" ? "busy" : "ok", now: new Date().toISOString() });
  }
  if (p === "/api/followed") {
    if (mode === "v1") return json({ teams: followedAbbrs() });
    return json({ teams: followedAbbrs(), by_league: { nba: followedAbbrs(), ncaab: FOLLOWED_NCAAB } });
  }

  if (p === "/api/predictions/record") {
    if (mode === "v1") return json({ detail: "Not Found" }, 404);
    if ((url.searchParams.get("league") ?? "nba") === "ncaab") return json(predictionRecord(30, true));
    const days = Number(url.searchParams.get("days") ?? 30) || 30;
    return json(predictionRecord(days, mode === "record0"));
  }

  if (p === "/api/parlays") {
    const t = (h: number) => new Date(Date.now() + h * 3600_000).toISOString();
    const leg = (id: string, label: string, matchup: string, h: number, state: "pre" | "in" | "post", status: "won" | "lost" | "push" | "pending", away: number | null, home: number | null, note: string | null, text: string) =>
      ({ game_id: id, label, matchup, start_time: t(h), state, status_text: text, away_score: away, home_score: home, status, note });
    const legs = [
      leg("m1", "Over 145.5", "Eastern Michigan Eagles @ Kennesaw State Owls", -3, "post", "won", 78, 74, "152 pts", "Final"),
      leg("m2", "Under 161.5", "Creighton Bluejays @ Michigan Wolverines", -1, "in", "pending", 52, 48, "100 pts, 61.5 under", "2nd 12:40"),
      leg("m3", "Over 134.5", "DePaul Blue Demons @ Purdue Boilermakers", -1, "in", "won", 70, 66, "136 pts", "2nd 3:10"),
      leg("m4", "Under 173.5", "Baylor Bears @ Alabama Crimson Tide", 3, "pre", "pending", null, null, null, "7:00 PM"),
    ];
    const count = (s: string) => legs.filter((l) => l.status === s).length;
    const parlay = { id: "28", placed_at: t(-20), book: "WilliamHill", tier: "lotto", price: 9142, status: "alive", won: count("won"), lost: 0, push: 0, pending: count("pending"), legs };
    const lost = { ...parlay, id: "31", price: 9144, status: "alive", lost: 1, won: 0, pending: 3, legs: [{ ...legs[0], status: "lost", label: "Under 145.5" }, ...legs.slice(1)] };
    lost.status = "lost";
    return json({ parlays: mode === "empty" ? [] : [parlay, lost], live: true, refresh_seconds: 30 });
  }

  if (p === "/api/bets") {
    const games = slateFor(etToday(), "nba")
      .filter((g) => g.bets?.length)
      .map((g) => shape(advanceLive(g), mode));
    games.sort((a, b) => ({ in: 0, pre: 1, post: 2 }[a.state] ?? 3) - ({ in: 0, pre: 1, post: 2 }[b.state] ?? 3));
    const live = games.some((g) => g.state === "in");
    return json({ games, live, refresh_seconds: live ? 5 : 300 });
  }

  if (p === "/api/scoreboard") {
    const date = url.searchParams.get("date") ?? etToday();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return json({ error: "bad_date" }, 400);
    const games = slateFor(date, league).map((g) => shape(advanceLive(g), mode));
    const live = games.some((g) => g.state === "in");
    const body: ScoreboardResponse = { date, games, live, refresh_seconds: live ? 30 : 300 };
    if (mode !== "v1" && date === etToday()) {
      const next = nextFollowedGame(league);
      body.next_followed_game = next ? shape(next, mode) : null;
    }
    return json(body);
  }

  const gm = p.match(/^\/api\/games\/([^/]+)$/);
  if (gm) {
    if (mode === "flaky" && ++detailPolls % 4 === 0) return json({ detail: "Game not found" }, 404);
    const id = decodeURIComponent(gm[1]);
    let card = allKnownCards().find((g) => g.id === id) ?? extraGames.get(id);
    if (!card) {
      // Deep link to a team-page game after a reload: regenerate those games.
      TEAMS.forEach((t) => teamPage(t.abbr));
      card = extraGames.get(id);
    }
    if (card && mode !== "v1" && (card.league ?? "nba") !== league) card = undefined; // wrong league => 404
    if (!card) return json({ detail: "Game not found" }, 404);
    const now = advanceLive(card);
    const body = gameDetail(shape(now, mode));
    if (mode === "v1" || mode === "noplays") return json(body);
    // Short refresh so the live screen visibly moves (the real server sends 10 during a live game).
    const refresh_seconds = now.state === "in" ? 5 : body.refresh_seconds;
    return json({ ...body, refresh_seconds, plays: playsFor(now), possession: possessionFor(now) });
  }

  if (p === "/api/standings") {
    const body: StandingsResponse = {
      season: "2026-27",
      conferences: [
        { name: "East", teams: standingRows("East") },
        { name: "West", teams: standingRows("West") },
      ],
    };
    return json(body);
  }

  const tm = p.match(/^\/api\/teams\/([^/]+)$/);
  if (tm) {
    const body = teamPage(decodeURIComponent(tm[1]));
    return body ? json(body) : json({ error: "not_found" }, 404);
  }

  if (p === "/api/glance") {
    const lines = [...slateFor(etToday()), ...(mode === "v1" ? [] : slateFor(etToday(), "ncaab"))]
      .filter((g) => g.followed)
      .map((g) =>
        g.state === "pre" || g.away.score == null
          ? `${g.away.abbr} @ ${g.home.abbr}  ${g.status_text}`
          : `${g.away.abbr} ${g.away.score}-${g.home.score} ${g.home.abbr}  ${g.status_text}`.slice(0, 30),
      );
    return json({ lines, refresh_seconds: 30 });
  }

  return json({ error: "not_found" }, 404);
}
