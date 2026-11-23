# Predicting the line move for et-v1 picks, and why live CLV is ~0 (2026-11-22)

**Questions (owner).** (1) With what we know at bet time (~18:00-21:00 PT the night before), can we predict
whether a college total will move toward an et-v1 pick, and is that a useful extra filter or ranking?
(2) Why does the live sample show ~0 CLV when the backtest shows +1.15 pts?

**Answers.**
1. **The move is partly predictable, but the predictable part doesn't pick winners.** Out of sample, the best model
   (gradient boosting on both model edges, line level, spread, early-season and schedule terms) explains about 9% of
   the open->close move on all games (corr +0.30 in both test seasons). Almost all of that comes from the model edges
   themselves: the market moves toward DS and MB by about 0.15-0.2 pts per point of edge. Adding situational terms
   adds nothing out of sample. Inside the et-v1 cell, predicted CLV doesn't order wins (AUC 0.51-0.53), and no
   pre-registered-style cut improved held-out win % by more than its noise. One GBM filter looks promising on the
   pooled held-out seasons, but it was the best of about 60 looks and can't count as found (details below).
2. **Live, it isn't timing and it isn't the book.** The ESPN opener is already up by the afternoon before
   (it equals the first DraftKings capture, at a median 16:12 PT on D-1, for 91% of games). The owner's
   evening number is, if anything, 0.2-0.3 pts *better* than the opener for our picks. WH, Caesars and DraftKings
   agree within about 0.25 pts at the same moment. The difference is that this season's market hasn't moved toward
   the models after the opener: et-v1 picks went opener->close **-0.32** (n = 73, CI -0.58 to +0.05). The backtest
   gives **+1.27** (+1.00 to +1.56) for the same calendar window (Nov 15-25). That gap is about 4 standard errors,
   so it's more than small-n noise. The backtest does have one very-early-season year that looked similar, though.

## Data and method
- Work folder `/Volumes/ExFATStorag/DeepSports/work/factors-2026-11-22/linemove/`: `build.py` (table),
  `predict.py`, `gbm_check.py`, `gbm_who.py`, `compare.py` (backtest), `extract_live.py`, `live.py`, `live2.py` (live).
  Each script has an `.out` file next to it.
- Backtest: the edge study's `games.csv` (DS + MB walk-forward totals, ESPN open and close, 2023-24 → 2025-26, 16,867
  games, et-v1 cell 4,325), joined to the situational rows and the opening spread (warehouse copy from 2026-11-20, read-only).
  Target: the raw move close - open. Pick-side CLV = side × move.
- Splits by season only: train 2023-24 → test 2024-25, then train 2023-24 + 2024-25 → test 2025-26. Fits use all games
  in the training seasons. Filter thresholds come from the training cell.
- Live (2026-11-15 → 23, read-only): 301 games found in the WH screenshot or Caesars 21:00 files, with ESPN opener,
  DraftKings pregame captures (ESPN, every ~30 min from about 16:00 PT on D-1), WH screenshot (`read_at` 18:00-20:45),
  Circa screenshot, Caesars feed (21:00) and ESPN close (DraftKings). The 97 logged et-v1 bets include 73 with a close
  and 72 graded (40-32). CIs on live bets are day-clustered bootstraps over only 6 days. Treat them as rough.

## Q1: predicting the move (out of sample)
| predictors | all games R², test 24-25 / 25-26 | corr | et-v1 cell corr with CLV | AUC for a win in the cell |
|---|---|---|---|---|
| average edge only | 0.077 / 0.092 | +0.28 / +0.32 | +0.25 / +0.09 | 0.508 / 0.497 |
| DS + MB edges | 0.076 / 0.093 | +0.28 / +0.32 | +0.24 / +0.09 | 0.509 / 0.498 |
| + early-season interactions | 0.076 / 0.081 | +0.28 / +0.29 | +0.25 / +0.02 | 0.510 / 0.494 |
| full linear (+ line level, spread, neutral, event game, rest <= 1, 3-in-7, altitude, altitude school on road, Feast Week) | 0.075 / 0.099 | +0.28 / +0.32 | +0.24 / +0.13 | 0.520 / 0.504 |
| gradient boosting, same inputs | **0.091 / 0.091** | **+0.30 / +0.30** | +0.28 / +0.14 | 0.530 / 0.512 |

- The market follows MB more than DS. With both edges in the fit, the slopes are about +0.14 for MB and +0.05 for DS per point.
  Short rest (-0.45 to -0.64 pts) and 3rd+ event games (-0.5 to -1.0) predict a drop in the total, as in the situational study.
- Inside the cell the target barely varies in a way we can predict: R² of pick-side CLV is 0.00-0.08.
- Diagnostic: the *realized* move still decides the outcome. Picks that moved 1+ against won 45.6% (n = 997); picks that
  moved 3+ toward won 62.3% (n = 1,108). The part we can predict is just the models' own edge, and the edge study
  already showed that doesn't rank winners.

**Filters and rankings on the held-out cell** (win % at the opener; cell baseline 51.2% in 2024-25, 57.0% in 2025-26):
| rule (threshold fixed from training) | 2024-25 keep / drop (n drop) | 2025-26 keep / drop (n drop) |
|---|---|---|
| drop predicted CLV <= 0 (linear) | 51.2 / 45.5% (22) | 57.0 / 62.5% (8) |
| drop bottom 25% predicted CLV (linear) | 51.4 / 50.0% (274) | 57.2 / 56.5% (331) |
| drop bottom 25% (DS+MB+early) | 51.8 / 49.0% (310) | 56.6 / 58.7% (317) |
| drop bottom 25% (GBM) | 52.2 / 47.9% (336) | 58.1 / 53.4% (371) |
| for comparison: drop bottom 25% of average edge | 52.4 / 47.4% (348) | 56.7 / 58.0% (355) |
| rank by average edge + 2 or 4 × predicted CLV (AUC) | 0.526-0.538 vs average edge 0.529 | 0.499-0.506 vs 0.497 |

- The GBM's bottom-25% filter is the only one with the same sign in both test seasons. Pooled: keep 55.4% vs drop
  50.8%, a gap of +4.6 points (CI +0.8 to +8.7), and ROI on kept bets +4.5% vs +2.6% for all. Across 6 hyperparameter
  settings the pooled gap was +2.6 to +6.3 points, and two of the six CIs include 0. Each season's CI spans 0 in most
  settings. The dropped picks have smaller edges (MB 5.5 vs 7.2) and higher totals (150 vs 146). Picks the GBM drops
  but the plain smallest-edge cut keeps won 45.5% (n = 200) and 52.0% (n = 221).
- **Verdict:** no filter has been shown to work. The GBM cut is a hypothesis: it was the best of 12 filter cells, and its
  settings were chosen after looking. Count of looks: about 60 in the backtest (5 fits × 2 seasons, 8 tercile tables,
  12 filter cells, 12 combined-score AUCs, 6 robustness runs, about 10 proxy cuts) and about 30 descriptive live splits.

## Q2: live vs backtest CLV
**When is the opener posted?** ESPN's opening odds have no posting time. `captured_at` is set to the tip time,
and the cached `core_odds` responses only carry open, current and close values, with no dates. The provider was
DraftKings in 2023-24, ESPN BET in 2024-25, DraftKings in 2025-26 and 2026-27. Live, the opener equals our *first*
DraftKings pregame capture in 91% of games (mean difference +0.02, n = 204) and some capture in 97%. The first capture is
at a median 22.5 h before tip (PT hour p10/median/p90 13.8 / 16.2 / 19.8). So the opener is posted the afternoon before
or earlier. By the time of the WH screenshot, DraftKings has moved from it by a mean of -0.09 pts (mean |move| 0.70; 56%
unchanged), and by 21:00 by -0.23 (|move| 0.95).

**Book differences at the same time (all games):**
| comparison | n | mean | mean abs | identical |
|---|---|---|---|---|
| WH screenshot - DraftKings at screenshot time | 223 | -0.07 (±0.07) | 0.28 | 65% |
| Caesars 21:00 feed - DraftKings at 21:00 | 273 | -0.02 (±0.05) | 0.23 | 67% |
| Caesars 21:00 - WH screenshot | 199 | -0.05 (±0.11) | 0.45 | 55% |
| Circa - WH screenshot | 121 | -0.03 (±0.13) | 0.50 | 43% |
| Caesars 21:00 - ESPN opener | 228 | -0.26 (±0.19) | 0.97 | 33% |

**Where the et-v1 picks' line went** (pick side, + = toward the pick; 6-day clustered CI):
| segment | n | mean pts | with / against |
|---|---|---|---|
| ESPN opener -> DraftKings at screenshot time | 68 | -0.26 (-0.59, +0.08) | 11 / 21 |
| bet line better than the opener by | 73 | +0.23 (-0.11, +0.49) | |
| bet line -> close (live CLV) | 73 | -0.09 (-0.26, +0.12) | 32 / 30 |
| Caesars 21:00 -> close | 66 | +0.00 (-0.20, +0.22) | 30 / 29 |
| **ESPN opener -> close (the backtest's measure)** | 73 | **-0.32 (-0.58, +0.05)** | 33 / 31 |
| same, only the 62 bets that also qualify vs the opener | 62 | +0.11 (-0.15, +0.47) | |
| backtest et-v1, Nov 15-25 of 3 seasons | 545 | **+1.27 (+1.00, +1.56)** | |
| backtest et-v1 by season, rt_n < 4 | 147 / 201 / 294 | +1.25 / +1.88 / +0.56 | |

**Do lines move toward the models at all this season?** Across all live games, the slope of (close - open) on (DS - open)
is +0.07 (±0.09, n = 246). After the screenshot it's +0.03 (±0.08), and after 21:00 it's -0.02 (±0.07). The backtest gives
+0.14 to +0.20 for whole seasons and +0.17 to +0.21 for Nov 15-25. The exception is 2025-26 with rt_n < 4: +0.06 (±0.05),
which looks like today. Caveat: 268 of 297 live DS rows were refreshed after the screenshot. Logged bets carry their
pre-bet totals.

**What explains the gap?**
- **Timing: no.** The opener comes before the bet, but by bet time only about 0.1-0.3 pts of movement is gone, and it went
  *against* our picks. So the evening number is slightly better than the opener.
- **Book or provider: no.** Same-time differences average under 0.1 pts. Backtest CLV is similar under DraftKings
  and ESPN BET openers (+1.02, +1.01, +1.39 by season).
- **The market isn't following the models yet this season (main reason).** This holds for all games, not only the picks.
  Possible reasons: early season (one backtest year looked the same for rt_n < 4), live model versions
  (`ncaab-v1-early`, MB gated) vs the walk-forward fits, or a real change. The gap is about 4 SE on independent bets.
  With 6 days of clustering, "noise" can't be ruled out completely.
- **A small backtest-only edge:** the walk-forward models know D-1 evening results that a 21:00 bettor doesn't. In
  rest <= 1 games, et-v1 backtest CLV is +1.25 / +1.56 / +2.67, vs +1.00 / +0.96 / +1.29 otherwise. That's about 8% of
  bets, worth about 0.1 pts of the +1.15.

**Live-only pre-bet signals (describe only, small n):**
- Momentum: the opener -> screenshot move correlates with the screenshot -> close move (r = +0.19, CI +0.06 to +0.32, n = 204).
  The opener -> 21:00 move correlates with 21:00 -> close (r = +0.27, CI +0.15 to +0.38, n = 249). Among picks where the line
  had already moved toward the pick by screenshot time: 8-3, +1.73 to close (n = 11). Where it had moved away (we got a
  better number): 7-13, -0.79 (n = 21).
- Circa vs WH: where Circa's number was *better* for our side than WH's (Circa had moved off our side), the picks went
  1-9 with -2.70 to close (n = 12). Where both books matched: 12-4. This fits the 2026-11-19 book split. Circa may lead.
- WH screenshot vs DraftKings at the same time: no relation to the later move (r = +0.04).

## Caveats
- No intermediate historical lines exist, so the backtest can't test momentum or book disagreement. Those signals rest on
  6 days.
- The backtest picks against the ESPN opener and the live rule picks against the WH line. In 11 of 73 live bets the two
  disagree.
- The live close is DraftKings via ESPN, the same as 2025-26's backtest close.

## What only the Odds API month can answer
- The backtest CLV measured from the **21:00 night-before line** (not the opener) across 2022-26. This directly tests whether
  the +1.15 survives at bet time. Live data say the opener and the 21:00 line are close (mean -0.26, |0.97|), so expect
  most of it to survive *if* the market keeps following the models.
- **Momentum** (opener -> 21:00 move predicting 21:00 -> close) and **sharp-book disagreement** (Pinnacle vs US books at 21:00)
  as pre-bet filters, on thousands of games instead of 70. These are the only pre-bet move predictors that look alive, and
  only the timestamped history can test them.
- It can't say why 2026-27 behaves differently. Only more live weeks can.

## Suggested next steps
1. Keep et-v1 unchanged (verdict at 300 bets). Don't add a predicted-move filter.
2. Add a column to the live log: the DraftKings line at screenshot time and the opener -> screenshot move. Recheck the
   momentum and Circa-vs-WH splits at about 150 bets. This needs a code change by its owner. The data are already in
   `odds_snapshots` (pregame), so it can also be computed afterwards, as done here.
3. Recheck the all-games market-follow slope (close - open on model edge) weekly. If it is still about 0 by mid-December
   (rt_n >= 10), et-v1's premise (the market moves to the models) is in doubt for this season.
4. **Odds API month: worth buying for this.** Pull 21:00 PT and 09:00 PT snapshots with Pinnacle. It is the only way to
   (a) re-run et-v1 at the real bet-time line on past seasons and (b) test momentum and sharp-book filters out of sample.
   Pre-register both filters before pulling.
5. If the month confirms a filter, pre-register it as a new watch-only version (et-v2), not a change to et-v1.
