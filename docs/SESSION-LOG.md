# SESSION-LOG.md — current state (exactly ONE live entry)

When a session ends, move the old entry verbatim into `docs/SESSION-LOG-ARCHIVE.md`
(append-only, newest on top) and write a fresh self-contained entry here.

---

## 2026-11-08 — College basketball model added; rank-feature leak found

**Done** (branch `feature/srla-college`, uncommitted; branched from `fix/deepsports-ensemble-launchd`)
- New `college_basketball/`: warehouse loader, features, models, Odds API lines, recommender, menu.
  `tools/college_walkforward.py`; `tests/test_college_basketball.py`; duckdb dependency.
- Saved models: `models/college_basketball_*_model.json`, trained on 17,144 games through 2026-11-07.
- Results and the 5-game gate: `docs/DECISIONS.md`. It trails DeepSports and the closing line.
- $50 bankroll from 2026-11-08 (NBA start date; old logs untouched) and Kelly sizing on college via
  `shared/bankroll.py`. Simulated, it fell to about $9 a season: see `docs/DECISIONS.md`.
- Found and fixed NBA rank-feature look-ahead (`basketball/NOTES.md` A6) on `fix/nba-rank-leak`; all three NBA
  models retrained on 27 seasons, and saved spread and total models match live features again.
- Compared with DeepSports: `DeepSports/docs/results/2026-11-07-srla-comparison.md`.

**Verify**
- `.venv/bin/python -m pytest tests/ -q`: the 2 known `test_opp_avg_win_pct.py` failures, the rest pass.
- This is a Mac now: use `.venv/bin/python`. The `.venv\Scripts` commands above don't apply here.

**Next**
1. OWNER: review and merge `feature/live-game-screen` (local, not pushed).
2. Grade the 4 open Nov 9 bets by hand from final scores: `logs/basketball/betting/spread_bets.csv` and `total_bets.csv`,
   `logs/college_basketball/betting/bets.csv`. Why by hand, and why the NBA menu reads a lower balance: `docs/DECISIONS.md`.
3. Grade the Nov 8-10 forward freeze:
   `/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/forward_freeze.csv`.
4. Previous items still open: NBA Batch 4 hardening (NOTES); hockey's random splits.
5. OWNER: the launchd sync failed on 2026-11-08 14:00 with `Operation not permitted` opening the warehouse on the
   external drive (`~/Library/Logs/DeepSports/sync.log`). Check macOS file access for it. Run by hand from a shell at
   20:50 PT (update and predict only), it worked; the paper log and calendar steps were not run.
6. NBA menu: `getUpcomingGames` only keeps today's local date, so at night it can't reach tomorrow's slate. "3. All" is
   listed but only choice 4 runs it. `stats.nba.com` timed out on two refresh attempts on 2026-11-08 at about 21:00 PT.
7. DeepSports live game screen (plays, possession, 10s refresh) is on `feature/live-game-screen` and served on :8787.
   Check it during a real live game: possession has only run on finished games, mocks and a replay. Known gap: a brief
   ESPN failure on `/api/games/{id}` returns 404, with no stale fallback.
