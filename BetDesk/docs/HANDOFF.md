# BetDesk handoff

## State (2026-11-10)
Phase 1 (read-only mirror) is built and tested locally, **not deployed yet**.
- Local end-to-end run: the pusher read the live DeepSports API and pushed 74 snapshots (26 game
  pages, ~1.4 MB) in 7 requests to `wrangler dev`; mirrored standings were byte-identical to
  DeepSports'. The second run correctly stayed idle (no live games, full push not due).
- `npm run check` passes (43 tests incl. the Worker's access rules, deploy dry run). A reviewer
  pass found no critical/high issues; its medium/low findings were fixed the same day.

## Next
1. **Owner:** `docs/SETUP.md` (Cloudflare account, deploy, Access with the owner's email, secrets,
   Keychain, `tools/launchd/install.sh`).
2. Check on a phone away from home: login, Today, Bets, Game, Standings, Team, Model record; the
   stale banner when the pusher is stopped.
3. Not yet verified against real Cloudflare: Access's JWT and service-token flow, and the
   expired-session reload in the installed iPhone app, and ingest CPU time on the free plan (check
   Workers observability on the first real full push; lower `CHUNK_CHARS` if near 10 ms). Watch the first live-game night in
   `~/Library/Logs/BetDesk/pusher.log`.
4. Later: add Gikaeh's email (SETUP.md, last section). Phase 2 proposal (bet logging, bankroll
   per person) needs its own decision.

## Known limits
- Game pages exist for yesterday through tomorrow only: every NBA game, plus college games that are
  followed or carry a bet. Other pages say "Not synced yet".
- While a DeepSports writer job runs, its scoreboards carry no predictions; the pusher mirrors that
  (same as the LAN app).
- Data is about a minute behind during live games, and goes stale while the Mac is asleep.
