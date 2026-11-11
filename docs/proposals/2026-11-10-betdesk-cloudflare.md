# Proposal: BetDesk, a shared app hosted on Cloudflare (2026-11-10)

Status: **phase 1 decided and built** (2026-11-10). Owner answers to the open questions are at the
end. Built as one Worker with static assets instead of Pages (`BetDesk/docs/DECISIONS.md`); setup in
`BetDesk/docs/SETUP.md`.
Decision log entry: `docs/DECISIONS.md` (2026-11-10). Diagram: `docs/diagrams/betdesk-phase1.svg`.

## Goal
One app that both owners (the owner and Gikaeh) can open from anywhere, not only on the home
Wi-Fi. Today DeepSports' app is served from the owner's Mac at `:8787` and reachable only on the
LAN (DeepSports DECISIONS 2026-11-03). BetDesk lives on Cloudflare's free tier, behind a login,
and grows step by step into the shared betting desk (phase 2) and the merged app for both projects.

## Where it lives
A new top-level project, `BetDesk/`, beside `DeepSports/` and `ManualBets/`. It will use data
from both projects (and tools outside DeepSports), so it is not a DeepSports subfolder. All
TypeScript: no `uv` environment.

```
BetDesk/
  CLAUDE.md          # project rules + finish line (lint, typecheck, tests, wrangler dry-run)
  web/               # Vite + React PWA (starts as a one-time copy of DeepSports/web/src)
  worker/            # Cloudflare Worker: serves /api/* from D1, receives snapshot pushes
  pusher/            # Node script on the owner's Mac: reads DeepSports' API, pushes a bundle
  tools/launchd/     # pusher's launchd agent (the owner installs it)
  docs/              # HANDOFF.md, DECISIONS.md, results/
```

## Phase 1: read-only mirror (this proposal)

**Flow.** `pusher` runs on the Mac, reads the DeepSports read API on `localhost:8787` (the
documented contract in `DeepSports/docs/API.md`), bundles the responses and `POST`s them to the
Worker's `/ingest` endpoint. The Worker stores each response in D1 under its API path and serves
it back at the same `/api/...` path, so the copied web app works with few changes.

**What is mirrored** (same JSON shapes as `DeepSports/docs/API.md`, plus `generated_at`):

| Endpoint | When pushed |
|---|---|
| `/api/scoreboard?league=nba\|ncaab&date=` (yesterday, today, next 2 days) | every 1 min while any game is live, else every 15 min |
| `/api/bets` (labels only, never stakes) | same as scoreboard |
| `/api/games/{id}` for live or just-final games that are followed or have an open bet | every 1 min while live; once when final |
| `/api/predictions/record?league=…` (default model versions) | every 15 min |
| `/api/standings`, `/api/teams/{abbr}` | every 15 min (change once a day in practice) |
| `/api/followed`, `/api/health` | every push |

The app shows "as of HH:MM" from `generated_at` and a stale banner when the newest push is older
than 20 min (Mac asleep, drive unplugged, DeepSports server down). Game pages that weren't pushed
show the scoreboard card only. Live data is about 1 min behind.

**Why push from the Mac instead of the alternatives**
- Cloudflare can't reach DuckDB on the external drive.
- Reading DeepSports' HTTP API, not DuckDB: no writer-lock interaction (the API already answers
  503 `warehouse_busy`; the pusher then keeps the last snapshot), and no import across projects.
- A Cloudflare Tunnel to `:8787` (option 3) needs no new code but exposes the Mac and goes dark
  whenever the Mac is off. The mirror keeps the last good data online.
- Calling ESPN directly from the Worker would mean rewriting DeepSports' Python parsers in
  TypeScript. Not in phase 1.

**Storage: D1, not KV.** KV's free tier allows 1,000 writes/day, which minute-level pushes would
exceed. D1 free: 5 GB, 100k rows written and 5M rows read per day. One row per API path, upserted:
around 30-60 row writes per push, well under the daily limit.

## Login: Cloudflare Access (how "the email thing" works)
Access (part of Cloudflare Zero Trust, free for up to 50 users) sits in front of the whole site,
the app and its `/api`, and lets in only the two allowed email addresses.

- **Not one-time.** Signing in creates a session cookie that lasts as long as we set (15 min to
  1 month). We'd pick 1 month, so each of you signs in about once a month per device or browser.
- **Two login methods**, either or both:
  - *One-time PIN:* type your email, Cloudflare emails a 6-digit code, enter it. Works with any
    email, nothing to set up.
  - *Google login:* one tap if the allowed address is a Google account. Smoother; recommended.
- An app installed to the iPhone home screen keeps its own cookies apart from Safari, so you sign
  in once inside the installed app too. If a session expires while the app is open, the API call
  gets redirected to the login page; the app detects that and reloads into the login.
- Access passes the signed-in email to the Worker (in a signed header). Phase 2 uses that as each
  person's identity: per-person bankrolls with no separate accounts or passwords.
- The Mac's pusher can't do an interactive login. It uses an Access **service token** (client id
  + secret) kept in the Mac's Keychain and read by the launchd script. Never in code or the repo.
- Signing up for Zero Trust may ask for a payment method even on the free plan; check at setup.

## Non-negotiables
- No stakes leave the Mac in phase 1: `/api/bets` is labels only by contract. Real stakes and
  bankrolls go to Cloudflare only in phase 2, after the owners agree (rule 2: bet logs hold real
  stakes).
- No secret values in code, docs or commits: Worker secrets via `wrangler secret`, the
  service token in Keychain, `wrangler login` (OAuth) for deploys. The Odds API key is not used.
- No bet placement or transmission (rule 1). BetDesk shows data and, in phase 2, records bets
  humans already placed.
- `noindex` headers; the site is unreachable without Access anyway.

## Repo changes when phase 1 is built
- New boundary edge, added to root `AGENTS.md`: *BetDesk's pusher reads DeepSports' read API on
  `localhost:8787`* (HTTP only, read-only).
- `AGENTS.md` project table gains `BetDesk/`; `frontend-dev` agent scope covers `BetDesk/web`.
- One-time copy of `DeepSports/web/src` into `BetDesk/web`, recorded in BetDesk's DECISIONS.
- DeepSports architecture diagram gains the pusher as a consumer of the API.

## Phase 2 (later, separate decision): shared bet desk
- "I placed this" logging from the phone: line, odds, stake, book; the owner is the Access email.
- **Bankroll per person** (owner decision 2026-11-10): each person's balance, P&L, ROI by market
  and model, and CLV, computed from their own rows only.
- Auto-grading by a Worker cron (ESPN scoreboard).
- Back to `logs/`: a Mac job pulls new rows and appends them to the CSVs, so the logs stay
  append-only and remain the source of truth ManualBets and DeepSports read.
- Today's picks side by side: ManualBets suggestions, DeepSports models, paper trades, ensemble vote.

## Open questions for the owners (answered 2026-11-10)
1. The two allowed emails, and Google login, one-time PIN, or both.
2. Name: `BetDesk/` (cheap to rename before the first commit).
3. Two copies of the web app: once BetDesk is live, should `DeepSports/web` freeze (LAN + glasses
   only) so new UI work goes to BetDesk? Recommended: yes.
4. Use the free `*.pages.dev` address, or a custom domain (needs a domain on Cloudflare)?

**Answers:** 1. The owner's email only for now (Gikaeh's later); One-time PIN first, Google login
optional later. Emails live only in Access and Worker secrets, not in the repo. 2. `BetDesk`. 3. Yes,
`DeepSports/web` is frozen. 4. Free address (`*.workers.dev`, since it's a Worker).

## Phase 1 "done"
Both owners sign in on their phones away from home; Today, Bets, Game, Standings, Team and Model
record screens load from Cloudflare; data is at most ~1 min behind while games are live; the stale
banner appears when the pusher stops; no stakes in D1; checks pass and a reviewer pass is clean.
