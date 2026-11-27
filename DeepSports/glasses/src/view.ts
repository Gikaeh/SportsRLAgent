// Pure view state: input handling and "what text goes on each container".
// Two tabs: Bets (every game with an open bet) and Parlays (each ticket's legs).
// Tap switches tabs; swipe down/up pages within the tab.
import type { BetGame, Parlay } from './types.ts'
import {
  LOADING_BODY,
  NO_BETS_BODY,
  NO_PARLAYS_BODY,
  OFFLINE_BODY,
  betPages,
  betTally,
  headerText,
  parlayPages,
} from './format.ts'

export type Input = 'tap' | 'up' | 'down'

export type Tab = 'bets' | 'parlays'

export type ViewState = { tab: Tab; page: number }

export const INITIAL_VIEW: ViewState = { tab: 'bets', page: 0 }

export type Model = {
  games: BetGame[] | null // /api/bets, server order (live, upcoming, finals); null = never loaded
  parlays: Parlay[] | null
  lastOk: number | null
  failing: boolean
}

export type Screen = { header: string; body: string }

function pagesFor(tab: Tab, m: Model, timeZone?: string): string[][] {
  if (tab === 'bets') return m.games ? betPages(m.games) : []
  return m.parlays ? parlayPages(m.parlays, timeZone) : []
}

export function reduce(view: ViewState, input: Input, m: Model, timeZone?: string): ViewState {
  if (input === 'tap') return { tab: view.tab === 'bets' ? 'parlays' : 'bets', page: 0 }
  const n = Math.max(1, pagesFor(view.tab, m, timeZone).length)
  const page = Math.min(view.page, n - 1)
  return { tab: view.tab, page: input === 'down' ? Math.min(page + 1, n - 1) : Math.max(page - 1, 0) }
}

export function render(view: ViewState, m: Model, now: number, timeZone?: string): Screen {
  const data = view.tab === 'bets' ? m.games : m.parlays
  let title = 'Parlays'
  if (view.tab === 'bets') {
    title = 'Bets'
    if (m.games) {
      const t = betTally(m.games)
      if (t.won + t.lost + t.push) title += ` ${t.won}-${t.lost}${t.push ? `-${t.push}` : ''}`
      if (t.live) title += ` · ${t.live} live`
    }
  } else if (m.parlays) {
    const alive = m.parlays.filter((p) => p.status === 'alive' && !p.lost).length
    if (alive) title += ` · ${alive} alive`
  }
  const head = (right?: string) => headerText({ title, now, lastOk: m.lastOk, failing: m.failing, right, timeZone })
  if (data == null) return { header: head(), body: m.failing ? OFFLINE_BODY : LOADING_BODY }
  const pages = pagesFor(view.tab, m, timeZone)
  if (pages.length === 0) return { header: head(), body: view.tab === 'bets' ? NO_BETS_BODY : NO_PARLAYS_BODY }
  const page = Math.min(view.page, pages.length - 1)
  const other = view.tab === 'bets' ? 'parlays' : 'bets'
  const hint = pages.length > 1 ? `Tap: ${other} · Swipe: more` : `Tap: ${other}`
  return {
    header: head(pages.length > 1 ? `${page + 1}/${pages.length}` : undefined),
    body: [...pages[page], hint].join('\n'),
  }
}
