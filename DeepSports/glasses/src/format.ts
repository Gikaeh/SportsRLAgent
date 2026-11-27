// Pure formatting: /api/bets and /api/parlays -> display strings for the G2 (no SDK, no DOM, no
// network). Every line is cut to fit ~560 px and <= 34 chars (see width.ts).
import type { BetGame, League, Parlay, ParlayLeg } from './types.ts'
import { fit, padRightPx, textWidth, BODY_WIDTH_PX } from './width.ts'

export const LIVE = '●'
export const NOT_STARTED = '○'
/** Body is 9 lines: up to 8 of content plus the hint line. */
export const BODY_LINES = 8
export const LEGS_PER_PAGE = BODY_LINES - 1 // first line of a parlay page is its summary

const leagueOf = (g: { league?: League }): League => g.league ?? 'nba'
const sep = (g: { neutral_site?: boolean }): string => (g.neutral_site ? 'vs' : '@')
const hasScore = (g: BetGame) => g.state !== 'pre' && g.away.score != null && g.home.score != null

/** Intl time without the narrow no-break space newer ICU puts before AM/PM (not in the font). */
export function clockTime(when: Date | number | string, timeZone?: string): string {
  const s = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone }).format(
    new Date(when),
  )
  return s.replace(/\s/g, ' ')
}

// ---------- one bet on one game ----------

export type BetResult = 'won' | 'lost' | 'push' | 'pending'
export type BetLabel = { kind: 'total' | 'spread' | 'ml'; side: string; line: number; half: boolean }

/** "Over 144.5", "Under 70.5 1H", "NEV -1", "NEV 1H +2.5", "NEV ML"; null if unreadable. */
export function parseLabel(label: string): BetLabel | null {
  const half = /\b1H\b/.test(label)
  const s = label.replace(/\s*\b1H\b/, '').trim()
  let m = /^(Over|Under) (\d+(?:\.\d+)?)$/i.exec(s)
  if (m) return { kind: 'total', side: m[1].toLowerCase(), line: Number(m[2]), half }
  m = /^(\S+) ML$/.exec(s)
  if (m) return { kind: 'ml', side: m[1], line: 0, half }
  m = /^(\S+) ([+-]\d+(?:\.\d+)?)$/.exec(s)
  if (m) return { kind: 'spread', side: m[1], line: Number(m[2]), half }
  return null
}

/** Regulation minutes elapsed from period + clock, or null when unknown or in overtime. */
export function minutesPlayed(g: BetGame): number | null {
  const college = leagueOf(g) === 'ncaab'
  const len = college ? 20 : 12
  const periods = college ? 2 : 4
  if (g.state !== 'in' || !g.period || g.period > periods) return null
  const m = /^(\d+):(\d+)/.exec(g.clock ?? '')
  if (!m) return null
  const left = Number(m[1]) + Number(m[2]) / 60
  return (g.period - 1) * len + Math.max(0, len - left)
}

/** Projected final total at the current scoring rate; null before 5 minutes or in OT. */
export function paceTotal(g: BetGame): number | null {
  const played = minutesPlayed(g)
  if (played == null || played < 5 || !hasScore(g)) return null
  const full = leagueOf(g) === 'ncaab' ? 40 : 48
  return Math.round((((g.away.score as number) + (g.home.score as number)) / played) * full)
}

/** Points that count for a bet: the whole game, or the first half / first quarter pair for 1H. */
function points(g: BetGame, half: boolean): { away: number; home: number; done: boolean } | null {
  if (!hasScore(g)) return null
  if (!half) return { away: g.away.score as number, home: g.home.score as number, done: g.state === 'post' }
  const n = leagueOf(g) === 'ncaab' ? 1 : 2 // college halves; NBA first half = Q1 + Q2
  const sum = (xs: number[]) => xs.slice(0, n).reduce((a, b) => a + (b ?? 0), 0)
  const done = g.state === 'post' || (g.period ?? 0) > n
  return { away: sum(g.away.linescores), home: sum(g.home.linescores), done }
}

const decided = (v: number): BetResult => (v > 0 ? 'won' : v < 0 ? 'lost' : 'push')

/** How one bet stands: result (decided early when it can't change) and a short note. */
export function betStatus(label: string, g: BetGame): { result: BetResult; note: string | null } {
  const b = parseLabel(label)
  const p = b ? points(g, b.half) : null
  if (!b || !p) return { result: 'pending', note: null }
  if (b.kind === 'total') {
    const total = p.away + p.home
    const over = b.side === 'over'
    if (p.done) return { result: decided(over ? total - b.line : b.line - total), note: `${total}` }
    if (total > b.line) return { result: over ? 'won' : 'lost', note: `${total}` }
    const pace = b.half ? null : paceTotal(g)
    return { result: 'pending', note: pace == null ? `${total}` : `${total} · pace ${pace}` }
  }
  const mine = b.side === g.away.abbr ? 'away' : b.side === g.home.abbr ? 'home' : null
  if (!mine) return { result: 'pending', note: null }
  const lead = mine === 'away' ? p.away - p.home : p.home - p.away
  if (b.kind === 'ml') {
    if (p.done) return { result: decided(lead), note: null }
    return { result: 'pending', note: lead === 0 ? 'tied' : lead > 0 ? `up ${lead}` : `down ${-lead}` }
  }
  const cover = lead + b.line
  if (p.done) return { result: decided(cover), note: null }
  return { result: 'pending', note: cover === 0 ? 'on the number' : cover > 0 ? `covering by ${cover}` : `short by ${-cover}` }
}

const WORD: Record<BetResult, string> = { won: 'WON', lost: 'LOST', push: 'PUSH', pending: '' }

/** "  Over 144.5 · 110 · pace 158", "  Under 156.5 · WON 154", "  NEV -1 · covering by 2". */
export function betLine(label: string, g: BetGame): string {
  if (g.state === 'pre') return fit(`  ${label}`)
  const { result, note } = betStatus(label, g)
  const tail = result === 'pending' ? note : [WORD[result], note].filter(Boolean).join(' ')
  return fit(tail ? `  ${label} · ${tail}` : `  ${label}`)
}

/** "● ME 53-45 LEM  2nd 12:25", "UMBC @ GW  1:00 PM", "STMN 67-76 LIB  Final". */
export function gameLine(g: BetGame): string {
  const core = hasScore(g) ? `${g.away.abbr} ${g.away.score}-${g.home.score} ${g.home.abbr}` : `${g.away.abbr} ${sep(g)} ${g.home.abbr}`
  return fit(`${g.state === 'in' ? `${LIVE} ` : ''}${core}  ${g.status_text}`)
}

/** Each game as a block of lines (game line, then one line per bet), kept whole on a page. */
export function betPages(games: BetGame[]): string[][] {
  const pages: string[][] = []
  let cur: string[] = []
  for (const g of games) {
    const block = [gameLine(g), ...g.bets.map((b) => betLine(b, g))].slice(0, BODY_LINES)
    if (cur.length + block.length > BODY_LINES) {
      pages.push(cur)
      cur = []
    }
    cur.push(...block)
  }
  if (cur.length) pages.push(cur)
  return pages
}

/** Today's tally of decided bets on screen, e.g. {won: 2, lost: 1, push: 0, live: 2}. */
export function betTally(games: BetGame[]) {
  const t = { won: 0, lost: 0, push: 0, live: games.filter((g) => g.state === 'in').length }
  for (const g of games) {
    for (const b of g.bets) {
      const r = betStatus(b, g).result
      if (r !== 'pending') t[r] += 1
    }
  }
  return t
}

// ---------- parlays ----------

/** "+2.1M", "+62.9K", "+596". */
export function priceText(price: number): string {
  const sign = price > 0 ? '+' : '-'
  const a = Math.abs(price)
  if (a >= 1_000_000) return `${sign}${(a / 1_000_000).toFixed(1)}M`
  if (a >= 10_000) return `${sign}${(a / 1000).toFixed(1)}K`
  return `${sign}${a}`
}

/** "Over 145.5" -> "O145.5", "Under 139" -> "U139"; spreads and MLs stay as they are. */
const shortLabel = (label: string) => label.replace(/^Over /, 'O').replace(/^Under /, 'U')

function legTeams(l: ParlayLeg): string {
  if (l.away_abbr && l.home_abbr) return `${l.away_abbr}/${l.home_abbr}`
  if (l.matchup) {
    const [a, h] = l.matchup.split(' @ ')
    return h ? `${a.split(' ')[0]}/${h.split(' ')[0]}` : l.matchup
  }
  return '?'
}

const LEG_MARK: Record<string, string> = { won: 'W', lost: 'L', push: 'P' }

/** "W UVA/XAV U156.5  154", "● ME/LEM U139  98, 2nd 12:25", "○ UMBC/GW U152.5  1:00 PM". */
export function legLine(l: ParlayLeg, timeZone?: string): string {
  const live = l.state === 'in'
  const mark = LEG_MARK[l.status] ?? (live ? LIVE : NOT_STARTED)
  const pts = l.away_score != null && l.home_score != null ? l.away_score + l.home_score : null
  let tail: string
  if (l.state === 'pre' || pts == null) tail = l.start_time ? clockTime(l.start_time, timeZone) : (l.status_text ?? '')
  else if (live) tail = l.status === 'pending' ? `${pts}, ${l.status_text ?? ''}` : `${pts}`
  else tail = `${pts}`
  return fit(`${mark} ${legTeams(l)} ${shortLabel(l.label)}  ${tail}`.trimEnd())
}

const isAlive = (p: Parlay) => p.status === 'alive'

export function parlayResult(p: Parlay): string {
  if (isAlive(p)) return p.lost ? 'LOST' : 'ALIVE'
  return ({ won: 'WON', win: 'WON', lost: 'LOST', loss: 'LOST', push: 'PUSH', void: 'VOID' } as Record<string, string>)[p.status] ?? p.status.toUpperCase()
}

/** "LOST +21.2M · 2-1 · 16/19 left", "WON +257 · 2-0 of 2". */
export function parlaySummary(p: Parlay): string {
  const n = p.legs.length
  const left = p.pending ? ` · ${p.pending}/${n} left` : ` of ${n}`
  return fit(`${parlayResult(p)} ${priceText(p.price)} · ${p.won}-${p.lost}${left}`)
}

/** Alive parlays first (newest first within each group, the server's order), 7 legs per page. */
export function parlayPages(parlays: Parlay[], timeZone?: string): string[][] {
  const ordered = [...parlays.filter(isAlive), ...parlays.filter((p) => !isAlive(p))]
  const pages: string[][] = []
  for (const p of ordered) {
    const n = Math.max(1, Math.ceil(p.legs.length / LEGS_PER_PAGE))
    for (let i = 0; i < n; i++) {
      const legs = p.legs.slice(i * LEGS_PER_PAGE, (i + 1) * LEGS_PER_PAGE).map((l) => legLine(l, timeZone))
      const from = i * LEGS_PER_PAGE + 1
      const head = i === 0 ? parlaySummary(p) : fit(`${parlayResult(p)} · legs ${from}-${from + legs.length - 1} of ${p.legs.length}`)
      pages.push([head, ...legs])
    }
  }
  return pages
}

// ---------- header and fixed bodies ----------

export const LOADING_BODY = 'Loading bets...'
export const OFFLINE_BODY = ["Can't reach DeepSports.", '', 'Is the Mac awake and the', 'server running? Retrying...'].join('\n')
export const NO_BETS_BODY = ['No open bets', '', 'Games with a bet that is not', 'graded yet show up here.', '', 'Tap: parlays'].join('\n')
export const NO_PARLAYS_BODY = ['No parlays today', '', 'Open parlays and ones placed', 'today show up here.', '', 'Tap: bets'].join('\n')

export type HeaderInput = {
  title: string // "Bets 2-1 · 2 live" or "Parlays"
  now: number
  lastOk: number | null // ms of the last successful fetch
  failing: boolean // the most recent fetch failed
  right?: string // page "1/5"
  timeZone?: string
}

export const HEADER_WIDTH_PX = BODY_WIDTH_PX

/** "Bets 2-1 · 2 live · 12:21 PM", "Bets 2-1 · 2 live · stale 3m", with an optional right-aligned page. */
export function headerText({ title, now, lastOk, failing, right, timeZone }: HeaderInput): string {
  let left = title
  if (lastOk == null) left += failing ? ' · offline' : ' · connecting'
  else {
    // Stale replaces the time so the header stays short: the age is what matters then.
    left += failing ? ` · stale ${Math.max(1, Math.floor((now - lastOk) / 60000))}m` : ` · ${clockTime(lastOk, timeZone)}`
  }
  if (!right) return fit(left)
  // Leave ~24 px slack: widths are estimates and a wrap would hide the header.
  const target = HEADER_WIDTH_PX - 24 - textWidth(right)
  return padRightPx(fit(left, target - 8), target) + right
}
