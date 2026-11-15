// Mock GET /api/picks/today. Page-URL switch (before the #): `?mock=nopicks` no run yet today.
import type { ModelPick, PicksTodayResponse } from "../api/types";

const at = (h: number, m = 0) => {
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toISOString();
};

const pick = (o: Partial<ModelPick> & Pick<ModelPick, "label" | "market" | "side" | "line">): ModelPick => ({
  game_id: "401810001",
  league: "nba",
  price: -110,
  tier: "strong",
  ds_edge: 4.6,
  mb_edge: 4.1,
  early: false,
  away: { abbr: "IND", name: "Pacers" },
  home: { abbr: "PHI", name: "76ers" },
  tip_utc: at(19),
  books: {},
  best: null,
  ...o,
});

export function picksToday(): PicksTodayResponse {
  if (new URLSearchParams(window.location.search).get("mock") === "nopicks") {
    return { available: false, run_at: null, top: [], more: [], counts: { strong: 0, lean: 0 } };
  }
  return {
    available: true,
    run_at: at(14, 3),
    rule_version: "mp-v1",
    top: [
      pick({ label: "PHI -7.5", market: "spread", side: "home", line: -7.5,
        books: { circa: { line: -7.5, price: -110 }, williamhill: { line: -7.5, price: -110 } } }),
      pick({ game_id: "401810002", label: "Under 226", market: "total", side: "under", line: 226, ds_edge: 4.2,
        mb_edge: 3.9, away: { abbr: "LAL", name: "Lakers" }, home: { abbr: "PHX", name: "Suns" }, tip_utc: at(21),
        books: { circa: { line: 226, price: -110 }, williamhill: { line: 226.5, price: -110 } } }),
      pick({ game_id: "401920705", league: "ncaab", label: "WCU -3.5", market: "spread", side: "home", line: -3.5,
        tier: "lean", ds_edge: 3.6, mb_edge: 3.1, early: true, away: { abbr: "CIT", name: "Bulldogs" },
        home: { abbr: "WCU", name: "Catamounts" }, tip_utc: at(16), books: { williamhill: { line: -3, price: -115 } } }),
      pick({ game_id: "401911308", league: "ncaab", label: "Under 158.5", market: "total", side: "under", line: 158.5,
        tier: "lean", ds_edge: 3.3, mb_edge: 3.0, away: { abbr: "AKR", name: "Zips" }, home: { abbr: "TULN", name: "Green Wave" },
        tip_utc: at(10) }),
    ],
    more: [
      pick({ game_id: "401810003", label: "CLE +4.5", market: "spread", side: "away", line: 4.5, tier: "lean",
        ds_edge: 3.2, mb_edge: 3.0, away: { abbr: "CLE", name: "Cavaliers" }, home: { abbr: "BOS", name: "Celtics" } }),
    ],
    counts: { strong: 2, lean: 3 },
  };
}
