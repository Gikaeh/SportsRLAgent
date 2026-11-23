# Venue altitude in DS's college totals model (2026-11-22)

**Question.** The situational study (`2026-11-22-situational-factors.md`) found that games at venues
>= 1,200 m beat both models and the close. With a real venue table (elevation per arena), does adding
altitude to `ncaab-v1`'s total model improve the totals out of sample, and does it help et-v1-style bets?

**Answer. A little, and only for bets, not for MAE.** Altitude features cut the model's under-shoot at high
venues roughly in half (1,500 m+: actual - model +2.08 -> +1.34), but total MAE barely moves (-0.006 pts
overall, -0.05 at >= 1,200 m, CIs span 0, and 2021-22 gets worse). In the et-v1 cell the altitude
DS number wins a bit more often than the baseline in every season with openers (paired: +0.4 win pts,
+0.8% ROI, CI excludes 0 for 2 of 6 variants). The effect is small, comes from ~45 swapped bets a season,
and is one of 6 variants tried. **Recommendation:** ship variant `gd` as a watch-only shadow version,
`ncaab-v1.1alt`, beside `ncaab-v1`, under the pre-registration below (owner to approve). Nothing in
`ncaab-v1`, `models/ncaab_v1`, et-v1 or the live predict pipeline changes.

## Data and method
- Warehouse copy 2026-11-22 23:01 PT (only `deepsports serve` was running; no writer). Venues: `games.venue_id`
  -> `venues.elevation_m` / `tz` (branch `feature/college-venue-geo`, data already in the warehouse; 598 of
  599 venues have an elevation; the one gap, Venetian Arena, 4 games, is NaN). A team's home arena per season
  = venue of most of its non-neutral home games (the branch's `team_home_venues` logic, recomputed in
  `deepsports.analysis.altitude`); seasons without a home game use the nearest season. Schedules are published
  before the season, so every feature is known before tip-off.
- Features (`src/deepsports/analysis/altitude.py`, tests `tests/test_altitude.py`): `venue_elev_km`; band
  dummies 800-1200 / 1200-1500 / 1500+ m; each team's home elevation; `alt_gain_sum` (km climbed by teams
  playing above home); `alt_drop_sum` (km dropped by teams playing below home); `tz_cross_sum` (hours from home).
- Walk-forward: the 2026-11-20 rebuild's path (`ncaab_prior.build_arms`, frozen `ncaab_v1` + `ncaab_prior`
  configs, weekly folds, training on every earlier D1 game, 2021-12-01 -> 2026-05-01). Only the total model
  (players feature set, Ridge alpha 10, same imputer/scaler) is refit per variant. DS number as live: no-prior
  arm at rt_n >= 5, else the prior arm (`ncaab-v1-early`). The baseline reproduces the edge study's DS totals
  exactly (median |diff| 0.000).
- Post-hoc alternative: per-band offsets (band mean residual minus the < 800 m mean residual of the baseline),
  fitted only on earlier seasons, added to the baseline; optionally a "altitude school down" offset
  (`alt_drop_sum` >= 0.8 km at a < 800 m venue). 2021-22 has no earlier season, so no offset.
- Market: the edge study's `games.csv` (16,867 games with opener + close, 2023-24 -> 2025-26) with the DS number
  swapped per variant; MB unchanged. et-v1 cell = both edges > 0 on one side and average edge >= 4 vs the
  opener, graded at the opener's price; win % vs the close at -110; CLV = close - open toward the pick.
- CIs: day-clustered bootstrap (2,000 resamples), paired where variant vs base.
- **Variants tried: 6** (feature sets `elev`, `bands`, `gd` = elev + gain + drop, `gdtz` = gd + time zones;
  post-hoc `ph`, `ph_drop`), each scored on 4 MAE slices and 2 market sets. No other variant was run.
- Work folder: `/Volumes/ExFATStorag/DeepSports/work/altitude-2026-11-22/` (`wf.py`, `preds.json`,
  `evaluate.py`/`.out`, `paired.py`/`.out`).

## Total MAE, paired difference vs baseline (negative = better; 95% CI)
Games with a closing total. Base = today's DS live number.

| slice | season | n | close | base | elev | bands | gd | gdtz | ph |
|---|---|---|---|---|---|---|---|---|---|
| all games | 2021-22 | 4,325 | 12.84 | 13.093 | +0.006 | +0.022 (+0.003,+0.043) | +0.005 | +0.018 | 0 |
| | 2022-23 | 5,551 | 12.94 | 13.139 | -0.004 | -0.007 | -0.003 | -0.001 | +0.005 |
| | 2023-24 | 5,609 | 12.97 | 13.301 | -0.009 (-0.017,-0.001) | -0.006 | -0.006 | -0.005 | -0.005 |
| | 2024-25 | 5,642 | 12.65 | 13.045 | -0.001 | 0.000 | -0.007 | -0.010 | +0.001 |
| | 2025-26 | 5,616 | 13.36 | 13.740 | -0.014 (-0.025,-0.004) | -0.007 | -0.016 (-0.031,-0.002) | -0.014 | -0.005 |
| | all | 26,743 | 12.95 | 13.272 | -0.005 (-0.009,-0.001) | -0.001 | -0.006 (-0.014,+0.002) | -0.003 | -0.001 |
| venue >= 1200 m | 2021-22 | 198 | 14.14 | 14.566 | +0.14 | +0.34 (+0.03,+0.66) | +0.27 (-0.22,+0.78) | +0.28 | 0 |
| | 2022-23 | 250 | 13.65 | 13.728 | -0.12 (-0.21,-0.04) | -0.19 (-0.34,-0.06) | -0.12 (-0.28,+0.03) | -0.12 | +0.07 |
| | 2023-24 | 245 | 12.24 | 12.157 | -0.06 | -0.11 | -0.16 (-0.38,+0.07) | -0.16 | -0.10 |
| | 2024-25 | 247 | 11.06 | 11.130 | +0.04 | +0.06 | -0.01 (-0.18,+0.16) | -0.01 | +0.08 |
| | 2025-26 | 257 | 12.55 | 13.194 | -0.13 | -0.11 | -0.14 (-0.36,+0.08) | -0.13 | -0.12 |
| | all | 1,197 | 12.67 | 12.894 | -0.03 (-0.11,+0.04) | -0.02 (-0.11,+0.07) | -0.05 (-0.16,+0.07) | -0.04 | -0.02 |
| 800-1200 m | all | 532 | 12.33 | 12.687 | +0.05 | +0.07 | +0.09 (-0.02,+0.19) | +0.10 | -0.01 |
| altitude school at < 800 m | all | 1,131 | 13.02 | 13.582 | 0.00 | 0.00 | -0.10 (-0.20,+0.00) | -0.10 | 0 (`ph_drop` -0.11) |

Unlabeled CIs span 0 (full CIs in `evaluate.out`). Fitted shift of `gd` vs base, mean by season 2021-22 ->
2025-26: 1,500 m+ -1.15 / +0.31 / +1.28 / +1.34 / +1.58; 1,200-1,500 m -0.50 / +0.60 / +0.99 / +1.19 / +1.32;
altitude school at < 800 m -2.2 / -1.8 / -1.3 / -1.2 / -1.5. The coefficient is unstable in 2021-22 (one
month of training data) and stable from 2022-23 on.

### Bias: mean (actual - prediction), all seasons
| band | n | close | base | elev | bands | gd | gdtz | ph |
|---|---|---|---|---|---|---|---|---|
| < 800 m | 25,014 | +0.77 | +0.19 | +0.24 | +0.20 | +0.24 | +0.24 | +0.19 |
| 800-1200 m | 532 | +0.46 | -0.76 | -1.19 | +0.07 | -0.87 | -0.87 | +0.46 |
| 1200-1500 m | 621 | +1.64 | +1.24 | +0.55 | +1.08 | +0.46 | +0.45 | +0.93 |
| 1500 m+ | 576 | +2.97 | +2.08 | +1.19 | +1.06 | +1.34 | +1.35 | +1.10 |

## Market (2023-24 -> 2025-26, vs the opener at its price)
| variant | et-v1 cell n | win % (95% CI) | ROI (95% CI) | win % vs close | CLV | per season win % 23-24 / 24-25 / 25-26 | agree side n, win %, ROI |
|---|---|---|---|---|---|---|---|
| base | 4,304 | 53.5% (51.9,55.1) | +1.3% (-1.7,+4.2) | 50.5% | +1.15 | 52.6 / 51.2 / 56.2 | 12,271, 52.3%, -0.4% |
| elev | 4,307 | 53.8% | +1.8% | 50.7% | +1.14 | 52.9 / 51.7 / 56.3 | 12,285, 52.4%, -0.2% |
| bands | 4,318 | 53.6% | +1.6% | 50.7% | +1.14 | 52.8 / 51.5 / 56.3 | 12,248, 52.4%, -0.3% |
| **gd** | 4,309 | 53.9% (52.3,55.3) | +2.1% (-0.9,+4.8) | 50.8% | +1.14 | 53.2 / 51.9 / 56.3 | 12,247, 52.7%, +0.2% |
| gdtz | 4,323 | 54.1% (52.5,55.6) | +2.5% (-0.4,+5.3) | 51.0% | +1.14 | 53.2 / 52.1 / 56.8 | 12,257, 52.7%, +0.3% |
| ph | 4,309 | 53.6% | +1.5% | 50.6% | +1.15 | 52.8 / 51.5 / 56.1 | 12,240, 52.3%, -0.4% |
| ph_drop | 4,295 | 53.7% | +1.6% | 50.7% | +1.15 | 53.0 / 51.5 / 56.2 | 12,170, 52.4%, -0.4% |

**Paired vs base (et-v1 cell, day-clustered):**
| variant | 2023-26 d win % | 2023-26 d ROI | 2023-25 only d win % | 2023-25 only d ROI |
|---|---|---|---|---|
| elev | +0.30 (-0.01,+0.61) | +0.58 (-0.02,+1.16) | +0.45 (+0.05,+0.85) | +0.87 (+0.10,+1.62) |
| bands | +0.17 (-0.06,+0.40) | +0.33 (-0.11,+0.76) | +0.26 | +0.49 |
| **gd** | +0.41 (+0.02,+0.81) | +0.80 (+0.05,+1.54) | +0.66 (+0.19,+1.13) | +1.29 (+0.39,+2.16) |
| gdtz | +0.63 (+0.20,+1.05) | +1.22 (+0.39,+2.00) | +0.73 (+0.23,+1.22) | +1.41 (+0.47,+2.34) |
| ph | +0.10 | +0.19 | +0.25 (+0.01,+0.48) | +0.47 (+0.02,+0.91) |
| ph_drop | +0.18 | +0.34 | +0.35 (0.00,+0.69) | +0.65 (0.00,+1.30) |

Where the gain comes from: `gd` swaps 140 bets into the cell (62.1% win vs the opener, 67% overs) and 135 out
(49.3%) over three seasons. At venues >= 1,200 m the cell goes 57.0% (n = 180) -> 60.5% (n = 210, ROI +14.8%,
CI +0.5 to +28.5). The rest of the swaps are altitude schools' road games, where the feature lowers the total.

## Caveats
- MAE is the stated success bar from the situational study ("MAE gain at altitude venues with no loss elsewhere,
  in each season"). **No variant meets it**: 2021-22 is worse at altitude for all feature variants, 800-1200 m is
  slightly worse, and every altitude-venue CI spans 0. Altitude venues are 4.5% of games, and the shift (~1-1.5
  pts) is small next to a 13-pt MAE.
- The bet gain is small (+0.4 win pts) and rests on ~45 swapped bets a season. 6 variants were tried; with a
  Bonferroni-style correction for 6, `gdtz` survives, `gd` is borderline. I recommend `gd`, not the best scorer
  `gdtz`: time zones had no support in the situational study and add +0.2 win pts that are within noise.
- The altitude effect was found on the same seasons (situational study, 2021-26), so this test isn't fully
  independent of the discovery. The per-season consistency (gain in all three opener seasons) is the main
  reason to keep it.
- Openers have no timestamp, and 2025-26's openers moved most (see the 2026-11-20 doc); the paired difference
  holds in 2023-25 alone.
- 2026-27 (current season) was not scored; too few altitude games so far.

## Pre-registration proposal (for the owner to approve; nothing built yet)
- **Version `ncaab-v1.1alt` (watch-only, hidden like `ncaab-v1p`):** `ncaab-v1` exactly (frozen
  `models/ncaab_v1/config.json`, same gate: both teams D1, >= 5 games), except the **total** model adds
  `venue_elev_km`, `alt_gain_sum`, `alt_drop_sum` from `deepsports.analysis.altitude`. Win and margin
  unchanged. Config in a new `models/ncaab_v1_1alt/config.json` that points at v1's and lists the 3 features;
  frozen at creation. Predictions stored under its own version with its own graded record.
- **Shadow rule `et-v1-alt` (watch-only, logged beside et-v1, never replacing it):** et-v1's exact rule with
  the `ncaab-v1.1alt` total in place of `ncaab-v1`'s (MB, lines, prices, timing identical). Logged in the same
  21:00 run, its own rule version, so the two records are paired on the same nights.
- **Primary metric:** on the paired nights, the difference in units between `et-v1-alt` and `et-v1` (only the
  bets where they differ count). Secondary: mean (actual - model) at venues >= 1,200 m for `ncaab-v1.1alt` vs
  `ncaab-v1` (target: closer to 0), and total MAE on all graded games (must not be worse by > 0.02).
- **Verdict:** end of the 2026-27 regular season (about 250 altitude-venue games, ~45 differing bets), with
  no early stop. Pass = differing bets net >= 0 units and altitude bias smaller, with total MAE within 0.02.
  A pass makes `et-v1-alt` a candidate for et-v2, considered only after et-v1's 300-bet verdict. Expect a
  noisy answer: 45 bets can't confirm a +0.4-pt edge, only rule out a harmful one.
- If not approved: drop. The feature module and tests stay; nothing else changes.

## Next steps
1. Owner: approve or drop the pre-registration above.
2. If approved: merge `feature/college-venue-geo` (venue data and the home-venue view are only on that branch),
   then build `ncaab-v1.1alt` (predict path + hidden version) and the `et-v1-alt` shadow log (data-analyst +
   data-engineer), with tests.
3. Independent of this: the open->close drift in neutral / short-rest games (situational study) is a timing
   note, not part of this version.
