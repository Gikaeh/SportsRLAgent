// Mock API (npm run dev:mock). Shapes follow docs/API.md (/api/bets, /api/parlays).
// Pick a scenario with ?scenario=default|busy|empty|flaky|down on the page URL.
import type { BetGame, BetsResponse, GameState, League, Parlay, ParlayLeg, ParlaysResponse } from '../types.ts'

const TZ = '-08:00' // server-local (Pacific, standard time in November)

type Spec = {
  id: string
  away: string
  home: string
  time: string // "HH:MM" server-local
  state: GameState
  league?: League
  status_text?: string
  period?: number
  clock?: string
  a?: number[]
  h?: number[]
  bets: string[]
}

function today(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Los_Angeles' }).format(new Date())
}

function timeLabel(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}

const sum = (xs: number[]) => xs.reduce((x, y) => x + y, 0)

export function game(s: Spec, date = today()): BetGame {
  const a = s.a ?? []
  const h = s.h ?? []
  const scored = s.state !== 'pre'
  const side = (abbr: string, xs: number[]) => ({ id: abbr, abbr, name: abbr, short_name: abbr, score: scored ? sum(xs) : null, linescores: xs })
  return {
    id: s.id,
    league: s.league ?? 'ncaab',
    state: s.state,
    status: { pre: 'STATUS_SCHEDULED', in: 'STATUS_IN_PROGRESS', post: 'STATUS_FINAL' }[s.state],
    status_text: s.status_text ?? (s.state === 'pre' ? timeLabel(s.time) : 'Final'),
    period: scored ? (s.period ?? a.length) : null,
    clock: s.state === 'in' ? (s.clock ?? null) : null,
    start_time: `${date}T${s.time}:00${TZ}`,
    away: side(s.away, a),
    home: side(s.home, h),
    bets: s.bets,
  }
}

export const SPECS: Spec[] = [
  { id: '1', away: 'ME', home: 'LEM', time: '11:00', state: 'in', period: 2, clock: '12:25', status_text: '2nd 12:25', a: [34, 19], h: [32, 13], bets: ['Under 139'] },
  { id: '2', away: 'FRES', home: 'USA', time: '11:00', state: 'in', period: 2, clock: '8:49', status_text: '2nd 8:49', a: [42, 20], h: [30, 18], bets: ['Over 144.5'] },
  { id: '3', away: 'LAL', home: 'SAC', time: '19:00', state: 'in', league: 'nba', period: 4, clock: '2:31', status_text: 'Q4 2:31', a: [28, 25, 22, 23], h: [24, 27, 26, 18], bets: ['LAL -2.5', 'Over 226.5'] },
  { id: '4', away: 'UMBC', home: 'GW', time: '13:00', state: 'pre', bets: ['Under 152.5'] },
  { id: '5', away: 'NIA', home: 'LAF', time: '13:30', state: 'pre', bets: ['Over 141.5'] },
  { id: '6', away: 'UVA', home: 'XAV', time: '08:00', state: 'post', a: [40, 43], h: [35, 36], bets: ['Under 156.5'] },
  { id: '7', away: 'STMN', home: 'LIB', time: '09:00', state: 'post', a: [30, 37], h: [38, 38], bets: ['Over 146.5'] },
]

const BUSY_EXTRA: Spec[] = [
  { id: '8', away: 'VILL', home: 'KU', time: '14:00', state: 'pre', bets: ['Under 159.5'] },
  { id: '9', away: 'WKU', home: 'ILL', time: '15:00', state: 'pre', bets: ['Under 177.5'] },
  { id: '10', away: 'WICH', home: 'UK', time: '18:00', state: 'pre', bets: ['Under 158.5', 'WICH +9.5'] },
]

export function betsFor(scenario: string): BetsResponse {
  if (scenario === 'empty') return { games: [], live: false, refresh_seconds: 300 }
  const specs = scenario === 'busy' ? [...SPECS, ...BUSY_EXTRA] : SPECS
  const games = specs.map((s) => game(s))
  const order = { in: 0, pre: 1, post: 2 }
  games.sort((x, y) => order[x.state] - order[y.state] || x.start_time.localeCompare(y.start_time))
  return { games, live: games.some((g) => g.state === 'in'), refresh_seconds: 30 }
}

function leg(g: BetGame, label: string, status: ParlayLeg['status']): ParlayLeg {
  const scored = g.state !== 'pre'
  return {
    game_id: g.id,
    label,
    matchup: `${g.away.name} @ ${g.home.name}`,
    away_abbr: g.away.abbr,
    home_abbr: g.home.abbr,
    start_time: g.start_time,
    state: g.state,
    status_text: g.status_text,
    away_score: scored ? g.away.score : null,
    home_score: scored ? g.home.score : null,
    status,
    note: null,
  }
}

function parlay(id: string, price: number, legs: ParlayLeg[]): Parlay {
  const c = (s: string) => legs.filter((l) => l.status === s).length
  const status = c('lost') ? 'lost' : c('pending') ? 'alive' : 'won'
  return { id, placed_at: `${today()}T03:20:28+00:00`, book: 'WilliamHill', tier: 'manual', price, status, won: c('won'), lost: c('lost'), push: c('push'), pending: c('pending'), legs }
}

export function parlaysFor(scenario: string): ParlaysResponse {
  if (scenario === 'empty') return { parlays: [], live: false, refresh_seconds: 300 }
  const g = Object.fromEntries([...SPECS, ...BUSY_EXTRA].map((s) => [s.id, game(s)]))
  const big = parlay('46', 21213755, [
    leg(g['6'], 'Under 156.5', 'won'),
    leg(g['7'], 'Over 146.5', 'lost'),
    leg(g['1'], 'Under 139', 'pending'),
    leg(g['2'], 'Over 144.5', 'pending'),
    leg(g['4'], 'Under 152.5', 'pending'),
    leg(g['5'], 'Over 141.5', 'pending'),
    leg(g['8'], 'Under 159.5', 'pending'),
    leg(g['9'], 'Under 177.5', 'pending'),
    leg(g['10'], 'Under 158.5', 'pending'),
  ])
  const small = parlay('42', 257, [leg(g['6'], 'Under 156.5', 'won'), leg(g['4'], 'Under 152.5', 'pending')])
  return { parlays: [big, small], live: true, refresh_seconds: 30 }
}

let calls = 0

/** Drop-in for httpFetchJson(). */
export function mockFetchJson(scenario: string) {
  return async (path: string): Promise<unknown> => {
    await new Promise((r) => setTimeout(r, 150))
    calls += 1
    if (scenario === 'down' || (scenario === 'flaky' && calls > 2)) throw new Error('mock: server unreachable')
    const url = new URL(path, 'http://mock')
    if (url.pathname === '/api/bets') return betsFor(scenario)
    if (url.pathname === '/api/parlays') return parlaysFor(scenario)
    throw new Error(`mock: 404 ${path}`)
  }
}
