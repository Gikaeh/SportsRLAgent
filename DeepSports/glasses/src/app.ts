// Controller: polling, input, and pushing text to the display only when it changed.
import {
  LEAGUES,
  RETRY_SECONDS,
  earliest,
  findNextFollowed,
  getAllScoreboards,
  pollSeconds,
  type FetchJson,
} from './api.ts'
import type { Display, DisplayInput, Slot } from './display.ts'
import { orderGames } from './format.ts'
import type { GameCard, League } from './types.ts'
import { INITIAL_VIEW, reduce, render, type Model, type ViewState } from './view.ts'

const CACHE_KEY = 'deepsports.glasses.v2' // v2: games from both leagues
const NEXT_GAME_TTL_MS = 30 * 60_000
const HEARTBEAT_MS = 5_000

type Cache = { games: GameCard[]; next: GameCard | null; lastOk: number }

/** Last good followed games per league, so one league failing keeps the other's scores fresh. */
type PerLeague = Partial<Record<League, GameCard[]>>

function loadCache(): Cache | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    return raw ? (JSON.parse(raw) as Cache) : null
  } catch {
    return null
  }
}

function saveCache(c: Cache): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(c))
  } catch {
    /* storage unavailable: fine, it's only a warm start */
  }
}

export async function runApp(display: Display, fetchJson: FetchJson): Promise<void> {
  const cached = loadCache()
  const model: Model = {
    games: cached?.games ?? null,
    next: cached?.next ?? null,
    lastOk: cached?.lastOk ?? null,
    // Cached data is old until the first fetch succeeds: show it as stale.
    failing: cached != null,
  }
  let view: ViewState = INITIAL_VIEW
  let nextCheckedAt = 0
  const byLeague: PerLeague = {}
  const okAt: Partial<Record<League, number>> = {}
  for (const g of cached?.games ?? []) (byLeague[g.league ?? 'nba'] ??= []).push(g)
  let nextPollAt = 0 // ms; 0 = poll on the next beat
  let stopped = false

  const first = render(view, model, Date.now())
  const shown: Record<Slot, string> = { header: first.header, body: first.body }
  await display.start(first.header, first.body)

  // Serialize writes so updates never interleave on the BLE link.
  let queue = Promise.resolve()
  function paint(): void {
    const screen = render(view, model, Date.now())
    for (const slot of ['header', 'body'] as const) {
      if (screen[slot] === shown[slot]) continue
      shown[slot] = screen[slot]
      const text = screen[slot]
      queue = queue.then(() => display.setText(slot, text)).catch((e) => console.error('setText failed', e))
    }
  }

  let inFlight = false
  async function poll(): Promise<void> {
    if (stopped || inFlight) return
    inFlight = true
    let wait = RETRY_SECONDS
    try {
      const results = await getAllScoreboards(fetchJson)
      const ok = results.flatMap((r) => (r.ok ? [r.sb] : []))
      for (const r of results) {
        if (r.ok) {
          byLeague[r.league] = r.sb.games.filter((g) => g.followed)
          okAt[r.league] = Date.now()
        } else console.warn(`${r.league} scoreboard fetch failed:`, r.error)
      }
      if (ok.length === 0) throw new Error('every scoreboard fetch failed')
      model.games = orderGames(LEAGUES.flatMap((l) => byLeague[l] ?? []))
      // "stale" whenever any league failed; the age shown is that of the oldest league's data.
      model.failing = ok.length < results.length
      model.lastOk = Math.min(...Object.values(okAt))
      wait = model.failing ? RETRY_SECONDS : pollSeconds(Math.min(...ok.map((sb) => sb.refresh_seconds)))
      if (model.games.length === 0) {
        // v2 servers send next_followed_game on today's scoreboard; older ones need a lookahead scan.
        if (ok.every((sb) => sb.next_followed_game !== undefined)) {
          model.next = earliest(ok.map((sb) => sb.next_followed_game))
        } else {
          const now = Date.now()
          const nextPassed = model.next != null && Date.parse(model.next.start_time) < now
          if (model.next == null ? now - nextCheckedAt > NEXT_GAME_TTL_MS : nextPassed) {
            nextCheckedAt = now
            model.next = await findNextFollowed(fetchJson, ok[0].date, undefined, LEAGUES).catch(() => model.next)
          }
        }
      } else {
        model.next = null
      }
      saveCache({ games: model.games, next: model.next, lastOk: model.lastOk })
    } catch (e) {
      console.warn('scoreboard fetch failed:', e)
      model.failing = true
    }
    nextPollAt = Date.now() + wait * 1000
    inFlight = false
    paint()
  }

  // One heartbeat drives both polling and the "stale Xm" header. If the WebView was suspended
  // (phone locked, app backgrounded), the first beat after it resumes polls straight away.
  function beat(): void {
    if (stopped) return
    if (Date.now() >= nextPollAt) void poll()
    else paint()
  }
  const heartbeat = setInterval(beat, HEARTBEAT_MS)

  const unsubscribe = display.onInput((input: DisplayInput) => {
    switch (input) {
      case 'double':
        display.exit() // system confirm dialog; clean up only on 'exit'
        return
      case 'tap':
      case 'up':
      case 'down':
        view = reduce(view, input, model.games ?? [])
        paint()
        return
      case 'foreground':
        void poll()
        return
      case 'exit':
        stopped = true
        clearInterval(heartbeat)
        unsubscribe()
        return
      default:
        return
    }
  })

  await poll()
}
