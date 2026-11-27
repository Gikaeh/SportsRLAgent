// Run with `npm test` (node:test + Node's built-in TypeScript stripping; no extra deps).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getAdvW, getTextWidth } from '@evenrealities/pretext'
import {
  betLine,
  betPages,
  betStatus,
  betTally,
  clockTime,
  gameLine,
  headerText,
  legLine,
  paceTotal,
  parlayPages,
  parlaySummary,
  parseLabel,
  priceText,
  BODY_LINES,
} from '../src/format.ts'
import { getBets, getParlays, pollSeconds } from '../src/api.ts'
import { reduce, render, INITIAL_VIEW, type Model } from '../src/view.ts'
import { textWidth, fit, BODY_WIDTH_PX } from '../src/width.ts'
import { betsFor, game, mockFetchJson, parlaysFor, SPECS } from '../src/mock/fixtures.ts'
import type { BetGame } from '../src/types.ts'

const TZ = 'America/Los_Angeles'
const RELIABLE = new Set([...'●○■□★☆━─·▲▼↑↓'])

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

const byId = (id: string) => game(SPECS.find((s) => s.id === id)!)
const model = (scenario: string): Model => ({
  games: betsFor(scenario).games,
  parlays: parlaysFor(scenario).parlays,
  lastOk: Date.now(),
  failing: false,
})

test('width table matches pretext within kerning slack', () => {
  for (const s of ['● FRES 62-48 USA  2nd 8:49', '  Over 144.5 · 110 · pace 158', 'Tap: parlays · Swipe: more']) {
    const diff = textWidth(s) - getTextWidth(s)
    assert.ok(diff >= -1 && diff <= getTextWidth(s) * 0.08, `${s}: est ${textWidth(s)} vs ${getTextWidth(s)}`)
  }
})

test('fit truncates by chars and pixels', () => {
  assert.equal(fit('short'), 'short')
  const long = fit('X'.repeat(80))
  assert.ok([...long].length <= 34 && textWidth(long) <= BODY_WIDTH_PX && long.endsWith('..'))
})

test('parseLabel reads every label the bets API sends', () => {
  assert.deepEqual(parseLabel('Over 144.5'), { kind: 'total', side: 'over', line: 144.5, half: false })
  assert.deepEqual(parseLabel('Under 70.5 1H'), { kind: 'total', side: 'under', line: 70.5, half: true })
  assert.deepEqual(parseLabel('NEV -1'), { kind: 'spread', side: 'NEV', line: -1, half: false })
  assert.deepEqual(parseLabel('NEV 1H -0.5'), { kind: 'spread', side: 'NEV', line: -0.5, half: true })
  assert.deepEqual(parseLabel('TA&M ML'), { kind: 'ml', side: 'TA&M', line: 0, half: false })
  assert.equal(parseLabel('something else'), null)
})

test('totals: live pace, decided early, final result', () => {
  // ME 53-45 LEM with 12:25 left in the 2nd: 27.6 min played, 98 pts -> pace 142.
  assert.equal(paceTotal(byId('1')), 142)
  assert.deepEqual(betStatus('Under 139', byId('1')), { result: 'pending', note: '98 · pace 142' })
  assert.equal(betLine('Under 139', byId('1')), '  Under 139 · 98 · pace 142')
  assert.deepEqual(betStatus('Under 156.5', byId('6')), { result: 'won', note: '154' })
  assert.equal(betLine('Over 146.5', byId('7')), '  Over 146.5 · LOST 143')
  assert.equal(betStatus('Under 90', byId('1')).result, 'lost') // live under already past the line
  assert.equal(betStatus('Over 90', byId('1')).result, 'won')
  const pre = byId('4')
  assert.equal(betLine('Under 152.5', pre), '  Under 152.5')
})

test('spreads, moneylines and first-half bets', () => {
  const lal = byId('3') // LAL 98-95 SAC, Q4 2:31
  assert.deepEqual(betStatus('LAL -2.5', lal), { result: 'pending', note: 'covering by 0.5' })
  assert.deepEqual(betStatus('SAC +2.5', lal), { result: 'pending', note: 'short by 0.5' })
  assert.deepEqual(betStatus('LAL ML', lal), { result: 'pending', note: 'up 3' })
  assert.deepEqual(betStatus('LAL -3', lal), { result: 'pending', note: 'on the number' })
  // NBA first half = Q1 + Q2 (LAL 53, SAC 51), decided since Q3 started.
  assert.equal(betStatus('Over 100.5 1H', lal).result, 'won')
  assert.equal(betStatus('LAL 1H -2', lal).result, 'push')
  const fin = byId('6') // UVA 83-71 XAV final
  assert.equal(betStatus('XAV +12', fin).result, 'push')
  assert.equal(betStatus('UVA ML', fin).result, 'won')
  assert.equal(betStatus('ZZZ -1', fin).result, 'pending') // unknown team: no guess
})

test('game lines', () => {
  assert.equal(gameLine(byId('1')), '● ME 53-45 LEM  2nd 12:25')
  assert.equal(gameLine(byId('4')), 'UMBC @ GW  1:00 PM')
  assert.equal(gameLine(byId('7')), 'STMN 67-76 LIB  Final')
})

test('bet pages keep a game with its bets and stay within 8 lines', () => {
  const games = betsFor('busy').games
  const pages = betPages(games)
  assert.equal(pages.flat().length, games.length + games.reduce((n, g) => n + g.bets.length, 0))
  for (const p of pages) assert.ok(p.length <= BODY_LINES)
  for (const p of pages) assert.ok(!p[0].startsWith('  '), 'a page starts with a game line, not a bet')
})

test('tally counts decided bets and live games', () => {
  assert.deepEqual(betTally(betsFor('default').games), { won: 1, lost: 1, push: 0, live: 3 })
})

test('parlay pages: summary, 7 legs a page, alive tickets first', () => {
  const parlays = parlaysFor('default').parlays
  assert.equal(priceText(21213755), '+21.2M')
  assert.equal(priceText(62877), '+62.9K')
  assert.equal(priceText(-120), '-120')
  assert.equal(parlaySummary(parlays[0]), 'LOST +21.2M · 1-1 · 7/9 left')
  const pages = parlayPages(parlays, TZ)
  assert.equal(pages.length, 3) // the alive 2-leg ticket, then the lost 9-leg one over 2 pages
  assert.equal(pages[0][0], 'ALIVE +257 · 1-0 · 1/2 left')
  assert.match(pages[2][0], /^LOST · legs 8-9 of 9$/)
  assert.equal(pages[1].length, 8)
  const legs = parlays[0].legs
  assert.equal(legLine(legs[0], TZ), 'W UVA/XAV U156.5  154')
  assert.equal(legLine(legs[1], TZ), 'L STMN/LIB O146.5  143')
  assert.equal(legLine(legs[2], TZ), '● ME/LEM U139  98, 2nd 12:25')
  assert.equal(legLine(legs[4], TZ), '○ UMBC/GW U152.5  1:00 PM')
  // Older servers send no abbreviations: fall back to the matchup's first words.
  assert.equal(legLine({ ...legs[4], away_abbr: undefined, matchup: 'UMBC Retrievers @ George Washington' }, TZ), '○ UMBC/George U152.5  1:00 PM')
})

test('every screen of every scenario fits the display (<= 9 lines, width, glyphs)', () => {
  for (const scenario of ['default', 'busy', 'empty']) {
    const m = model(scenario)
    for (const tab of ['bets', 'parlays'] as const) {
      for (let page = 0; page < 6; page++) {
        const s = render({ tab, page }, m, Date.now(), TZ)
        assert.ok(s.body.split('\n').length <= 9, `${scenario}/${tab}/${page}: ${s.body}`)
        assertDisplayable(s.body)
        assertDisplayable(s.header, 576 - 8)
      }
    }
  }
})

test('reduce: tap switches tabs, swipes page and clamp', () => {
  const m = model('busy')
  let v = INITIAL_VIEW
  v = reduce(v, 'up', m)
  assert.deepEqual(v, { tab: 'bets', page: 0 })
  v = reduce(reduce(v, 'down', m), 'down', m)
  const n = betPages(m.games!).length
  assert.equal(v.page, Math.min(2, n - 1))
  for (let i = 0; i < 10; i++) v = reduce(v, 'down', m)
  assert.equal(v.page, n - 1)
  v = reduce(v, 'tap', m)
  assert.deepEqual(v, { tab: 'parlays', page: 0 })
  v = reduce(v, 'tap', m)
  assert.deepEqual(v, { tab: 'bets', page: 0 })
})

test('render: header tally, page indicator, hints, empty, loading, offline', () => {
  const now = Date.parse('2026-11-27T12:21:00-08:00')
  const m = { ...model('busy'), lastOk: now }
  const s = render(INITIAL_VIEW, m, now, TZ)
  assert.match(s.header, /^Bets 1-1 · 3 live · 12:21 PM +1\/\d$/)
  assert.ok(s.body.endsWith('Tap: parlays · Swipe: more'))
  const p = render({ tab: 'parlays', page: 0 }, m, now, TZ)
  assert.match(p.header, /^Parlays · 1 alive · 12:21 PM +1\/3$/)
  assert.match(render(INITIAL_VIEW, { ...model('empty'), lastOk: now }, now, TZ).body, /^No open bets/)
  assert.match(render({ tab: 'parlays', page: 0 }, { ...model('empty'), lastOk: now }, now, TZ).body, /^No parlays today/)
  const none: Model = { games: null, parlays: null, lastOk: null, failing: false }
  assert.equal(render(INITIAL_VIEW, none, now).body, 'Loading bets...')
  assert.match(render(INITIAL_VIEW, { ...none, failing: true }, now).body, /^Can't reach DeepSports/)
  assert.match(render(INITIAL_VIEW, { ...m, failing: true }, now + 3 * 60_000, TZ).header, /stale 3m/)
})

test('header: time, stale marker, right-aligned indicator', () => {
  const lastOk = Date.parse('2026-11-03T19:42:00-08:00')
  assert.equal(headerText({ title: 'Bets', now: lastOk, lastOk, failing: false, timeZone: TZ }), 'Bets · 7:42 PM')
  assert.equal(headerText({ title: 'Bets', now: 0, lastOk: null, failing: false }), 'Bets · connecting')
  const h = headerText({ title: 'Bets 12-11 · 4 live', now: lastOk + 61_000, lastOk, failing: true, right: '12/12', timeZone: TZ })
  assert.match(h, /12\/12$/)
  assertDisplayable(h, 576 - 8)
  assert.ok(!/ /.test(clockTime(lastOk, TZ)), 'no narrow no-break space')
})

test('api: shapes checked, poll interval has a 15 s floor', async () => {
  const f = mockFetchJson('default')
  assert.ok((await getBets(f)).games.length > 0)
  assert.ok((await getParlays(f)).parlays.length > 0)
  await assert.rejects(getBets(async () => ({ nope: 1 })))
  assert.equal(pollSeconds(30), 30)
  assert.equal(pollSeconds(5), 15)
  assert.equal(pollSeconds(undefined), 60)
})

test('real-world label shapes never crash a bet line', () => {
  const g: BetGame = byId('3')
  for (const label of ['Over 216.5', 'TOR -2.5', 'LAL ML', 'Under 110.5 1H', '', 'weird label']) assertDisplayable(betLine(label, g))
})
