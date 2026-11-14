# BetDesk web

Mobile-first PWA for both owners, served by the BetDesk Worker on Cloudflare. Copied from
`DeepSports/web` on 2026-11-10 (that copy is now frozen); it reads the same API contract
(`../../DeepSports/docs/API.md`), proxied live from the owner's Mac by `../worker`. Vite + React + TypeScript,
no UI framework, one plain stylesheet, hash routing.

BetDesk additions: a "Mac offline" banner and error state when the Worker answers `503 mac_offline`
(`src/components/MacStatus.tsx`, polls `/api/health`), and a page reload when the Cloudflare Access
session has expired (`src/api/client.ts`). The Circa screen (`#/circa`, `src/screens/Circa.tsx`)
uploads Circa odds-board screenshots (`POST /api/circa/screenshots`, XHR for progress, batches under
30 MB) and shows today's read status; mock switches `?mock=circa0|circaread|circafull|uploadfail`
(`src/mocks/circa.ts`).

## Commands (from `BetDesk/`)
```bash
npm run dev -w web        # Vite on :5173, proxies /api to the local Worker on :8788 (`npm run dev`)
npm run dev:mock -w web   # fixtures from src/mocks/, no backend (switches: see DeepSports/web/README.md)
npm run build -w web      # typecheck + build -> web/dist (the Worker's static assets)
npm run check             # everything BetDesk checks, incl. this build
```
