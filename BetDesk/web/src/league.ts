import { useSyncExternalStore } from "react";
import type { GameCard, League } from "./api/types";

const KEY = "deepsports.league";
const listeners = new Set<() => void>();

export const isLeague = (v: unknown): v is League => v === "nba" || v === "ncaab";

function read(): League {
  try {
    const v = window.localStorage.getItem(KEY);
    return isLeague(v) ? v : "nba";
  } catch {
    return "nba"; // private mode / blocked storage
  }
}

let current: League = read();

/** Remember the Today screen's league choice (best effort). */
export function setLeague(league: League) {
  if (league === current) return;
  current = league;
  try {
    window.localStorage.setItem(KEY, league);
  } catch {
    /* storage unavailable: the choice lasts for this visit only */
  }
  listeners.forEach((l) => l());
}

export function useLeague(): League {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => current,
  );
}

/** A v1 server has no `league` field; everything it returns is NBA. */
export const gameLeague = (g: GameCard): League => g.league ?? "nba";

export const LEAGUE_LABEL: Record<League, string> = { nba: "NBA", ncaab: "College" };

/** NBA: four 12-minute quarters. College: two 20-minute halves. */
export function regulationPeriods(league: League): number {
  return league === "ncaab" ? 2 : 4;
}

export function periodLabel(i: number, league: League = "nba"): string {
  const reg = regulationPeriods(league);
  if (i < reg) return league === "ncaab" ? `H${i + 1}` : String(i + 1);
  return i === reg ? "OT" : `${i - reg + 1}OT`;
}

/** A play's 1-based period, compactly: "Q3", "H2", "OT", "2OT". */
export function periodShort(period: number, league: League = "nba"): string {
  if (period <= regulationPeriods(league)) return `${league === "ncaab" ? "H" : "Q"}${period}`;
  return periodLabel(period - 1, league);
}

const ORDINALS = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th"];

/** A play's 1-based period in words: "3rd quarter", "2nd half", "Overtime", "2nd overtime". */
export function periodName(period: number, league: League = "nba"): string {
  const reg = regulationPeriods(league);
  const nth = (n: number) => ORDINALS[n - 1] ?? `${n}th`;
  if (period <= reg) return `${nth(period)} ${league === "ncaab" ? "half" : "quarter"}`;
  return period === reg + 1 ? "Overtime" : `${nth(period - reg)} overtime`;
}
