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

(Filled in after the run.)
