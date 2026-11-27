# Handoff: state of DeepSports (updated 2026-11-13)

Read this first in a new session, then the open items in docs/ROADMAP.md. Rules: CLAUDE.md;
other docs on demand via the index in README.md.

## What's running on its own
| Thing | How | Check |
|---|---|---|
| App server: API + web app + glasses plugin on `:8787` | launchd `com.deepsports.serve` (restarts itself) | `curl -s localhost:8787/api/health` · logs `~/Library/Logs/DeepSports/serve.log` |
| Scheduled sync at 08:00 and 14:00: update NBA + college → opening lines for new finals (`odds-history --with-opening --days 4`) → predict v1.0 + v1.1 + v1.1i → paper log (no Claude call; the calendar sync was scrapped for now on 2026-11-13) | launchd `com.deepsports.sync` → `tools/scheduled-sync.sh` | `~/Library/Logs/DeepSports/sync.log` |
| Daily models-only picks (watch-only, since 2026-11-13): `books grab` (Circa + William Hill lines from OddsPapi, since 2026-11-14), `circa read` (headless Claude transcribes today's Circa and, since 2026-11-16, William Hill screenshots; screenshot lines win over the feed), then DeepSports' model and ManualBets' model vs the best of DraftKings', Circa's and WH's lines (rule `mp-v1.1`) for games tipping before the next run → top 5 (each with Circa's and WH's line and price) + strong/lean tables to Discord, then a second message with the To The Moon proposal (tier `mix`, Circa prices). Replaced the ensemble-agent vote, which stays runnable by hand (`tools/ensemble-daily.sh`) | weekdays after the 14:00 sync, Saturday and Sunday after the 08:00 sync (each run covers the games until the next one) → `tools/model-picks-daily.sh` | runs in `/Volumes/ExFATStorag/DeepSports/reports/model-picks/` · `deepsports model-picks grade` · `deepsports circa status` · `deepsports books status` |
| Evening night-before lines at 21:00 (watch-only opening-totals forward test, added 2026-11-14): `books grab --early` writes tomorrow's William Hill (Caesars) lines to `books/williamhill/early/<date>.json`, then `circa read --early --book williamhill` (the owner's WH opening screenshots, uploaded by 21:00 on the `/circa` page, "Tomorrow (opening)"), then `early-totals log` (pre-registered `et-v1`, amended 2026-11-16: WH screenshot lines first, Caesars feed for gaps; verdict at 300 bets), then Circa's opening read (recorded only) | launchd `com.deepsports.books-evening` → `tools/books-evening.sh` | `~/Library/Logs/DeepSports/books.log` · `deepsports books status --early` · `deepsports early-totals status\|grade` |
| Pre-tip injury refresh at :20 and :50: NBA games tipping in 5-100 min → fresh ESPN injury report → v1.1i predictions (installed 2026-11-10) | launchd `com.deepsports.pretip` → `tools/pretip.sh` | `~/Library/Logs/DeepSports/pretip.log` (one line per run) · `deepsports status` (`pretip v1.1i` runs) |
| The Odds API live capture (built and installed 2026-11-23; momentum night 1 = 2026-11-23): college + NBA totals/spreads, 10 books, 09:00 + every 30 min 12:00-21:30, ~84 credits/day, stops after 2026-12-24 or under 2,000 credits; at 18:30/19:00/19:30 it also runs `momentum-freeze` (momentum forward-test inputs, `reports/momentum-forward/frozen/`) | launchd `com.deepsports.oddsapi-live` → `tools/oddsapi-live.sh` | `~/Library/Logs/DeepSports/oddsapi-live.log` · `data/raw/oddsapi/live/ledger.jsonl` |
| Discord turn notifications | global Stop/Notification hooks → `~/.claude/tools/notify.py` | |

Restart the server after code changes: `launchctl kickstart -k gui/$(id -u)/com.deepsports.serve`.
Rebuild clients: `(cd web && npm run build)`, `(cd glasses && npm run build)`; Even Hub package: `npm run pack:lan`.

## Where things are
- **Owner's SSH into this Mac:** `ssh jaeminbbq@172.16.0.61`. Copy files off with scp, e.g. the glasses package:
  `scp jaeminbbq@172.16.0.61:/Users/jaeminbbq/Projects/SportsRLAgent/DeepSports/glasses/deepsports-glasses.ehpk .`
- **Data:** `data/` → `/Volumes/ExFATStorag/DeepSports/data` (DuckDB + raw ESPN cache). Backup before the
  league migration: `/Volumes/ExFATStorag/DeepSports/backups/`. Reports: `/Volumes/ExFATStorag/DeepSports/reports/`.
- **Warehouse:** NBA 2021-22 → today (7,267 games, closing lines ~100%); college (men's D1) 2021-22 → today
  (19,899 games in 2023-24 → 2025-26, plus 2021-22 and 2022-23 loaded 2026-11-19, below; ~92% of all final games have a closing line, D1-vs-D1 ~100%, but per field D1-vs-D1 is
  spread 99-100%, total ~100%, moneyline 96-98%: ESPN/DraftKings shows the moneyline as "OFF", mostly on
  20+ point spreads; see DATA_SOURCES.md); pre-tip injury snapshots from 2026-11-03 on; predictions for the
  next 14 days (NBA v1.0 + v1.1, + v1.1i for games with an injury report; college `ncaab-v1`, `ncaab-v1p`, opt-in `ncaab-v1-early`, hidden altitude shadow `ncaab-v1.1alt`).
- **Followed:** NBA LAL, LAC, GS, BOS; college Nevada (NEV). See `config/calendar.toml`.
- **Code:** the `DeepSports/` folder of `Gikaeh/SportsRLAgent`; feature branch + PR to `main` (git rules in `../AGENTS.md`).

## Results
In short: the displayed win probabilities are calibrated, but no model or rule so far beats the closing
line (no betting edge). Details: the done summary in docs/ROADMAP.md and the dated
reports in `docs/results/`. Model v1.1i (pre-tip injury reports) has no backtest (snapshots start
2026-11-03) and is graded live, paired with v1.1 on the same games. Player impact ratings / injury impact in
points (2026-11-11) were dropped: no edge, ratings not face-valid; the code stays as research tooling.

## Parlay tracker (2026-11-23)
**Glasses (2026-11-27, v0.3.0):** the G2 plugin now shows the same Bets + Parlays lists (tap switches, swipe pages); the old
followed-team scoreboard is gone (glasses/README.md). Repacked `glasses/deepsports-glasses.ehpk`; the owner uploads it to Even Hub.
The local app's Bets screen has **Games | Parlays** tabs (`#/bets?tab=parlays`): every parlay logged in the moon
ledger (`deepsports moon log parlay`), ungraded or graded but placed today (PT; settled ones drop off the next day), with each leg's time, matchup, bet, live
score and ✓/✗/●/○. API `GET /api/parlays` (docs/API.md). The owner uses this local app only (BetDesk is unused);
BetDesk got the same tab, undeployed.

## To The Moon (betting)
**Since 2026-11-23 moon is the nightly lotto card** (root `docs/DECISIONS.md` 2026-11-23): the 21:00 job turns tomorrow's
et-v1 legs into a $1 top-7 test ticket + 18 x $0.25 7-leg spread tickets (rule `lotto-v2`, pre-registered) → Discord + `reports/moon/lotto/cards.jsonl`; `deepsports moon lotto grade`.
The 14:00 `mix` proposal message is retired; the text below describes it (still runnable by hand).
`deepsports moon` (guide `docs/TO_THE_MOON.md`; why: root `docs/DECISIONS.md` 2026-11-13/14): proposals from the
model-picks run, repriced at Circa's lines: OddsPapi's Circa feed (`deepsports books grab`, since 2026-11-14) plus the
owner's screenshots (the `/circa` page on home Wi-Fi or the iCloud inbox; docs/PIPELINE.md, Circa), screenshots winning, sent to Discord with the picks (weekdays 14:00, weekends 08:00); the owner places every bet and logs it in the
append-only `../logs/moon/bets.csv`.
Plan: $50 for 2026-11 (rows 8-9: $77 deposited, $27 of manual picks before; units size from the $50), tier `mix`.
Next: `deepsports moon grade` + `status` after the 08:00 sync. Owner: check the first real Circa read
(`circa status`, the lines file; the test reply fixture is synthetic); if `circa ingest` says `inbox blocked`,
give uv's Python Full Disk Access; deploying BetDesk is still the owner's (`../BetDesk/docs/SETUP.md`).

## Next session (state at 2026-11-23, after et-v2 phase 2)
**et-v2 work is in progress.** et-v1 is unchanged and frozen: live 40-32-1 at the last grade, verdict at 300 bets.
- **Research 2026-11-22.** Results are in `docs/results/2026-11-22-*`:
  - edge size barely predicts which pick wins;
  - no situational factor explains wins, but altitude held;
  - college injuries add nothing;
  - live CLV from bet time is about 0.
- **Merged** (PRs #40-#44): the venue table, the watch-only altitude shadow `ncaab-v1.1alt` / `et-v1-alt` (first logs from the 21:00 run on 11-23), the et-v2 pre-registration (`docs/results/2026-11-23-et-v2-preregistration.md`, commit 3970720) and the market context log.
- **Odds API historical pull is done.** The owner's own key is at `~/.config/deepsports/oddsapi.key`. It holds 2,916 college snapshots, 2021-22 to 2025-26, at -1@15:00, -1@18:00, -1@21:00 and 0@09:00 PT, from 10 books, totals and spreads. They live in `data/raw/oddsapi/historical/` on the external drive, which is the only copy (the owner is OK with that).
- **Phase 1, the lines-only sanity report, is done** (`docs/results/2026-11-23-et-v2-sanity.md`, branch `research/et-v2-sanity`; check its PR):
  - Event match rate 99.35%. Line agreement is fine (WH vs DraftKings at T: mean absolute 0.23).
  - By the 60% rule, 2021-22 is dropped and 2022-23 to 2025-26 are graded at `williamhill_us`.
  - That rule is **provisional**: it was measured on all D1 games. The pre-registration says games with both model numbers, so recompute it on that subset before scoring.
- **Phase 2 is scored: none of the 9 pass, so there is no et-v2** (`docs/results/2026-11-23-et-v2-results.md`, branch `research/et-v2-scoring`, Amendment 1 `0458f6b` written before outcomes).
  - C0 (et-v1's cell at the 21:00 WH line) is -3.9% ROI on 3,470 bets and loses in 3 of 4 seasons. et-v1 continues unchanged.
  - Exploratory only: unders drain every rule; the market-momentum rules C4/K2 are the only positive ones. Either needs a new pre-registration plus forward data.
- **Lotto + betting-type investigation (2026-11-23):** `docs/results/2026-11-23-lotto-investigation.md`, `-overs-vs-unders.md`.
  No parlay or side edge survives a check on new seasons; spreads and moneylines dropped. Lotto card = `lotto-v2`
  (pre-registered sweep test, verdict at 150 qualifying nights).
- **NBA night-before pull (owner OK 2026-11-23):** pre-registered `nt-v1` (`docs/results/2026-11-23-nba-totals-preregistration.md`,
  commits f8ce5bc + 6bda7aa on branch `research/nba-totals-preregistration`) before the pull; totals only, 10 books,
  -1@21:00 / 0@09:00 / 0@15:00, 2023-24 to 2025-26 (~19K credits; log `work/nba-totals-prereg-2026-11-23/pull.log`).
  Scored 2026-11-23: **FAIL** (pooled -3.45%, 0 of 3 seasons positive; `docs/results/2026-11-23-nba-totals-nt-v1-results.md`); NBA night-before totals dropped, no 2026-27 pull needed.
- **Odds API credits:** 22,580 left after the NBA pull, usable until about 2026-12-23; the live capture needs ~2.6K.
- **To do:**
  - Grade the Nov 23 bets after the 2026-11-24 08:00 sync (games tip tonight) in `logs/college_basketball/betting/bets.csv`: 13 WH and 2 Circa, plus a $0.25 13-leg parlay and a $3 2-leg Circa parlay.

## Known gaps / gotchas
- ESPN gaps (warnings in `deepsports check`): 8 NBA playoff summaries 404; 29 NBA team-games and ~430 college
  team-games (mostly 2023-24 player boxes, plus 11 listed team-games >2 pts off; ids in
  `quality.KNOWN_POINTS_MISMATCH` and DATA_SOURCES.md) where points don't add up (upstream). `check` exits 0;
  any new mismatch still fails.
- College prior model (2026-11-06): `ncaab-v1p` (>= 5 games, graded beside `ncaab-v1`, not displayed) and
  `ncaab-v1-early` (opt-in) share one fit. Early predictions made before 2026-11-06 09:00 UTC came from the
  no-prior v1 model; split the early record there.
- Historical ESPN injury lists are fetch-time, so they **leak**. Only pre-tip snapshots are valid model inputs.
- The API returns 503 `warehouse_busy` while a job holds the writer lock; live scores keep working.
- launchd processes needed the macOS "Removable Volumes" permission (granted 2026-11-03). Only uv's Python has it:
  launchd scripts must use `uv run python`, not shell tools or system `python3`, for files on the drive.
- The packaged glasses build has `http://172.16.0.61:8787` built in; repack if the Mac's IP changes.
- `collab/` (DeepSeek's notes on the friend's SportsRLAgent) is local and git-ignored; our summary is
  `docs/research/sportsrlagent-review.md`. The friend granted permission to use their data/methods.

## Next steps
1. Waiting on data: `ncaab-v1p` vs `ncaab-v1` record (a few hundred gated games; early-gate re-test after
   2027-01-31); injury-impact model once pre-tip snapshots accumulate; paper-trade review at season end.
   Altitude shadow (2026-11-22, branch `feature/ncaab-alt-shadow`): hidden `ncaab-v1.1alt` (sync predict step) +
   `et-v1-alt` logged by the 21:00 run to `reports/early-totals/alt/`; `early-totals grade --alt`; verdict after 2027-03-14.
   Bet market context (2026-11-23, branch `feature/et-context-log`): `early-totals context --log` at the end of the 21:00 run → `reports/early-totals/context.jsonl`; run `early-totals context --backfill` once after merge (Nov 17+ bets); `early-totals context` prints the describe-only split.
2. Opening-line timing: 30-min pregame captures (since 2026-11-06) will give real posting times; re-test opening
   totals forward once a few hundred bets exist.
3. v1.1i vs v1.1 paired review once a few hundred NBA games with a pre-tip report are graded.
4. Step-by-step integration with ManualBets (one data source, one app); each step is decided in
   `../docs/DECISIONS.md` first.
5. Owner: DHCP reservation for 172.16.0.61; glasses background-update test; paid odds API decision.
6. Carried over from 2026-11-09: confirm the Bets tab shows on the owner's phone; watch the live screen during a
   real game (a brief ESPN failure on `/api/games/{id}` returns 404 with no stale fallback); grade the Nov 8-10
   forward freeze (`/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/forward_freeze.csv`);
   `%-` strftime codes fail on Windows (matters for a Windows collaborator).
7. ~~`exclude-newer` vs `uv.lock` mismatch~~: settled 2026-11-16 (`exclude-newer` = 2026-11-10, the lock's date).
8. Player impact: better ratings (box-score prior or stint-level RAPM) gated on a face-validity check; only then a
   possible `v1.2i` shadow with snapshot OUT lists (ROADMAP, Features and ratings).
