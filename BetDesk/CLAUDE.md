# BetDesk

Repo-wide rules (non-negotiables, git, boundary, context hygiene) are in `../AGENTS.md`. This file
adds only what is specific to BetDesk.

BetDesk is the shared app for both owners, hosted on Cloudflare's free tier behind Cloudflare
Access. Phase 1 is a read-only mirror of DeepSports' read API; phase 2 (not decided yet) adds
shared bet logging with a bankroll per person. Proposal: `../docs/proposals/2026-11-10-betdesk-cloudflare.md`.

## Read first
1. `docs/HANDOFF.md`: current state and next steps.
2. `docs/SETUP.md` before touching Cloudflare, Access, secrets or the launchd job.

## Layout
- `web/`: Vite + React PWA, copied from `DeepSports/web` on 2026-11-10. New UI work happens here;
  `DeepSports/web` is frozen (LAN + glasses only).
- `worker/`: Cloudflare Worker + D1. Serves `/api/*` from snapshots, `POST /ingest` for the pusher,
  static assets from `web/dist`. Checks the Access JWT itself and fails closed.
- `pusher/`: Node script on the owner's Mac (launchd, every 60 s): reads DeepSports' HTTP API on
  `localhost:8787` and pushes snapshots. `tools/pusher.sh` is its launchd entry point.

## Rules
- **Boundary:** the pusher reads DeepSports only over HTTP (the contract in
  `../DeepSports/docs/API.md`). No DuckDB access, no imports from other projects.
- **What leaves the Mac:** only the endpoints in the Worker's allowlist (`worker/src/snapshots.ts`).
  No stakes, bankroll or bet amounts until phase 2 is decided in `../docs/DECISIONS.md`.
- **Secrets:** Worker secrets via `wrangler secret put`; the pusher's from the Keychain (service
  `betdesk`). Owner emails and the team domain stay out of the repo too.
- **API changes:** when DeepSports adds an endpoint the app uses, extend the pusher's plan
  (`pusher/src/plan.ts`) and the Worker allowlist together.
- **Free-tier limits** shape the design: ≤ 40 entries per ingest (D1's 50 queries per call),
  D1 upserts skip unchanged rows, KV isn't used (1,000 writes/day).
- Dependencies: `npm install --before=<a date ≥ 2 weeks ago>`, versions pinned in `package.json`.
- Deploying (`npm run deploy`) publishes to the owners' live site: only when the owner asks.

## Finish line
```bash
npm run check     # typecheck (3 workspaces) + vitest (worker, pusher) + web build + wrangler deploy --dry-run
```
End-to-end locally: `cp worker/.dev.vars.example worker/.dev.vars`, `npm run migrate:local -w worker`,
`npm run dev` (Worker on :8788), then
`BETDESK_URL=http://127.0.0.1:8788 BETDESK_INGEST_TOKEN=dev-token BETDESK_STATE=/tmp/x.json npm run push`.
