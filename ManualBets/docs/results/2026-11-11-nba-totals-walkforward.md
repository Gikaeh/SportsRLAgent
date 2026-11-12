# NBA totals model: walk-forward backtest (2026-11-11)

Question: should ManualBets' NBA total (over/under) model come back as a watch-only
recommendation? It is trained (`models/basketball_total_model.json`) but commented out of the NBA
menu, bet logging and `tools/export_predictions.py`, with no recorded reason.

## 1. Pre-registration (committed before the holdout was scored)

Everything in this section was fixed before any 2025-26 (holdout) or 2026-27 (forward) result
was computed. Nothing here is tuned on the holdout.

**Data.**
- Games, team and player logs: ManualBets' own nba.com files (`{season}_game_stats.csv`,
  `_team_stats.csv`, `_player_stats.csv`) for 2000-01 to 2026-27, fetched with
  `basketball/data_pipeline/basketball_data.py` (seasons before 2026-27 fetched 2026-11-11 on the
  LAN Raspberry Pi into a scratch folder; 2026-27 copied from the Mac's `data/basketball/`).
  Features come from `NBATrainingDataPreparer.createGameMatchupData`, unchanged.
- Market: DeepSports warehouse copy (`/Volumes/ExFATStorag/DeepSports/scratch/totals-backtest/deepsports.duckdb`,
  copied 2026-11-11 15:25 PT, read-only), `odds_snapshots` rows with `source='closing'`:
  `over_under`, `over_price`, `under_price`. Opening rows (`source='opening'`) only for CLV.
- Matching: ManualBets game -> warehouse game by US Eastern game date and home/away team
  (NBA.com codes mapped to ESPN: NYK->NY, SAS->SA, NOP->NO, UTA->UTAH, GSW->GS, WAS->WSH).
  Unmatched games are scored for MAE only where a closing total exists; the match rate is reported.
- Scored games: `season_type` 2, 3, 5 (regular season, playoffs, play-in) from 2021-10-01
  (first season with closing lines) to 2026-11-10. The feature pipeline drops each team's first
  10 games of a season (no L10 window), so the first ~3 weeks of each season have no predictions.
- Periods: development 2021-22 to 2024-25 (reported, not used for decisions); **holdout 2025-26
  (locked; decides)**; forward 2026-27 to date (reported separately, too small to decide).

**Features.** Exactly the saved model's 36 inputs (`booster.feature_names` of
`models/basketball_total_model.json`), i.e. the training frame minus
`BasketballTotalModel.getLeakageColumns()` minus the target `total_score`. The tool asserts that
the pipeline output minus the drop lists equals that list.

**Model and walk-forward.**
- Hyperparameters: the saved model file does not keep the Optuna-tuned values, and they were tuned
  on a validation window overlapping the backtest. So they are re-tuned **once**, with the
  production routine (`BasketballTotalModel.tuneHyperparameters`, same search space, 100 trials,
  TPE seed 42, MAE), on games dated before 2021-10-01 only (chronological 80/10/10 split of that
  data, train vs val as in `ModelRetrainer`), then frozen for every refit.
- Monthly refit (as `tools/college_walkforward.py`): for each calendar month in the scored range,
  train on every game dated before the month's first day, predict that month's games. Within the
  training games, the last 10% by date is the early-stopping set (1000 trees max, 50 rounds
  patience, objective `reg:absoluteerror`, `random_state=42`); the rest is fit.
- Sigma: `residual_std` = std of (actual - predicted) on that refit's early-stopping set, as
  `ModelRetrainer` measures it on its validation split.
- No game a model was fit or early-stopped on is scored by that model (asserted).

**Bet rule** (as `BettingRecommender.makeTotalRecommendations` implements it today; thresholds
not changed):
- `MIN_TOTAL_EDGE` is not set in `betting_config.py`, so the code's default 8.0 points applies.
- Over if `pred - line >= 8`, Under if `line - pred >= 8`; then `cover_prob = Phi(edge / sigma)`
  (`normalCoverProbability`) must be `>= MIN_PROBABILITY` (0.55), and the Kelly fraction
  (`KELLY_FRACTION` 0.20, cap 5%) must be positive. With sigma near 19 the probability gate never
  binds (Phi(8/19) = 0.66), so the 8-point edge is the rule.
- Line and price: the closing `over_under` and the closing price of the side bet; -110 when that
  price is missing. (The live recommender uses the best Nevada-book price at bet time; closing
  prices are a conservative, reproducible stand-in.)
- Staking for ROI: flat 1 unit per bet. Not modelled: the menu's daily 50% risk cap (totals have
  the lowest priority) and whole-dollar rounding.
- Grading: Over wins if actual total > line, Under if < line, equal is a push (stake back).

**Metrics** (per season, per period, and Over vs Under):
- Model total MAE vs closing-total MAE on the same games; bias = mean(pred - actual).
- Bets, W-L-P, win rate (pushes excluded), mean break-even rate of the prices taken
  (implied probability of each bet's price, averaged over non-push bets), ROI per unit staked.
- 95% CIs by a **slate-clustered bootstrap**: resample US Eastern game dates with replacement,
  10,000 draws, seed 0, percentile interval of the ratio (sum over picked dates / count over picked
  dates), as DeepSports' `analysis/ensemble.py::cluster_bootstrap`. This interval governs
  (DeepSports DECISIONS 2026-11-11). A naive binomial (Wilson) interval is reported beside it.
- CLV where an opening total exists (2023-24 onward): points the line moved toward the bet from
  opening to closing (positive = market moved our way), mean and share positive.
- Also reported, not the backtest: the saved model's own test-split numbers from
  `models/metadata/basketball/retraining_total_metadata.json`.

**Ship rule** (both on the 2025-26 holdout):
1. Win-rate slate-clustered 95% CI lower bound > the mean break-even rate of the prices taken; and
2. model total MAE - closing total MAE <= 0.5 points.

Pass: add totals to `tools/export_predictions.py` as watch-only output and render them in
DeepSports' ManualBets context; re-enabling the menu/logging stays the owner's decision.
Fail: totals stay disabled; this tool and doc are the record.

## 2. Results

**Verdict: FAIL on both conditions. Totals stay disabled.**

| Holdout 2025-26 | Value | Rule | |
|---|---|---|---|
| Bets, W-L-P | 188, 92-96-0 | | |
| Win rate, slate-clustered 95% CI | 48.9% (42.3% to 55.6%) | lower bound > break-even 52.3% | FAIL |
| Model MAE - closing MAE | 15.27 - 14.44 = +0.83 | <= 0.5 | FAIL |
| ROI per unit (slate CI) | -6.6% (-19.3% to +6.0%) | | |

Run: `NBA_WAREHOUSE_DB=<copy> uv run python tools/total_walkforward.py --data-dir <nba-hist> --start 2021-10-01
--end 2026-11-11 --out <dir> --tune-trials 100` (310 s on the Mac). Reproduction: section 3.

### Coverage
- 30,364 games built from 27 seasons; the tool's features equal the saved model's 36 inputs (same order).
- 6,155 non-preseason games predicted from 2021-10-29 to 2026-11-10; 100% matched to a warehouse game;
  6,154 have a closing total (missing: MIL v POR, 2025-11-24). 0 score mismatches. No bet needed the -110
  fallback. One closing row per game (no duplicates).
- Mix: 5,702 regular season, 422 playoff, 30 play-in, 1 NBA Cup final.
- Tuned once on games before 2021-10-01 (train 2000-11-21..2017-02-25, val 2017-02-25..2019-03-15):
  max_depth 5, learning_rate 0.0102, subsample 0.61, colsample_bytree 0.62, min_child_weight 3, gamma 2.26,
  reg_alpha 2.22, reg_lambda 0.18. Refits used 529-751 trees; refit sigma 18.7-19.4.

### By period and season
Win rate excludes pushes; ROI counts them as staked with 0 profit. CIs: slate-clustered bootstrap
(US Eastern dates, 10,000 draws, seed 0) unless marked Wilson. CLV: points the line moved toward the bet from
open to close (opening lines exist from 2023-24).

| Period | Games | Model MAE | Closing MAE | Diff | Bias | Bets | W-L-P | Win rate | Win CI (slate) | Win CI (Wilson) | Break-even | ROI | ROI CI (slate) | CLV mean / share + / n |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| development | 4866 | 14.93 | 14.14 | 0.78 | -0.96 | 892 | 424-460-8 | 48.0% | 44.6% to 51.3% | 44.7% to 51.3% | 52.4% | -8.3% | -14.6% to -2.1% | -2.49 / 22.6% / 548 |
| holdout | 1221 | 15.27 | 14.44 | 0.83 | -0.86 | 188 | 92-96-0 | 48.9% | 42.3% to 55.6% | 41.9% to 56.0% | 52.3% | -6.6% | -19.3% to 6.0% | -2.95 / 11.2% / 188 |
| forward | 67 | 14.09 | 12.65 | 1.44 | 3.35 | 10 | 4-6-0 | 40.0% | 20.0% to 71.4% | 16.8% to 68.7% | 52.6% | -23.3% | -61.8% to 37.9% | -4.00 / 0.0% / 4 |

| Season | Games | Model MAE | Closing MAE | Diff | Bias | Bets | W-L-P | Win rate | Win CI (slate) | Win CI (Wilson) | Break-even | ROI | ROI CI (slate) | CLV mean / share + / n |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021-22 | 1231 | 14.78 | 13.95 | 0.83 | -0.53 | 171 | 72-98-1 | 42.4% | 35.6% to 49.1% | 35.2% to 49.9% | 52.4% | -19.1% | -31.8% to -6.1% | - / - / 0 |
| 2022-23 | 1181 | 15.02 | 14.25 | 0.77 | -1.64 | 173 | 84-87-2 | 49.1% | 41.7% to 56.5% | 41.7% to 56.6% | 52.4% | -6.2% | -20.5% to 7.4% | - / - / 0 |
| 2023-24 | 1225 | 15.13 | 14.31 | 0.82 | -1.15 | 315 | 156-154-5 | 50.3% | 44.7% to 55.9% | 44.8% to 55.9% | 52.3% | -3.8% | -14.6% to 7.1% | -2.06 / 26.3% / 315 |
| 2024-25 | 1229 | 14.78 | 14.07 | 0.71 | -0.53 | 233 | 112-121-0 | 48.1% | 41.5% to 54.7% | 41.7% to 54.5% | 52.4% | -8.2% | -20.7% to 4.6% | -3.06 / 17.6% / 233 |
| 2025-26 | 1221 | 15.27 | 14.44 | 0.83 | -0.86 | 188 | 92-96-0 | 48.9% | 42.3% to 55.6% | 41.9% to 56.0% | 52.3% | -6.6% | -19.3% to 6.0% | -2.95 / 11.2% / 188 |
| 2026-27 | 67 | 14.09 | 12.65 | 1.44 | 3.35 | 10 | 4-6-0 | 40.0% | 20.0% to 71.4% | 16.8% to 68.7% | 52.6% | -23.3% | -61.8% to 37.9% | -4.00 / 0.0% / 4 |

### Over vs Under (bets)

| Period | Side | Bets | W-L-P | Win rate | Win CI (slate) | Break-even | ROI | ROI CI (slate) | CLV mean / share + / n |
|---|---|---|---|---|---|---|---|---|---|
| development | Over | 405 | 192-210-3 | 47.8% | 43.0% to 52.6% | 52.4% | -8.7% | -17.7% to 0.7% | -2.91 / 22.9% / 249 |
| development | Under | 487 | 232-250-5 | 48.1% | 43.6% to 52.6% | 52.3% | -8.0% | -16.4% to 0.5% | -2.14 / 22.4% / 299 |
| holdout | Over | 71 | 36-35-0 | 50.7% | 39.4% to 61.8% | 52.2% | -3.1% | -24.6% to 18.2% | -1.93 / 21.1% / 71 |
| holdout | Under | 117 | 56-61-0 | 47.9% | 39.3% to 56.4% | 52.4% | -8.8% | -24.9% to 7.5% | -3.57 / 5.1% / 117 |
| forward | Over | 9 | 3-6-0 | 33.3% | 7.7% to 71.4% | 52.6% | -36.0% | -85.1% to 37.9% | -5.00 / 0.0% / 3 |
| forward | Under | 1 | 1-0-0 | 100.0% | 100.0% to 100.0% | 52.4% | 90.9% | 90.9% to 90.9% | -1.00 / 0.0% / 1 |

Tables are the tool's `summary.md` verbatim (one-bet rows have degenerate CIs).

### Saved model (not the backtest)
`retraining_total_metadata.json` (retrain 2026-11-08): test MAE 15.04, test residual std 18.85, val residual
std 19.14 (the sigma the live recommender uses). Its val numbers are double-dipped (NOTES.md A3), and it was fit
on data overlapping this backtest, so it can't be scored here.

### Reading
- The model is 0.7-0.8 points MAE worse than the closing total in every season. When it disagrees with the
  close by 8+ points (about 18% of games), the close is right more often: 48% wins over 1,080 development +
  holdout bets, and the development ROI CI (-14.6% to -2.1%) excludes zero.
- CLV averages -2 to -3 points and is positive on only 11-26% of bets: the line moves from open to close
  *away* from the model's side. The
  model's big disagreements are mostly information the market has (injuries, rest decisions, lineups) and its
  box-score L10 features don't.
- No side works: Overs and Unders both lose.

### Caveats
- Bets are priced and selected at the close. Live bets come earlier, at the best Nevada-book price, when
  the line (per the negative CLV) usually sits closer to the model's number. That means a better number
  but also bets the market later corrects against. Which effect wins can't be checked without timestamped
  pre-tip lines and prices (C3 snapshots are accumulating). The close is the standard benchmark, and the
  model doesn't beat it.
- Leakage audit (builder, then validator, section 3): no feature uses the game's own or later results. Two
  train/serve differences were found and logged in `basketball/NOTES.md` (A7: live team L10 stats lag one
  game; A8: traded players). Both make live features *worse* than the backtest's, so they don't rescue the
  result.
- Hyperparameters were tuned once on pre-2021 data, not with the production per-retrain Optuna run.
- The menu's 50% daily risk cap, whole-dollar stakes and the `MIN_BET_AMOUNT` drop aren't modelled
  (flat 1-unit stakes; at an 8+ edge Kelly hits the 5% cap, so no live bet would round to $0).
- The early-stopping slice is the last 10% of all prior games (~2 seasons), so each refit's trees are fit
  on data ending ~2 seasons before the month it predicts (as pre-registered; it mirrors the production split).
  This handicaps the model, not the market; a refit on all data is unlikely to close a 0.8-point MAE gap.
- The 2025-26 NBA Cup final (neutral site, both nba.com rows say "@") drops out of the feature frame.

## 3. Validation

An independent validator (a session that didn't write the tool) checked the run on 2026-11-11. All checks
passed and no number changed.
- **Re-run from scratch** (`--rebuild-features --tune-trials 100`): same tuned parameters, identical
  features, predictions and summary, so tuning is deterministic. Two seasons rebuilt in empty folders with no
  player cache matched exactly.
- **Recomputed without the tool's code:**
  - Join: the US Eastern date + team join gives the same warehouse game for all 6,155 games. A UTC-date join
    would match only 1,388, and a home/away swap matches 0.
  - Odds and scores: closing and opening totals and prices agree with `odds_snapshots` for every game, and
    every game's score agrees.
  - Bets: side, price, result, profit and CLV agree in every row. Every table cell above reproduces.
- **Clustered CI:**
  - The clusters are US Eastern game dates: 119 days in the holdout.
  - Pushes are left out of the win rate but counted in ROI.
  - A literal port of DeepSports' `cluster_bootstrap` gives the same intervals.
  - Sensitivity of the holdout win-rate CI to how bets are clustered: ISO week 41.8% to 56.7%, UTC date
    42.2% to 55.4%, per game 42.0% to 55.9%. The verdict doesn't depend on the clustering.
- **Future-perturbation leakage tests:**
  - Feature level (raw logs corrupted or deleted after, or on and after, the cutoffs 2024-01-15 and
    2025-11-20): the 36 features of every game on or before the cutoff are unchanged (max abs diff 0.0),
    while ~99% of later games change.
  - Model level (`walkForward`, cutoff 2024-01-15): predictions before the first refit that can see the
    perturbed games are unchanged (0.0 over 2,914-3,030 games).
- **Conformance** to section 1: no material deviation.
  - The tool requires Kelly > 0, while the recommender drops $0 stakes instead. The two are equivalent at
    these prices.
  - The tuning split is by row, so one date (2017-02-25) sits in both train and val, as in production.
- **Pipeline read:** no leakage. Train/serve differences A7 and A8 are logged in `basketball/NOTES.md`.
  - Preseason games feed early-season L10 windows. This is consistent between training and live use.
  - Neutral-site Cup finals whose nba.com rows both say "@" drop out (A9).
- **Reviewer:** no blockers. The should-fix items were fixed:
  - The feature-list check is now an assert, as section 1 promises.
  - One closing and one opening row per game in SQL (latent duplicate-row drop).
  - The feature cache is keyed to `--data-dir`.
  - After the fixes, the tool, re-run from the cached parameters, reproduced the same predictions and
    summary.
- **Tests:** `uv run pytest -q` gives 68 passed and 2 known failures (`test_opp_avg_win_pct`).
