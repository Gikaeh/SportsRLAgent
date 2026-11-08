// Pure formatting: API data -> display strings for the G2 (no SDK, no DOM, no network).
// Every line is cut to fit ~560 px and <= 34 chars (see width.ts).
import type { GameCard, League } from './types.ts'
import { fit, padLeftPx, padRightPx, textWidth, BODY_WIDTH_PX } from './width.ts'

/** "vs" at a neutral site (no real home team), "@" otherwise. */
const sep = (g: { neutral_site?: boolean }): string => (g.neutral_site ? "vs" : "@")

export const PAGE_SIZE = 5
export const LIVE = '●'
/** College marker. Plain ASCII: emoji aren't in the G2 firmware font (they'd be dropped). */
export const COLLEGE = 'NCAA'

const leagueOf = (g: GameCard): League => g.league ?? 'nba'
const isCollege = (g: GameCard) => leagueOf(g) === 'ncaab'
const collegePrefix = (g: GameCard) => (isCollege(g) ? `${COLLEGE} ` : '')

/** Followed teams' games from all leagues, live first, then by start time (stable). */
export function orderGames(games: GameCard[]): GameCard[] {
  const followed = games
    .filter((g) => g.followed)
    .map((g, i) => ({ g, i }))
    .sort((a, b) => Date.parse(a.g.start_time) - Date.parse(b.g.start_time) || a.i - b.i)
    .map((x) => x.g)
  return [...followed.filter((g) => g.state === 'in'), ...followed.filter((g) => g.state !== 'in')]
}

export function pageCount(n: number, size = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(n / size))
}

/** NBA: four quarters (Q1-Q4). College: two halves (H1, H2). Then OT, 2OT, ... */
export function periodLabel(period: number, league: League = 'nba'): string {
  const reg = league === 'ncaab' ? 2 : 4
  if (period <= reg) return league === 'ncaab' ? `H${period}` : `Q${period}`
  return period === reg + 1 ? 'OT' : `${period - reg}OT`
}

/** Intl time without the narrow no-break space newer ICU puts before AM/PM (not in the font). */
export function clockTime(when: Date | number | string, timeZone?: string): string {
  const s = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone }).format(
    new Date(when),
  )
  return s.replace(/\s/g, ' ')
}

export function dayLabel(when: Date | number | string, timeZone?: string): string {
  const s = new Intl.DateTimeFormat('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    timeZone,
  }).format(new Date(when))
  return s.replace(/\s/g, ' ')
}

const hasScore = (g: GameCard) => g.state !== 'pre' && g.away.score != null && g.home.score != null

/** One list line, e.g. "● LAL 98-95 SAC  Q4 2:31", "GS @ MIA  7:00 PM", "LAL 112-104 BOS  Final". */
export function gameLine(g: GameCard): string {
  const a = g.away.abbr
  const h = g.home.abbr
  const core = hasScore(g) ? `${a} ${g.away.score}-${g.home.score} ${h}` : `${a} ${sep(g)} ${h}`
  const prefix = (g.state === 'in' ? `${LIVE} ` : '') + collegePrefix(g)
  return fit(`${prefix}${core}  ${g.status_text}`)
}

/** "Prediction: BOS 81% · by ~6"; once final, whether the pick was right. null = no prediction. */
export function predictionLine(g: GameCard): string | null {
  const p = g.prediction
  if (!p || p.early) return null // early-season college picks stay phone-only (opt-in there)
  const head = `Prediction: ${p.favorite_abbr} ${Math.round(p.favorite_prob * 100)}%`
  if (g.state === 'post' && p.result) return fit(`${head} · ${p.result.winner_correct ? 'right' : 'wrong'}`)
  const m = Math.round(Math.abs(p.pred_home_margin))
  return fit(m === 0 ? `${head} · toss-up` : `${head} · by ~${m}`)
}

/** "LAL up 3", "tied", or "LAL won by 8" in plain language. */
export function marginText(g: GameCard): string | null {
  if (!hasScore(g)) return null
  const as = g.away.score as number
  const hs = g.home.score as number
  if (as === hs) return g.state === 'post' ? null : 'tied'
  const [lead, diff] = as > hs ? [g.away.abbr, as - hs] : [g.home.abbr, hs - as]
  return g.state === 'post' ? `${lead} won by ${diff}` : `${lead} up ${diff}`
}

/** Status line for the detail view. */
export function statusLine(g: GameCard, timeZone?: string): string {
  if (g.state === 'pre') {
    if (g.status !== 'STATUS_SCHEDULED') return g.status_text // postponed, delayed, ...
    return `Tip-off ${clockTime(g.start_time, timeZone)}`
  }
  const margin = marginText(g)
  let base = g.status_text
  if (g.state === 'in' && g.period && g.clock && !/half|end/i.test(g.status_text)) {
    base = `${periodLabel(g.period, leagueOf(g))} · ${g.clock} left`
  }
  return margin ? `${base} · ${margin}` : base
}

const LABEL_PX = 56
const COL_PX = 42
const TOTAL_PX = 64

function row(label: string, cells: string[], total: string): string {
  let line = padRightPx(label, LABEL_PX)
  let end = LABEL_PX
  for (const c of cells) {
    end += COL_PX
    line += padLeftPx(c, end - textWidth(line))
  }
  end += TOTAL_PX
  line += padLeftPx(total, end - textWidth(line))
  return line
}

/** Quarter-by-quarter table, or [] when there are no linescores yet. */
export function linescoreTable(g: GameCard): string[] {
  const a = g.away.linescores
  const h = g.home.linescores
  if (!hasScore(g) || (a.length === 0 && h.length === 0)) return []
  const league = leagueOf(g)
  const n = Math.max(league === 'ncaab' ? 2 : 4, a.length, h.length)
  const heads = Array.from({ length: n }, (_, i) => periodLabel(i + 1, league))
  const cells = (xs: number[]) => Array.from({ length: n }, (_, i) => (xs[i] == null ? '-' : String(xs[i])))
  return [
    row('', heads, 'Total'),
    row(g.away.abbr, cells(a), String(g.away.score)),
    row(g.home.abbr, cells(h), String(g.home.score)),
  ].map((l) => fit(l, BODY_WIDTH_PX, 80)) // padding spaces are narrow; only pixels matter here
}

export function tvLine(g: GameCard): string | null {
  return g.broadcasts.length ? fit(`TV: ${g.broadcasts.join(', ')}`) : null
}

/** Detail view for one game. `isLast` changes the hint (tap returns to the list). */
export function detailBody(g: GameCard, isLast: boolean, timeZone?: string): string {
  const a = g.away
  const h = g.home
  const title = hasScore(g) ? `${a.abbr} ${a.score} - ${h.score} ${h.abbr}` : `${a.short_name} ${sep(g)} ${h.short_name}`
  const lines: string[] = [
    fit((g.state === 'in' ? `${LIVE} ` : '') + collegePrefix(g) + title),
    fit(statusLine(g, timeZone)),
  ]
  const pred = predictionLine(g)
  if (pred) lines.push(pred)
  const table = linescoreTable(g)
  if (table.length) {
    // Keep within 9 lines: the prediction takes the spacer's place.
    lines.push(...(pred ? [] : ['']), ...table)
  } else {
    if (a.record || h.record) lines.push(fit(`Records: ${a.abbr} ${a.record ?? '?'}, ${h.abbr} ${h.record ?? '?'}`))
    if (g.venue) lines.push(fit(`At ${g.venue}`))
  }
  const tv = tvLine(g)
  if (tv) lines.push(tv)
  lines.push('', isLast ? 'Tap: back to list' : 'Tap: next game')
  return lines.join('\n')
}

/** Main list for one page of games. */
export function listBody(games: GameCard[], page: number): string {
  const pages = pageCount(games.length)
  const p = Math.min(Math.max(0, page), pages - 1)
  const lines = games.slice(p * PAGE_SIZE, (p + 1) * PAGE_SIZE).map(gameLine)
  lines.push('', pages > 1 ? 'Tap: details · Swipe: more' : 'Tap: details · Double-tap: exit')
  return lines.join('\n')
}

/** Shown when no followed team plays today. */
export function emptyBody(next: GameCard | null, timeZone?: string): string {
  const lines = ['No followed games today']
  if (next) {
    lines.push(
      '',
      'Next up:',
      fit(`${collegePrefix(next)}${next.away.abbr} ${sep(next)} ${next.home.abbr}`),
      fit(`${dayLabel(next.start_time, timeZone)} · ${clockTime(next.start_time, timeZone)}`),
    )
    const tv = tvLine(next)
    if (tv) lines.push(tv)
  }
  return lines.join('\n')
}

export const LOADING_BODY = 'Loading scores...'
export const OFFLINE_BODY = [
  "Can't reach DeepSports.",
  '',
  'Is the Mac awake and the',
  'server running? Retrying...',
].join('\n')

export type HeaderInput = {
  now: number
  lastOk: number | null // ms of the last successful fetch
  failing: boolean // the most recent fetch failed
  right?: string // e.g. page "1/2" or game "2/3"
  timeZone?: string
}

export const HEADER_WIDTH_PX = BODY_WIDTH_PX

/** "Scores · 7:42 PM", "Scores · 7:42 PM · stale 3m", with an optional right-aligned indicator.
 *  "Scores" rather than "NBA" since the list mixes NBA and college games. */
export function headerText({ now, lastOk, failing, right, timeZone }: HeaderInput): string {
  let left = 'Scores'
  if (lastOk == null) left += failing ? ' · offline' : ' · connecting'
  else {
    left += ` · ${clockTime(lastOk, timeZone)}`
    if (failing) left += ` · stale ${Math.max(1, Math.floor((now - lastOk) / 60000))}m`
  }
  if (!right) return fit(left)
  // Leave ~24 px slack: widths are estimates and a wrap would hide the header.
  const target = HEADER_WIDTH_PX - 24 - textWidth(right)
  return padRightPx(left, target) + right
}
