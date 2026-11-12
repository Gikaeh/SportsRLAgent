# BetDesk handoff

## State (2026-11-11)
Switched from the snapshot mirror to a live proxy through a Cloudflare Tunnel (decision in
`DECISIONS.md`, 2026-11-11). Built and tested locally, **not deployed yet**.
- The pusher, D1 and `/ingest` are gone. The Worker checks the Access JWT, allows GETs on an
  endpoint allowlist only, and forwards them to the tunnel with an Access service token.
- Local end-to-end run: `wrangler dev` with `ORIGIN_URL=http://127.0.0.1:8787` served health,
  scoreboard, standings and bets from the live DeepSports API (standings byte-identical);
  `/api/glance` → 404, POST → 405.
- `npm run check` passes (32 worker tests, web build, deploy dry run).

## Next
1. **Owner:** `docs/SETUP.md` (deploy, Access on the Worker, tunnel on the Mac, Access on the
   tunnel hostname, Worker secrets).
2. Check on a phone away from home: login, Today, Bets, Game, Standings, Team, Model record; the
   "Mac offline" banner when the tunnel is stopped (`sudo launchctl stop` the cloudflared daemon).
3. Not yet verified against real Cloudflare: the Worker → tunnel service-token flow, Access's JWT
   on the Worker, and the expired-session reload in the installed iPhone app.
4. Later: add Gikaeh's email (SETUP.md, last section). Phase 2 proposal (bet logging, bankroll per
   person) needs its own decision; writes would now go straight to the Mac.

## Known limits
- The app works only while the Mac, DeepSports' server and `cloudflared` are up (the Mac mini runs
  24/7). There is no cached copy when it's offline.
- While a DeepSports writer job runs, its scoreboards carry no predictions (same as the LAN app).
- Free plan: 100,000 Worker requests per day. Live polling from two phones stays far below that.
