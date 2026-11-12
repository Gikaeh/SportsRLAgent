# BetDesk decisions

Append-only, newest at the bottom; strike through a reversal and point to it. Repo-wide decisions
(the project's existence, boundary edges) are in `../../docs/DECISIONS.md`.

### 2026-11-10: One Worker with static assets instead of Pages + Functions
The proposal named Pages. A single Worker serving `web/dist` as Workers static assets plus
`/api/*` is one deploy, one `workers.dev` hostname and one Access application, on the same free tier.
`run_worker_first` covers only `/api/*` and `/ingest`; the app shell is served without the Worker
(it holds no data).

### ~~2026-11-10: D1 for snapshots, one row per API path~~ (reversed 2026-11-11: live tunnel, below)
KV's free tier allows 1,000 writes/day; minute-level pushes would exceed it. D1 upserts skip
unchanged bodies, and date-scoped rows (old scoreboards and game pages) expire after 10 days.

### 2026-11-10: The Worker verifies the Access JWT itself
Access blocks at the edge, but if the Access app were removed or misconfigured, the Worker must not
serve data. It verifies `Cf-Access-Jwt-Assertion` (RS256, team certs, AUD, issuer, expiry), applies a
required email allowlist secret (`ALLOWED_EMAILS`), and fails closed when any of them is unset.
`DEV_NO_ACCESS` works only on localhost. Service tokens may only push; `/ingest` also needs the
bearer token. The "last synced" time moves only with a push's final chunk, so a half-failed push
shows as stale.

### ~~2026-11-10: The pusher decides its own cadence; launchd runs it every 60 s~~ (reversed 2026-11-11: live tunnel, below)
Live games → push scoreboards, bets and live game pages; otherwise a full push every 15 min;
otherwise exit "idle". It reads DeepSports over HTTP only, so it never touches the DuckDB writer lock,
and a 503 from DeepSports keeps the mirror's last good copy. After a failed push it backs off 5 min.
Chunks are ≤ 35 entries and ≤ 300 KB so each ingest stays well inside the free plan's CPU limit. Polling is clamped to ≥ 30 s in pushed
bodies, since the mirror changes about once a minute.

### 2026-11-10: Web app copied from DeepSports/web, which is now frozen
Owner decision: new UI work happens in `BetDesk/web`; `DeepSports/web` stays as the LAN + glasses
build. The copy was made once (no shared package across the project boundary). BetDesk changes: an
"as of" / stale indicator from `/api/health`, a reload when the Access session expires, a "Not synced
yet" message for pages outside the mirror, and its own name and service-worker cache.

### 2026-11-10: Free `workers.dev` address; One-time PIN login first
Owner decision: no custom domain for now. The owner's email is the only allowed user until Gikaeh's
is added. One-time PIN needs no setup; Google login can be added later (it needs a Google OAuth client).

### 2026-11-11: Live proxy through a Cloudflare Tunnel instead of the snapshot mirror
Owner decision: simpler, and the Mac mini runs 24/7, which removes the mirror's main advantage
(data while the Mac is off). The Worker now forwards allowed GETs to DeepSports' API through a
Cloudflare Tunnel (`cloudflared` on the Mac → `localhost:8787`) on the owner's domain. The pusher, D1
and `/ingest` are removed (in git history). Why a Cloudflare Tunnel, not ngrok: the owner's domain is
on Cloudflare, so the same Access account guards both hops, it's free with no bandwidth cap or
browser interstitial, and the Mac side is one `cloudflared service install`.
Security: the tunnel hostname has its own Access application with a **service-token-only** policy, so
only the Worker can reach the Mac (optionally `cloudflared` checks the Access token too). The Worker
keeps the people check (Access JWT + `ALLOWED_EMAILS`, fails closed), allows GET only on an
endpoint allowlist (`worker/src/origin.ts`), and sends the Mac only `Accept` plus the service token,
never the user's cookies or JWT. The tunnel exposes only port 8787. Trade-offs: no data while the
Mac is offline (the app shows "Mac offline"); data is live instead of ~1 min behind; phase 2 writes
can go straight to the Mac.
