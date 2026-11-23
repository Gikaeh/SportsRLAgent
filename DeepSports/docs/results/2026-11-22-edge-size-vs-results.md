# Edge size vs results for et-v1 night-before totals (2026-11-22)

**Question (owner).** The day's biggest-edge picks don't seem to do best; wins are spread through
the list. Why? Would a different ranking work better?

**Answer.** Edge size tells you almost nothing about which et-v1 pick wins. Across three
out-of-sample seasons, each extra point of average edge adds about +0.7 points of win % at the
opener (95% CI about 0 to +1.4), and about 0 at the close. In 2025-26, the season the rule was
built on, the slope is flat (-0.2 points per point of edge), and the day's top 5 picks won *less*
than the rest (55.4% vs 58.0%). With 5-10 picks a night, that slope can't show up in a daily list:
even a 3-point win % gap would take thousands of bets to see. No other ranking we tried did better
out of sample. Treat qualifying picks as equals.

## Data and method
- Work folder `/Volumes/ExFATStorag/DeepSports/work/factors-2026-11-22/edge/` (`build.py`, `lib.py`,
  `q1_buckets.py` .. `q4_early.py`, `live.py`, and an `.out` file for each).
- History: the 2026-11-20 walk-forward predictions (DS live-style choice, MB monthly refits), all
  out of sample, plus opening and closing totals from that day's warehouse copy (read-only). Seasons
  with openers: 2023-24 (5,609 games), 2024-25 (5,642) and 2025-26 (5,616). The et-v1 cell (both
  edges > 0, average >= 4 vs the opener) has 1,350, 1,386 and 1,589 bets. The 2025-26 cell
  reproduces the study's 57.0%.
- The pick is chosen against the opener. "Win % open" grades it at the opener, "win % close" grades
  the same side at the closing total, and CLV = (close - open) from the pick's side. The ROI uses
  the real opening price. CIs are 95% bootstraps that resample whole game days.
- Rankings were compared on forward splits only: train on 2023-24 and test on 2024-25, then train on
  2023-24 + 2024-25 and test on 2025-26. The set of bets stays fixed; only the order changes.
- Live data: 73 graded et-v1 bets (Nov 17-22, from `early-totals grade`) and the owner's
  night-before rows in `logs/` (results only).

## Key table: et-v1 cell by average edge, three seasons pooled
| avg edge | n | win % open (CI) | win % close (CI) | CLV pts (CI) | ROI at open |
|---|---|---|---|---|---|
| agree 0-2 (no bet) | 3,242 | 50.2% (48.4-52.0) | 49.9% | +0.19 | -4.2% |
| agree 2-4 (no bet) | 4,734 | 52.2% (50.7-53.6) | 50.7% | +0.52 | -0.4% |
| 4-5 | 1,574 | 52.5% (50.0-55.2) | 50.4% (47.9-53.0) | +0.79 (+0.67 to +0.91) | -0.0% |
| 5-6 | 1,059 | 52.8% (49.7-55.9) | 49.9% (46.9-53.1) | +0.97 (+0.82 to +1.14) | +0.4% |
| 6-8 | 1,085 | 54.3% (51.3-57.4) | 50.4% (47.4-53.4) | +1.29 (+1.11 to +1.46) | +2.9% |
| 8-10 | 378 | 56.2% (51.1-61.9) | 51.6% (46.2-56.9) | +1.64 (+1.30 to +1.96) | +5.6% |
| 10+ | 229 | 60.3% (54.5-66.1) | 54.1% (48.2-60.2) | +3.06 (+2.36 to +3.73) | +10.3% |
| all et-v1 | 4,325 | 53.8% (52.3-55.3) | 50.6% (49.1-52.1) | +1.15 (+1.04 to +1.27) | +1.8% |

By season, win % at the opener for the 4-5 / 5-6 / 6-8 / 8-10 / 10+ buckets:

| season | 4-5 | 5-6 | 6-8 | 8-10 | 10+ |
|---|---|---|---|---|---|
| 2023-24 | 51.1% (500) | 51.5% (344) | 53.6% (334) | 55.4% (122) | 62.0% (50) |
| 2024-25 | 48.4% (517) | 50.3% (354) | 52.6% (329) | 56.0% (109) | 61.0% (77) |
| 2025-26 | 57.6% (557) | 56.5% (361) | 56.2% (422) | 57.1% (147) | 58.8% (102) |

Logistic slope of win at the opener on average edge, within the cell (per point of edge, with
the approximate change in win %): 2023-24 +0.043 (CI -0.019 to +0.100, about +1.1 points of win %);
2024-25 +0.062 (+0.014 to +0.116, about +1.5); 2025-26 -0.007 (-0.048 to +0.035, about -0.2);
pooled +0.028 (-0.002 to +0.054, about +0.7). At the close, every season's slope is 0.00 to +0.02,
and every CI spans 0.

## Findings
1. **The edge-to-win slope is small next to the noise (high confidence).** A total lands about 17
   points from the opener (SD), so a 4.5-point pick and a 9-point pick differ by about 3 points of
   win % at best, and by 0 in 2025-26. In a list of 5-10 picks a night, that difference is
   invisible. The owner's impression that wins are spread evenly through the list is what the data
   predicts.
2. **The market takes most of a big edge (high confidence).** CLV rises by about 0.25 points per
   point of edge (CI +0.17 to +0.33, positive in all three seasons), and 72% of 10+ picks move the
   pick's way. Measured from the opener, the pick side gains only about 0.25 points of result per
   point of edge (CI +0.02 to +0.47). Measured from the close, it gains 0.00 (CI -0.23 to +0.21). So a
   "10-point edge" holds about 2.5 points of real value, mostly gone by the close. The models
   overstate big edges about four times.
3. **Big edges count only early in the season (medium-low confidence, found after the fact).**
   With fewer than 10 games played, win % at the opener rises with edge: 4-6 51.4%, 6-8 56.1%, 8-10
   60.8%, 10+ 63.5% (n = 838 / 412 / 181 / 156). The 8+ group won 64%, 63% and 60% in the three
   seasons. From 10 games on, the slope is flat at the opener (-0.005) and *negative* at the close
   (-0.056, CI -0.098 to -0.008). Edges of 8+ from 10 games on won 52.4% at the opener and 45.9% at
   the close. For those games the closing line beats both models (MAE 13.1 vs DS 14.7 and MB 15.4),
   so late big edges are mostly model error. Early on, the opener is the stale number. This came
   out of about 40 cuts, and a score fitted on 2023-24 with a games-played term did *not* order
   2024-25 better, so it is a hypothesis, not a rule.
4. **Disagreement, min edge, line level and side don't matter (medium confidence).**
   - DS/MB gap terciles: 54.7%, 53.0% and 53.5%.
   - One model alone (smaller edge under a quarter of the larger): 54.0%, with the sign flipping by
     season (45%, 61%, 56%).
   - Minimum edge under 2 vs 6+: 53.6% vs 55.6%.
   - Opening total under 135 vs 155+: 54.9% vs 54.0%.
   - Over vs under: 54.4% vs 52.7%.
   No gap is consistent across seasons, or larger than its CI.
5. **What actually decides a pick is the line move after 21:00, which isn't known when the bet is
   made (diagnostic only).** Picks whose line moved 1+ points against them won 45.6% at the opener
   (n = 997). Picks that moved 3+ points their way won 62.3% (n = 1,108). This holds at every edge
   size. The outcome tracks whether later information (injuries, lineups, sharp money) agreed with
   the models, and the edge size at 21:00 doesn't predict that.

## Rankings (the same bets, reordered; forward test)
| score | AUC, test 2024-25 | top 5 per day vs rest, 2024-25 | AUC, test 2025-26 | top 5 per day vs rest, 2025-26 |
|---|---|---|---|---|
| average edge (current) | 0.529 | 53.2% vs 49.6% | 0.497 | 55.4% vs 58.0% |
| min edge (agreement-weighted) | 0.520 | 53.5% vs 49.4% | 0.498 | 55.4% vs 58.0% |
| geometric mean | 0.522 | 53.5% vs 49.4% | 0.503 | 55.0% vs 58.3% |
| shrunk to market (fit: points beaten at the opener ~ DS + MB edge) | 0.524 | 53.2% vs 49.6% | 0.496 | 55.9% vs 57.7% |
| shrunk + games-played interaction | 0.509 | 52.0% vs 50.5% | 0.499 | 55.3% vs 58.1% |
| early-season first | 0.515 | 53.2% vs 49.6% | 0.500 | 55.6% vs 57.9% |
| inverted average (check) | 0.471 | 52.0% vs 50.5% | 0.503 | 57.8% vs 56.6% |

**None held.** No score beats the current average out of sample. Every AUC is between 0.47 and
0.54, so the ordering barely beats a coin flip. The top-5-per-day CIs are about ±4 points. The
cell averages 10 bets a day (median 8), so a 5-a-day cap picks a near-random subset either way.

## Live 2026-27 (73 graded bets over 6 days; describe, don't conclude)
- By average edge: 4-5 went 10-7, 5-6 11-10, 6-8 12-10 and 8+ 7-5. Each CI is about ±22 points. The
  slope is +0.05 per point (CI -0.22 to +0.38).
- Within-day rank: the top 5 went 16-12 (57%) and ranks 6+ went 24-20 (55%).
- DS/MB gap under 3 went 28-15 and gap 3+ went 12-17. History shows about a 1-point difference here,
  so this is most likely noise. Recheck at 300 bets.
- The owner's night-before rows (W/L only): William Hill 4-6 edge 14-10, 6+ 20-10; Circa 4-6 4-4,
  6+ 0-5. This repeats the 2026-11-19 book split (Circa lines are the issue), not an edge-size
  effect.

## Multiple comparisons
I tried 9 bucket rows × 5 views, 8 slope fits × 4 views, 41 within-cell cuts, 10 ranking scores × 2
forward tests and 8 early/late buckets: roughly 120 looks. Findings 1, 2 and the "none held" result
hold in every season. Finding 3 is the only subgroup that is consistent in all three seasons, but it
was chosen after looking at them all, so it needs forward data. Live 2026-27 bets are all early
season (rt_n < 10) and are too few to say.

## Recommendation
- Keep et-v1 as pre-registered (no rule change; verdict at 300). Don't size or select by edge
  rank, and don't read a bad night for the top picks as a signal.
- When the 5-bet cap binds, choose by the line instead of the edge: picks that qualify at William
  Hill, at the best number, and avoid Circa-only qualifiers.
- Candidates for a separate pre-registered watch-only test (each a new version, the owner's call,
  not now):
  - (a) Early-season big edges (avg >= 8, fewer than 10 games played), checked on 2026-27 through
    December.
  - (b) A day-of recheck: skip or flag a pick whose William Hill line has moved 1+ points against
    it by the morning grab. This would need the day-of captures, which `clv_dayof` already reads.
