# SESSION-LOG.md — current state (exactly ONE live entry)

When a session ends, move the old entry verbatim into `docs/SESSION-LOG-ARCHIVE.md`
(append-only, newest on top) and write a fresh self-contained entry here.

---

## 2026-08-25 — data/ untracked; uv env; NBA full refetch + clean-splits retrain DONE

**Done**
- Repo hygiene: `/data/` added to `.gitignore`; all 593 tracked data files
  untracked via `git rm -r --cached data/` (working-tree copies intact). History
  still ~558 MB of data blobs — rewrite (filter-repo) optional, owner call.
  Deleted `models/hockey_*.json` (pre-remediation semantics; see Next #3).
- Env: switched from venv to **uv** (`uv venv` + `uv pip install -r
  requirements.txt`; interpreter `.venv\Scripts\python.exe`; AGENTS.md table
  updated). requirements.txt += **pytz** — imported by all three odd_scraping.py
  but never declared; smoke tests caught it.
- Bugfixes surfaced by the refetch+retrain (both would bite any fresh clone now
  that data/ ships untracked):
  1. `retrainModel()` early-exit returned a bare dict while both main.py menus
     unpack `(bool, dict)` → TypeError masked the real failure. Fixed in BOTH
     sports' `model_retrainer.py`: returns `(False, {'reason': ...})`.
  2. `NBATrainingDataPreparer.prepareAllSeasons()` never created
     `phase1/separated_seasons/` — historically worked only because the tracked
     repo shipped the dir. Now mkdir'd. Hockey's preparer already did this.
  3. `basketball/main.py` retraining loop globbed ALL `models/*.json`, loading
     hockey models as Basketball models and overwriting them with NBA-trained
     weights on save. Now `basketball_*.json`.
- OWNER TASK COMPLETE: full refetch of all 26 NBA seasons (game/team/player) +
  phase1 training rebuild + retrain. h2h v4 & spread v4: 30,502 games, strict
  chronological splits (train ≤2021-11-03 < val ≤2024-02-03 < test →2026-06-13).
  Clean metrics landed as predicted (lower than leak-inflated logs): h2h
  val_acc 0.643 / test_acc 0.659 / test_AUC 0.724; spread val_MAE 10.73 /
  test_MAE 11.49. Spread `residual_std` now measured 13.70 (was 11.8 fallback).
  NOTE: no basketball total model file existed before this session either
  (total disabled in menu) — still absent.
- (same day, follow-up) models/metadata restructured per sport:
  `models/metadata/basketball/` + `models/metadata/hockey/` (3 JSONs moved via
  git mv; hockey retrainer already pointed at hockey/ subfolder). Updated
  basketball main.py metadata_path, basketball ModelRetrainer default (+ parent
  mkdir parity with hockey), BettingRecommender.loadResidualSigma default dir,
  NOTES.md + DECISIONS.md path references. .gitignore now `/data/**` +
  negations keeping `data/*/odds_data/**` tracked (360 files, 4.2 MB — staged;
  rationale in DECISIONS.md). Historical odds backfill feasibility researched —
  The Odds API has snapshot archive back to 2020 (Business tier $99/mo includes
  it at zero extra credits; lower tiers ~10x credit cost); free closing-line
  datasets exist but lack timestamps → leakage-unsafe for point-in-time
  features (rule #4).
- pytest: 11 passed.

**Next**
1. OWNER: review + commit working tree (staged deletions: data/ files + hockey
   models; modified: .gitignore, requirements.txt, AGENTS.md,
   basketball/main.py, 2× model_retrainer.py, prepare_data.py, this log).
2. Batch 4 hardening per NOTES §Suggested fix order (A5 drop-list single source
   of truth, A4 remainder, C-R3 ladder collapse + availability gating, C3/C4
   features) using analyzeFeatureImportance on the new clean splits.
3. Hockey has NO models on disk until rebuilt; hockey mirror debt (A/B-class
   issues + old random-split initial_*_setup.py flows) still unscoped — do NOT
   run hockey initial setups as-is, they bypass the chronological-split fixes.
4. Vectorized rolling/cache wiring (NOTES §Salvaged #3) still deferred — safe to
   start now that the retrain is done.

**Blocked-open**
- Odds API key rotation (key public in git history); M1 secrets cleanup queued.
- Injury system revisit timing (module ready, unwired).
- Stale branch deletion (no_injuries/fullstack-app safe; others after salvage check).
