# Handoff: state of DeepSports (updated 2026-11-06)

Read this first in a new session, then CLAUDE.md → AGENTS.md → docs/ROADMAP.md.

## What's running on its own
| Thing | How | Check |
|---|---|---|
| App server: API + web app + glasses plugin on `:8787` | launchd `com.deepsports.serve` (restarts itself) | `curl -s localhost:8787/api/health` · logs `~/Library/Logs/DeepSports/serve.log` |
| Scheduled sync at 08:00 and 14:00: update NBA + college → predict v1.0 + v1.1 → headless Claude `/sync-game-calendar` → Discord | launchd `com.deepsports.sync` → `tools/scheduled-sync.sh` | `~/Library/Logs/DeepSports/sync.log` |
| Daily ensemble-betting vote (watch-only): 10 Sonnet bettors on games tipping in the next 24 h → majority picks to Discord | end of the 14:00 sync → `tools/ensemble-daily.sh` | runs in `/Volumes/ExFATStorag/DeepSports/reports/ensemble-bets/` · `deepsports ensemble-bets grade` |
| Discord turn notifications | global Stop/Notification hooks → `~/.claude/tools/notify.py` | |

Restart the server after code changes: `launchctl kickstart -k gui/$(id -u)/com.deepsports.serve`.
Rebuild clients: `(cd web && npm run build)`, `(cd glasses && npm run build)`; Even Hub package: `npm run pack:lan`.

## Where things are
- **Owner's SSH into this Mac:** `ssh jaeminbbq@172.16.0.61`. Copy files off with scp, e.g. the glasses package:
  `scp jaeminbbq@172.16.0.61:/Users/jaeminbbq/Projects/SportsRLAgent/DeepSports/glasses/deepsports-glasses.ehpk .`
- **Data:** `data/` → `/Volumes/ExFATStorag/DeepSports/data` (DuckDB + raw ESPN cache). Backup before the
  league migration: `/Volumes/ExFATStorag/DeepSports/backups/`. Reports: `/Volumes/ExFATStorag/DeepSports/reports/`.
- **Warehouse:** NBA 2021-22 → today (7,267 games, closing lines ~100%); college (men's D1) 2023-24 → today
  (19,899 games; ~92% of all final games have a closing line, D1-vs-D1 ~100%, but per field D1-vs-D1 is
  spread 99-100%, total ~100%, moneyline 96-98%: ESPN/DraftKings shows the moneyline as "OFF", mostly on
  20+ point spreads; see DATA_SOURCES.md); pre-tip injury snapshots from 2026-11-03 on; predictions for the
  next 14 days (NBA v1.0 + v1.1; college `ncaab-v1`, `ncaab-v1p`, opt-in `ncaab-v1-early`).
- **Followed:** NBA LAL, LAC, GS, BOS; college Nevada (NEV). See `config/calendar.toml`.
- **Code on GitHub:** private `JaeminBBQ/DeepSports`. Commit or push only when asked.

## Results so far (docs/results/)
- Analysis: home court 54–58% / +2 pts; the closing-line favorite wins ~68%; spread MAE ~10.7.
- Model v1.0: beats Elo and home-always, **not** the closing line (Brier 0.211 vs 0.199; margin MAE 11.2 vs 10.8).
- Model v1.1 (+ player availability): margin MAE 11.22→11.20 (real), Brier within noise. The apps show v1.1.
- $100 simulation of v1 (`docs/results/2026-11-04-sim-v1-100usd.md`, chart `docs/diagrams/sim-v1-bankroll.svg`):
  closing line → $0 on spreads/totals/moneyline (the −110 cut eats ~$0.09 per $2 bet); opening-line totals
  → $172 (53.4%, CI overlaps break-even; openings have no posting time, so treat it as a best case).
  The model is overconfident on its moneyline picks, so Kelly isn't justified.
- Calibration (`docs/results/2026-11-06-calibration.md`): displayed NBA v1.1 and college ncaab-v1 win % are
  calibrated (app says ~75% → won ~73%). The pick overconfidence is the winner's curse, not fixable by rescaling.
  `v1.1c` / `ncaab-v1c` built but **not wired** (gains are noise-sized); display unchanged.
- Spread/total prices backfilled from cache (`deepsports prices-backfill`; closing ~100%). $100 sim re-run at real
  prices (`docs/results/2026-11-06-sim-v1.1-prices.md`): closing → still $0 everywhere; opening totals $172 → $111
  (v1.0) / $137 (v1.1), 53.7% vs 53.2% break-even, CI includes it. The model's opening picks sit on the pricier side.

## Known gaps / gotchas
- ESPN gaps (warnings in `deepsports check`): 8 NBA playoff summaries 404; 29 NBA team-games and ~430 college
  team-games (mostly 2023-24 player boxes, plus 7 listed D1-vs-non-D1 boxes >2 pts off; ids in
  `quality.KNOWN_POINTS_MISMATCH` and DATA_SOURCES.md) where points don't add up (upstream). `check` exits 0;
  any new mismatch still fails.
- College prior model (2026-11-06): `ncaab-v1p` (>= 5 games, graded beside `ncaab-v1`, not displayed) and
  `ncaab-v1-early` (opt-in) share one fit. Early predictions made before 2026-11-06 09:00 UTC came from the
  no-prior v1 model; split the early record there.
- Historical ESPN injury lists are fetch-time, so they **leak**. Only pre-tip snapshots are valid model inputs.
- One DuckDB writer at a time. The API returns 503 `warehouse_busy` during jobs; live scores keep working.
- launchd processes needed the macOS "Removable Volumes" permission (granted 2026-11-03).
- The packaged glasses build has `http://172.16.0.61:8787` built in; repack if the Mac's IP changes.
- `collab/` (DeepSeek's notes on the friend's SportsRLAgent) is local and git-ignored; our summary is
  `docs/research/sportsrlagent-review.md`. The friend granted permission to use their data/methods.

## Next steps
1. **NHL** (season under way; keyless `api-web.nhle.com`): capture OT/SO/period/empty-net at ingest.
2. Waiting on data: `ncaab-v1p` vs `ncaab-v1` record (a few hundred gated games; early-gate re-test after
   2027-01-31); injury-impact model once pre-tip snapshots accumulate; paper-trade review at season end.
3. Opening-line timing: 30-min pregame captures (since 2026-11-06) will give real posting times; re-test opening
   totals forward once a few hundred bets exist.
4. Owner: DHCP reservation for 172.16.0.61; glasses background-update test; paid odds API decision.
