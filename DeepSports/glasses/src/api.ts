// Network access to the DeepSports read API (docs/API.md). Relative URLs by default because
// the plugin is served same-origin at /glasses/; VITE_API_BASE overrides that for packaged builds.
import type { GameCard, League, ScoreboardResponse } from './types.ts'

export type FetchJson = (path: string) => Promise<unknown>

export const MIN_REFRESH_SECONDS = 15
export const RETRY_SECONDS = 30
export const LOOKAHEAD_DAYS = 7
export const LEAGUES: League[] = ['nba', 'ncaab']

export function httpFetchJson(base = ''): FetchJson {
  return async (path) => {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 10_000)
    try {
      const res = await fetch(base + path, { signal: ctrl.signal, cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${path}`)
      return await res.json()
    } finally {
      clearTimeout(timer)
    }
  }
}

function isScoreboard(x: unknown): x is ScoreboardResponse {
  const o = x as ScoreboardResponse
  return !!o && Array.isArray(o.games) && typeof o.date === 'string'
}

export const leagueOf = (g: GameCard): League => g.league ?? 'nba'

export function scoreboardPath(league: League, date?: string): string {
  const q = new URLSearchParams({ league })
  if (date) q.set('date', date)
  return `/api/scoreboard?${q}`
}

/**
 * One league's scoreboard. A v1 server ignores league= and returns NBA games; those are
 * dropped here so college requests never duplicate NBA games.
 */
export async function getScoreboard(fetchJson: FetchJson, date?: string, league: League = 'nba'): Promise<ScoreboardResponse> {
  const body = await fetchJson(scoreboardPath(league, date))
  if (!isScoreboard(body)) throw new Error('unexpected /api/scoreboard shape')
  const games = body.games.filter((g) => leagueOf(g) === league)
  const next = body.next_followed_game
  return {
    ...body,
    games,
    ...(next !== undefined ? { next_followed_game: next && leagueOf(next) === league ? next : null } : {}),
  }
}

export type LeagueResult = { league: League; ok: true; sb: ScoreboardResponse } | { league: League; ok: false; error: unknown }

/** Today's scoreboard for every league, in parallel; one league failing doesn't hide the other. */
export async function getAllScoreboards(fetchJson: FetchJson, leagues = LEAGUES): Promise<LeagueResult[]> {
  return Promise.all(
    leagues.map(async (league): Promise<LeagueResult> => {
      try {
        return { league, ok: true, sb: await getScoreboard(fetchJson, undefined, league) }
      } catch (error) {
        return { league, ok: false, error }
      }
    }),
  )
}

/** Earliest not-yet-started game of a list, or null. */
export function earliest(games: (GameCard | null | undefined)[]): GameCard | null {
  let best: GameCard | null = null
  for (const g of games) if (g && (!best || Date.parse(g.start_time) < Date.parse(best.start_time))) best = g
  return best
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

/**
 * Fallback for servers without next_followed_game: first followed game in the `days` after
 * `date` (the scoreboard's own game day), across `leagues`.
 */
export async function findNextFollowed(
  fetchJson: FetchJson,
  date: string,
  days = LOOKAHEAD_DAYS,
  leagues: League[] = ['nba'],
): Promise<GameCard | null> {
  for (let i = 1; i <= days; i++) {
    const found: GameCard[] = []
    for (const league of leagues) {
      const sb = await getScoreboard(fetchJson, addDays(date, i), league)
      const game = sb.games.find((g) => g.followed)
      if (game) found.push(game)
    }
    if (found.length) return earliest(found)
  }
  return null
}

/** Poll interval: the server's refresh_seconds (30 live / 300 idle), never below 15 s. */
export function pollSeconds(refreshSeconds: number | undefined): number {
  const s = Number.isFinite(refreshSeconds) ? (refreshSeconds as number) : 60
  return Math.max(MIN_REFRESH_SECONDS, s)
}
