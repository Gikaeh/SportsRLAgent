# Handoff: state of DeepSports (updated 2026-11-10)

Read this first in a new session, then the open items in docs/ROADMAP.md. Rules: CLAUDE.md;
other docs on demand via the index in README.md.

## What's running on its own
| Thing | How | Check |
|---|---|---|
| App server: API + web app + glasses plugin on `:8787` | launchd `com.deepsports.serve` (restarts itself) | `curl -s localhost:8787/api/health` · logs `~/Library/Logs/DeepSports/serve.log` |
| Scheduled sync at 08:00 and 14:00: update NBA + college → predict v1.0 + v1.1 + v1.1i → headless Claude `/sync-game-calendar` → Discord | launchd `com.deepsports.sync` → `tools/scheduled-sync.sh` | `~/Library/Logs/DeepSports/sync.log` |
| Daily ensemble-betting vote (watch-only): 10 Sonnet bettors on games tipping in the next 24 h → majority picks to Discord | end of the 14:00 sync → `tools/ensemble-daily.sh` | runs in `/Volumes/ExFATStorag/DeepSports/reports/ensemble-bets/` · `deepsports ensemble-bets grade` |
| Pre-tip injury refresh at :20 and :50: NBA games tipping in 5-100 min → fresh ESPN injury report → v1.1i predictions (installed 2026-11-10) | launchd `com.deepsports.pretip` → `tools/pretip.sh` | `~/Library/Logs/DeepSports/pretip.log` (one line per run) · `deepsports status` (`pretip v1.1i` runs) |
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
  next 14 days (NBA v1.0 + v1.1, + v1.1i for games with an injury report; college `ncaab-v1`, `ncaab-v1p`, opt-in `ncaab-v1-early`).
- **Followed:** NBA LAL, LAC, GS, BOS; college Nevada (NEV). See `config/calendar.toml`.
- **Code:** the `DeepSports/` folder of `Gikaeh/SportsRLAgent`; feature branch + PR to `main` (git rules in `../AGENTS.md`).

## Results
In short: the displayed win probabilities are calibrated, but no model or rule so far beats the closing
line (no betting edge). Details: the done summary in docs/ROADMAP.md and the dated
reports in `docs/results/`. Model v1.1i (pre-tip injury reports) has no backtest (snapshots start
2026-11-03) and is graded live, paired with v1.1 on the same games.

## Known gaps / gotchas
- ESPN gaps (warnings in `deepsports check`): 8 NBA playoff summaries 404; 29 NBA team-games and ~430 college
  team-games (mostly 2023-24 player boxes, plus 7 listed D1-vs-non-D1 boxes >2 pts off; ids in
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
