# BetDesk web

Mobile-first PWA for both owners, served by the BetDesk Worker on Cloudflare. Copied from
`DeepSports/web` on 2026-11-10 (that copy is now frozen); it reads the same API contract
(`../../DeepSports/docs/API.md`), served from snapshots by `../worker`. Vite + React + TypeScript,
no UI framework, one plain stylesheet, hash routing.

BetDesk additions: the "Synced HH:MM" pill and stale banner (`src/components/MirrorStatus.tsx`, from
`/api/health`), a page reload when the Cloudflare Access session has expired (`src/api/client.ts`), and
the "Not synced yet" state for `404 not_mirrored`.

## Commands (from `BetDesk/`)
```bash
npm run dev -w web        # Vite on :5173, proxies /api to the local Worker on :8788 (`npm run dev`)
npm run dev:mock -w web   # fixtures from src/mocks/, no backend (switches: see DeepSports/web/README.md)
npm run build -w web      # typecheck + build -> web/dist (the Worker's static assets)
npm run check             # everything BetDesk checks, incl. this build
```
