import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { GameDetailResponse, Play } from "../../api/types";

/** One combined "+N" for a team since the last poll. `n` restarts the animation. */
export type ScoreFloat = { n: number; points: number };

export type LiveFx = {
  floats: { away: ScoreFloat | null; home: ScoreFloat | null };
  /** Plays that arrived on the last poll; they slide in and highlight briefly. */
  freshIds: ReadonlySet<string>;
  /** Polite screen-reader text for the latest scoring. Stays set, so it isn't read twice. */
  announcement: string;
};

/** ESPN's text is verbatim and can hold newlines ("Bad Pass\nTurnover"): show it on one line. */
export const playText = (p: Play) => p.text.replace(/\s+/g, " ").trim();

const NO_IDS: ReadonlySet<string> = new Set();
const FX_MS = 2200; // a little longer than the longest one-shot CSS animation
const MAX_NEW_PLAYS = 15; // more than this in one poll is a catch-up, not live action

type Baseline = {
  ids: Set<string>;
  maxSeq: number;
  state: string;
  at: number;
};

/**
 * Turns polled game data into one-shot effects by diffing against the previous response.
 * The first load, the first response after the tab was hidden or a failed poll, and any response
 * after a long gap only move the baseline: old plays never replay as animations.
 */
export function useLiveFx(data: GameDetailResponse | undefined, error: unknown): LiveFx {
  const base = useRef<Baseline | null>(null);
  const skipNext = useRef(false);
  const counter = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const [fx, setFx] = useState<LiveFx>({ floats: { away: null, home: null }, freshIds: NO_IDS, announcement: "" });

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState !== "visible") skipNext.current = true;
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearTimeout(timer.current);
    };
  }, []);

  // A failed poll means plays piled up unseen; the next success is a catch-up. This renders before it.
  useEffect(() => {
    if (error != null) skipNext.current = true;
  }, [error]);

  // Layout effect: the effects are on screen in the same paint as the new numbers.
  useLayoutEffect(() => {
    if (!data) return;
    const g = data.game;
    const plays = data.plays ?? [];
    const before = base.current;
    const now = Date.now();
    // Remember every id ever seen, so a response with a temporarily empty list can't replay the game.
    const ids = before?.ids ?? new Set<string>();
    const fresh = plays.filter((p) => !ids.has(p.id) && p.seq > (before?.maxSeq ?? -Infinity));
    plays.forEach((p) => ids.add(p.id));
    base.current = {
      ids,
      maxSeq: plays.reduce((m, p) => Math.max(m, p.seq), before?.maxSeq ?? -Infinity),
      state: g.state,
      at: now,
    };

    const hidden = document.visibilityState !== "visible";
    const caughtUp = skipNext.current || hidden;
    skipNext.current = hidden;
    const maxGapMs = Math.max(30, data.refresh_seconds * 3) * 1000;
    if (!before || caughtUp || now - before.at > maxGapMs || fresh.length > MAX_NEW_PLAYS) return;
    if (g.state !== "in" && before.state !== "in") return;

    if (fresh.length === 0) return;

    // From the new plays' points, not a score difference: the header can run ahead of the plays.
    const scoring = fresh.filter((p) => p.scoring && p.points > 0);
    const gain = (teamId: string) => scoring.reduce((sum, p) => (p.team_id === teamId ? sum + p.points : sum), 0);
    const awayGain = gain(g.away.id);
    const homeGain = gain(g.home.id);

    const float = (points: number): ScoreFloat | null => (points > 0 ? { n: ++counter.current, points } : null);
    const detail = scoring.map(playText).join(". ");
    setFx((cur) => ({
      floats: { away: float(awayGain), home: float(homeGain) },
      freshIds: new Set(fresh.map((p) => p.id)),
      announcement: detail
        ? `${detail}. ${g.away.short_name} ${g.away.score}, ${g.home.short_name} ${g.home.score}.`
        : cur.announcement,
    }));
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setFx((cur) => ({ ...cur, floats: { away: null, home: null }, freshIds: NO_IDS }));
    }, FX_MS);
  }, [data]);

  return fx;
}
