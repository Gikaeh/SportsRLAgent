import type { GameCard, GameDetailResponse, PlayerLine, TeamBox } from "../api/types";
import { rosterFor } from "./rosters";

function rng(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const STARTER_MIN = [34, 33, 32, 30, 28];
const BENCH_MIN = [24, 20, 17, 14, 10, 6, 0, 0];

function elapsedFraction(g: GameCard): number {
  if (g.league === "ncaab") {
    // Two 20-minute halves; scaled so minutes stay under 40.
    const k = 40 / 48;
    if (g.state === "post") return k * ((g.period ?? 2) > 2 ? 45 / 40 : 1);
    if (g.state !== "in" || !g.period) return 0;
    const [m, s] = (g.clock ?? "20:00").split(":").map(Number);
    const left = (m || 0) + (s || 0) / 60;
    return k * Math.min(1, (Math.min(g.period, 2) - 1 + (20 - left) / 20) / 2);
  }
  if (g.state === "post") return (g.period ?? 4) > 4 ? 53 / 48 : 1;
  if (g.state !== "in" || !g.period) return 0;
  const [m, s] = (g.clock ?? "12:00").split(":").map(Number);
  const left = (m || 0) + (s || 0) / 60;
  return Math.min(1, (Math.min(g.period, 4) - 1 + (12 - left) / 12) / 4);
}

function buildTeam(abbr: string, teamId: string, score: number, margin: number, frac: number, seed: number) {
  const r = rng(seed);
  const names = rosterFor(abbr);
  const players: PlayerLine[] = names.map((name, i) => {
    const starter = i < 5;
    const baseMin = starter ? STARTER_MIN[i] : BENCH_MIN[i - 5];
    const dnp = baseMin === 0;
    const minutes = dnp ? 0 : Math.max(1, Math.round(baseMin * frac + (r() * 4 - 2)));
    const fga = dnp ? 0 : Math.round(minutes * (0.3 + r() * 0.2));
    const fgm = Math.round(fga * (0.38 + r() * 0.18));
    const fg3a = Math.round(fga * (0.25 + r() * 0.25));
    const fg3m = Math.min(fgm, Math.round(fg3a * (0.28 + r() * 0.15)));
    const fta = dnp ? 0 : Math.round(minutes * r() * 0.15);
    const ftm = Math.round(fta * (0.7 + r() * 0.25));
    const z = (k: number) => (dnp ? 0 : Math.round(minutes * k * (0.6 + r() * 0.8)));
    return {
      athlete_id: `${teamId}${String(i).padStart(3, "0")}`,
      name, starter, did_not_play: dnp,
      dnp_reason: dnp ? (i === names.length - 1 ? "Coach's Decision" : "Injury/Illness - Left Ankle; Sprain") : null,
      minutes: dnp ? null : minutes,
      pts: 0, reb: z(0.17), ast: z(0.11), stl: z(0.03), blk: z(0.02), tov: z(0.05), pf: z(0.06),
      fgm, fga, fg3m, fg3a, ftm, fta,
      plus_minus: dnp ? null : Math.round((margin * minutes) / 48 + (r() * 10 - 5)),
    };
  });
  const active = players.filter((p) => !p.did_not_play);
  const points = (p: PlayerLine) => 2 * (p.fgm ?? 0) + (p.fg3m ?? 0) + (p.ftm ?? 0);
  // Nudge free throws/field goals so the players add up to the team score exactly.
  let total = active.reduce((a, p) => a + points(p), 0);
  let guard = 0;
  while (total !== score && guard++ < 500) {
    const p = active[Math.floor(r() * Math.min(active.length, 7))];
    if (total < score) {
      p.ftm = (p.ftm ?? 0) + 1;
      p.fta = (p.fta ?? 0) + 1;
      total += 1;
    } else if (total - score >= 2 && (p.fgm ?? 0) > (p.fg3m ?? 0)) {
      p.fgm = (p.fgm ?? 0) - 1;
      total -= 2;
    } else if ((p.ftm ?? 0) > 0) {
      p.ftm = (p.ftm ?? 0) - 1;
      p.fta = (p.fta ?? 0) - 1; // keep FT% realistic: drop the attempt too
      total -= 1;
    }
  }
  for (const p of players) {
    if (p.did_not_play) {
      for (const k of ["pts", "reb", "ast", "stl", "blk", "tov", "pf", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta"] as const) p[k] = null;
    } else {
      p.pts = points(p);
    }
  }
  const s = (k: keyof PlayerLine) => active.reduce((a, p) => a + ((p[k] as number | null) ?? 0), 0);
  const reb = s("reb");
  const oreb = Math.round(reb * 0.24);
  const box: TeamBox = {
    team_id: teamId, abbr,
    fgm: s("fgm"), fga: s("fga"), fg3m: s("fg3m"), fg3a: s("fg3a"), ftm: s("ftm"), fta: s("fta"),
    oreb, dreb: reb - oreb, reb, ast: s("ast"), stl: s("stl"), blk: s("blk"), tov: s("tov"), pf: s("pf"),
    points_in_paint: 2 * Math.round((s("fgm") - s("fg3m")) * 0.6),
    fast_break_points: Math.round(score * (0.08 + r() * 0.08)),
  };
  return { box, players };
}

export function gameDetail(g: GameCard): GameDetailResponse {
  const refresh_seconds = g.state === "in" ? 30 : 300;
  if (g.state === "pre" || g.away.score == null || g.home.score == null) {
    return { game: g, teams: [], players: {}, refresh_seconds };
  }
  const frac = elapsedFraction(g);
  const seed = Number(g.id) % 100000;
  const away = buildTeam(g.away.abbr, g.away.id, g.away.score, g.away.score - g.home.score, frac, seed);
  const home = buildTeam(g.home.abbr, g.home.id, g.home.score, g.home.score - g.away.score, frac, seed + 7);
  return {
    game: g,
    teams: [away.box, home.box],
    players: { [g.away.id]: away.players, [g.home.id]: home.players },
    refresh_seconds,
  };
}
