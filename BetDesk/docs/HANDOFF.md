# BetDesk handoff

## State (2026-11-13): Circa screenshot upload (edge 6, root `docs/DECISIONS.md` 2026-11-14)
Built against mocks and unit tests, **not deployed, not run end to end yet** (DeepSports' endpoints
weren't on :8787 when this was built).
- Worker: allowlist adds `GET /api/circa/screenshots/today`; the one write route is
  `POST /api/circa/screenshots` (Access JWT required, `multipart/form-data` only (415), body capped at
  35 MB (413) whatever Content-Length says, foreign `Origin` refused (403)). The body goes to the Mac
  unchanged with the service token only. Every other non-GET is still 405.
- Web: new **Circa** tab (`#/circa`): "Add screenshots" (opens Photos on iPhone), previews with
  per-file checks (image type, 10 MB), upload progress, then today's status (count, last added,
  read time and lines matched, or "not read yet; read at 2 PM").

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
0. **Circa:** local GET end-to-end done 2026-11-14 (`/today` 200, JSON POST 415, DELETE 405). Before the
   first tunnel upload, restart `com.deepsports.serve` so it runs with `proxy_headers=False` (otherwise
   cloudflared's `X-Forwarded-For` hides the loopback client and uploads get 403). Still to do: the local end-to-end
   (`npm run dev`, then `curl -s 127.0.0.1:8788/api/circa/screenshots/today` and a tiny PNG
   `curl -F file=@x.png 127.0.0.1:8788/api/circa/screenshots`). After the owner deploys: upload a real
   screenshot from the iPhone (check HEIC vs JPEG arrives) and see the count change.
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
