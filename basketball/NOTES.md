# Basketball — Audit Notes & Feature Plan

Audit date: 2026-08-22. Status: **Batch 1 + Batch 2 IMPLEMENTED same day**
(see ✅ markers below); remaining batches pending. Owner rulings recorded below —
a fresh agent should treat this file as the spec for the basketball remediation
work and re-verify line numbers before editing (code may have moved).

> ⚠️ Models must be RETRAINED before daily use: saved basketball models were
> trained under the old (leaky) feature semantics — p1..p6 slots meant "who played
> the most minutes tonight". Predictions from stale models on new features are
> invalid until `Model Retraining` runs.

---

## Owner rulings (2026-08-22)

1. **Injuries: deferred.** Owner thought an injury implementation existed; it does
   not (see "Injury system state" below). We will return to injuries later.
2. **`total_l10`:** owner's understanding of the feature is correct (avg of last-10
   game totals including opponent points). Clarification recorded in C-R1: it is
   still exactly `ppg_l10 + opp_ppg_l10`, so it adds no information while both
   components exist as columns.
3. **Momentum features:** delegated to agent → keep `plus_minus_diff`, drop the
   raw duplicates (C-R2).
4. **Top-player ladders:** delegated to agent, with owner intent noted: ladders
   also existed as scaffolding for future injury weighting (weight injured players,
   let it affect team aggregates). Plan in C-R3 preserves that capability without
   keeping three overlapping windows per stat.
5. **Market features:** owner concern — historical devigged probability data is
   hard to get for free. Response in C1: no paid source is needed; devigging is
   arithmetic on two-sided prices already fetched free from The Odds API, and
   timestamped snapshots already accumulate in `data/basketball/odds_data/`. The
   real limitation is *historical backfill depth* (features only exist going
   forward), documented there too.
6. All other findings below were reviewed and accepted as written.

---

## A. Leakage / model validity

### A1 — Player-selection leak in training (highest priority) — ✅ FIXED 2026-08-22
`prepare_data.py` (`getTopPlayersWithStats`): top-6 players were chosen by
actual minutes played **in that game** (`sort_values('MIN')`) — post-game info
deciding *which* players become features. Their stat values were pre-game rolling
averages (shift(1)), but selection itself leaked game narrative (blowouts, close
rotations, in-game injuries).
At predict time (`addUpcomingPlayerFeatures`) selection used career mpg instead — a
different rule that also included injured/suspended stars who would not play tonight.

**Implemented fix:** replaced with `getTopPlayersAsOf()` — top-6 ranked by
`mpg_rolling`, each player's latest row strictly BEFORE the game date, identical
semantics to the prediction path. Missing slots now fill 0 in BOTH paths (also
closes the NaN-vs-zero skew for player aggregates, A4's main case). Regression test:
`tests/test_basketball_fixes.py::test_player_selection_is_pregame_only`.

### A2 — Random split across seasons violates non-negotiable #4 — ✅ FIXED 2026-08-22
`model_retrainer.py` used `train_test_split(..., random_state=42)` — shuffled all
seasons together: model trains on future, validates on past; early stopping and
Optuna selected on the leaked val set.

**Implemented fix:** `shared/splitting.py::chronologicalSplit` (sport-independent)
now splits by date preserving the old proportions chronologically (80% train /
10% val / 10% test; earliest→latest). Split date ranges printed during retraining.
Regression test: `tests/test_basketball_fixes.py::TestChronologicalSplit`.

### A3 — Validation metrics double-dipped
After tuning + early stopping on X_val, `evaluate(X_val)` is logged as
"val_accuracy" (`model_retrainer.py:191-199`). Biased high even ignoring A2.
**Fix:** hold out a final untouched eval window.

### A4 — NaN-vs-zero train/predict skew
Training left player aggregates NaN when data was missing (merge `how='left'`);
prediction filled explicit zeros. XGBoost routes NaN and 0 differently — silent
distribution shift.
**Status:** player-aggregate case ✅ CLOSED by A1 fix (both paths zero-fill missing
slots). Any remaining NaN sources (team features) still open for batch 4 review.

### A5 — "leakage_cols" misnamed + duplicated lists
The per-model drop lists are mostly low-importance removals (total model prunes
~30 cols), not leakage. They exist twice — `model_retrainer.retrainModel` and
`live_data_updater.getPredictionReadyData` — synced by hand. One edit in one place
= feature mismatch crash at best, silent misalignment at worst.
**Fix:** single source of truth (e.g., saved feature list alongside each model).

## B. Bugs

| # | Bug | Where | Status |
|---|---|---|---|
| B1 | Started-games filter discarded: second filter assignment overwrites `cleaned_data`, dropping the `commence_time > now` result | `odd_scraping.py` (all 3 methods) | ✅ FIXED — `upcomingGamesWindow()` helper, regression tested |
| B2 | Line/price mismatch: spread/total `point` taken from first row (arbitrary book) while `price` was max across books | `betting_recommender.py` | ✅ FIXED — `bestOutcomeRow()` pairs point+price+book from the same (best-priced) row; totals use the Over line and best matching Under; predict-time confidence uses midpoint of available lines |
| B3 | Crash on fresh log file: `existing_data` referenced before assignment when log missing/empty | `logRecommendations` | ✅ FIXED — initialized to empty DataFrame |
| B4 | Pushes graded as losses: no push branch for spreads/totals; stake docked on exact landings | `updateBetResults` | ✅ FIXED — exact landing grades `'P'` (stake refunded: bankroll/win-rate math already counts only W/L) |
| B5 | `BettingRecommender(model_path=None)` crashes: `.split('_')` runs before None-coalesce | `betting_recommender.py` | pending |
| B6 | Div-by-zero in `calculateBetPriority` when Kelly yields fraction 0 → bet_amount 0 | `betting_recommender.py` | pending |
| B7 | `getActiveBets` returns after first existing file only; activeBets menu re-prompts save + re-writes archive rows | `betting_recommender.py` | pending |
| B8 | Dead/stale config: kellyCriterion confidence arg commented out; UNDERDOG_KELLY_MULTIPLIER unused here; comments contradict values | `betting_config.py` | pending |
| B9 | Retrain status check triggers full season refetch just to count rows | `model_retrainer.py` | pending |
| B10 | Silent bet dropping in display (totals skipped but risk-counted; pops with no notice) | `displayRecommendations` | pending |
| B11 | `displayModelWinRate` divides by zero on fresh logs | `betting_recommender.py` | pending |
| B12 | Season flip July 1 (`getCurrentSeason`): mid-July runs target nonexistent files | `prepare_data.py` | pending |
| B13 | Grading limited to current season CSVs — end-of-season bets orphan at rollover | `updateBetResults` | pending |

## C. Adjustments / feature plan

### Decisions applied to current feature set (72 features)

**C-R1 — Remove `home_total_l10`, `away_total_l10`.** Per-game TOT_PTS is defined
as PTS + OPP_PTS (`prepare_data.py:29-30`) and all three use identical windows and
shifts, so `total_l10 ≡ ppg_l10 + opp_ppg_l10` row-for-row. The feature measures
what the owner intended — it's just fully redundant given its components are also
columns. Zero marginal information; drop for parsimony (not correctness).

**C-R2 — Momentum (agent decision).** Keep `plus_minus_diff` only. Drop
`home_plus_minus_l10`, `away_plus_minus_l10`, `home_top6_total_plusminus`,
`away_top6_total_plusminus` — same signal, importance dilution complicates pruning.

**C-R3 — Ladders (agent decision, preserving owner's injury-weighting intent).**
Collapse top3/top5/top6 ladders to ONE window per stat (top5), keep `*_top3_avg_ppg`
as star-power proxy. Do NOT delete the per-player slot machinery (`p1..p6_*`):
when injury features arrive, apply availability weights at the per-player level
(weight 0 for OUT players) *before* aggregating — that achieves "injuries affect
team aggregates" without 3x window duplication. Availability-gate every player
aggregate now (see Tier-1 injuries below).

**Change:**
- `fg_pct_l10` / `fg3_pct_l10`: averaging percentages-of-percentages underweights
  high-volume games; aggregate makes/shots or points-per-shot instead.
- Rest/B2B: add schedule density (games-in-last-4-days / 3-in-4 flag); single b2b
  binary is weaker than density.
- Revisit h2h "leakage_cols" pruning AFTER A2 fix: `opp_ppg_l10` (defense) and fg%
  were dropped based on importances measured on randomly-shuffled val sets;
  defense almost certainly belongs in a winner model.

**Additions (ranked by value/effort):**

1. **Market features (C1).** Model currently competes against the market blind.
   Devigged home-implied-prob (+ spread/total lines) as features is the strongest
   available predictor. Cost answer: devigging is free math on the two-sided
   prices The Odds API already returns; timestamped snapshots accumulate in
   `data/basketball/odds_data/`. Limitation: no historical backfill — features
   join training data only from when snapshot retention starts, so start persisting
   nightly devigged snapshots immediately and train market-feature models on the
   accumulated window (XGBoost handles older rows' missing values natively).
2. **Availability features (Tier-1 injuries — trainable today, no ESPN needed).**
   From existing player game logs: count of top-6-by-mpg players who missed last
   game / last 3 games; days since each top player played. Logs ARE retrospective
   injury/rest truth, historically complete. Also fixes A1 skew as a side effect.
3. **Pace/possession normalization for totals.** Proxy possessions =
   FGA + 0.44·FTA − ORB + TOV per game; offensive/defensive efficiency L10. Raw
   points are pace-confounded — likely why totals underperform.
4. **Home/away split form.** Current L10 blends home+away games; road scoring is
   much weaker signal for away games.
5. **Season-stage index** (month / games-played) — early-season L10 noise; lets
   model learn reliability curve.
6. **Injury tier-2 (DEFERRED per owner).** Port hockey's module only after fixing
   these four flaws first:
   - Only a mutable snapshot exists (`current_injuries.csv` overwritten each
     fetch) → cannot train on un-archived history. Needs dated append-only
     snapshots from day one.
   - QUESTIONABLE treated as OUT overstates impact — weight statuses (start
     OUT-only if simpler).
   - `injury_severity` composite uses magic constants — feed raw components
     (star_out, production-lost) and let the model combine them.
   - Staleness gate required (a stale snapshot consulted months later silently
     poisons recommendations).

### Other adjustments (accepted unchanged)
- **Cover-probability heuristics replaced** (`marginToProbability` / ✅ FIXED
  2026-08-22 as `normalCoverProbability`): P(cover) = Φ(edge/σ) with σ = measured
  validation residual std, written by ModelRetrainer into
  `models/metadata/retraining_*_metadata.json['residual_std']` and loaded by the
  recommender (config fallbacks until first post-fix retrain). Signed edges now
  allowed (<0.5 rejected by gates). Push mass at integer lines ignored — pushes
  grade 'P' and refund.
- **Devig before edge calc** ✅ FIXED 2026-08-22 (`calculateEdge` + `devigTwoWay`):
  h2h edge compares model prob to the two-sided fair (proportional devig of best
  prices). `market_prob` log column now stores the DEVIGGED fair probability
  (raw implied recoverable from odds columns). Devigged edges run ~2% higher than
  the old vig-inclusive numbers — that is the correction, not a strategy change.
- **Odds freshness gate**: require `last_update` within N minutes before
  recommending (pairs with B1). Still pending. Snapshot retention itself already
  exists de facto — every fetch writes a timestamped CSV under `odds_data/`.

## Suggested fix order

1. ~~**A2 + A1**~~ — ✅ IMPLEMENTED 2026-08-22 (+B1–B4 pulled forward).
2. ~~**B1–B4**~~ — ✅ IMPLEMENTED 2026-08-22.
3. ~~**C1 + C2**~~ — ✅ IMPLEMENTED 2026-08-22 (normal-approx cover probs with
   measured σ pipeline; devigged h2h edge). Snapshot retention: already satisfied
   by timestamped odds CSVs; market-FEATURE engineering remains future work.
4. Then A5/A4-remainder/C-R3/C3 hardening; injuries revisit deferred by owner.

## Retrain requirement

⚠️ All three basketball models are now semantically stale: their p1..p6 feature
slots were learned under in-game-minutes ordering. Run `Model Retraining` from
`.venv/bin/python basketball/main.py` before acting on any new recommendation.
Expect metrics to DROP vs the old logs — the old numbers were inflated by the
A2/A1 leakage; that is the point. (Reference: main's logged h2h test_acc of
~0.66-0.67 was leak-inflated; clean chronological splits will likely land
~0.62-0.65.)

## Salvaged components (2026-08-22, from side branches — none merged as-is)

1. **`basketball/data_pipeline/injury_data.py`** — extracted from `origin/injury`
   (b64cab7 lineage): ESPN fetch, team-abbr correction, unicode name matching,
   player-ID matching, OUT/DOUBTFUL-vs-QUESTIONABLE getters with weights.
   Deliberately EXCLUDED: severity composite and all probability/margin
   adjustment math (magic constants; owner disabled them live). ADDED vs source:
   every snapshot write also appends `injury_data/archive/injuries_YYYY-MM-DD.csv`
   so point-in-time history accumulates (Tier-2 requirement #1).
   **Status: NOT wired into any pipeline** — revive per §Additions #6 when owner
   says injuries are back on the table.
2. **`BasketballH2HModel.analyzeFeatureImportance()`** — permutation-importance +
   correlation-based redundancy report, salvaged from `origin/new_player_data`
   (8e8ea37) and generalized (scoring switches by model type; returns a DataFrame;
   optional CSV export). Use it for Batch 4 pruning decisions ON CLEAN SPLITS —
   the source branch's own pruning lists came from leaky validation and must not
   be reused.
3. **Vectorized rolling + cache: nothing to copy** — main's
   `shared/base_data_preparer.py` already contains `computeRollingStatsVectorized`,
   `getCachedData`/`saveCachedData` (with source-file freshness invalidation),
   identical to the branch version. The remaining work is WIRING:
   make `NBATrainingDataPreparer` inherit `BaseTrainingDataPreparer`, replace the
   per-player loop in `precomputePlayerRollingAverages` with
   `self.computeRollingStatsVectorized(df, 'PLAYER_ID', {...}, min_periods=1)`
   plus `.shift(1)` per group, and wrap the body in
   `cached = self.getCachedData('player_rolling', season, source_file=player_file)`.
   Defer until after the pending retrain to avoid changing feature semantics
   mid-rebuild (semantics-neutral in principle, but verify parity on one season).
