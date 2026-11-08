import type { GameCard, GameResult, TeamResponse } from "../api/types";
import { addDays, etToday, makeCard } from "./scoreboard";
import { FOLLOWED, TEAMS, standingRows, teamByAbbr, teamRef } from "./teams";

/** Extra games referenced from team pages, so tapping a result can open its box score. */
export const extraGames = new Map<string, GameCard>();

function hash(s: string) {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0;
  return Math.abs(h);
}

function resultSequence(wins: number, losses: number, streak: string): ("W" | "L")[] {
  const kind = streak[0] as "W" | "L";
  const len = Number(streak.slice(1));
  const seq: ("W" | "L")[] = [];
  let w = wins, l = losses;
  // Before the streak: the game that broke the previous streak is the opposite result.
  const tail = Array.from({ length: len }, () => kind);
  if (kind === "W") w -= len; else l -= len;
  const breaker = kind === "W" ? "L" : "W";
  if ((breaker === "L" ? l : w) > 0) {
    if (breaker === "L") l--; else w--;
    tail.unshift(breaker);
  }
  while (w > 0 || l > 0) {
    if (w >= l && w > 0) { seq.push("W"); w--; } else { seq.push("L"); l--; }
  }
  return [...seq, ...tail];
}

export function teamPage(abbr: string): TeamResponse | null {
  const t = teamByAbbr(abbr);
  if (!t) return null;
  const others = TEAMS.filter((o) => o.abbr !== t.abbr);
  const h = hash(t.abbr);
  const today = etToday();
  const seq = resultSequence(t.wins, t.losses, t.streak).slice(-10);

  const recent: GameResult[] = seq
    .map((res, i) => {
      const daysAgo = (seq.length - i) * 2;
      const date = addDays(today, -daysAgo);
      const opp = others[(h + i * 7) % others.length];
      const home = (h + i) % 2 === 0;
      const ours = 100 + ((h + i * 13) % 25);
      const margin = 1 + ((h + i * 5) % 14);
      const theirs = res === "W" ? ours - margin : ours + margin;
      const id = `4018${String(h % 1000).padStart(3, "0")}${String(i).padStart(2, "0")}`;
      const [aw, hm] = home ? [opp.abbr, t.abbr] : [t.abbr, opp.abbr];
      const [aScore, hScore] = home ? [theirs, ours] : [ours, theirs];
      const q = (n: number) => { const b = Math.floor(n / 4); return [b + 2, b - 1, b + 1, n - 4 * b - 2]; };
      extraGames.set(id, makeCard(date, {
        id, away: aw, home: hm, time: "19:00", state: "post", status: "STATUS_FINAL",
        status_text: "Final", period: 4, clock: "0.0", awayLines: q(aScore), homeLines: q(hScore),
      }));
      return {
        id,
        date: `${date}T19:00:00-08:00`,
        opponent: opp.abbr,
        home,
        result: res,
        score: `${ours}-${theirs}`,
        status_text: "Final",
      };
    })
    .reverse(); // most recent first

  const upcoming: GameResult[] = Array.from({ length: 5 }, (_, i) => {
    const date = addDays(today, 1 + i * 2);
    const opp = others[(h + 3 + i * 5) % others.length];
    const home = (h + i) % 2 === 1;
    const time = ["16:00", "17:00", "19:00", "19:30"][(h + i) % 4];
    const id = `4019${String(h % 1000).padStart(3, "0")}${String(i).padStart(2, "0")}`;
    const card = makeCard(date, {
      id, away: home ? opp.abbr : t.abbr, home: home ? t.abbr : opp.abbr, time, state: "pre",
      status: "STATUS_SCHEDULED", broadcasts: ["NBA League Pass"],
    });
    extraGames.set(id, card);
    return { id, date: card.start_time, opponent: opp.abbr, home, result: null, score: null, status_text: card.status_text };
  });

  const standing = standingRows(t.conference as "East" | "West").find((r) => r.abbr === t.abbr)!;
  return { team: teamRef(t.abbr), standing, recent, upcoming };
}

export const followedAbbrs = () => FOLLOWED;
