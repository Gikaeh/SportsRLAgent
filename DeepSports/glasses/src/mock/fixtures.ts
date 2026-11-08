// Mock API (npm run dev:mock). Shapes follow docs/API.md (GameCard, /api/scoreboard).
// Pick a scenario with ?scenario=default|busy|empty|flaky|down|v1 on the page URL.
// v2: league=nba|ncaab, `league` + `prediction` on cards, next_followed_game on today's scoreboard.
// `v1` mimics a pre-v2 server (ignores league=, no v2 fields).
import type { GameCard, GameState, League, Prediction, ScoreboardResponse, TeamRef } from '../types.ts'
import { addDays } from '../api.ts'

const TEAMS: Record<string, [string, string, string]> = {
  LAL: ['13', 'Los Angeles Lakers', 'Lakers'],
  SAC: ['23', 'Sacramento Kings', 'Kings'],
  GS: ['9', 'Golden State Warriors', 'Warriors'],
  MIA: ['14', 'Miami Heat', 'Heat'],
  BOS: ['2', 'Boston Celtics', 'Celtics'],
  NY: ['18', 'New York Knicks', 'Knicks'],
  DEN: ['7', 'Denver Nuggets', 'Nuggets'],
  PHX: ['21', 'Phoenix Suns', 'Suns'],
  MIL: ['15', 'Milwaukee Bucks', 'Bucks'],
  ORL: ['19', 'Orlando Magic', 'Magic'],
  LAC: ['12', 'LA Clippers', 'Clippers'],
  DAL: ['6', 'Dallas Mavericks', 'Mavericks'],
}
const COLLEGE: Record<string, [string, string, string]> = {
  NEV: ['2440', 'Nevada Wolf Pack', 'Wolf Pack'],
  SMC: ['2608', "Saint Mary's Gaels", 'Gaels'],
  UNLV: ['2439', 'UNLV Rebels', 'Rebels'],
  SDSU: ['21', 'San Diego State Aztecs', 'Aztecs'],
  DUKE: ['150', 'Duke Blue Devils', 'Blue Devils'],
  KU: ['2305', 'Kansas Jayhawks', 'Jayhawks'],
}
const FOLLOWED = ['LAL', 'GS', 'BOS']
const FOLLOWED_NCAAB = ['NEV']
const RECORDS: Record<string, string> = { LAL: '5-3', SAC: '4-4', GS: '6-2', MIA: '4-4', BOS: '3-5', NY: '5-2', NEV: '2-0', SMC: '2-0' }
const VENUES: Record<string, string> = {
  SAC: 'Golden 1 Center', MIA: 'Kaseya Center', BOS: 'TD Garden', GS: 'Chase Center', LAL: 'Crypto.com Arena',
  PHX: 'PHX Arena', ORL: 'Kia Center', LAC: 'Intuit Dome', MIL: 'Fiserv Forum',
}
const TZ = '-08:00' // server-local (Pacific, standard time in November)

function team(abbr: string, followed: string[], league: League = 'nba'): TeamRef {
  const [id, name, short] = (league === 'ncaab' ? COLLEGE : TEAMS)[abbr]
  return { id, abbr, name, short_name: short, logo: null, record: RECORDS[abbr] ?? null, followed: followed.includes(abbr) }
}

type Spec = {
  id: string
  away: string
  home: string
  time: string // "HH:MM" server-local
  state: GameState
  status?: string
  status_text?: string
  period?: number
  clock?: string
  a?: number[]
  h?: number[]
  tv?: string[]
  venue?: string
  /** Pre-tip prediction: [p_home_win, pred_home_margin]; omitted = none (common in college). */
  pred?: [number, number]
}

function timeLabel(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}

const sum = (xs: number[]) => xs.reduce((x, y) => x + y, 0)

function prediction(s: Spec, away: number | null, home: number | null, league: League): Prediction | null {
  if (!s.pred) return null
  const [p, margin] = s.pred
  const college = league === 'ncaab'
  const total = college ? 141.5 : 226.5
  const pred: Prediction = {
    model: college ? 'ncaab_ridge' : 'elo_box_v1',
    model_version: college ? 'ncaab-v1' : 'v1.1',
    created_at: '2026-11-03T12:00:00-08:00',
    p_home_win: p, pred_home_margin: margin, pred_total: total,
    favorite_abbr: p >= 0.5 ? s.home : s.away, favorite_prob: Math.max(p, 1 - p),
  }
  if (s.state === 'post' && away != null && home != null) {
    pred.result = {
      winner_correct: (home - away > 0) === (margin > 0),
      margin_error: Math.abs(home - away - margin),
      total_error: Math.abs(home + away - total),
    }
  }
  return pred
}

function card(date: string, s: Spec, followed: string[], league: League = 'nba'): GameCard {
  const a = s.a ?? []
  const h = s.h ?? []
  const scored = s.state !== 'pre'
  const away = team(s.away, followed, league)
  const home = team(s.home, followed, league)
  const defaultStatus = { pre: 'STATUS_SCHEDULED', in: 'STATUS_IN_PROGRESS', post: 'STATUS_FINAL' }[s.state]
  return {
    id: s.id,
    state: s.state,
    status: s.status ?? defaultStatus,
    status_text: s.status_text ?? (s.state === 'pre' ? timeLabel(s.time) : 'Final'),
    period: scored ? (s.period ?? Math.max(a.length, 4)) : null,
    clock: s.state === 'in' ? (s.clock ?? null) : null,
    start_time: `${date}T${s.time}:00${TZ}`,
    away: { ...away, score: scored ? sum(a) : null, linescores: a },
    home: { ...home, score: scored ? sum(h) : null, linescores: h },
    broadcasts: s.tv ?? [],
    odds: s.state === 'pre' ? `${s.home} -3.5, O/U 228.5` : null,
    venue: s.venue ?? VENUES[s.home] ?? null,
    followed: away.followed || home.followed,
    league,
    prediction: prediction(s, scored ? sum(a) : null, scored ? sum(h) : null, league),
  }
}

const T0 = Date.now()

/** A live game whose clock runs down 22 s every 30 s, so auto-refresh is visible. */
function liveGame(): Spec {
  const ticks = Math.floor((Date.now() - T0) / 30_000)
  const secs = Math.max(0, 151 - ticks * 22)
  const clock = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`
  const extraA = Math.floor(ticks / 2) * 2
  const extraH = Math.floor((ticks + 1) / 2) * 3
  return {
    id: '401810001',
    away: 'LAL',
    home: 'SAC',
    time: '19:00',
    state: 'in',
    period: 4,
    clock,
    status_text: `Q4 ${clock}`,
    a: [28, 25, 22, 23 + extraA],
    h: [24, 27, 26, 18 + extraH],
    tv: ['ESPN', 'SportsNet LA'],
  }
}

function slate(scenario: string): Spec[] {
  const base: Spec[] = [
    { id: '401810002', away: 'NY', home: 'BOS', time: '16:30', state: 'post', a: [30, 22, 27, 25], h: [26, 31, 24, 31], tv: ['NBC'], pred: [0.81, 6.5] },
    liveGame(),
    { id: '401810003', away: 'GS', home: 'MIA', time: '19:30', state: 'pre', tv: ['TNT'], pred: [0.38, -3.5] },
    { id: '401810004', away: 'MIL', home: 'ORL', time: '16:00', state: 'in', period: 2, clock: '0:00', status_text: 'Halftime', a: [27, 30], h: [25, 29] },
  ]
  if (scenario !== 'busy') return base
  return [
    ...base,
    { id: '401810005', away: 'DEN', home: 'GS', time: '17:00', state: 'post', status_text: 'Final/OT', a: [25, 30, 22, 28, 12], h: [30, 21, 27, 27, 9], tv: ['ESPN'] },
    { id: '401810006', away: 'LAL', home: 'PHX', time: '18:00', state: 'in', period: 1, clock: '7:42', status_text: 'Q1 7:42', a: [12], h: [9] },
    { id: '401810007', away: 'BOS', home: 'LAC', time: '19:30', state: 'pre', tv: ['NBA TV'] },
    { id: '401810008', away: 'DAL', home: 'LAL', time: '19:30', state: 'pre', status: 'STATUS_POSTPONED', status_text: 'Postponed' },
  ]
}

/** College slate: Nevada's neutral-site game (followed, no prediction) plus an unfollowed live game.
 *  In `busy`, Nevada's live OT game has a college prediction (favoring UNLV). */
function collegeSlate(scenario: string): Spec[] {
  const base: Spec[] = [
    { id: '401830200', away: 'SMC', home: 'NEV', time: '13:30', state: 'pre', tv: ['CBSSN'], venue: 'T-Mobile Arena' },
    { id: '401830201', away: 'DUKE', home: 'KU', time: '16:30', state: 'in', period: 2, clock: '8:12', status_text: '2nd 8:12', a: [36, 24], h: [33, 27] },
  ]
  if (scenario !== 'busy') return base
  return [
    ...base,
    { id: '401830202', away: 'UNLV', home: 'NEV', time: '18:00', state: 'in', period: 3, clock: '1:05', status_text: 'OT 1:05', a: [30, 34, 4], h: [33, 31, 6], tv: ['MWN'], pred: [0.29, -5.5] },
  ]
}

function etToday(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date())
}

function specsFor(date: string, scenario: string, league: League): Spec[] {
  const today = etToday()
  if (league === 'ncaab') {
    if (date === today) return scenario === 'empty' ? [] : collegeSlate(scenario)
    // In the empty scenario, Nevada plays tomorrow: earlier than the NBA's next game (day +2).
    if (date === addDays(today, 1) && scenario === 'empty') {
      return [{ id: '401830210', away: 'SMC', home: 'NEV', time: '13:30', state: 'pre', tv: ['CBSSN'], venue: 'T-Mobile Arena' }]
    }
    return []
  }
  if (date === today) {
    return scenario === 'empty' ? [{ id: '401810010', away: 'PHX', home: 'MIL', time: '17:00', state: 'pre', tv: ['ESPN'] }] : slate(scenario)
  }
  if (date === addDays(today, 2)) return [{ id: '401810020', away: 'LAL', home: 'BOS', time: '16:30', state: 'pre', tv: ['ESPN'] }]
  return []
}

function gamesFor(date: string, scenario: string, league: League): GameCard[] {
  const followed = league === 'ncaab' ? FOLLOWED_NCAAB : FOLLOWED
  const games = specsFor(date, scenario, league).map((s) => card(date, s, followed, league))
  games.sort((x, y) => Number(!x.followed) - Number(!y.followed) || x.start_time.localeCompare(y.start_time))
  return games
}

export function scoreboardFor(date: string, scenario: string, league: League = 'nba'): ScoreboardResponse {
  const today = etToday()
  const v1 = scenario === 'v1'
  let games = gamesFor(date, scenario, v1 ? 'nba' : league)
  if (v1) games = games.map(({ league: _l, prediction: _p, ...g }) => g)
  const live = games.some((g) => g.state === 'in')
  const body: ScoreboardResponse = { date, games, live, refresh_seconds: live ? 30 : 300 }
  if (!v1 && date === today) {
    let next: GameCard | null = null
    for (let d = 0; d <= 7 && !next; d++) {
      next = gamesFor(addDays(today, d), scenario, league).find((g) => g.followed && g.state === 'pre' && (d > 0 || Date.parse(g.start_time) > Date.now())) ?? null
    }
    body.next_followed_game = next
  }
  return body
}

let calls = 0

/** Drop-in for httpFetchJson(). */
export function mockFetchJson(scenario: string) {
  return async (path: string): Promise<unknown> => {
    await new Promise((r) => setTimeout(r, 150))
    calls += 1
    if (scenario === 'down' || (scenario === 'flaky' && calls > 1)) throw new Error('mock: server unreachable')
    const url = new URL(path, 'http://mock')
    if (url.pathname === '/api/scoreboard') {
      const league = url.searchParams.get('league') === 'ncaab' ? 'ncaab' : 'nba'
      return scoreboardFor(url.searchParams.get('date') ?? etToday(), scenario, league)
    }
    throw new Error(`mock: 404 ${path}`)
  }
}
