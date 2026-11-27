// Subset of the read API contract (docs/API.md) that the glasses use: /api/bets and /api/parlays.

export type GameState = 'pre' | 'in' | 'post'

/** Live endpoints take league=nba|ncaab; a card without `league` is NBA. */
export type League = 'nba' | 'ncaab'

export type Side = {
  id: string
  abbr: string
  name: string
  short_name: string
  score: number | null
  linescores: number[]
}

/** A scoreboard game card plus the owner's open bet labels ("Over 144.5", "NEV -1", "NEV ML", "Over 70.5 1H"). */
export type BetGame = {
  id: string
  league?: League
  neutral_site?: boolean
  state: GameState
  status: string
  status_text: string // "1:00 PM", "2nd 12:25", "Halftime", "Final"
  period: number | null
  clock: string | null
  start_time: string
  home: Side
  away: Side
  bets: string[]
}

export type BetsResponse = { games: BetGame[]; live: boolean; refresh_seconds: number }

export type LegStatus = 'won' | 'lost' | 'push' | 'pending'

export type ParlayLeg = {
  game_id: string
  label: string // "Over 145.5"
  matchup: string | null // "Away Team @ Home Team"; null when the game isn't on a scoreboard
  away_abbr?: string | null // newer servers only
  home_abbr?: string | null
  start_time: string | null
  state: GameState | null
  status_text: string | null
  away_score: number | null
  home_score: number | null
  status: LegStatus // decided early when a live total can't change
  note: string | null
}

export type Parlay = {
  id: string
  placed_at: string
  book: string | null
  tier: string | null
  price: number // American odds of the ticket (never the stake)
  status: string // "alive" | "won" | "lost" | "push" (or a graded "win"/"loss")
  won: number
  lost: number
  push: number
  pending: number
  legs: ParlayLeg[]
}

export type ParlaysResponse = { parlays: Parlay[]; live: boolean; refresh_seconds: number }
