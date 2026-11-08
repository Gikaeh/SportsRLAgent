import { httpFetchJson, type FetchJson } from './api.ts'
import { runApp } from './app.ts'
import type { Display } from './display.ts'
import { createEvenDisplay } from './even.ts'
import { createPreviewDisplay, withMirror } from './preview.ts'

const params = new URLSearchParams(location.search)

async function main(): Promise<void> {
  let fetchJson: FetchJson = httpFetchJson(import.meta.env.VITE_API_BASE ?? '')
  if (import.meta.env.VITE_MOCK) {
    const { mockFetchJson } = await import('./mock/fixtures.ts')
    fetchJson = mockFetchJson(params.get('scenario') ?? 'default')
    console.info('DeepSports glasses: mock data, scenario', params.get('scenario') ?? 'default')
  }
  // ?preview runs in a plain browser (no Even app bridge); otherwise wait for the bridge.
  const display: Display = params.has('preview') ? createPreviewDisplay() : withMirror(await createEvenDisplay())
  await runApp(display, fetchJson)
  console.info('DeepSports glasses: ready')
}

main().catch((e) => console.error('DeepSports glasses failed to start', e))
