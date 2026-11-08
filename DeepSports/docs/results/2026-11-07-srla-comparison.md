# DeepSports vs SportsRLAgent: same-games NBA comparison (2026-11-07)

Watch-only analysis. No bets were placed or recommended. The plan was fixed before results were seen.
Files (predictions, joined table, forward freeze, scripts): `/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/`.

## Bottom line
- DeepSports v1.1 beats honest SportsRLAgent on win probability, margin and totals, every full season.
- SportsRLAgent's default features leak future games. Without the leak its Brier goes from .2095 to .2203.
- Neither system beats the closing line, and neither is profitable betting into it.
- A 50/50 blend is worse than v1.1 alone.

## Method
- **Games:** 3,328 NBA games (regular season, play-in, playoffs), 2023-24 to Nov 6 2026, predicted by both systems, with
  closing moneyline, spread and total. Joined on ET date and teams; 3,336 joined with 0 score mismatches. 6 Nov 7 games
  were dropped because the warehouse copy didn't have their results yet.
- **Walk-forward:** both refit monthly on earlier games only, with no tuning on the test window.
- **SportsRLAgent:** fresh in-memory models at default parameters, run two ways: as shipped (`srd`) and without the four
  rank features (`srn`). `srn` is the honest estimate.
- **DeepSports:** existing backtest. Per-game capture reproduced all 145 published values checked. Scrambling future scores
  changed no earlier feature or prediction, at 9 sampled cutoffs.
- **Benchmark:** closing lines from the warehouse, moneyline de-vigged proportionally. CIs: 2,000 bootstrap resamples over
  577 game days. The Odds API was not used.

## The SportsRLAgent leak
`prepare_data.py:68-69` averages `PTS_RANK` and `PLUS_MINUS_RANK` from the NBA team game log. Those ranks compare a game with
the team's other games that season **as of the fetch date**, so old values change as later games are played. For the same 347
team-games fetched Nov 3 and Nov 7, `PTS_RANK` changed in 203 rows and `PLUS_MINUS_RANK` in 224; `PTS` changed in 2 and
`PLUS_MINUS` in none (checked independently of the subagent). The ranks also don't carry over to live prediction: historical
`home_pts_rank_l10` averages about 45, against about 7 this season. On the Nov 8-10 slate, `srd`'s win probability and margin
pick different winners in 7 of 21 games (`srn`: 1 of 21).

## Results (n = 3,328; lower is better)
| Model | Brier | Log loss | Accuracy | Margin MAE | Total MAE | ECE |
|---|---|---|---|---|---|---|
| Closing line | **.1967** | **.5760** | **.695** | **10.86** | **14.19** | **.015** |
| DeepSports v1.1 | .2070 | .6009 | .676 | 11.28 | 14.89 | .021 |
| DeepSports v1.0 | .2075 | .6019 | .674 | 11.32 | 14.88 | .021 |
| SportsRLAgent as shipped (leak) | .2095 | .6074 | .672 | 11.45 | 15.23 | .028 |
| 50/50 blend (v1.1 + no-rank) | .2095 | .6070 | .667 | 11.47 | 14.92 | .041 |
| SportsRLAgent no-rank (honest) | .2203 | .6307 | .645 | 11.92 | 15.22 | .033 |

Paired differences, 95% CI (negative = first is better):
| Pair | Brier | Margin MAE | Total MAE |
|---|---|---|---|
| v1.1 vs no-rank | -.0133 [-.0174, -.0093] | -.64 [-.77, -.49] | -.33 [-.48, -.17] |
| v1.1 vs as shipped | -.0025 [-.0066, +.0016] | -.17 [-.32, -.03] | -.34 [-.52, -.17] |
| v1.1 vs closing | +.0103 [+.0074, +.0132] | +.42 [+.30, +.54] | +.70 [+.52, +.89] |
| no-rank vs closing | +.0235 [+.0184, +.0283] | +1.05 [+.87, +1.24] | +1.03 [+.81, +1.27] |
| blend vs v1.1 | +.0025 [+.0006, +.0044] | +.19 [+.12, +.26] | +.03 [-.05, +.12] |

Brier by season (v1.1 / no-rank): 2023-24 .2101 / .2255; 2024-25 .2082 / .2225; 2025-26 .2039 / .2139; 2026-27 (40 games)
.1883 / .2205. As-shipped was worst in 2026-27 at .2526, a small sample.

## Betting check: flat 1 unit at closing price, every game (break-even at -110 is 52.4%)
| Model | ATS win % | ATS ROI [95% CI] | O/U win % | O/U ROI [95% CI] |
|---|---|---|---|---|
| v1.1 | 49.2 | -6.2% [-9.5, -2.8] | 50.3 | -4.0% [-7.2, -0.8] |
| v1.0 | 48.5 | -7.6% [-10.8, -4.2] | 50.5 | -3.6% [-6.9, -0.4] |
| no-rank | 48.8 | -6.9% [-10.2, -3.5] | 50.2 | -4.1% [-7.3, -0.8] |
| as shipped (leak) | 51.3 | -2.2% [-5.4, +1.1] | 50.2 | -4.3% [-7.5, -1.1] |
| blend | 48.1 | -8.2% [-11.4, -5.0] | 49.9 | -4.8% [-8.2, -1.5] |

Even with look-ahead, the as-shipped spread picks stay below break-even.

## Do the systems agree?
- **Winner:** they pick the same team in 79% of games, and that team wins 70.2% (closing favorite 71.7%). In the 692 games
  where they differ, v1.1's pick wins 57.4%, no-rank's 42.6%, the closing favorite 61.3%.
- **Agreement doesn't help against the spread:** v1.1 wins 48.7% when both take the same side (n = 2,442) and 50.9% when they
  differ (n = 877). Neither reaches break-even.
- **Correlation with the closing win probability:** v1.1 .895, no-rank .694. v1.1 mostly tracks the market, and no-rank's extra
  independence comes with worse accuracy.

## Limits
- SportsRLAgent ran at default parameters, while its saved models were tuned. Tuned as-shipped metadata (Brier .2125, margin MAE
  11.50, on a different test window) is close to the as-shipped default run, so tuning probably isn't the gap, but tuned no-rank
  wasn't tested.
- Older seasons can't be rebuilt without their raw files, so only the rank columns could be removed. Other issues remain:
  preseason rows in rolling windows and 194 noisy `point_diff` targets.
- SportsRLAgent has no prediction for each team's first 10 games, so early-season games are excluded for both.
- Closing lines mix books over time (DraftKings, ESPN BET), and fetched closing rows can't be independently checked before Nov 3 2026.
- Neither model reads injury reports. v1.1 infers availability from earlier box scores.

## Forward test (ungraded)
`forward_freeze.csv` holds 21 games on Nov 8-10 from both systems. SportsRLAgent saw results through Nov 7. DeepSports predictions
were created Nov 7 22:01 UTC and don't include Nov 7 games. They differ on the winner in 4 games, all Nov 10: BOS@PHI, LAC@PHX,
MIA@UTAH and OKC@POR. 21 games is far too few to change these conclusions.

## SportsRLAgent production status
Saved spread and total models fail with `feature_names mismatch`; saved h2h runs, but includes the rank features. Retraining alone
would keep the leak.
