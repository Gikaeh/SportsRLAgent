# SESSION-LOG-ARCHIVE.md — append-only, newest on top

Move superseded entries from `docs/SESSION-LOG.md` here verbatim. Never edit or
delete archived entries.

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

## 2026-08-22 — Side-branch salvage extracted; awaiting owner's big refetch + retrain

**Done**
- Branch state: `basketball-remediation` holds all remediation work in 3 commits
  and is PUBLISHED to origin (not merged to main). `main` untouched at f40c7f9.
  Audited ALL branches: `no_injuries` + `fullstack-app` are fully-merged ancestors
  with zero unique code (deletion candidates, owner call); `injury`/`working`/
  `new_player_data` have unique work but predate the leakage fixes — none merged.
- Salvage decision + extraction (`basketball/NOTES.md` §Salvaged components):
  1. `basketball/data_pipeline/injury_data.py` — NEW file from `origin/injury`:
     ESPN fetch, abbr correction, unicode name matching, player-ID matching,
     weighted OUT/DOUBTFUL vs QUESTIONABLE getters. Severity composites and
     probability/margin multipliers deliberately dropped. ADDED: every snapshot
     write also appends a dated copy under `injury_data/archive/`. NOT wired into
     any pipeline — revive only when owner reopens injuries.
  2. `BasketballH2HModel.analyzeFeatureImportance()` — permutation-importance +
     correlation redundancy report from `origin/new_player_data`, generalized by
     model type (works for spread/total too), returns DataFrame, optional CSV out.
     Its old branch's pruning LISTS are invalid (leaky val); tool only.
  3. Vectorized rolling + cache: NO copy needed — main already has the helpers in
     `shared/base_data_preparer.py`; wiring instructions documented in NOTES.
     Defer wiring until after retrain (keep feature semantics frozen).
- pytest: 11 passed. Smoke-checked injury module (dated snapshot verified) and
  analyzer presence.

**Next**
1. OWNER: full data refetch + delete stale training CSVs +
   `data/training_data/basketball/phase1/separated_seasons/*` rebuild + one big
   retrain of all three basketball models (see previous entries for gotchas:
   prepareAllSeasons skips existing season files; expect clean-split metrics
   ~0.62-0.65 h2h, lower than leak-inflated logs; confirm metadata prints
   residual sigma "(measured)").
2. After retrain: Batch 4 per NOTES §Suggested fix order (A5 drop-list single
   source of truth, A4 remainder, C-R3 ladder collapse + availability gating,
   C3/C4 features) using analyzeFeatureImportance on the new clean splits.

**Blocked-open (awaiting owner, not code)**
- Odds API key rotation: key remains public in git history (M1 secrets cleanup
  also still queued).
- Injury system revisit timing (module ready but unwired).
- Delete stale branches? no_injuries / fullstack-app safe; injury / working /
  new_player_data after confirming nothing else needs salvage.
- Hockey mirror debt: same A/B-class issues exist there; unscoped until owner asks.

---

## 2026-08-22 — Basketball remediation Batches 1–3 complete; retrain pending

**Done**
- Batches 1+2 (see archive for detail): A2 chronological splits
  (`shared/splitting.py`), A1 leak-free player selection + zero-fill alignment
  (`prepare_data.py::getTopPlayersAsOf`), B1 odds window filter, B2 same-book
  line/price pairing, B3 fresh-log crash, B4 push grading `'P'`.
- **Batch 3 — C1:** `betting_recommender.py` cover probabilities are now
  `normalCoverProbability(edge, sigma)` = Φ(edge/σ), replacing the old logistics
  that returned ≥0.5 for any positive edge. σ comes from
  `models/metadata/retraining_*_metadata.json['residual_std']`, which
  `model_retrainer.py` now writes after each spread/total retrain (val-based);
  until the next retrain, config fallbacks apply (spread 11.8 / total 14.0,
  league-typical placeholders).
- **Batch 3 — C2:** h2h edges are devigged (`devigTwoWay`: fair = implied /
  overround of both best prices). The `market_prob` column in bet logs now stores
  the DEVIGGED fair probability (semantic change going forward). MIN_EDGE_H2H=0.02
  now means 2% vs fair prob; expect ~2% more headroom than the old vig-inclusive
  numbers.
- Owner is handling the full data refetch + rebuild of training CSVs and a single
  big retrain (old training files were built with leak-era feature semantics;
  `prepareAllSeasons` skips existing season files unless they are deleted first).
- pytest: 11 passed.

**Next** (after owner's refetch + retrain)
1. Sanity-check retrain output: metadata `residual_std` populated and printed as
   "(measured)"; val/test metrics on clean chronological splits (expect lower than
   historical logs); split date ranges strictly ordered train < val < test.
2. Batch 4 hardening per `basketball/NOTES.md` §Suggested fix order: A5 single
   source of truth for drop lists, A4 remainder, C-R3 ladder collapse +
   availability gating, C3/C4 feature additions.
(M1 secrets cleanup remains queued if not done sooner.)

**Blocked-open (awaiting owner, not code)**
- Odds API key rotation: key is public in git history regardless of code cleanup.
- Injury system revisit: deferred by owner until after remediation batches.
- Hockey mirror debt: identical issues likely exist in hockey's pipeline; out of
  scope until owner says so.


## 2026-08-22 — Basketball remediation Batches 1+2 implemented

**Done**
- **A2 time-based splits:** `shared/splitting.py::chronologicalSplit` replaces the
  random `train_test_split` in `basketball/model/model_retrainer.py`. Proportions
  preserved chronologically: earliest 80% train / next 10% val / latest 10% test.
  Split date ranges print during retraining.
- **A1 player-selection de-leak:** `basketball/data_pipeline/prepare_data.py`
  replaced `getTopPlayersWithStats` (ranked by in-game MIN — leaked) with
  `getTopPlayersAsOf` (top-6 by `mpg_rolling`, latest row strictly before the game
  date; same semantics as prediction). Missing player slots now zero-fill in BOTH
  paths, which also closes the A4 NaN-vs-zero skew for player aggregates.
- **B1:** `odd_scraping.py::upcomingGamesWindow()` fixes the discarded
  started-games filter in all three odds methods.
- **B2:** `betting_recommender.py::bestOutcomeRow()` pairs spread/total line,
  price, and book from the SAME best-priced row; totals confidence uses midpoint
  of available lines.
- **B3:** fresh/empty bet-log files no longer crash `logRecommendations`.
- **B4:** spread/total pushes grade `'P'` (stake refunded) instead of `'L'`;
  bankroll and win-rate math already treat non-W/L as neutral.
- Verified end-to-end on real data: `createGameMatchupData('2023-24')` builds
  1077 games with ZERO NaN player features. pytest: 10 passed.

**Next**
1. ⚠️ RETRAIN all three basketball models (`Model Retraining` in
   `.venv/bin/python basketball/main.py`) — existing models are semantically stale
   under the new feature rules; see `basketball/NOTES.md` §Retrain requirement.
   Expect metrics to drop vs old logs (old ones were leak-inflated).
2. Batch 3 per `basketball/NOTES.md` §Suggested fix order: C1 empirical cover
   probabilities + C2 devigged edge calc.
(M1 secrets cleanup remains queued if not done sooner — see archive.)

**Blocked-open (awaiting owner, not code)**
- Odds API key rotation: key is public in git history regardless of code cleanup.
- Injury system revisit: deferred by owner until after remediation batches.
- Hockey mirror debt: identical A/B-class issues likely exist in hockey's pipeline;
  out of scope until owner says so.

## 2026-08-22 — Basketball audit complete; remediation spec written

**Done**
- Full basketball code audit (leakage, bugs, feature plan). Consolidated findings
  plus owner rulings live in `basketball/NOTES.md` — that file is the remediation
  spec; read it before touching basketball code. AGENTS.md references it.
- Owner rulings recorded (details in NOTES.md §Owner rulings): injuries DEFERRED
  (none exist for basketball; hockey's module is commented out); `total_l10`
  semantics clarified; momentum + player-ladder restructuring delegated to agent;
  market-feature cost concern resolved (devig = free math on odds already fetched;
  limitation is historical backfill depth only).
- `basketball/NOTES.md` un-hidden from git via `.gitignore` negation
  (`!basketball/NOTES.md`) since `basketball/*.md` is ignored.
- Resolved the stash-pop conflict in `requirements.txt` (kept owner's fastapi +
  SQLAlchemy additions and the pytest section).
- pytest green: 5 passed (`docs/SESSION-LOG.md`, bet-log integrity, sport imports).

**Next** — Basketball remediation, in `basketball/NOTES.md` §Suggested fix order:
1. Batch 1 (validity): A2 time-based train/val/test splits + A1 player-selection
   leak fix (top-6 by rolling mpg as-of-date in both training and prediction paths).
2. Batch 2 (money correctness): B1 started-games filter, B2 line/price pairing,
   B3 fresh-file crash, B4 push grading.
3. Then C1/C2 (empirical cover probs + devig) per NOTES.md.
(M1 secrets cleanup from the bootstrap entry remains queued if not done sooner —
see archive.)

**Blocked-open (awaiting owner, not code)**
- Odds API key rotation: key is public in git history regardless of code cleanup.
- Injury system revisit: deferred by owner until after remediation batches; when
  resumed, start with Tier-1 availability features from existing game logs
  (NOTES.md §C-R3 / Additions #2).

## 2026-08-21 — Bootstrap: repo made self-sufficient

**Done**
- Wrote the operational docs an agent needs to start cold: `AGENTS.md` (constitution:
  non-negotiables, commands, layout, workflow, escalation), `docs/PROJECT.md`
  (goal, M1 milestone, out-of-scope, constraints), `docs/DECISIONS.md`,
  this file, and `docs/SESSION-LOG-ARCHIVE.md`.
- Added `tests/` with pytest smoke tests (imports, bet-log integrity) and registered
  `pytest>=8.0.0` in `requirements.txt`; verification command is
  `.venv/bin/python -m pytest tests/ -v`.
- Updated `.gitignore` to exclude `.env`.
- Audited for secrets: found the Odds API key hardcoded in three `odd_scraping.py`
  files (hockey, basketball, baseball), already in git history. Not removed yet.

**Next** — M1 secrets cleanup (`docs/PROJECT.md`):
1. In all three `odd_scraping.py` files, replace the hardcoded API key with
   `os.environ["ODDS_API_KEY"]` (fail fast with a clear message if unset).
2. Create `.env.example` documenting `ODDS_API_KEY=<your key>`; keep `.env` gitignored.
3. Verify: `.venv/bin/pip install -r requirements.txt && .venv/bin/python -m pytest tests/ -v`,
   then run `.venv/bin/python hockey/main.py` once with the env var set.
4. Update SESSION-LOG; append a DECISIONS row if injection method differs from above.

**Blocked-open (awaiting owner, not code)**
- Owner should consider rotating the Odds API key: it is already public in git
  history, so removing it from code does not un-leak it.
