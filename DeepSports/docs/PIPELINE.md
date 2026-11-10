# Pipeline runbook

## Commands
| Command | What it does | Network |
|---|---|---|
| `deepsports update [--back 3 --ahead 14] [--no-injuries]` | Routine refresh: recent results, upcoming games + odds, pre-tip injury snapshots for games in the next 2 days, missing box scores | ~20 scoreboards + 1 summary per game in the next 48 h (NBA ~15-30) + new box scores |
| `deepsports backfill --season 2025-26` | Every day Oct 1 → Jun 30 (capped at yesterday), then all box scores | ~30 min once, cached after |
| `deepsports schedule --start 2026-11-01 --end 2026-11-07 [--refresh]` | Scoreboards for a range | 1 request/day |
| `deepsports boxscores [--limit N]` | Box scores for final games that lack them | 1 request/game |
| `deepsports odds-history [--with-opening] [--limit N]` | Historical lines from the ESPN core API for final games missing a closing line (or an opening line, with `--with-opening`) | 1 request/game, cached |
| `deepsports odds-snapshot [--league nba\|ncaab\|all] [--days 2]` | Light pregame line capture (launchd every 30 min): fresh scoreboards for today + tomorrow (US/Eastern), both leagues by default, and **only** `pregame` odds rows (no games, box scores, summaries or injuries). A new row only when a line or price moved. Fetches first, then holds the writer lock only for the short write; if another writer holds the lock (before fetching, or for 10 s at write time) it prints one `skipped, warehouse busy` line and exits 0. Logs a run in `ingest_runs` (`odds-snapshot nba,ncaab`) | 4 scoreboards (~5 s) |
| `deepsports pretip [--window-min 100] [--min-lead 5]` | Light pre-tip job (launchd at :20 and :50): NBA games tipping between now + `min-lead` and now + `window-min` minutes get one fresh ESPN summary each (their injury report, saved under `summary_pregame/<id>/<UTC time>`), then, in one short writer session, the pre-tip snapshots go into `injury_captures`/`injury_reports` and model **v1.1i** predictions are written for exactly those freshly captured games (a team without a report keeps the box-score rule). A game whose fresh summary shows it already started (status not `pre`) or moved before the fetch gets no snapshot and no prediction (`skipped_started`). Selects games with a brief read-only open, fetches with no lock held, writes with a 10 s lock wait. A held lock (before or at write time) prints one `skipped, warehouse busy` line and exits 0; no games in the window prints one line and exits 0 without fetching; any other open error prints `FAILED, cannot open the warehouse` and exits 1. Prints and logs (`ingest_runs`, command `pretip v1.1i`) `games= captured= predicted= fallback_teams= skipped_started=` | 1 summary per game in the window (usually 0-4) + one model fit (~2 s) |
| `deepsports upcoming [--league nba\|ncaab\|all] [--days N] [--teams GS,LAL] [--all] [--json]` | Upcoming games (per-league follow lists from `config/calendar.toml`). JSON rows carry `league`, `neutral_site`, and `calendar_key` = `deepsports:<league>:<game_id>` | none |
| `deepsports injuries-backfill` | Offline: re-parse injury snapshots from cached summaries under `data/raw/espn/<league>/` (`summary/` as post-game, `summary_pregame/` as pre-tip) | none |
| `deepsports prices-backfill [--league nba\|ncaab\|all] [--dry-run]` | Offline (no network): fill NULL spread/total prices on existing `opening`/`closing` odds rows (both leagues by default) by re-parsing the cached response each row was built from: opening rows and closing rows stamped with the tip time from `core_odds/`, other closing rows from the summary `pickcenter` in `summary/`. A row is filled only when the cached provider, spread, total and moneylines equal the stored ones (otherwise counted as `mismatch` and left alone); `captured_at`, lines and any existing price are never changed and no row is inserted. Reads with a read-only connection, parses without the lock, then takes the writer lock (waits up to 120 s) only for one short `UPDATE`. Idempotent; `--dry-run` prints the counts and writes nothing. Prints per-league status counts (`fill`, `no_prices`, `mismatch`, `missing`, `no_cache`) and logs a run in `ingest_runs` | none (~3.5 min for both leagues on the external drive; reads ~45k cached files) |
| `deepsports predict [--league nba\|ncaab] [--model-version v1.0] [--days 14]` | Train the league's model on all completed games, predict every not-yet-started game in the next N days, upsert into `predictions` (one row per game/model/version, the latest pre-tip one; games whose tip time has passed are skipped), log the run in `ingest_runs`. NBA: model v1 (`v1.0` default, `v1.1`, `v1.1i` = v1.1 + pre-tip injury reports, only for games with a captured report, the rest counted as `skipped_no_injury_capture`). College: `--league ncaab` (version `ncaab-v1`, the default; frozen `models/ncaab_v1/config.json`), only D1-vs-D1 games where **both teams have >= 5 completed games this season**. `ncaab-v1p` is the cross-season prior model (frozen `models/ncaab_prior/config.json`) on the same >= 5 gate, graded beside `ncaab-v1` but never displayed; `ncaab-v1-early` uses the prior model for D1 games where each team has >= 1 game (opt-in in the web app; never on the calendar, since `upcoming` ignores `*-early` and `ncaab-v1p`). `--model-version` takes a comma list (`ncaab-v1p,ncaab-v1-early` fits the prior model once) or `all` for college; one output line and `ingest_runs` row per version, the rest counted as `skipped_few_games` / `skipped_non_d1` | none (NBA ~2 s, college ~15-30 s per model) |
| `deepsports paper log [--days 1]` | Forward paper-trade log (watch-only, no money): applies the frozen rules in `src/deepsports/analysis/paper.py` to not-started regular-season games on today's US/Eastern game day (`--days N`: N game days) using the stored predictions and the latest `pregame` odds snapshot captured before now, and inserts qualifying bets into `paper_bets` (insert-only: a bet already logged is never changed). Prints new/qualifying/skip counts per rule and logs the run in `ingest_runs` | none |
| `deepsports ensemble-bets context [--agents 5] [--days 3] [--league all\|nba\|ncaab] [--seed 0]` | Read-only: writes a run dir under `/Volumes/ExFATStorag/DeepSports/reports/ensemble-bets/<UTC time>/` with `slate.json` and `context-aNN.md` per agent (games with a pregame line tipping 1 h to N days out). Used by `/ensemble-betting` | none |
| `deepsports ensemble-bets tally <run>` | Files only: validates `picks-aNN.json`, prices every pick from the slate, drops picks on games already tipped, writes `tally.md`/`tally.json` (once per run) | none |
| `tools/ensemble-daily.sh` | Daily watch-only vote (called by the 14:00 sync; `SKIP_ENSEMBLE=1` to skip): `ensemble-bets context --agents $ENSEMBLE_AGENTS (10) --days $ENSEMBLE_DAYS (1)`, copies the contexts to `.sync/ensemble/`, headless `claude -p --model sonnet "/ensemble-betting prefetched …"` (Read/Write/Agent only) launches the bettors and saves replies, then `tally`, `grade` and a Discord post of the majority picks. ~30k Sonnet tokens per bettor (≈300k a day at 10) on the owner's claude.ai plan | none |
| `deepsports ensemble-bets grade` | Read-only: record, units, ROI of every run's majority picks (1 unit each) and of all agent picks | none |
| `deepsports paper report [--json]` | Read-only: per rule logged/graded/pending, record, win%, ROI with a 95% day-clustered bootstrap CI, units, CLV vs the closing line (`paper_results` view, graded with `analysis.betting`) | none |
| `deepsports migrate` | Bring the warehouse schema up to date and print rows before/after per rebuilt table; a no-op when current (docs/DATA_MODEL.md, Migrations) | none |
| `deepsports status` | Row counts + last 5 runs | none |
| `deepsports check` | Data-quality checks; exit 1 on hard failures (box scores, points add up, scores present); warnings for odds coverage per season | none |
| `deepsports serve [--port 8787]` | Read API + web app (docs/API.md) | live ESPN, cached 10s–5min |
| `deepsports teams` | Refresh team list | 1 |

Every collection command (`teams`, `schedule`, `boxscores`, `update`, `backfill`, `odds-history`,
`injuries-backfill`) and `upcoming` take `--league nba|ncaab` (default `nba`; `upcoming` also takes
`all`). Raw files go under `data/raw/espn/<league>/...` (the NBA keeps `espn/nba/...`).
`update --league ncaab` takes injury snapshots only for the followed college teams (`[ncaab] teams`);
with no college follow list it takes none. Add `-v` for per-day logging. Commands that collect data exit 1 if any fetch failed; the
errors are also stored in `ingest_runs.notes`.

## Storage location
`data/` is a **symlink to `/Volumes/ExFATStorag/DeepSports/data`** (external drive, exFAT), so the
raw zone and the warehouse don't fill the Mac's disk. Expected size: about 1 GB for 2021-22 → present
(the drive uses 128 KB blocks, so small raw files take up more space than their size).
- If the drive isn't mounted, every `deepsports` command exits 2 with "Is the external drive
  (ExFATStorag) mounted?". It never creates a stray local `data/`.
- To recreate on a new machine: `mkdir -p /Volumes/<drive>/DeepSports/data && ln -s /Volumes/<drive>/DeepSports/data data`.
  Or set `DEEPSPORTS_DATA_DIR`.
- `.venv` (~95 MB) and `web/node_modules` (~70 MB) stay on the internal disk: they're small,
  can be regenerated, and node_modules relies on symlinks, which exFAT doesn't support well.

## Historical data
Seasons 2021-22 → 2025-26 plus the current season, collected with:
```bash
for s in 2025-26 2024-25 2023-24 2022-23 2021-22; do uv run deepsports backfill --season $s; done
uv run deepsports odds-history --with-opening   # fill closing-line gaps + opening lines
uv run deepsports check
```
We start at 2021-22 on purpose: 2019-20 (bubble) and 2020-21 (mostly empty arenas) distort
home-court effects. Older seasons can be added later with the same command.

## College basketball (NCAA men's D1)
Follow list: `config/calendar.toml`:
```toml
teams = ["LAL", "LAC", "GS", "BOS"]   # top level = NBA (or [nba] teams = [...])

[ncaab]
teams = ["NEV"]                        # empty list = no college games on the calendar
```
Commands (one writer at a time; each is resumable and idempotent, since settled responses are cached):
```bash
uv run deepsports teams --league ncaab                      # 1 request: 362 D1 teams
uv run deepsports backfill --league ncaab --season 2026-27  # this season so far (Nov 1 -> yesterday)
uv run deepsports update --league ncaab                     # daily: 18 scoreboards + new box scores
uv run deepsports backfill --league ncaab --season 2025-26  # history: ~166 scoreboards + ~6,300 summaries (~1.8 h)
uv run deepsports odds-history --league ncaab --with-opening  # ~1 request per final game (~1.8 h/season)
uv run deepsports check
```
Loaded so far: college 2023-24 → today (backfilled 2026-11-04/05: each older season took ~1.8 h; one
`odds-history --league ncaab --with-opening` over both seasons was 12,541 requests, ~3.5 h). Older
college summaries carry no `pickcenter`, so run `odds-history` after backfilling a past season or
it has no lines at all.
Sizes: a D1 season is ~6,000-6,300 games. Raw summaries are ~36 KB gzipped (~250 MB per season on the
external drive); the warehouse grows by ~165k player rows per season. A routine `update --league ncaab`
fetches ~150 box scores on a busy day.

## Schema migrations
The first writer that opens a warehouse created by older code rebuilds the stale tables (all rows
kept, one transaction). To do it deliberately and see the counts:
```bash
uv run deepsports status       # read-only: row counts before
uv run deepsports migrate      # prints "migrated <table> rows N -> N" or "nothing to migrate"
uv run deepsports check        # same results as before
```
Optional dry run on a copy (only while no writer is running; copy the `.wal` too if present):
`mkdir -p /tmp/dsmig && cp data/deepsports.duckdb* /tmp/dsmig/ &&
DEEPSPORTS_DB=/tmp/dsmig/deepsports.duckdb uv run deepsports migrate`.

## Concurrency
- Writers (`update`, `backfill`, `odds-history`, ...) wait up to 15s for the lock, then fail.
- `status`, `check`, `upcoming` open read-only, and `serve` takes short read-only connections per
  request. While a writer runs, the warehouse endpoints return 503 `warehouse_busy`; live endpoints keep working.

## Caching rules
- Every response is saved to `data/raw/...json.gz`.
- A cached **scoreboard** is reused only if every game on it was over (`state = post`) when it
  was saved; otherwise it's refetched. `update` and `odds-snapshot` always refetch their window
  (the fresh response overwrites `scoreboard/YYYYMMDD.json.gz`, so the raw zone keeps only the
  latest scoreboard per day; the line history lives in `odds_snapshots`).
- A cached **summary** is reused only if the game was completed.
- To force a refetch: `--refresh` (schedule), or delete the file under `data/raw/`.
- To rebuild the warehouse from raw: delete `data/deepsports.duckdb` and re-run
  `backfill` / `update`. Settled responses come from the cache, so it's fast and offline.

## Always-on (launchd)
Four per-user LaunchAgents (templates in `tools/launchd/`), installed by the owner with
`tools/launchd/install.sh` and removed with `tools/launchd/install.sh uninstall` (add agent names
to act on only those, e.g. `tools/launchd/install.sh install com.deepsports.odds`):
| Agent | What | When |
|---|---|---|
| `com.deepsports.serve` | `uv run deepsports serve --port 8787` (API + web app + glasses plugin) | At login; restarted if it exits (throttled to 30s) |
| `com.deepsports.sync` | `tools/scheduled-sync.sh`: `deepsports update` (nba, ncaab), `deepsports predict` (NBA v1.0, v1.1 and v1.1i, then `--league ncaab --model-version ncaab-v1` and `ncaab-v1p,ncaab-v1-early` (one prior-model fit); each continues on failure), `deepsports paper log` (non-fatal), exports `upcoming --json` to `.sync/`, then headless `claude -p "/sync-game-calendar prefetched .sync"` with only Read + Google Calendar tools (no `deepsports` commands: they hang in the headless sandbox) ; on the 14:00 run, `tools/ensemble-daily.sh` (ensemble vote below) | 08:00 and 14:00 local |
| `com.deepsports.odds` | `tools/odds-snapshot.sh`: `deepsports odds-snapshot` (pregame lines for today + tomorrow, NBA + college). Yields to every other job: skips (exit 0, one log line) when the drive is missing or another writer holds the warehouse | Every 30 min at :15 and :45 (never together with the 08:00/14:00 sync) |
| `com.deepsports.pretip` | `tools/pretip.sh`: `deepsports pretip` (fresh injury reports + v1.1i predictions for NBA games tipping in the next 5-100 min). Yields like the odds job: skips (exit 0, one log line) when the drive is missing or another writer holds the warehouse. `Nice` 10, `LowPriorityIO` | Every 30 min at :20 and :50 (offset from the odds job and the sync), so each game is refreshed 3 times in its last 100 min, the last one 5-35 min before tip |

- Predictions: `predict` runs in bash before Claude, so the calendar skill only reads them via
  `upcoming --json` (`prediction` per game). Each run refreshes predictions for games that haven't
  started; graded results appear in the `prediction_results` view once games are final.
- Paper trades: `paper log` runs right after the predict steps, so each rule sees fresh
  predictions and the morning/afternoon pregame line. The first log of a bet is frozen; the 14:00
  run only adds games that qualify for the first time. `deepsports paper report` shows the record.
- College predictions are sparse early in the season: none until both teams have 5 completed
  games (about late November). The API shows `prediction: null` for those games unless the opt-in
  `ncaab-v1-early` exists (flagged `early`).
- Logs: `~/Library/Logs/DeepSports/{serve,sync,odds,pretip}.log` (`odds.log`, `pretip.log`: one timestamped line per run).
- Install only the odds snapshot (after checking a manual run: `tools/odds-snapshot.sh`):
  `tools/launchd/install.sh install com.deepsports.odds`; status:
  `launchctl print gui/$(id -u)/com.deepsports.odds`; remove:
  `tools/launchd/install.sh uninstall com.deepsports.odds`. It uses the same "Removable Volumes"
  permission as the sync (same `uv`/`python3.12`).
- Install only the pre-tip job (after checking a manual run: `tools/pretip.sh`):
  `tools/launchd/install.sh install com.deepsports.pretip`; status:
  `launchctl print gui/$(id -u)/com.deepsports.pretip`; remove:
  `tools/launchd/install.sh uninstall com.deepsports.pretip`. Same drive permission as the odds job.
- Model v1.1i on cards: the API prefers v1.1i, then v1.1 (docs/API.md); the calendar export, paper log
  and ensemble vote stay on v1.1. Compare v1.1i with v1.1 paired on the same games (DECISIONS 2026-11-10).
- Status: `launchctl print gui/$(id -u)/com.deepsports.serve`.
- The sync posts its summary to Discord through the global Stop hook, and posts a "blocked" message if the
  drive is missing or Claude fails.
- If the Mac is asleep at a scheduled time, launchd runs the job when it wakes.
- **macOS privacy:** launchd processes need their own "Removable Volumes" permission (System Settings →
  Privacy & Security → Files and Folders → python3.12 / uv / bash). Until it's granted, access to the drive
  *hangs* instead of failing. The server copes (live data is cached internally, warehouse opens time out
  to 503), but the scheduled sync needs the permission. The prompt only appears on the Mac's screen, not over SSH.
  Only uv's Python has it today: under launchd, bash globs, `cp`, `ls` and `/usr/bin/python3` get `Operation not
  permitted` on the drive, so scripts must go through `uv run python` (DECISIONS 2026-11-07).
- Claude agents can't install these themselves: Claude Code's auto mode blocks creating login items. The owner runs the installer.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `Could not set lock on file ...duckdb` | Another deepsports process is running. Wait for it; don't run jobs in parallel |
| `Cannot open file ...duckdb: Operation not permitted` (launchd jobs) | macOS refused drive access. Seen once, 2026-11-08 13:57 until the restart for the macOS 27.2 update; cleared on its own after the restart. The sync preflight retries 3× then alerts on Discord and stops; `odds-snapshot` and `pretip` print `FAILED, cannot open the warehouse` (it used to call this "busy"). If it persists after a restart, check Privacy & Security for uv's Python |
| `pretip.log` says `predicted=0` while `captured>0` | No completed games to train on (see the `error:` part of the line), or every captured game's tip time in `games` had already passed (stale schedule: the next `update` fixes it) |
| `pretip.log` shows `skipped, warehouse busy` at :20/:50 every time | A long writer (backfill, a stuck job) holds the lock. Find it with `ps aux \| grep deepsports`; the 08:00/14:00 sync can overlap one run, which is fine |
| A game has v1.1 on its card but no v1.1i | No pre-tip injury report was captured for either team (ESPN summary had no `injuries`, the fetch failed, or the game tipped before the job ran); the card falls back to v1.1 |
| `HTTP 400` on scoreboard | Bad date param (ranges are not supported) |
| Many 429/503 retries | ESPN throttling: raise `DEEPSPORTS_MIN_INTERVAL` (e.g. 2.0) |
| Parser test failures after a fixture refresh | ESPN changed its JSON shape; update `parse_espn.py` and the field maps |
| Game shows on the calendar but was postponed | It's `status = STATUS_POSTPONED`; the calendar sync removes or moves it on its next run |
