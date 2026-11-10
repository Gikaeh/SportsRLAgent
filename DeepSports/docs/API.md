# Read API (contract)

Served by `uv run deepsports serve` (FastAPI + uvicorn) on `http://0.0.0.0:8787`, so the
phone on the same Wi-Fi uses `http://<mac-lan-ip>:8787`. The same server hosts the built web
app (`web/dist`) at `/`. All responses are JSON; times are ISO 8601 with offset.

**Data freshness:**
- **Live endpoints** (`/api/scoreboard`, `/api/games/{id}`) proxy ESPN through `PoliteClient`
  with an in-memory TTL: scoreboard 30s if any game is in progress, 5 min otherwise; a game's
  detail 10s while that game is in progress, 5 min otherwise. They never touch DuckDB, except to
  attach predictions when the warehouse is free (see v2).
- **Warehouse endpoints** (`/api/standings`, `/api/teams/{abbr}`) read DuckDB in read-only mode.
  While a collection job holds the DB, they return **503** `{"error": "warehouse_busy"}`;
  the client should show "Stats refreshing, try again shortly".

## Types
```ts
type TeamRef = {
  id: string; abbr: string; name: string;      // "LAL", "Los Angeles Lakers"
  short_name: string;                          // "Lakers"
  logo: string | null;                         // ESPN logo URL
  record: string | null;                       // "5-3"
  followed: boolean;                           // in config/calendar.toml
};
type GameCard = {
  id: string;
  state: "pre" | "in" | "post";
  status: string;          // "STATUS_IN_PROGRESS", "STATUS_FINAL", "STATUS_POSTPONED", ...
  status_text: string;     // "Q3 4:12", "Halftime", "Final", "Final/OT", "7:30 PM" (local)
  period: number | null;   // 1-4, 5+ = OT
  clock: string | null;    // "4:12"
  start_time: string;      // local ISO
  home: TeamRef & { score: number | null; linescores: number[] };
  away: TeamRef & { score: number | null; linescores: number[] };
  broadcasts: string[];
  odds: string | null;     // "LAL -11.5, O/U 238.5" (pre-game only)
  venue: string | null;
  followed: boolean;       // either team followed
  bets?: string[];         // labels of the owner's open bets ("TOR -2.5", "Over 216.5"); only when present and not final. Never the stake
};
```

## Endpoints
| Method & path | Returns |
|---|---|
| `GET /api/health` | `{ok: true, warehouse: "ok" \| "busy", now: string}` |
| `GET /api/scoreboard?date=YYYY-MM-DD` | `{date, games: GameCard[], live: boolean, refresh_seconds: number, next_followed_game?: GameCard \| null}`. `next_followed_game` (today only) is the first followed game not yet started, looking up to 7 days ahead. Defaults to today's US/Eastern game day. Followed teams' games sort first, then by start time |
| `GET /api/games/{id}` | `{game: GameCard, teams: TeamBox[], players: {[team_id]: PlayerLine[]}, refresh_seconds}` |
| `GET /api/standings` | `{season: "2026-27", conferences: [{name: "East" \| "West", teams: StandingRow[]}]}` |
| `GET /api/teams/{abbr}` | `{team: TeamRef, standing: StandingRow, recent: GameResult[], upcoming: GameResult[]}` (last 10 / next 5) |
| `GET /api/glance` | `{lines: string[], refresh_seconds}`: compact text for the glasses, e.g. `"LAL 98-95 SAC  Q4 2:31"`, `"GS vs MIA  7:00 PM"`; followed teams only, ≤ 30 chars per line |
| `GET /api/followed` | `{teams: string[]}` |

```ts
type TeamBox = { team_id: string; abbr: string; fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, reb,
                 ast, stl, blk, tov, pf, points_in_paint, fast_break_points: number | null };
type PlayerLine = { athlete_id: string; name: string; starter: boolean; did_not_play: boolean;
                    dnp_reason: string | null; minutes, pts, reb, ast, stl, blk, tov, pf,
                    fgm, fga, fg3m, fg3a, ftm, fta, plus_minus: number | null };
type StandingRow = { abbr: string; name: string; logo: string | null; conference: string; wins: number;
                     losses: number; pct: number; games_back: number; home: string; away: string;
                     last10: string; streak: string; followed: boolean };
type GameResult = { id: string; date: string; opponent: string; home: boolean;
                    result: "W" | "L" | null; score: string | null; status_text: string };
```

## Conventions (clarified 2026-11-03)
- `GameResult.opponent` is an abbreviation; `score` is from the team's own side (`"112-104"`); `date` is a local ISO timestamp.
- `players` in `/api/games/{id}` is keyed by team `id`. Before tip-off, `teams` and `players` are empty.
- Scores are `null` before tip-off. Standings rows come in seed order (sorted by win %), so a row's position is its seed.
- Errors: unknown game or team → 404 (FastAPI shape `{"detail": "..."}`); clients should key on the status code.
  Busy warehouse → 503 `{"error": "warehouse_busy"}`. Warehouse unreachable (drive unmounted, or the
  macOS removable-volume permission not yet granted, detected by a 5s open timeout) → 503
  `{"error": "warehouse_unavailable"}`; the web app shows both as "refreshing". ESPN unreachable → 502
  `{"error": "upstream_unavailable"}`.
- Live endpoints cache ESPN responses in `~/Library/Caches/DeepSports/live` (internal disk), so they work
  without the external drive.
- `/api/standings` and `/api/teams/{abbr}` have no `refresh_seconds`; the web app refreshes them every 10 minutes.
- CORS: any origin may `GET` (for the G2 glasses WebView).

## Open bets (2026-11-09)
`GET /api/bets` → `{games: GameCard[], live, refresh_seconds}`: every game (NBA and college, yesterday to
tomorrow ET) that has an open owner bet in the SportsRLAgent bet logs, each with `bets: string[]` labels.
Live first, then upcoming, then finals (a finished game stays until its bet is graded in the log).
Labels only, never the stake. The web app's Bets tab polls it.

## v2 additions (2026-11-04): college basketball + predictions
**League:** live endpoints take `league=nba|ncaab` (default `nba`): `/api/scoreboard?league=ncaab&date=...`,
`/api/games/{id}?league=ncaab`. College scoreboards cover all D1 games for the day (~30–60), followed teams first.
Standings and team pages stay NBA-only for now.

```ts
type Prediction = {
  model: string; model_version: string; created_at: string;   // made before tip-off
  p_home_win: number;            // 0..1
  pred_home_margin: number;      // + = home wins by this many
  pred_total: number;            // combined points
  favorite_abbr: string;         // team with p >= 0.5
  favorite_prob: number;         // max(p, 1-p)
  // present once the game is final:
  result?: { winner_correct: boolean; margin_error: number; total_error: number };
};
// GameCard gains:
//   league: "nba" | "ncaab"
//   prediction: Prediction | null   (null if no pre-tip prediction exists; NBA shows v1.1, college shows ncaab-v1 once both teams have ≥5 games, else ncaab-v1-early when a team has 1-4; ncaab-v1p is never shown on cards)
//   prediction.early: boolean   (true for ncaab-v1-early; the web app hides these unless the owner turns on "Early-season predictions"; the glasses never show them)
```

| Method & path | Returns |
|---|---|
| `GET /api/glance` | Now includes followed games from **both** leagues (college lines unchanged in format, e.g. `"SMC vs NEV  1:30 PM"`) |
| `GET /api/followed` | `{teams: string[] /* NBA, unchanged */, by_league: {nba: string[], ncaab: string[]}}` |
| `GET /api/predictions/record?league=nba\|ncaab&days=30&model_version=...` (model_version defaults to the league's display version, `v1.1` / `ncaab-v1`; also e.g. `v1.0`, `ncaab-v1p`, `ncaab-v1-early`; unknown league → 400 `unknown_league`) | `{model, model_version, window_days, games, winner_accuracy, margin_mae, total_mae, market: {games, winner_accuracy, margin_mae, total_mae} \| null, recent: GradedPrediction[] /* newest first, ≤20 */}` |

```ts
type GradedPrediction = { game_id: string; date: string; matchup: string /* "LAL @ SAC" */;
  favorite_abbr: string; favorite_prob: number; pred_home_margin: number; actual_home_margin: number;
  winner_correct: boolean };
```
Prediction fields are read from the warehouse. If it's busy or unavailable, `prediction` is `null` and `/api/predictions/record`
returns 503 like the other warehouse endpoints.

### v2 clarifications (2026-11-04, after frontend integration)
- Scoreboard responses include a top-level `league` field.
- `GameCard.neutral_site: boolean`: show "vs" instead of "@" (common in college).
- Before tip-off, `/api/games/{id}` returns `teams: []` and `players: {}`.
- `/api/predictions/record` with 0 graded games: `games: 0`, metric fields are `null`, `market: null`.

## v3 additions (2026-11-08): play-by-play and possession
`GET /api/games/{id}?league=nba|ncaab` gains `plays` and `possession`, and reports `refresh_seconds: 10`
while the game is in progress (scoreboard stays at 30; before and after the game stay at 300). Responses
over 1 KB are gzipped.

```ts
type Play = {
  id: string;
  seq: number;              // sequenceNumber; plays sorted ascending by this (NOT ESPN's list order)
  period: number;           // 1-4, 5+ OT for NBA; 1-2, 3+ OT for college
  clock: string | null;     // "4:12" time remaining
  text: string;             // ESPN's description
  team_id: string | null;   // same id space as game.away.id / game.home.id
  away_score: number;       // cumulative AFTER this play, after a running-max fixup
  home_score: number;
  scoring: boolean;
  points: number;           // points scored on this play, 0 if not scoring
  kind: "shot_made" | "shot_missed" | "free_throw_made" | "free_throw_missed" | "rebound" | "turnover"
      | "foul" | "timeout" | "substitution" | "period_end" | "other";
  coord: { x: number; y: number } | null;  // feet: x 0-50 across court, y from baseline (hoop at x=25,y=0);
                                           // null for missing or sentinel values, free throws, non-shots
};
// added to the response:
plays: Play[];   // whole game so far, chronological; [] before tip-off or if ESPN has none
possession: { team_id: string; source: "espn" | "inferred" } | null;  // null when not in progress or unknown
```

**Plays:** `scoring` and made/missed come from ESPN's `scoringPlay`, never the type text. Scores only rise,
so a stale annotation repeats the previous score. Show the headline score from `game.home.score` /
`game.away.score`, not `plays[-1]`: ESPN's per-play scores can differ from the final by a few points
(about 4 of the last 150 NBA games ran over it). `y` can exceed half court on heaves. End of game is
`period_end`. A jump ball, block, steal, violation or review is `other`.

**Possession** is only set for state `"in"`. `source: "espn"` means ESPN said so (a competitor's
`possession: true`, or a `situation` block). Otherwise it's inferred from the latest play, skipping
substitutions, and is `null` whenever it can't be said honestly:

| Latest play | Result |
|---|---|
| Rebound (offensive, defensive, team, dead ball) | rebounder's team |
| Made shot, turnover, offensive foul or charge | other team |
| College `Steal` play | stealer's team |
| Made free throw, last of a set ("2 of 2") | other team |
| Earlier free throw, missed free throw, technical / flagrant / clear-path free throw, or a free throw with no count in its text | `null` |
| Missed shot, block, tip, timeout, end of period, any other foul, review, violation | `null` |
| Halftime / end of period status, a clock of 0, or a play from an earlier period | `null` |

`inferred` is a best guess that lags ESPN's feed. On finished games replayed play by play it matches the next
shooting team about 98-99% of the time after rebounds and turnovers, and about 93% after made shots: an
and-one looks like a change of possession until the foul posts.
