import type { GradedPrediction, PredictionRecordResponse } from "../api/types";
import { addDays, etToday, slateFor } from "./scoreboard";
import { TEAMS } from "./teams";

function rng(seed: number) {
  return () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
}

/** Yesterday's real mock finals first, then older synthetic graded games. */
function gradedGames(n: number): (GradedPrediction & { total_error: number })[] {
  const today = etToday();
  const out: (GradedPrediction & { total_error: number })[] = [];
  for (const d of [0, -1]) {
    for (const c of slateFor(addDays(today, d))) {
      const p = c.prediction;
      if (!p?.result || c.home.score == null || c.away.score == null) continue;
      out.push({
        game_id: c.id,
        date: c.start_time,
        matchup: `${c.away.abbr} @ ${c.home.abbr}`,
        favorite_abbr: p.favorite_abbr,
        favorite_prob: p.favorite_prob,
        pred_home_margin: p.pred_home_margin,
        actual_home_margin: c.home.score - c.away.score,
        winner_correct: p.result.winner_correct,
        total_error: p.result.total_error,
      });
    }
  }
  const r = rng(42);
  for (let i = 0; out.length < n; i++) {
    const a = TEAMS[Math.floor(r() * TEAMS.length)];
    let h = TEAMS[Math.floor(r() * TEAMS.length)];
    if (h.abbr === a.abbr) h = TEAMS[(TEAMS.indexOf(a) + 1) % TEAMS.length];
    const pHome = 0.25 + r() * 0.6;
    const predMargin = Math.round((pHome - 0.5) * 56) / 2;
    const actual = Math.round(predMargin + (r() - 0.5) * 26) || 1;
    out.push({
      game_id: `40180${String(9000 + i)}`,
      date: `${addDays(today, -2 - Math.floor(i / 3))}T19:00:00-08:00`,
      matchup: `${a.abbr} @ ${h.abbr}`,
      favorite_abbr: pHome >= 0.5 ? h.abbr : a.abbr,
      favorite_prob: Math.round(Math.max(pHome, 1 - pHome) * 1000) / 1000,
      pred_home_margin: predMargin,
      actual_home_margin: actual,
      winner_correct: (actual > 0) === (predMargin > 0),
      total_error: Math.round(r() * 220) / 10,
    });
  }
  return out.slice(0, n);
}

export function predictionRecord(days: number, empty: boolean): PredictionRecordResponse {
  const base = { model: "elo_box_v1", model_version: "v1.1", window_days: days };
  if (empty) {
    return { ...base, games: 0, winner_accuracy: null, margin_mae: null, total_mae: null, market: null, recent: [] };
  }
  const graded = gradedGames(46);
  const n = graded.length;
  const mean = (xs: number[]) => Math.round((xs.reduce((a, b) => a + b, 0) / xs.length) * 10) / 10;
  return {
    ...base,
    games: n,
    winner_accuracy: Math.round((graded.filter((g) => g.winner_correct).length / n) * 1000) / 1000,
    margin_mae: mean(graded.map((g) => Math.abs(g.actual_home_margin - g.pred_home_margin))),
    total_mae: mean(graded.map((g) => g.total_error)),
    market: { games: n - 3, winner_accuracy: 0.674, margin_mae: 9.6, total_mae: 14.2 },
    recent: graded.slice(0, 20).map(({ total_error: _t, ...g }) => g),
  };
}
