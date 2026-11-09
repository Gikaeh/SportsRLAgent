# SESSION-LOG.md — current state (exactly ONE live entry)

When a session ends, move the old entry verbatim into `docs/SESSION-LOG-ARCHIVE.md`
(append-only, newest on top) and write a fresh self-contained entry here.

---

## 2026-11-09 — Live game screen, owner bets logged, one bankroll

**Done** (branch `feature/live-game-screen`, pushed; PR #6 open and mergeable)
- DeepSports game screen: play-by-play, possession, last-shot court, score animations, about 10s refresh for live games.
  iOS tab bar fix, confirmed by the owner on an iPhone.
- Owner's real bets logged, plus a new `logs/college_basketball/betting/bets.csv`. Balance $86.36 with $16 open.
- NBA bankroll now includes college results. Why, and the logging limits: `docs/DECISIONS.md`.
- Warehouse refreshed by hand on 2026-11-08 at about 20:50 PT (update and predict only).

**Verify**
- `.venv/bin/python -m pytest tests/ -q`: the 2 known `test_opp_avg_win_pct.py` failures, the rest pass.
- `cd DeepSports && uv run pytest -q`: all pass.
- This is a Mac now: use `.venv/bin/python`. The `.venv\Scripts` commands in AGENTS.md don't apply here.

**Next**
1. Grade the 4 open Nov 9 bets by hand from final scores: Hawks +2 ($3), DEN @ HOU Over 216.5 ($5), NO @ GS Over 231.5
   ($5), Illinois St @ Purdue Over 145 ($3). They're in `logs/basketball/betting/spread_bets.csv` and `total_bets.csv`,
   and `logs/college_basketball/betting/bets.csv`.
2. OWNER: review and merge PR #6.
3. Watch the live screen during a real game: possession has only run on finished games, mocks and a replay. Known gap:
   a brief ESPN failure on `/api/games/{id}` returns 404, with no stale fallback.
4. OWNER: the launchd sync failed on 2026-11-08 14:00 with `Operation not permitted` opening the warehouse on the
   external drive (`~/Library/Logs/DeepSports/sync.log`). Check macOS file access for it. The 08:00 run may fail too.
5. NBA menu: `getUpcomingGames` only keeps today's local date, so at night it can't reach tomorrow's slate. "3. All" is
   listed but only choice 4 runs it. `stats.nba.com` timed out and `cdn.nba.com` returned 403 on 2026-11-08 at night.
6. Grade the Nov 8-10 forward freeze:
   `/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/forward_freeze.csv`.
7. Previous items still open: NBA Batch 4 hardening (NOTES); hockey's random splits.
