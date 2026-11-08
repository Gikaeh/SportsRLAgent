// Run with `npm test` (node:test + Node's built-in TypeScript stripping; no extra deps).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getAdvW, getTextWidth } from '@evenrealities/pretext'
import {
  clockTime,
  detailBody,
  emptyBody,
  gameLine,
  headerText,
  linescoreTable,
  listBody,
  orderGames,
  periodLabel,
  predictionLine,
  statusLine,
} from '../src/format.ts'
import { addDays, pollSeconds, findNextFollowed, getAllScoreboards, getScoreboard, earliest } from '../src/api.ts'
import { reduce, render, INITIAL_VIEW, type Model } from '../src/view.ts'
import { textWidth, fit, BODY_WIDTH_PX } from '../src/width.ts'
import { scoreboardFor, mockFetchJson } from '../src/mock/fixtures.ts'
import type { GameCard } from '../src/types.ts'

const TZ = 'America/Los_Angeles'
const RELIABLE = new Set([...'●○■□★☆━─·▲▼↑↓'])

function etToday(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date())
}

/** Every line fits the width budget, and every glyph exists in the firmware font. */
function assertDisplayable(text: string, maxPx = BODY_WIDTH_PX + 8) {
  for (const line of text.split('\n')) {
    assert.ok(getTextWidth(line) <= maxPx, `too wide (${getTextWidth(line)}px): ${JSON.stringify(line)}`)
    for (const ch of line) {
      const cp = ch.codePointAt(0)!
      if (cp >= 32 && cp < 127) continue
      assert.ok(RELIABLE.has(ch), `unlisted glyph U+${cp.toString(16)} in ${JSON.stringify(line)}`)
      assert.ok(getAdvW(cp) > 0, `glyph missing from font: ${ch}`)
    }
  }
}

const today = etToday()
const busy = orderGames(scoreboardFor(today, 'busy').games)
const byId = (id: string) => busy.find((g) => g.id === id) as GameCard

test('width table matches pretext within kerning slack', () => {
  for (const s of ['LAL 98-95 SAC  Q4 2:31', '● GS 101-99 MIA  Q4 0:42', 'Tap: details · Swipe: more', 'Wed, Nov 5 · 7:30 PM']) {
    const diff = textWidth(s) - getTextWidth(s)
    assert.ok(diff >= -1 && diff <= getTextWidth(s) * 0.08, `${s}: est ${textWidth(s)} vs ${getTextWidth(s)}`)
  }
})

test('fit truncates by chars and pixels', () => {
  assert.equal(fit('short'), 'short')
  const long = fit('X'.repeat(80))
  assert.ok([...long].length <= 34 && textWidth(long) <= BODY_WIDTH_PX && long.endsWith('..'))
})

test('orderGames: followed only, live first, server order otherwise', () => {
  assert.ok(busy.every((g) => g.followed))
  const firstNonLive = busy.findIndex((g) => g.state !== 'in')
  assert.ok(busy.slice(0, firstNonLive).every((g) => g.state === 'in'))
  assert.ok(busy.slice(firstNonLive).every((g) => g.state !== 'in'))
  assert.ok(!busy.some((g) => g.id === '401810004'), 'unfollowed MIL-ORL excluded')
})

test('game lines', () => {
  assert.match(gameLine(byId('401810001')), /^● LAL \d+-\d+ SAC {2}Q4 \d:\d\d$/)
  assert.equal(gameLine(byId('401810002')), 'NY 104-112 BOS  Final')
  assert.equal(gameLine(byId('401810003')), 'GS @ MIA  7:30 PM')
  assert.equal(gameLine(byId('401810008')), 'DAL @ LAL  Postponed')
  for (const g of busy) assertDisplayable(gameLine(g))
})

test('status lines in plain language', () => {
  assert.equal(statusLine(byId('401810002')), 'Final · BOS won by 8')
  assert.equal(statusLine(byId('401810006')), 'Q1 · 7:42 left · LAL up 3')
  assert.equal(statusLine(byId('401810003'), TZ), 'Tip-off 7:30 PM')
  assert.equal(statusLine(byId('401810008'), TZ), 'Postponed')
})

test('linescore table includes OT columns and totals', () => {
  const t = linescoreTable(byId('401810005'))
  assert.equal(t.length, 3)
  assert.match(t[0], /Q1\s+Q2\s+Q3\s+Q4\s+OT\s+Total/)
  assert.match(t[1], /^DEN\s+25\s+30\s+22\s+28\s+12\s+117$/)
  assert.deepEqual(linescoreTable(byId('401810003')), [])
  // Q1-only live game pads unplayed quarters with '-'.
  assert.match(linescoreTable(byId('401810006'))[1], /^LAL\s+12\s+-\s+-\s+-\s+12$/)
})

test('every view of every scenario fits the display (<= 9 lines, width, glyphs)', () => {
  for (const g of busy) {
    const body = detailBody(g, false, TZ)
    assert.ok(body.split('\n').length <= 9, body)
    assertDisplayable(body)
  }
  for (const page of [0, 1]) {
    const body = listBody(busy, page)
    assert.ok(body.split('\n').length <= 9)
    assertDisplayable(body)
  }
})

test('header: time, stale marker, right-aligned indicator', () => {
  const lastOk = Date.parse('2026-11-03T19:42:00-08:00')
  assert.equal(headerText({ now: lastOk, lastOk, failing: false, timeZone: TZ }), 'Scores · 7:42 PM')
  assert.equal(
    headerText({ now: lastOk + 5 * 60_000 + 10, lastOk, failing: true, timeZone: TZ }),
    'Scores · 7:42 PM · stale 5m',
  )
  assert.equal(headerText({ now: 0, lastOk: null, failing: false }), 'Scores · connecting')
  const h = headerText({ now: lastOk, lastOk, failing: true, right: 'Game 2/7', timeZone: TZ })
  assert.match(h, /^Scores · 7:42 PM · stale 1m +Game 2\/7$/)
  assertDisplayable(h, 576 - 8)
  assert.ok(!/\u202f/.test(clockTime(lastOk, TZ)), 'no narrow no-break space')
})

test('empty state shows the next followed game', async () => {
  const next = await findNextFollowed(mockFetchJson('empty'), today)
  assert.ok(next)
  assert.equal(next.start_time.slice(0, 10), addDays(today, 2))
  const body = emptyBody(next, TZ)
  assert.match(body, /^No followed games today\n\nNext up:\nLAL @ BOS\n\w{3}, \w{3} \d+ · 4:30 PM\nTV: ESPN$/)
  assertDisplayable(body)
  assert.equal(emptyBody(null), 'No followed games today')
})

test('reduce: tap cycles details then back to list; swipes page', () => {
  let v = reduce(INITIAL_VIEW, 'down', busy)
  assert.deepEqual(v, { mode: 'list', page: 1 })
  assert.deepEqual(reduce(v, 'down', busy), { mode: 'list', page: 1 }, 'clamped at last page')
  v = reduce(INITIAL_VIEW, 'tap', busy)
  assert.deepEqual(v, { mode: 'detail', gameId: busy[0].id })
  for (let i = 1; i < busy.length; i++) v = reduce(v, 'tap', busy)
  assert.deepEqual(v, { mode: 'detail', gameId: busy[busy.length - 1].id })
  assert.deepEqual(reduce(v, 'tap', busy), INITIAL_VIEW, 'tap after last game returns to list')
  assert.deepEqual(reduce({ mode: 'detail', gameId: busy[0].id }, 'up', busy), INITIAL_VIEW)
  assert.deepEqual(reduce({ mode: 'detail', gameId: 'gone' }, 'tap', busy), { mode: 'detail', gameId: busy[0].id })
  assert.deepEqual(reduce(INITIAL_VIEW, 'tap', []), INITIAL_VIEW)
})

test('render: loading, offline, stale data, empty', () => {
  const now = Date.now()
  const base: Model = { games: null, next: null, lastOk: null, failing: false }
  assert.equal(render(INITIAL_VIEW, base, now).body, 'Loading scores...')
  assert.match(render(INITIAL_VIEW, { ...base, failing: true }, now).body, /^Can't reach DeepSports/)
  const stale = render(INITIAL_VIEW, { ...base, games: busy, lastOk: now - 180_000, failing: true }, now)
  assert.match(stale.header, /stale 3m +Page 1\/2$/)
  assert.ok(stale.body.startsWith('● '))
  assert.equal(render(INITIAL_VIEW, { ...base, games: [], lastOk: now }, now).body, 'No followed games today')
})

test('poll interval honours refresh_seconds with a 15 s floor', () => {
  assert.equal(pollSeconds(30), 30)
  assert.equal(pollSeconds(300), 300)
  assert.equal(pollSeconds(5), 15)
  assert.equal(pollSeconds(undefined), 60)
})

// ---------- v2: college + predictions ----------
const college = scoreboardFor(today, 'busy', 'ncaab').games
const both = orderGames([...scoreboardFor(today, 'busy').games, ...college])
const anyId = (id: string) => both.find((g) => g.id === id) as GameCard

test('college: halves, NCAA marker, followed only', () => {
  assert.equal(periodLabel(2, 'ncaab'), 'H2')
  assert.equal(periodLabel(3, 'ncaab'), 'OT')
  assert.equal(periodLabel(4, 'ncaab'), '2OT')
  assert.equal(periodLabel(4), 'Q4')
  assert.equal(gameLine(anyId('401830200')), 'NCAA SMC @ NEV  1:30 PM')
  assert.match(gameLine(anyId('401830202')), /^● NCAA UNLV 68-70 NEV {2}OT 1:05$/)
  assert.ok(!both.some((g) => g.id === '401830201'), 'unfollowed DUKE-KU excluded')
  assert.equal(statusLine(anyId('401830202')), 'OT · 1:05 left · NEV up 2')
  const t = linescoreTable(anyId('401830202'))
  assert.match(t[0], /H1\s+H2\s+OT\s+Total/)
  assert.ok(!/Q3/.test(t[0]), 'no empty quarter columns for college')
})

test('mixed leagues: live first across leagues, then by start time', () => {
  const firstNonLive = both.findIndex((g) => g.state !== 'in')
  assert.ok(both.slice(0, firstNonLive).some((g) => g.league === 'ncaab'))
  assert.ok(both.slice(firstNonLive).every((g) => g.state !== 'in'))
  const rest = both.slice(firstNonLive).map((g) => Date.parse(g.start_time))
  assert.deepEqual(rest, [...rest].sort((a, b) => a - b))
  for (const g of both) {
    const body = detailBody(g, false, TZ)
    assert.ok(body.split('\n').length <= 9, body)
    assertDisplayable(body)
    assertDisplayable(gameLine(g))
  }
  for (const page of [0, 1, 2]) assertDisplayable(listBody(both, page))
})

test('prediction line in the detail view', () => {
  assert.equal(predictionLine(anyId('401810003')), 'Prediction: GS 62% · by ~4')
  assert.equal(predictionLine(anyId('401810002')), 'Prediction: BOS 81% · right')
  assert.equal(predictionLine(anyId('401830200')), null, 'college has no prediction')
  const pre = detailBody(anyId('401810003'), false, TZ)
  assert.match(pre, /^GS @ MIA|^Warriors @ Heat/)
  assert.match(pre.split('\n')[2], /^Prediction: GS 62%/)
  const fin = detailBody(anyId('401810002'), false, TZ).split('\n')
  assert.equal(fin[2], 'Prediction: BOS 81% · right')
  assert.ok(fin.length <= 9)
  assert.ok(!/Model/.test(detailBody(anyId('401830200'), false, TZ)))
})

test('college prediction: same line, long abbreviations still fit', () => {
  // Fixture: UNLV @ NEV (live, OT) has an ncaab-v1 prediction favoring UNLV.
  const live = anyId('401830202')
  assert.equal(live.prediction?.model_version, 'ncaab-v1')
  assert.equal(predictionLine(live), 'Prediction: UNLV 71% · by ~6')
  const body = detailBody(live, false, TZ).split('\n')
  assert.equal(body[2], 'Prediction: UNLV 71% · by ~6')
  assert.ok(body.length <= 9, body.join('\n'))
  assertDisplayable(body.join('\n'))
  // Worst case: a 5-letter favorite, 100%-ish, double-digit margin, pre and graded.
  const base = { ...live, home: { ...live.home, abbr: 'WAKE' }, away: { ...live.away, abbr: 'UCONN' } }
  const pred = { ...live.prediction!, favorite_abbr: 'UCONN', favorite_prob: 0.996, pred_home_margin: -24.4 }
  const pre: GameCard = { ...base, state: 'pre', prediction: { ...pred, result: undefined } }
  assert.equal(predictionLine(pre), 'Prediction: UCONN 100% · by ~24')
  const fin: GameCard = {
    ...base,
    state: 'post',
    prediction: { ...pred, result: { winner_correct: false, margin_error: 30, total_error: 12 } },
  }
  assert.equal(predictionLine(fin), 'Prediction: UCONN 100% · wrong')
  for (const g of [pre, fin]) {
    assertDisplayable(predictionLine(g)!)
    assertDisplayable(detailBody(g, true, TZ))
  }
})

test('getScoreboard drops NBA games a v1 server returns for league=ncaab', async () => {
  const sb = await getScoreboard(mockFetchJson('v1'), undefined, 'ncaab')
  assert.equal(sb.games.length, 0)
  assert.equal(sb.next_followed_game, undefined, 'v1: no next_followed_game, so the app falls back to lookahead')
  const nba = await getScoreboard(mockFetchJson('v1'))
  assert.ok(nba.games.length > 0)
})

test('next_followed_game: earliest across both leagues', async () => {
  const results = await getAllScoreboards(mockFetchJson('empty'))
  assert.ok(results.every((r) => r.ok))
  const nexts = results.map((r) => (r.ok ? r.sb.next_followed_game : null))
  const next = earliest(nexts)
  assert.ok(next)
  assert.equal(next.league, 'ncaab')
  const body = emptyBody(next, TZ)
  assert.match(body, /^No followed games today\n\nNext up:\nNCAA SMC @ NEV\n\w{3}, \w{3} \d+ · 1:30 PM\nTV: CBSSN$/)
  assertDisplayable(body)
  // The lookahead fallback (v1 servers) also checks college.
  const scanned = await findNextFollowed(mockFetchJson('empty'), today, 7, ['nba', 'ncaab'])
  assert.equal(scanned?.id, '401830210')
})

test('early-season college predictions are never shown on the glasses', () => {
  const live = anyId('401830202')
  assert.ok(live.prediction)
  const early = { ...live, prediction: { ...live.prediction, model_version: 'ncaab-v1-early', early: true } }
  assert.equal(predictionLine(early), null)
})
