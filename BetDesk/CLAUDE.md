# BetDesk

Repo-wide rules (non-negotiables, git, boundary, context hygiene) are in `../AGENTS.md`. This file
adds only what is specific to BetDesk.

BetDesk is the shared app for both owners, hosted on Cloudflare's free tier behind Cloudflare
Access. Phase 1 is a read-only live view of DeepSports' read API, proxied from the owner's Mac
through a Cloudflare Tunnel; phase 2 (not decided yet) adds
shared bet logging with a bankroll per person. Proposal: `../docs/proposals/2026-11-10-betdesk-cloudflare.md`.

## Read first
1. `docs/HANDOFF.md`: current state and next steps.
2. `docs/SETUP.md` before touching Cloudflare, Access, the tunnel or secrets.

## Layout
- `web/`: Vite + React PWA, copied from `DeepSports/web` on 2026-11-10. New UI work happens here;
  `DeepSports/web` is frozen (LAN + glasses only).
- `worker/`: Cloudflare Worker. Serves static assets from `web/dist`; checks the Access JWT itself
  (fails closed) and forwards allowed `GET /api/*` to the tunnel hostname with an Access service token
  (`src/origin.ts`). On the Mac, `cloudflared` (a launchd daemon, set up in SETUP.md) forwards the
  tunnel to `localhost:8787`. No code of BetDesk's runs on the Mac.

## Rules
- **Boundary:** BetDesk reads DeepSports only over HTTP (the contract in
  `../DeepSports/docs/API.md`). No DuckDB access, no imports from other projects.
- **What leaves the Mac:** only the endpoints in the Worker's allowlist (`worker/src/origin.ts`).
  The tunnel hostname stays service-token-only; people log in at the Worker, never at the tunnel.
  No stakes, bankroll or bet amounts until phase 2 is decided in `../docs/DECISIONS.md`.
- **Secrets:** Worker secrets via `wrangler secret put`; the tunnel token lives only in the
  cloudflared daemon. Owner emails, the team domain and the tunnel hostname stay out of the repo too.
- **API changes:** when DeepSports adds an endpoint the app uses, add it to the Worker allowlist.
- **Free tier:** 100,000 Worker requests/day; keep app polling sensible.
- Dependencies: `npm install --before=<a date ≥ 2 weeks ago>`, versions pinned in `package.json`.
- Deploying (`npm run deploy`) publishes to the owners' live site: only when the owner asks.

## Finish line
```bash
npm run check     # typecheck (web, worker) + vitest (worker) + web build + wrangler deploy --dry-run
```
End-to-end locally (DeepSports' API on :8787): `cp worker/.dev.vars.example worker/.dev.vars`,
`npm run dev` (Worker on :8788), then `curl -s 127.0.0.1:8788/api/standings`.
