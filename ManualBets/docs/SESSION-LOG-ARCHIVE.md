# SESSION-LOG-ARCHIVE.md — append-only, newest on top

Move superseded entries from `docs/SESSION-LOG.md` here verbatim. Never edit or
delete archived entries.

---

## 2026-11-09 — Live game screen, owner bets logged, one bankroll

**Done** (PR #6 merged into `main`)
- DeepSports game screen: play-by-play, possession, last-shot court, score animations, about 10s refresh for live games.
  iOS tab bar fix, confirmed by the owner on an iPhone.
- Owner's real bets logged, plus a new `logs/college_basketball/betting/bets.csv`. Balance $86.36 with $21 open (TOR -2.5 added Nov 9 at 4:40 PM PST, see Next 1).
- NBA bankroll now includes college results. Why, and the logging limits: `docs/DECISIONS.md`.
- Warehouse refreshed by hand on 2026-11-08 at about 20:50 PT (update and predict only).

**Verify**
- `.venv/bin/python -m pytest tests/ -q`: the 2 known `test_opp_avg_win_pct.py` failures, the rest pass.
- `cd DeepSports && uv run pytest -q`: all pass.
- This is a Mac now: use `.venv/bin/python`. The `.venv\Scripts` commands in AGENTS.md don't apply here.

**Next**
1. Grade the 5 open Nov 9 bets by hand from final scores: Hawks +2 ($3), MEM @ TOR: TOR -2.5 at -110 ($5, placed
   after the 10-agent ensemble run), DEN @ HOU Over 216.5 ($5), NO @ GS Over 231.5
   ($5), Illinois St @ Purdue Over 145 ($3). They're in `logs/basketball/betting/spread_bets.csv` and `total_bets.csv`,
   and `logs/college_basketball/betting/bets.csv`.
2. Watch the live screen during a real game: possession has only run on finished games, mocks and a replay. Known gap:
   a brief ESPN failure on `/api/games/{id}` returns 404, with no stale fallback.
3. OWNER: the launchd sync failed on 2026-11-08 14:00 with `Operation not permitted` opening the warehouse on the
   external drive (`~/Library/Logs/DeepSports/sync.log`). Check macOS file access for it. The 08:00 run may fail too.
4. NBA menu: `getUpcomingGames` only keeps today's local date, so at night it can't reach tomorrow's slate. "3. All" is
   listed but only choice 4 runs it. `stats.nba.com` timed out and `cdn.nba.com` returned 403 on 2026-11-08 at night.
5. Grade the Nov 8-10 forward freeze:
   `/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/forward_freeze.csv`.
6. Previous items still open: NBA Batch 4 hardening (NOTES); hockey's random splits.

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
   `logs/college_basketball/betting/bets.csv`. Why by hand: `docs/DECISIONS.md`. The NBA menu's bankroll now includes college.
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

---

---
## 2026-11-07 — NBA initial setup scripts now split chronologically (A2 complete)

**Done**
- `basketball/initial_h2h_setup.py`, `initial_spread_setup.py`,
  `initial_total_setup.py`: replaced the two-stage
  `train_test_split(..., random_state=42)` (random shuffle across seasons — the
  A2 leak) with `shared.splitting.chronologicalSplit`: earliest games train,
  then validation, latest games test, 80/10/10 like `ModelRetrainer` and
  `tools/pipeline_smoke_test.py`. The scripts now print each split's date range.
- All four training entry points normalize the date column before splitting
  with `pd.to_datetime(..., utc=True).dt.tz_localize(None)`.
  `prepareAllSeasons` can mix freshly-built datetime columns with cached CSV
  string columns; mixed dtypes break `sort_values`, and chronological order is
  the whole point of the split.
- `basketball/model/model_retrainer.py`: already used `chronologicalSplit` from
  the 2026-08-22 A2 fix; hardened for parity with the smoke test:
  - same date normalization before the split;
  - the three duplicated leakage-drop/target-extraction blocks are now one
    `splitFeaturesAndTarget()` method with the same `splitXY` shape as
    `tools/pipeline_smoke_test.py`. Target + drop list still come from the model
    class, so train and live-predict cannot drift.
- Initial-model split proportions move from the old random split's 60/20/20 to
  the retrainer/smoke-test 80/10/10 — one split rule everywhere. Expect
  initial-model metrics to drop; the old numbers were leak-inflated.

**Verify**
- `.venv\Scripts\python.exe -m pytest tests/ -v`: 14 passed, 2 FAILED. The 2
  failures are the known PRE-EXISTING `tests/test_opp_avg_win_pct.py` ones
  (`calculateOpponentStrengthL10` has never existed; the method is
  `calculateOpponentStrength`), identical to HEAD before these edits.
- New tests in `tests/test_basketball_fixes.py`:
  `test_basketball_training_paths_split_chronologically` (source guard: no
  `train_test_split` in any of the four entry points) and
  `test_retrainer_splits_features_and_target_consistently` (all three model
  types drop target + leakage columns and keep feature order).

**Next**
1. OWNER: retrain all three NBA models (`basketball/main.py` → Model
   Retraining) so saved models match the clean-split semantics.
2. Batch 4 hardening (NOTES §Suggested fix order) remains — A3 (validation
   double-dip), A5 (single source of truth for drop lists), C-R3, C3/C4.
3. Hockey is out of scope (owner: NBA focus); its `initial_*_setup.py` files
   still use random splits — mirror this change when hockey comes back.

---
## 2026-09-07 — NBA prepare_data.py de-duplicated; shrunk 996 → 712 lines

**Done**
- Removed the near-identical duplicate feature-building paths in
  `basketball/data_pipeline/prepare_data.py` (no behavior change; same feature
  sets and output column names).
- `addPlayerFeatures` + `addUpcomingPlayerFeatures` collapsed into one
  `_buildPlayerFeatureMatrix(matchup_data, season, use_game_date=...)`; the only
  prior difference — top-6 selection by game date (`getTopPlayersAsOf`, the A1
  non-leaky path) vs latest-rolling — is now a parameter. Both wrappers kept
  their original ValueError messages.
- Shared block in `createGameMatchupData` + `createUpcomingMatchupData`
  (metadata + team-window rename map + player-agg rename map + existing-col
  selection + rename + float-3 rounding) extracted to `_buildMatchupFeatureFrame()`.
- Added module constants `PLAYER_SLOT_STATS`, `PLAYER_AGG_STATS`,
  `TEAM_WINDOW_STATS`. Both methods previously carried their own copies; the two
  team-window lists were the same 20 stats in different order, which risks
  column-order drift between train and predict.
- Deleted ~135 lines of dead commented-out `prediction_data = pd.DataFrame({...})`
  legacy block (already removed from the training path in the prior commit).
- File: 996 → 712 lines. Net `git diff`: 67 insertions / 350 deletions.
- (follow-up) NBA `NBATrainingDataPreparer` now genuinely uses the shared base:
  inherits `BaseTrainingDataPreparer`; dropped its duplicate `calculateRestDays`;
  `precomputePlayerRollingAverages` rewritten to the shared
  `computeRollingStatsVectorized` (expanding mean, shift 1, fillna 0) + parquet
  cache via `getCachedData`/`saveCachedData` — resolves NOTES §Salvaged #3.
  Semantics are unchanged (verified parity old-loop == vectorized on synthetic
  data); no retrain required on semantic grounds.
- Remaining `shared/` usage after wiring: `base_data_fetcher.py` (BasketballData)
  and `splitting.py` (model_retrainer) were already NBA-consumed; all three
  shared modules are now NBA-used, so nothing is dead code.
- New standalone tool `tools/calibration_diagnostic.py` prints pick share + win
  rate (W/(W+L), pushes excluded) by bet_side for each market from the graded
  bet logs — a home-bias read. Registered in AGENTS.md command table. It already
  surfaces a h2h signal: home picks 3/9=33.3% vs away picks 6/9=66.7% (n=18).
- `requirements.txt` trimmed to NBA: removed `nhl-api-py`, `fastapi`,
  `SQLAlchemy`; added `requests` (direct import) and `pyarrow` (parquet cache
  engine for `shared/base_data_preparer.py`).

**Verify**
- `.venv\Scripts\python.exe -m pytest tests/ -v`: 11 passed, 2 FAILED.
  The 2 failures — `tests/test_opp_avg_win_pct.py::test_opp_avg_win_pct_invariants`
  and `::test_preview_opponent_breakdown` — are PRE-EXISTING and unrelated: the
  test calls `NBATrainingDataPreparer.calculateOpponentStrengthL10()`, which has
  never existed in the codebase (method is `calculateOpponentStrength`). Confirmed
  they fail identically on the stashed (unmodified) HEAD.
- `tests/test_basketball_fixes.py` (incl. A1 player-selection regression): 6/6 pass.

**Next**
1. OWNER: review working tree (`prepare_data.py`, README.md, docs changes) +
   commit if desired.
2. Batch 4 hardening (NOTES §Suggested fix order) remains — A5 drop-list single
   source of truth, C-R3 availability gating, C3/C4 features, etc.
3. Hockey is out of scope for now (per owner: NBA focus) — NHL shared-base wiring
   and its mirror debt are frozen until it comes back in scope.

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
