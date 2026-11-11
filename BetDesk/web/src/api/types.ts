// Mirrors docs/API.md exactly. Keep in sync with the contract.

export type TeamRef = {
  id: string;
  abbr: string;
  name: string;
  short_name: string;
  logo: string | null;
  record: string | null;
  followed: boolean;
};

export type GameTeam = TeamRef & { score: number | null; linescores: number[] };

export type GameState = "pre" | "in" | "post";

/** v2: live endpoints take `league=nba|ncaab` (default nba). */
export type League = "nba" | "ncaab";

/** v2: a pre-tip model prediction. `result` appears once the game is final. */
export type Prediction = {
  model: string;
  model_version: string;
  created_at: string;
  p_home_win: number; // 0..1
  pred_home_margin: number; // + = home wins by this many
  pred_total: number;
  favorite_abbr: string;
  favorite_prob: number; // max(p, 1-p)
  /** College only: made before both teams had 5 games (`ncaab-v1-early`). Hidden unless the owner opts in. */
  early?: boolean;
  result?: { winner_correct: boolean; margin_error: number; total_error: number };
};

export type GameCard = {
  id: string;
  /** true at a neutral site (common in college): show "vs" instead of "@" */
  neutral_site?: boolean;
  state: GameState;
  status: string;
  status_text: string;
  period: number | null;
  clock: string | null;
  start_time: string;
  home: GameTeam;
  away: GameTeam;
  broadcasts: string[];
  odds: string | null;
  venue: string | null;
  followed: boolean;
  /** v2. Optional so a v1 server (no field) still type-checks at runtime; treat missing as "nba". */
  league?: League;
  /** v2. null when no pre-tip prediction exists (all college games for now). */
  prediction?: Prediction | null;
  /** Labels of the owner's open bets on this game ("TOR -2.5"). Absent when there are none. */
  bets?: string[];
};

/** Games with an open owner bet, live games first, finals last (until the bet is graded). */
export type BetsResponse = {
  games: GameCard[];
  live: boolean;
  refresh_seconds: number;
};

export type ScoreboardResponse = {
  date: string;
  games: GameCard[];
  live: boolean;
  refresh_seconds: number;
  next_followed_game?: GameCard | null;
};

export type TeamBox = {
  team_id: string;
  abbr: string;
  fgm: number | null;
  fga: number | null;
  fg3m: number | null;
  fg3a: number | null;
  ftm: number | null;
  fta: number | null;
  oreb: number | null;
  dreb: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  tov: number | null;
  pf: number | null;
  points_in_paint: number | null;
  fast_break_points: number | null;
};

export type PlayerLine = {
  athlete_id: string;
  name: string;
  starter: boolean;
  did_not_play: boolean;
  dnp_reason: string | null;
  minutes: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  tov: number | null;
  pf: number | null;
  fgm: number | null;
  fga: number | null;
  fg3m: number | null;
  fg3a: number | null;
  ftm: number | null;
  fta: number | null;
  plus_minus: number | null;
};

export type PlayKind =
  | "shot_made"
  | "shot_missed"
  | "free_throw_made"
  | "free_throw_missed"
  | "rebound"
  | "turnover"
  | "foul"
  | "timeout"
  | "substitution"
  | "period_end"
  | "other";

/** v3: one play-by-play event. */
export type Play = {
  id: string;
  seq: number; // ascending = chronological; plays arrive sorted, oldest first
  period: number; // 1-4, 5+ OT for NBA; 1-2, 3+ OT for college
  clock: string | null; // "4:12" time remaining
  text: string; // ESPN's description
  team_id: string | null; // matches game.away.id / game.home.id
  away_score: number; // cumulative after this play
  home_score: number;
  scoring: boolean;
  points: number; // 0 if not scoring
  kind: PlayKind;
  /** Feet: x 0-50 across the court, y from the baseline (hoop x=25, y=0). null for free throws/non-shots. */
  coord: { x: number; y: number } | null;
};

/** v3: who has the ball. "inferred" = worked out from the last play, so it can lag. */
export type Possession = { team_id: string; source: "espn" | "inferred" };

export type GameDetailResponse = {
  game: GameCard;
  teams: TeamBox[];
  players: { [team_id: string]: PlayerLine[] };
  refresh_seconds: number; // 10 during a live game (v3)
  /** v3. Whole game so far, [] before tip-off. Absent on an older server: treat as []. */
  plays?: Play[];
  /** v3. null when unknown or not in progress. Absent on an older server. */
  possession?: Possession | null;
};

export type StandingRow = {
  abbr: string;
  name: string;
  logo: string | null;
  conference: string;
  wins: number;
  losses: number;
  pct: number;
  games_back: number;
  home: string;
  away: string;
  last10: string;
  streak: string;
  followed: boolean;
};

export type StandingsResponse = {
  season: string;
  conferences: { name: "East" | "West"; teams: StandingRow[] }[];
};

export type GameResult = {
  id: string;
  date: string;
  opponent: string;
  home: boolean;
  result: "W" | "L" | null;
  score: string | null;
  status_text: string;
};

export type TeamResponse = {
  team: TeamRef;
  standing: StandingRow;
  recent: GameResult[];
  upcoming: GameResult[];
};

export type GradedPrediction = {
  game_id: string;
  date: string;
  matchup: string; // "LAL @ SAC" (away @ home)
  favorite_abbr: string;
  favorite_prob: number;
  pred_home_margin: number;
  actual_home_margin: number;
  winner_correct: boolean;
};

export type RecordStats = {
  games: number;
  winner_accuracy: number | null; // 0..1; null-safe in case 0 games
  margin_mae: number | null;
  total_mae: number | null;
};

export type PredictionRecordResponse = RecordStats & {
  model: string;
  model_version: string;
  window_days: number;
  market: RecordStats | null;
  recent: GradedPrediction[];
};

export type FollowedResponse = { teams: string[]; by_league?: { nba: string[]; ncaab: string[] } };

export type ApiErrorBody = { error: string };

/** BetDesk only: `/api/health` from the Worker, describing the newest snapshot pushed from the Mac. */
export type MirrorHealth = {
  ok: boolean;
  /** DeepSports warehouse state at the last push ("busy" while a data job was writing). */
  warehouse: "ok" | "busy";
  now: string;
  /** When the newest snapshot was taken on the Mac; null before the first push. */
  generated_at: string | null;
  age_seconds: number | null;
  stale: boolean;
};
