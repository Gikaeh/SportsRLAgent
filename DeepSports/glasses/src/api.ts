// Network access to the DeepSports read API (docs/API.md). Relative URLs by default because
// the plugin is served same-origin at /glasses/; VITE_API_BASE overrides that for packaged builds.
import type { BetsResponse, ParlaysResponse } from './types.ts'

export type FetchJson = (path: string) => Promise<unknown>

export const MIN_REFRESH_SECONDS = 15
export const RETRY_SECONDS = 30

export function httpFetchJson(base = ''): FetchJson {
  return async (path) => {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 10_000)
    try {
      const res = await fetch(base + path, { signal: ctrl.signal, cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${path}`)
      return await res.json()
    } finally {
      clearTimeout(timer)
    }
  }
}

export async function getBets(fetchJson: FetchJson): Promise<BetsResponse> {
  const body = (await fetchJson('/api/bets')) as BetsResponse
  if (!body || !Array.isArray(body.games)) throw new Error('unexpected /api/bets shape')
  return body
}

export async function getParlays(fetchJson: FetchJson): Promise<ParlaysResponse> {
  const body = (await fetchJson('/api/parlays')) as ParlaysResponse
  if (!body || !Array.isArray(body.parlays)) throw new Error('unexpected /api/parlays shape')
  return body
}

/** Poll interval: the server's refresh_seconds (30 live / 300 idle), never below 15 s. */
export function pollSeconds(refreshSeconds: number | undefined): number {
  const s = Number.isFinite(refreshSeconds) ? (refreshSeconds as number) : 60
  return Math.max(MIN_REFRESH_SECONDS, s)
}
