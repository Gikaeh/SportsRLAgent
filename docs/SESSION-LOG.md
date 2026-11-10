# SESSION-LOG.md — current state (exactly ONE live entry)

When a session ends, move the old entry verbatim into `docs/SESSION-LOG-ARCHIVE.md`
(append-only, newest on top) and write a fresh self-contained entry here.

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
