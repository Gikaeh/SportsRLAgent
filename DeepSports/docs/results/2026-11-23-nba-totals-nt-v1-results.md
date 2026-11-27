# nt-v1 results: NBA v1.1 totals at William Hill's night-before line (2026-11-23): FAIL

Scored exactly as pre-registered (`2026-11-23-nba-totals-preregistration.md`, commits f8ce5bc + 6bda7aa, before the
pull). Scripts, `choices.json` (coverage and fallbacks, written before outcomes were loaded) and every number:
`/Volumes/ExFATStorag/DeepSports/work/nba-totals-prereg-2026-11-23/scoring/`. Predictions hash verified.

**Data:** 1,904 of 1,908 snapshots usable (4 returned > 30 min early); event match 99.6 / 99.5 / 99.9%. WH coverage
at -1@21:00 among predicted games: 78.9 / 86.1 / 95.3%, so every season is graded at WH -1@21:00 (no fallback used).

| Season | n | W-L-P | Win % | ROI [95% CI, game days] |
|---|---|---|---|---|
| 2023-24 | 489 | 245-239-5 | 50.6 | -3.3% [-11.8, +5.3] |
| 2024-25 | 508 | 260-243-5 | 51.7 | -1.3% [-10.7, +8.0] |
| 2025-26 | 508 | 250-257-1 | 49.3 | -5.8% [-14.0, +2.3] |
| **Pooled** | **1,505** | **755-739-11** | **50.5** | **-3.45% [-8.50, +1.54]** |

**Verdict: FAIL** (needed pooled ROI > 0 with CI lower bound > 0 and ROI > 0 in 2 of 3 seasons; got 0 of 3). Per the
pre-registration, NBA night-before totals are dropped, with no re-test on these seasons.

Descriptive only: same bets at the ESPN close 49.4% (-5.7%); overs -1.1%, unders -6.5%; edge >= 3 -2.9%, >= 5 -4.4%;
Pinnacle -3.3%, DraftKings -2.7%; WH at 0@09:00 -6.7%, at 0@15:00 -6.5%. The close moved toward the pick by +0.55
pts on average (52% of bets beat the close), yet the bets lose at both lines: the same pattern as college et-v1. The
53.6% against ESPN's opener (unknown posting time) does not exist at a line that can be bet the night before.

Resolved before grading (in `choices.json`): coverage denominator = all games with a prediction; season types 2 and
3 (play-in excluded); game day = Eastern date of tip; a WH line = pre-game, both sides at one point, 150-320, exact
team names (alias LA Clippers), start within 3 hours.
