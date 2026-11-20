# NBA spread feature ablation: the hand prune list is harmful (2026-11-20)

**Question.** The shipping spread model drops 41 of 68 frame columns: 13 leakage/identity
columns plus a 99-name hand `low_importance_cols` list. Does that pruning improve a
chronological holdout, or does keeping the features do better?

**Answer.** Keeping the features is better, consistently. Same split, same
hyperparameters, three seeds:

| variant | features | test MAE | resid std | within 5 | R2 |
|---|---|---|---|---|---|
| current hand prune | 27 | 11.819 | 14.988 | 26.1% | 0.151 |
| **all non-leakage features** | **54** | **11.711** | **14.889** | **27.0%** | **0.164** |
| data-driven prune (perm importance <= 0) | 36 | 11.737 | 14.910 | 26.9% | 0.161 |

The all-features model beats the shipping list by **0.107 MAE** on 3,035 holdout games.
A day-clustered paired bootstrap (10,000 resamples, 515 days) puts the difference at
**+0.058 to +0.155 MAE** (positive = all-features better), so it is not seed noise.
All-features was better on 57% of days.

## Method

- Frame: `data/training_data/basketball/all_seasons_training_data.csv`, 30,350 games,
  2000-11-21 to 2026-11-08. No rebuild needed.
- Split: `chronologicalSplit(test_frac=0.2, val_frac_of_test=0.5)` -> train 24,280,
  val 3,035, test 3,035 (2024-02-11 to 2026-11-08). The test slice is never used for
  fitting or feature selection.
- Model: `XGBRegressor`, `objective=reg:absoluteerror`, same params for every variant
  (lr 0.03, depth 6, 2,000 trees, early stop 100 on val). Parameters were deliberately
  **not** tuned per variant: tuning would confound the feature comparison.
- Seeds 0, 1, 2; metrics are the mean. Paired delta computed per seed.
- Data-driven prune: permutation importance (`neg_mean_absolute_error`, 5 repeats) on
  the **validation** slice of the all-features model; drop features with importance <= 0.
- Script: `tools/feature_ablation.py`. Outputs `...ablation.csv`, `...json`,
  `...feature-importance.csv` next to this file.

## What the hand list removed that mattered

Of the 27 currently pruned features, **14 have positive permutation importance** in the
all-features model:

| rank | feature | perm importance |
|---|---|---|
| 8 | away_top5_avg_ppg | 0.0183 |
| 9 | home_top5_avg_ppg | 0.0173 |
| 10 | home_top5_avg_blk | 0.0158 |
| 13 | away_wins_l10 | 0.0148 |
| 14 | home_wins_l10 | 0.0141 |
| 16 | away_top5_avg_apg | 0.0089 |
| 18 | home_top5_avg_rpg | 0.0063 |
| 22 | away_stl_l10 | 0.0039 |
| 23 | home_tov_l10 | 0.0036 |
| 24 | home_top5_avg_stl | 0.0035 |
| 26 | home_top5_avg_mpg | 0.0032 |
| 30 | home_top5_avg_tov | 0.0022 |
| 33 | away_opp_ppg_l10 | 0.0015 |
| 36 | away_top5_avg_tov | 0.0002 |

The top of the all-features model is team quality and efficiency: `home_net_rating_l10`,
`home_plus_minus_l10`, `away_net_rating_l10`, `away_rolling_srs_l10`,
`away_plus_minus_l10`, `home_rolling_srs_l10`, then the top-5 player aggregates.
The hand list kept the ratings but threw away the record (`wins_l10`), the player
scoring/rebounding/size (`top5_avg_ppg/rpg/blk/apg/mpg`) and steals/turnovers.

The other 13 pruned features are genuinely neutral or harmful on this split
(`home_opp_ppg_l10`, `away_blk_l10`, `away_top5_avg_stl/rpg`, `home_reb_l10`, ...), so
the hand list was not wrong about everything; it was wrong about the biggest ones.

## Verdict

- Do **not** ship the current hand prune list for the spread model.
- Best accuracy: keep all 54 non-leakage features. The 36-feature data-driven prune is
  within 0.026 MAE and is the more parsimonious fallback.
- **Shipped 2026-11-20:** `model_spread.low_importance_cols` is now empty; the model was
  retrained on all 30,350 games with the fixed params (396 trees) and saved as version 6.
  Validation MAE 11.688, residual std 14.862. `tools/retrain_spread.py`.
- This is a model-accuracy result, not a betting result. A 0.1-point MAE gain is small
  next to the 3-point edge threshold; there is still no spread walk-forward against
  closing lines to say whether it changes ROI. Expect "slightly less wrong", not "edge".

## Caveats

- One chronological window (Feb 2024 to Nov 2026). Day-clustered CIs cover within-window
  correlation, not a different era.
- Parameters are fixed and shared; they were not tuned for either variant.
- The test window overlaps ManualBets' 2024-25 default-tuning season, but nothing here
  was tuned on it (the params are fixed a priori).
- Features are still the pre-2026-11-20 frame; C4 availability is not in it.

## Reproduce

```bash
cd ManualBets
uv run python tools/feature_ablation.py
```
