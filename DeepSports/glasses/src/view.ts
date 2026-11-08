// Pure view state: input handling and "what text goes on each container".
import type { GameCard } from './types.ts'
import {
  LOADING_BODY,
  OFFLINE_BODY,
  detailBody,
  emptyBody,
  headerText,
  listBody,
  pageCount,
  PAGE_SIZE,
} from './format.ts'

export type Input = 'tap' | 'up' | 'down'

export type ViewState = { mode: 'list'; page: number } | { mode: 'detail'; gameId: string }

export const INITIAL_VIEW: ViewState = { mode: 'list', page: 0 }

export type Model = {
  games: GameCard[] | null // ordered followed games (orderGames); null = never loaded
  next: GameCard | null // next followed game, for the empty state
  lastOk: number | null
  failing: boolean
}

export type Screen = { header: string; body: string }

/** Resolve the detail game index, falling back to the list if the game vanished. */
function normalize(view: ViewState, games: GameCard[]): ViewState {
  if (view.mode === 'detail') {
    return games.some((g) => g.id === view.gameId) ? view : INITIAL_VIEW
  }
  return { mode: 'list', page: Math.min(view.page, pageCount(games.length) - 1) }
}

/**
 * tap: list -> first game's detail; detail -> next game's detail; after the last -> list.
 * up/down: list -> previous/next page; detail -> previous/next game (up from the first -> list).
 */
export function reduce(view: ViewState, input: Input, games: GameCard[]): ViewState {
  const v = normalize(view, games)
  if (games.length === 0) return INITIAL_VIEW
  if (v.mode === 'list') {
    const pages = pageCount(games.length)
    if (input === 'tap') return { mode: 'detail', gameId: games[v.page * PAGE_SIZE]?.id ?? games[0].id }
    if (input === 'down') return { mode: 'list', page: Math.min(v.page + 1, pages - 1) }
    return { mode: 'list', page: Math.max(v.page - 1, 0) }
  }
  const i = games.findIndex((g) => g.id === v.gameId)
  if (input === 'tap') return i + 1 < games.length ? { mode: 'detail', gameId: games[i + 1].id } : INITIAL_VIEW
  if (input === 'down') return { mode: 'detail', gameId: games[Math.min(i + 1, games.length - 1)].id }
  return i === 0 ? INITIAL_VIEW : { mode: 'detail', gameId: games[i - 1].id }
}

export function render(view: ViewState, m: Model, now: number, timeZone?: string): Screen {
  const head = (right?: string) => headerText({ now, lastOk: m.lastOk, failing: m.failing, right, timeZone })
  if (m.games == null) return { header: head(), body: m.failing ? OFFLINE_BODY : LOADING_BODY }
  const games = m.games
  if (games.length === 0) return { header: head(), body: emptyBody(m.next, timeZone) }
  const v = normalize(view, games)
  if (v.mode === 'detail') {
    const i = games.findIndex((g) => g.id === v.gameId)
    return {
      header: head(`Game ${i + 1}/${games.length}`),
      body: detailBody(games[i], i === games.length - 1, timeZone),
    }
  }
  const pages = pageCount(games.length)
  return { header: head(pages > 1 ? `Page ${v.page + 1}/${pages}` : undefined), body: listBody(games, v.page) }
}
