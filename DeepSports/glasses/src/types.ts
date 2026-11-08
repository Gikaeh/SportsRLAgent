// Subset of the read API contract (docs/API.md) that the glasses use.

export type GameState = 'pre' | 'in' | 'post'

/** v2: live endpoints take league=nba|ncaab (default nba). */
export type League = 'nba' | 'ncaab'

export type Prediction = {
  model: string
  model_version: string
  created_at: string
  p_home_win: number
  pred_home_margin: number
  pred_total: number
  favorite_abbr: string
  favorite_prob: number
  /** college early-season prediction (a team has < 5 games); the glasses never show these */
  early?: boolean
  result?: { winner_correct: boolean; margin_error: number; total_error: number }
}

export type TeamRef = {
  id: string
  abbr: string
  name: string
  short_name: string
  logo: string | null
  record: string | null
  followed: boolean
}

export type Side = TeamRef & { score: number | null; linescores: number[] }

export type GameCard = {
  id: string
  /** true at a neutral site: show "vs" instead of "@" */
  neutral_site?: boolean
  state: GameState
  status: string
  status_text: string
  period: number | null
  clock: string | null
  start_time: string
  home: Side
  away: Side
  broadcasts: string[]
  odds: string | null
  venue: string | null
  followed: boolean
  /** v2; missing on a v1 server, which means "nba". */
  league?: League
  /** v2; null when there's no pre-tip prediction (many college games: both teams need >= 5 games). */
  prediction?: Prediction | null
}

export type ScoreboardResponse = {
  date: string
  games: GameCard[]
  live: boolean
  refresh_seconds: number
  /** Today only: first followed game not yet started, up to 7 days ahead. Missing on old servers. */
  next_followed_game?: GameCard | null
}

export type GlanceResponse = { lines: string[]; refresh_seconds: number }
