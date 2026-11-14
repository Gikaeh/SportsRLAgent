# BetDesk handoff

## State (2026-11-14): deployed and live
- Live on workers.dev behind Worker-level Access (Workers & Pages → betdesk → **Access** tab, policy
  "Cloudflare account"); the Worker re-checks the JWT and `ALLOWED_EMAILS`. All 6 secrets set.
- Tunnel `deepsports-mac` (cloudflared 2026.11.0, launchd daemon) → `localhost:8787`; its hostname has
  a Service Auth-only Access app (`betdesk-worker` token). It replaced a dead 2025 tunnel service on
  the Mac ("Tunnel not found"). `com.deepsports.serve` restarted with `proxy_headers=False`.
- Verified from outside: no login → 302 to Access; tunnel hostname without or with a fake token →
  403; LAN upload without code → 403. Phone sign-in loads live data through the tunnel.
- Setup gotcha: a wrong `ACCESS_TEAM_DOMAIN` gives every signed-in request 403. `wrangler tail` now
  shows `access_refused <reason>` (one word, never values) for each refused request.

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
1. **Owner:** Add to Home Screen; tap through Today, Bets, Game, Standings, Team, Model record; the
   "Mac offline" banner when the tunnel is stopped (`sudo launchctl stop com.cloudflare.cloudflared`).
2. **Circa:** one real upload from the iPhone (check HEIC vs JPEG arrives) and see the count change.
3. After a month: the expired-session reload in the installed iPhone app.
4. Service token: renew before it expires (if it was given a year), then update `ORIGIN_CLIENT_*`.
5. Later: add Gikaeh (SETUP.md, last section). Phase 2 proposal (bet logging, bankroll per person)
   needs its own decision; writes would now go straight to the Mac.

## Known limits
- The app works only while the Mac, DeepSports' server and `cloudflared` are up (the Mac mini runs
  24/7). There is no cached copy when it's offline.
- While a DeepSports writer job runs, its scoreboards carry no predictions (same as the LAN app).
- Free plan: 100,000 Worker requests per day. Live polling from two phones stays far below that.
