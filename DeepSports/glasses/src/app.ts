// Controller: polling /api/bets + /api/parlays, input, and pushing text to the display only when it changed.
import { RETRY_SECONDS, getBets, getParlays, pollSeconds, type FetchJson } from './api.ts'
import type { Display, DisplayInput, Slot } from './display.ts'
import type { BetGame, Parlay } from './types.ts'
import { INITIAL_VIEW, reduce, render, type Model, type ViewState } from './view.ts'

const CACHE_KEY = 'deepsports.glasses.v3' // v3: bets + parlays
const HEARTBEAT_MS = 5_000

type Cache = { games: BetGame[] | null; parlays: Parlay[] | null; lastOk: number }

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
    parlays: cached?.parlays ?? null,
    lastOk: cached?.lastOk ?? null,
    // Cached data is old until the first fetch succeeds: show it as stale.
    failing: cached != null,
  }
  let view: ViewState = INITIAL_VIEW
  const okAt: { bets?: number; parlays?: number } = {}
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
    const [bets, parlays] = await Promise.allSettled([getBets(fetchJson), getParlays(fetchJson)])
    const refresh: number[] = []
    if (bets.status === 'fulfilled') {
      model.games = bets.value.games
      okAt.bets = Date.now()
      refresh.push(bets.value.refresh_seconds)
    } else console.warn('bets fetch failed:', bets.reason)
    if (parlays.status === 'fulfilled') {
      model.parlays = parlays.value.parlays
      okAt.parlays = Date.now()
      refresh.push(parlays.value.refresh_seconds)
    } else console.warn('parlays fetch failed:', parlays.reason)
    // "stale" whenever either failed; the age shown is that of the older data.
    model.failing = refresh.length < 2
    const times = Object.values(okAt)
    if (times.length) model.lastOk = Math.min(...times)
    if (!model.failing) wait = pollSeconds(Math.min(...refresh))
    if (refresh.length) saveCache({ games: model.games, parlays: model.parlays, lastOk: model.lastOk ?? Date.now() })
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
        view = reduce(view, input, model)
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
