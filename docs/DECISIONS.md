# DECISIONS.md: repo-wide decisions

Decisions that span both projects: repo structure, scope, agents, integration steps.
Project-specific decisions stay in `DeepSports/docs/DECISIONS.md` and
`ManualBets/docs/DECISIONS.md`. Append-only, newest at the bottom; strike through a reversed
decision and point to the reversal.

### 2026-11-10: Agent-driven development with one root context
Development is mostly done by AI agents. The repo root now holds the shared rules
(`AGENTS.md`, with `CLAUDE.md` importing it) and the dev agents (`.claude/agents/`: architect,
data-engineer, data-analyst, frontend-dev, reviewer). Why: the two projects are going to be
merged, and a session started at the root couldn't see `DeepSports/.claude/agents` (nested
skills appear only after the session touches files under `DeepSports/`), while a session
started in a project folder does see root agents and skills (checked 2026-11-10 with Claude
Code 2.1.322). Runtime agents and skills used by DeepSports' headless launchd jobs (bettor,
calendar-agent, `/sync-game-calendar`, `/ensemble-betting`) stay in `DeepSports/.claude/`,
because those jobs run from `DeepSports/` and their skills assume that working directory.
Repo-wide rules (non-negotiables, git, boundary, context hygiene) live only in the root
`AGENTS.md`; project files keep only their own specifics. This reverses ManualBets'
2026-08-21 single-agent decision.

### 2026-11-10: Basketball only
Work focuses on NBA and NCAA men's D1 basketball. `ManualBets/hockey/` and
`ManualBets/baseball/` stay in the tree but get no new work, and NHL/NFL plans were removed
from the roadmaps. Revisit only when the owner asks.

### 2026-11-10: BetDesk, a shared app on Cloudflare (phase 1 = read-only mirror) (mirror replaced by a live tunnel 2026-11-11, below)
**Status:** decided; phase 1 built (not yet deployed). Owner answers: start with the owner's email
only (Gikaeh's later; emails stay out of the repo), name `BetDesk`, `DeepSports/web` frozen, free
`workers.dev` address. Hosting detail and BetDesk-internal choices: `BetDesk/docs/DECISIONS.md`.
Both owners need the app away from the home Wi-Fi, but DeepSports' app is LAN-only (DeepSports
DECISIONS 2026-11-03). A new top-level project `BetDesk/` (not under `DeepSports/`, because it will
use data and tools from both projects) hosts a PWA on a Cloudflare Worker (static assets) + D1, behind
Cloudflare Access for the two owners' emails. Phase 1: a pusher on the Mac reads DeepSports' read
API on `localhost:8787` and pushes snapshots; no stakes leave the Mac. Phase 2 (separate decision):
shared bet logging with a bankroll per person (owner decision), appended back to `logs/`. This adds
one boundary edge (BetDesk pusher → DeepSports read API, HTTP, read-only; edge 3 in `AGENTS.md`).
Details, alternatives and open questions: `docs/proposals/2026-11-10-betdesk-cloudflare.md`.

### 2026-11-10: ManualBets and the Odds API are normal tools, not off limits
Owner instruction, repeated because sessions kept avoiding them: betting analysis and picks use
all of the repo's resources, DeepSports and ManualBets (models, predictions, menus) plus fresh Odds
API lines. The old "only when the task needs fresh odds" wording read as a ban and was replaced
by an explicit section in `AGENTS.md`. Limits that stay: humans place bets, never print the key,
append-only logs, one DuckDB writer.

### 2026-11-11: Edge 4, DeepSports' ensemble reads a ManualBets export
Owner instruction: the ensemble-betting agents must use all of the repo's tools, not only DeepSports.
`ManualBets/tools/export_predictions.py` (ManualBets' own env, no logging, stakes as bankroll fractions,
key never printed) writes a JSON of its NBA + college model numbers, Kelly picks and best Odds API
prices; DeepSports reads only that file (`analysis/manualbets_context.py`), no imports either way.
DeepSports' `tools/ensemble-daily.sh` launches the export as a subprocess before building the context.
nba.com blocks the Mac's NordVPN, so the NBA half runs on a Raspberry Pi on the LAN (ssh `rpi`,
everything inside `~/SportsRLAgent` there). Detail: `DeepSports/docs/DECISIONS.md` 2026-11-11.

### 2026-11-11: Edge 2 widened, ManualBets' NBA side reads closing lines from the warehouse
ManualBets keeps no long NBA odds history, so a backtest of its NBA totals model needs DeepSports'
closing totals and prices (`odds_snapshots`, `source='closing'`, ~100% of games since 2021-22).
Edge 2 (until now `college_basketball/` only) now also covers `ManualBets/tools/total_walkforward.py`:
read-only DuckDB open, path from `NBA_WAREHOUSE_DB` (pointed at a scratch copy for long runs, so
the scheduled writers are never blocked), no imports across the boundary. The NBA menu and its
live recommendations don't read the warehouse. Result and method:
`ManualBets/docs/results/2026-11-11-nba-totals-walkforward.md`.

### 2026-11-11: BetDesk reads DeepSports live through a Cloudflare Tunnel (edge 3 changed)
Owner decision, replacing the pusher + D1 mirror of 2026-11-10 (phase 1 otherwise unchanged): the
Mac mini runs 24/7 and the owner's domain is on Cloudflare, so the BetDesk Worker forwards allowed
GETs to DeepSports' API through a Cloudflare Tunnel (`cloudflared` on the Mac). The tunnel hostname
accepts only the Worker's Access service token; people log in at the Worker as before. Edge 3 is now
"BetDesk Worker → DeepSports read API over the tunnel" (still HTTP, read-only, allowlisted; no stakes).
Details and trade-offs: `BetDesk/docs/DECISIONS.md` 2026-11-11.

### 2026-11-13: To The Moon (betting) is built in DeepSports; new edge 5 (moon ledger under `logs/moon/`)
Owner decisions on `docs/TO_THE_MOON_BETTING.md`:
1. **Lives in DeepSports** as a terminal app (`deepsports.moon`, no new dependencies); a BetDesk tab can
   come later on the same code.
2. **Ledger:** a new append-only CSV `logs/moon/bets.csv`, apart from the normal bet logs. DeepSports
   writes it (only appends, rule 3) — that is **edge 5**. Stakes in it never leave the Mac; the read API
   and BetDesk don't serve it.
3. **DeepStocks stays separate:** the engine pattern is re-written here, nothing is imported from or
   shared with `~/Projects/DeepStocks` (owner: "always its own separate thing").
4. **Books: Circa** (owner may add William Hill/Caesars). Neither is in The Odds API feed (checked
   2026-11-13: 16 US/US2 books, no `circasports`, no `williamhill_us`; 437 credits left). Proposals show
   the best price across the books in the feed as a reference; the owner checks Circa (or sends a
   same-day screenshot) and the ledger records the price actually taken. Bet types: spreads, totals,
   moneylines and ordinary parlays; no props, futures or same-game parlays.
5. **Budget** $50 / $75 / $100 a month (default $75); targets $1k, $2.5k, $10k over 12 months.
Default assumption EV = −vig per bet (no model beats the close); edge only from a graded record.

### 2026-11-13: To The Moon is played one month at a time; default play is one 2-leg ticket
The owner rejected the 12-month framing ("not a long term investment, calculated risks knowing what we
are risking") and "save, then bold", then delegated the choice. Decided with a `data-analyst` check:
1. **One month at a time.** Each month's deposit ($50-100, the owner picks it monthly) is that month's
   whole risk. A winning ticket's payout is set aside, never re-staked (otherwise it drifts into "let it
   ride").
2. **Default play: the month's deposit on one 2-leg parlay** of the model-picks' top legs (tier 11
   `ticket2`, the new `propose` default): about +264, hits ~25% at -vig, EV -8.9%. A 3-leg ticket
   (`ticket3`, ~12.5%, EV -13%) is the opt-in "moon month". Bold play on singles to the same multiple
   has the same odds within noise (25.1% to 3.64x) but needs about two chained bets and twice the money
   in play, so it isn't the default.
3. **Hand-placed daily picks stay in the ledger as tier `manual`.** They count against the month's
   deposit. `status` shows the manual share per month and flags stakes above the month's deposit.
   `propose` counts only the plan tier's own bets toward its one-a-month limit.
4. The tool gained `--months` (1 = this month only) on `tiers`/`sim`/`propose`, a `P(up)` column (ahead
   of keeping the cash), and the payout at the stake in each proposal. Numbers:
   `DeepSports/docs/results/2026-11-13-moon-one-month.md`.
Legs are assumed independent: avoid correlated legs, and check Circa's real parlay price.

### 2026-11-14: Circa screenshots: new edge 6 (BetDesk → DeepSports, one write route); daily moon message
Owner request (2026-11-13): upload Circa screenshots in the web app, have them read on a schedule before the
picks, get the 2 PM bets by message, and be reminded at 11 AM and 1 PM if nothing was uploaded that day.
1. **Edge 6:** the BetDesk Worker allows exactly one write, `POST /api/circa/screenshots`, forwarded to
   DeepSports' API through the tunnel (Access JWT checked, multipart images only, size and count capped).
   Data only flows in (the owner's own odds-board screenshots); no stakes leave the Mac. Every other
   non-GET is still refused. BetDesk isn't deployed yet, so an iCloud Drive inbox folder is the interim
   upload path.
2. **Reading:** in the 14:00 job, before `model-picks run`, `deepsports circa read` asks headless Claude
   (Sonnet, Read only) to transcribe the board into JSON, validates it, matches lines to games, and writes
   `circa/lines/<date>.json` on the external drive. The moon proposal uses Circa's line and price and drops
   a leg when Circa's line or price is worse. A Claude call is fine here: it's a transcription step, and the
   betting rule stays deterministic code.
3. **Messages** via the existing Discord notifier: the 14:00 run sends the moon proposal after the picks;
   a new launchd agent `com.deepsports.circa-remind` (11:00, 13:00) asks for screenshots only when none
   arrived that day.
4. **Budget:** 2026-11 is a $50 month (ledger row 8 tops up the $27). The play mixes small singles with a
   parlay (tier `mix`; numbers in `DeepSports/docs/results/2026-11-14-moon-mix-tier.md`).
5. **Tier 12 `mix` is the default play** (data-analyst, then adjusted by the orchestrator). Each day can bet up
   to 2 singles at 6% of the month's deposit plus one 2-leg parlay at 4% ($3 + $3 + $2 at $50). The day's
   allowance is an even share of what's left of the month's deposit over the days left, and a day bets as
   much of that card as its share covers. The deposit is a hard cap: every stake counts against it, manual
   ones included, and winnings never refill it. Sim at $50 for one month: 41% chance to end ahead, 6% to lose
   more than half, mean end $47. Proposals are repriced at Circa's screenshot lines: a worse line or price
   drops the leg (compared with the slate's own price).
6. **The 14:00 moon message carries stake figures** (balance, what's left of the month, each bet's stake) to the
   owner's own Discord webhook, the same notifier the Stop hook uses. It's the owner's private channel, and
   the owner asked for the bets by message, so this is allowed. The read API, BetDesk and the Circa endpoints
   still never serve stakes, and the message never includes past rows from `logs/`.
7. **Temporary upload page on home Wi-Fi** (owner, 2026-11-14): `GET /circa` on DeepSports' server is one
   standalone page; the frozen `DeepSports/web` app is untouched. Uploads from the LAN need the header
   `X-Circa-Upload-Code`, checked against a code kept only on the Mac (`~/.config/deepsports/circa-upload-code`,
   mode 600, `deepsports circa code [--rotate]`). Ten bad codes in ten minutes return 429. The BetDesk path stays
   loopback-only. Once BetDesk is deployed this page can go.
