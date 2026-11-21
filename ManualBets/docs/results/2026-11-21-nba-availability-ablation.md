# NBA spread: core availability + current rotation (2026-11-21)

**Question.** Do the two new player lists improve the spread model on a chronological
holdout?

- **Core top 5** (season-to-date minutes per game played): availability features
  (`missed_last3/5`, `days_since`, `minutes/ppg lost`). An injured starter stays on
  this list, which is the point.
- **Current rotation** (last 5 team games, zero-filled for missed games): production
  features (`rot5_avg_*`, `rot5_minutes`, `rot5_games`). A replacement passes an
  injured starter after a few games.

**Answer.** Yes, mostly through availability. Same split, same fixed params, three seeds:

| variant | features | test MAE | resid std | within 5 | R² |
|---|---|---|---|---|---|
| baseline | 54 | 11.7174 | 14.9276 | 26.95% | 0.1588 |
| + rotation | 72 | 11.6659 | 14.8824 | 27.50% | 0.1645 |
| + availability | 68 | 11.5492 | 14.7545 | 28.09% | 0.1788 |
| **+ both** | **86** | **11.5418** | **14.7487** | **28.33%** | **0.1795** |

Paired, day-clustered delta for **baseline − both: +0.1976 MAE [0.1209, 0.2756]**
(positive = both better; 10,000 resamples). The interval excludes zero.

Reading:
- **Availability is the driver** (−0.168 MAE alone).
- **Rotation adds a small amount** (−0.052 alone).
- Both together is best, but only 0.0074 MAE better than availability-only, which is
  inside the noise. The rotation list is a sensible small addition, not the main signal.

## Method

- Deleted `data/training_data/basketball` and rebuilt it with the retrainer's own
  `prepareAllSeasons` (no append script). Result: 30,439 games × 96 columns.
- The live upcoming frame has 86 features; every one is present in the rebuilt frame.
- Chronological split: 80% train, 10% validation, 10% test (roughly Feb 2024 to
  Nov 2026). The test slice is never used for fitting or feature selection.
- `XGBRegressor(objective='reg:absoluteerror')`, fixed params (lr 0.03, depth 6,
  min_child_weight 5, subsample 0.8, colsample 0.8, 2,000 trees, early stop 100).
  Parameters were not tuned per variant.
- Seeds 0, 1, 2; metrics are the mean.

## Ship

Spread model **version 7**: 86 features, 478 trees, training on all 30,439 games.

- Validation MAE **11.4865**, residual std **14.6982** (now the recommender's sigma).
- Old v6 model backed up to `%TEMP%\basketball_spread_model.before-2026-11-21.json`.
- h2h and total models unchanged (h2h paused, total disabled).

## Caveats

- One chronological window; the day-clustered CI covers within-window correlation, not a
  different era.
- MAE is not ROI. There is still no spread walk-forward against closing lines.
- The current game's injury report is **not** in these features yet. At prediction time
  the plan is to map `OUT/DOUBTFUL/QUESTIONABLE/PROBABLE` to an expected participation
  probability and adjust `core_minutes_lost` / `core_ppg_lost`; the model learned the
  effect of lost minutes from historical participation.
- The 26-game roster/tenure edge cases (A8 trades) are filtered by "latest team", but
  two-way and G-League assignments remain approximate.
