// Play-by-play fixtures (v3). Each game gets one seeded timeline whose scoring adds up exactly to its
// linescores. A live game reveals its timeline over time, and its card (score, clock, linescore) is
// derived from the plays revealed so far, so scoreboard, header and feed always agree.
import type { GameCard, GameTeam, Play, Possession } from "../api/types";
import { rng } from "./boxscore";
import { rosterFor } from "./rosters";

const T0 = Date.now();
const MS_PER_PLAY = 2500; // about two new plays per 5-second poll
const LIVE_START = 0.62; // live games open about here in their timeline

type Rand = () => number;
const pick = <T,>(r: Rand, xs: T[]) => xs[Math.floor(r() * xs.length)];
const isCollege = (g: GameCard) => g.league === "ncaab";

function shotCoord(r: Rand, three: boolean, college: boolean) {
  const dist = three ? (college ? 22.5 : 24) + r() * 4 : 1 + r() * r() * 19;
  const angle = r() * Math.PI;
  const x = Math.min(50, Math.max(0, 25 + dist * Math.cos(angle)));
  const y = dist * Math.sin(angle);
  return { dist: Math.round(dist), coord: { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 } };
}

/** Split a period's points into baskets: 3s, 2s, and the odd free throw. */
function baskets(r: Rand, points: number): number[] {
  const out: number[] = [];
  let left = points;
  while (left > 0) {
    const roll = r();
    const v = left >= 3 && roll < 0.28 ? 3 : left >= 2 && roll < 0.86 ? 2 : 1;
    out.push(v);
    left -= v;
  }
  return out;
}

type Draft = Pick<Play, "text" | "team_id" | "points" | "kind" | "coord">;

function periodPlays(r: Rand, g: GameCard, period: number, awayPts: number, homePts: number): Draft[] {
  const college = isCollege(g);
  const left: Record<string, number[]> = { [g.away.id]: baskets(r, awayPts), [g.home.id]: baskets(r, homePts) };
  const out: Draft[] = [];
  const name = (t: GameTeam) => pick(r, rosterFor(t.abbr).slice(0, 9));
  let turn = r() < 0.5 ? g.away : g.home;
  const other = (t: GameTeam) => (t.id === g.away.id ? g.home : g.away);

  while (left[g.away.id].length > 0 || left[g.home.id].length > 0) {
    const team = turn;
    const rival = other(team);
    const queue = left[team.id];
    if (queue.length > 0 && r() < 0.52) {
      const pts = queue.pop()!;
      if (pts === 1) {
        out.push({ text: `${name(rival)} shooting foul`, team_id: rival.id, points: 0, kind: "foul", coord: null });
        out.push({ text: `${name(team)} makes free throw`, team_id: team.id, points: 1, kind: "free_throw_made", coord: null });
      } else {
        const { dist, coord } = shotCoord(r, pts === 3, college);
        const shot = pts === 3 ? "three point jumper" : dist < 4 ? "driving layup" : `${dist}-foot jumper`;
        const assist = r() < 0.5 ? ` (${name(team)} assists)` : "";
        out.push({ text: `${name(team)} makes ${shot}${assist}`, team_id: team.id, points: pts, kind: "shot_made", coord });
      }
      turn = rival;
      continue;
    }
    const roll = r();
    if (roll < 0.58) {
      const three = r() < 0.42;
      const { dist, coord } = shotCoord(r, three, college);
      const shot = three ? "three point jumper" : dist < 4 ? "layup" : `${dist}-foot jumper`;
      out.push({ text: `${name(team)} misses ${shot}`, team_id: team.id, points: 0, kind: "shot_missed", coord });
      const offensive = r() < 0.26;
      const reb = offensive ? team : rival;
      out.push({ text: `${name(reb)} ${offensive ? "offensive" : "defensive"} rebound`, team_id: reb.id, points: 0, kind: "rebound", coord: null });
      turn = reb;
    } else if (roll < 0.76) {
      // Real quirks: ESPN text can hold a newline, and college steals arrive as their own "other" play.
      const how = r() < 0.5 ? "Bad Pass\nTurnover" : "Traveling\nTurnover";
      out.push({ text: `${name(team)} ${how}`, team_id: team.id, points: 0, kind: "turnover", coord: null });
      if (college) out.push({ text: `${name(rival)} Steal`, team_id: rival.id, points: 0, kind: "other", coord: null });
      turn = rival;
    } else if (roll < 0.86) {
      out.push({ text: `${name(rival)} personal foul`, team_id: rival.id, points: 0, kind: "foul", coord: null });
      out.push({ text: `${name(team)} misses free throw`, team_id: team.id, points: 0, kind: "free_throw_missed", coord: null });
      out.push({ text: `${name(rival)} defensive rebound`, team_id: rival.id, points: 0, kind: "rebound", coord: null });
      turn = rival;
    } else if (roll < 0.93) {
      out.push({ text: `${name(team)} enters the game for ${name(team)}`, team_id: team.id, points: 0, kind: "substitution", coord: null });
    } else if (r() < 0.6) {
      out.push({ text: `${team.short_name} timeout`, team_id: team.id, points: 0, kind: "timeout", coord: null });
    } else {
      out.push({ text: "Official timeout", team_id: null, points: 0, kind: "timeout", coord: null });
    }
  }
  const reg = college ? 2 : 4;
  const label = period > reg ? "overtime" : college ? `half ${period}` : `quarter ${period}`;
  out.push({ text: `End of ${label}`, team_id: null, points: 0, kind: "period_end", coord: null });
  return out;
}

const fmtClock = (secs: number) => `${Math.floor(secs / 60)}:${String(Math.floor(secs % 60)).padStart(2, "0")}`;

const cache = new Map<string, Play[]>();

/** The whole game's plays. A live card's lines are placeholders, so its final score is seeded instead. */
function timeline(g: GameCard): Play[] {
  const hit = cache.get(g.id);
  if (hit) return hit;
  const r = rng(Number(g.id) % 100000);
  const college = isCollege(g);
  const reg = college ? 2 : 4;
  const seeded = () => Array.from({ length: reg }, () => (college ? 28 : 20) + Math.floor(r() * 15));
  const live = g.state === "in";
  const awayLines = live ? seeded() : g.away.linescores;
  const homeLines = live ? seeded() : g.home.linescores;
  if (live && awayLines.reduce((a, b) => a + b, 0) === homeLines.reduce((a, b) => a + b, 0)) homeLines[reg - 1] += 2;

  const plays: Play[] = [];
  let seq = 1000;
  let away = 0;
  let home = 0;
  awayLines.forEach((awayPts, i) => {
    const period = i + 1;
    const drafts = periodPlays(r, g, period, awayPts, homeLines[i] ?? 0);
    const secs = period > reg ? 300 : college ? 1200 : 720;
    drafts.forEach((d, j) => {
      const isEnd = d.kind === "period_end";
      if (d.team_id === g.away.id) away += d.points;
      if (d.team_id === g.home.id) home += d.points;
      seq += 5;
      plays.push({
        ...d,
        id: `${g.id}-${seq}`,
        seq,
        period,
        clock: fmtClock(isEnd ? 0 : secs * (1 - (j + 1) / drafts.length)),
        away_score: away,
        home_score: home,
        scoring: d.points > 0,
      });
    });
  });
  cache.set(g.id, plays);
  return plays;
}

function revealed(all: Play[]): number {
  return Math.min(all.length, Math.floor(all.length * LIVE_START) + Math.floor((Date.now() - T0) / MS_PER_PLAY));
}

/** A live card with its score/clock/linescore from the plays so far; "post" once the timeline runs out. */
export function advanceLive(card: GameCard): GameCard {
  if (card.state !== "in") return card;
  const all = timeline(card);
  const n = revealed(all);
  const shown = all.slice(0, n);
  const last = shown[n - 1];
  const college = isCollege(card);
  const lines = (side: "away_score" | "home_score", team: GameTeam) => {
    const out: number[] = [];
    let prev = 0;
    for (let p = 1; p <= last.period; p++) {
      const inPeriod = shown.filter((x) => x.period === p);
      const end = inPeriod.length ? inPeriod[inPeriod.length - 1][side] : prev;
      out.push(end - prev);
      prev = end;
    }
    return { ...team, score: last[side], linescores: out };
  };
  const ended = n === all.length;
  const p = last.period;
  const label = college ? `${p === 1 ? "1st" : p === 2 ? "2nd" : "OT"}` : p > 4 ? "OT" : `Q${p}`;
  return {
    ...card,
    state: ended ? "post" : "in",
    status: ended ? "STATUS_FINAL" : last.kind === "period_end" ? "STATUS_END_PERIOD" : "STATUS_IN_PROGRESS",
    status_text: ended ? "Final" : last.kind === "period_end" ? `End of ${label}` : `${label} ${last.clock}`,
    period: p,
    clock: last.clock,
    away: lines("away_score", card.away),
    home: lines("home_score", card.home),
  };
}

export function playsFor(card: GameCard): Play[] {
  if (card.state === "pre" || card.away.linescores.length === 0) return [];
  const all = timeline(card);
  return card.state === "in" ? all.slice(0, revealed(all)) : all;
}

/** Who has the ball after the latest play. NBA reports "inferred", college "espn", to exercise both. */
export function possessionFor(card: GameCard): Possession | null {
  if (card.state !== "in") return null;
  const plays = playsFor(card);
  const last = plays[plays.length - 1];
  if (!last || !last.team_id || last.kind === "period_end" || last.kind === "timeout") return null;
  const rival = last.team_id === card.away.id ? card.home.id : card.away.id;
  const keeps = last.kind === "other" || last.kind === "rebound" || last.kind === "shot_missed" || last.kind === "substitution" || last.kind === "free_throw_missed";
  const fouled = last.kind === "foul" ? rival : null;
  const team_id = fouled ?? (keeps ? last.team_id : rival);
  return { team_id, source: isCollege(card) ? "espn" : "inferred" };
}
