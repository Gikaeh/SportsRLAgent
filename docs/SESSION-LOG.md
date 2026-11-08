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
- Found NBA rank-feature look-ahead: `basketball/NOTES.md` A6. Not fixed.
- Compared with DeepSports: `DeepSports/docs/results/2026-11-07-srla-comparison.md`.

**Verify**
- `.venv/bin/python -m pytest tests/ -q`: the 2 known `test_opp_avg_win_pct.py` failures, the rest pass.
- This is a Mac now: use `.venv/bin/python`. The `.venv\Scripts` commands above don't apply here.

**Next**
1. OWNER: remove the NBA rank features before retraining (A6). Saved NBA spread and total models fail
   with `feature_names mismatch`, so the live NBA recommender probably fails too.
2. OWNER: decide whether college bets should be logged.
3. Grade the Nov 8-10 forward freeze:
   `/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/forward_freeze.csv`.
4. Previous items still open: NBA Batch 4 hardening (NOTES); hockey's random splits.
