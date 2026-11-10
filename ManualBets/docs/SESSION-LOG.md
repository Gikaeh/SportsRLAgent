# SESSION-LOG.md — current state (exactly ONE live entry)

When a session ends, move the old entry verbatim into `docs/SESSION-LOG-ARCHIVE.md`
(append-only, newest on top) and write a fresh self-contained entry here.

---

## 2026-11-10 — NBA/NHL menus reach the next slate (tomorrow's games at night)

**Done**
- `shared/base_data_fetcher.py`: new `nextSlate(games, now)`. It looks at games dated today and tomorrow by the
  schedule's own US Eastern date, keeps those whose UTC tip time is still ahead, and returns only the earliest such
  date. `getUpcomingGames(now=None)` in basketball and hockey use it.
- Cause: basketball compared the Mac's local (Pacific) date with `gameDateEst` and never looked at tip times, so at
  10 PM PT it kept only today's finished games. Hockey asked the NHL API for the local date and used only
  `gameWeek[0]`; it also indexed `gameWeek` before its empty-response check (fixed).
- `upcoming_games.csv` keeps the same columns and date format (the tip-time column is dropped before saving).
- One date, not two: see `docs/DECISIONS.md` 2026-11-10.

**Verify**
- `.venv/bin/python -m pytest tests/ -q` (macOS): 45 passed, 2 failed. The 2 are the known
  `test_opp_avg_win_pct` failures (this Mac has no `data/basketball/team_data/2024-25_team_stats.csv`).
- New `tests/test_upcoming_slate.py` (8 tests, no network): noon, 6 PM, 8 PM and 10 PM PT.
- Not checked live: `stats.nba.com` and `cdn.nba.com` refuse this Mac (timeout / 403). Field names
  (`gameDateEst`, `gameDateTimeUTC`) are confirmed against the installed `nba_api`. A game with an empty
  `gameDateTimeUTC` (time TBD) is dropped.

**Next**
1. OWNER: run the NBA menu once late in the evening on Windows and confirm it lists tomorrow's games.
2. Hockey odds: `hockey/data_pipeline/odd_scraping.py:82-84` still overwrites the "not started yet" filter
   (the bug basketball fixed as NOTES B1).
3. Previous items still open: DeepSports `%-` strftime on Windows, grade open bets, retrain NBA models, Batch 4.

---

## 2026-11-08 — Odds scraping works again on pandas 3.1 (arrow 'str' dtype)

**Problem**
- `basketball/main.py` → Betting Recommendations crashed in
  `basketball/data_pipeline/odd_scraping.py:68`:
  `TypeError: Invalid value '2026-11-08 12:40:00-08:00' for dtype 'str'`
  (`df.iat[i,0] = pst_datetime`).
- Cause: pandas 3.1 gives `pd.json_normalize` text columns the pyarrow-backed
  `str` dtype, which rejects assigning a `datetime` object one cell at a time.
  This is not an Odds API problem; the same loop existed in all three sports.

**Done**
- `toPacificTime(series, timezone)` (module-level helper in all three
  `odd_scraping.py` files) converts the whole ISO-8601 UTC column at once:
  `pd.to_datetime(series, utc=True, format='ISO8601').dt.tz_convert(tz)`.
  Result is a real tz-aware `datetime64[us, America/Los_Angeles]` column, which
  is what `upcomingGamesWindow` and the `sort_values` calls actually need. CSV
  output is byte-identical to before (`2026-11-08 12:40:00-08:00`), so existing
  `h2h_*.csv` / `spread_*.csv` / `total_*.csv` files stay compatible.
- `mapTeamCodes(series, team_mapping)` replaced the per-row
  `df.at[i, 'home_team'] = ...` team-code loops (unknown names pass through,
  same as the old `if name in mapping` guard).
- The three duplicated row loops per file (h2h / spread / total) are gone:
  `basketball/data_pipeline/odd_scraping.py`, `hockey/data_pipeline/odd_scraping.py`,
  `baseball/odd_scraping.py`.
- No threshold, model, or bet-log changes. Hockey's `commence_time` filter bug
  (NOTES B1: second assignment discards the `> now` filter) and baseball's
  identical filter are untouched — this session only fixed the dtype crash.

**Verify**
- `.venv\Scripts\python.exe -m pytest tests/ -v`: 18 passed, 2 FAILED. The 2
  failures are the known PRE-EXISTING `tests/test_opp_avg_win_pct.py` ones
  (missing `data/basketball/team_data/2024-25_team_stats.csv`; the test also
  calls `calculateOpponentStrengthL10`, which has never existed).
- New `tests/test_odd_scraping_datetime.py`: stubs `requests.get` with a
  two-event payload (one upcoming, one already started), runs
  `BasketballOddScraping.getH2hOdds()` for real, and asserts one game survives
  the window, team codes map (BOS/LAL), and both datetime columns are tz-aware
  `datetime64`; plus a source guard that none of the three scrapers assign
  datetimes cell by cell.

**Next**
1. OWNER: rerun `basketball/main.py` → Betting Recommendations; the odds call
   should now print counts and reach the predictions step.
2. OWNER: retrain all three NBA models (`basketball/main.py` → Model
   Retraining) so saved models match the clean-split semantics (still open from
   2026-11-07).
3. Batch 4 hardening (NOTES §Suggested fix order) remains — A3 (validation
   double-dip), A5 (single source of truth for drop lists), C-R3, C3/C4.
4. Odds API key is still hardcoded in the three `odd_scraping.py` files
   (non-negotiable #2) — env-var extraction + owner key rotation still pending.

---

## 2026-11-09 — TOR -2.5 logged; open-bet labels and a Bets tab in the app

**Done** (PRs #8 to #11)
- Logged the owner's MEM @ TOR bet: TOR -2.5 at -110, $5, placed 4:40 PM PST after the 10-agent ensemble run (6/10 took
  TOR -2.5). Appended to `logs/basketball/betting/spread_bets.csv` as `401909955`, open. Balance $86.36 with $21 open.
- DeepSports API: `api/bets.py` reads open (no result) rows from the bet logs; cards and game detail get `bets: string[]`
  labels ("TOR -2.5", "Over 216.5"). New `GET /api/bets` lists every game with an open bet, live first, finals kept until graded.
- DeepSports web: bet chip on game cards and the game header, plus a fourth **Bets** tab with live scores that refresh.
  Why labels only, never the stake: `docs/DECISIONS.md`.
- The `com.deepsports.serve` launchd service runs the working tree, so it needs `launchctl kickstart -k gui/$(id -u)/com.deepsports.serve`
  after a backend change, and `npm run build` in `DeepSports/web` after a web change.

**Verify**
- `cd DeepSports && uv run pytest -q`: 422 passed. ruff, `npm run typecheck` and `npm run build` clean.
- The Bets tab was checked in headless Chrome on the mock build only, and `/api/bets` against the live server. The owner
  said the chip did not show on their phone before the tab shipped; not confirmed fixed (stale app copy or another URL?).
- Root `.venv/bin/python -m pytest tests/ -q` not run this session (only a CSV row and docs changed there).

**Next**
1. Grade the 5 open Nov 9 bets by hand from final scores: Hawks +2 ($3), TOR -2.5 ($5), DEN @ HOU Over 216.5 ($5),
   NO @ GS Over 231.5 ($5), Illinois St @ Purdue Over 145 ($3). Rows are in `logs/basketball/betting/spread_bets.csv` and
   `total_bets.csv`, and `logs/college_basketball/betting/bets.csv`. Grading a row removes it from the Bets tab.
2. OWNER: confirm the Bets tab shows on the phone. If not, say which URL or home-screen icon it opens.
3. Watch the live screen during a real game: possession has only run on finished games, mocks and a replay. Known gap:
   a brief ESPN failure on `/api/games/{id}` returns 404, with no stale fallback.
4. OWNER: the launchd sync failed on 2026-11-08 14:00 with `Operation not permitted` opening the warehouse on the
   external drive (`~/Library/Logs/DeepSports/sync.log`). Check macOS file access for it.
5. NBA menu: `getUpcomingGames` only keeps today's local date, so at night it can't reach tomorrow's slate.
6. Grade the Nov 8-10 forward freeze:
   `/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/forward_freeze.csv`.
7. Previous items still open: NBA Batch 4 hardening (NOTES); hockey's random splits.
