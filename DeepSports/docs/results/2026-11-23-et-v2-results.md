# et-v2 phase 2: scoring the 9 pre-registered candidates at the 21:00 WH line

Written 2026-11-23. Scored exactly as pre-registered (`2026-11-23-et-v2-preregistration.md`, commit `3970720`)
with its **Amendment 1** (commit `0458f6b`, written and committed before any outcome was loaded). Watch-only
research. Nothing here changes et-v1 or its live test.

## Verdict: none pass
**No candidate passes, so there is no et-v2 from this data.** Per the pre-registered outcome statement, et-v1
continues as pre-registered toward its 300-bet verdict.
- **Season test:** every rule fails it. Each has a losing graded season with >= 100 bets, or fewer than 3
  seasons with >= 100 bets.
- **Holm:** no pooled win % beats break-even after correction. The smallest one-sided p is 0.165 (C2); Holm's
  first threshold is 0.05 / 9 = 0.0056.
- **C0 itself fails** (et-v1's cell re-scored at the bet line): pooled ROI is -3.9% (95% CI -7.2% to -0.7%)
  over 3,470 bets at the 21:00 `williamhill_us` line and price. Its win % is 50.3% against a 52.4%
  break-even. Only 2022-23 is barely positive (+0.6%).
- **2025-26**, the season et-v1 was tuned on, loses at the bet line: -2.5%, 51.0%.

What et-v1's backtest edge was measured against was the ESPN opener. At the line actually available at 21:00
PT, the cell does not beat the vig in any of the four graded seasons by a margin the data can tell apart from
zero, and loses in three.

## Data and protocol (summary; full detail in the pre-registration + Amendment 1)
- **Graded seasons:** 2022-23 to 2025-26, all at `williamhill_us` at T = 21:00 PT on D-1. 2021-22 is dropped:
  on the pre-registered denominator WH covered 57.8% and DK 54.8% (Amendment 1, item 1).
- **Universe:** 26,762 D1 games with DS and MB numbers and a final score. Of those, 22,434 fall in the graded
  seasons, and WH quotes 16,293 at T.
- **Bets:** 1 unit at the side's own WH price. ROI CIs are day-clustered bootstrap (10,000 resamples,
  seed 0). p is one-sided: the share of resamples with win % <= break-even.
- **Win % at close:** the same side graded at the ESPN close at -110.
- **CLV:** the move toward the pick from L to the close, in points. CLV09 uses WH at 0@09:00 on D.
- **C5 fits** (b_DS, b_MB), from all earlier seasons' games with a WH line at T, including 2021-22
  (Amendment 1, item 2):

  | test season | b_DS | b_MB | fit set |
  |---|---|---|---|
  | 2022-23 | 0.120 | 0.085 | 2,503 games |
  | 2023-24 | 0.119 | 0.060 | 6,443 games |
  | 2024-25 | 0.107 | 0.049 | 11,242 games |
  | 2025-26 | 0.039 | 0.059 | 15,123 games |

## The 9 rules: pass test

| rule | bets / season (22-23, 23-24, 24-25, 25-26) | pooled n | pooled win % (BE 52.4%) | pooled ROI (95% CI) | ROI sign by season | p (one-sided) | Holm | season test | >= 150/season | PASS |
|---|---|---|---|---|---|---|---|---|---|---|
| C0 | 669, 1,069, 772, 960 | 3,470 | 50.3% | -3.9% (-7.2 to -0.7) | + - - - | 0.989 | no | fail | yes | **no** |
| C1 | 675, 1,083, 776, 945 | 3,479 | 50.8% | -2.9% (-6.3 to +0.5) | 0 - - - | 0.951 | no | fail | yes | **no** |
| C2 | 41, 59, 28, 98 | 226 | 55.6% | +6.1% (-6.1 to +17.8) | - + - + | 0.165 | no | fail (0 seasons >= 100) | no | **no** |
| C3 | 365, 501, 582, 637 | 2,085 | 50.1% | -4.2% (-8.3 to -0.0) | + - - - | 0.976 | no | fail | yes | **no** |
| C4 | 171, 488, 142, 288 | 1,089 | 52.7% | +0.6% (-5.2 to +6.4) | + - + - | 0.423 | no | fail | no (142) | **no** |
| C5 | 84, 85, 27, 11 | 207 | 47.3% | -9.5% (-23.2 to +3.9) | - - - + | 0.917 | no | fail (0 seasons >= 100) | no | **no** |
| C6 | 633, 1,007, 763, 898 | 3,301 | 50.2% | -4.0% (-7.4 to -0.7) | + - - - | 0.991 | no | fail | yes | **no** |
| K1 | 640, 1,022, 768, 887 | 3,317 | 50.8% | -2.9% (-6.3 to +0.4) | + - - + | 0.955 | no | fail | yes | **no** |
| K2 | 97, 214, 112, 180 | 603 | 54.3% | +3.6% (-3.7 to +11.0) | + - + - | 0.170 | no | fail | no (97) | **no** |

C1 in 2022-23 is +0.03% (shown as 0). The pre-registered tie-break doesn't apply: there are no practical passers.

## Per season (every candidate)
In the record column, W-L-P counts pushes as P. CLV is the mean, with the share > 0 in brackets.

| rule | season | n | W-L-P | win % at L | win % at close | CLV pts (share > 0) | CLV09 | ROI (95% CI) |
|---|---|---|---|---|---|---|---|---|
| C0 | 2022-23 | 669 | 349-313-7 | 52.7% | 52.0% | +0.27 (49%) | +0.20 | +0.6% (-6.7 to +8.1) |
| C0 | 2023-24 | 1,069 | 525-530-14 | 49.8% | 48.0% | +0.28 (49%) | +0.22 | -4.9% (-10.8 to +1.4) |
| C0 | 2024-25 | 772 | 365-396-11 | 48.0% | 47.8% | +0.22 (50%) | +0.07 | -8.3% (-15.6 to -1.0) |
| C0 | 2025-26 | 960 | 487-467-6 | 51.0% | 48.9% | +0.72 (56%) | +0.38 | -2.5% (-8.3 to +3.2) |
| C1 | 2022-23 | 675 | 350-318-7 | 52.4% | 51.7% | +0.29 (50%) | +0.23 | +0.0% (-7.1 to +7.7) |
| C1 | 2023-24 | 1,083 | 536-534-13 | 50.1% | 48.4% | +0.26 (49%) | +0.22 | -4.3% (-10.4 to +2.0) |
| C1 | 2024-25 | 776 | 372-392-12 | 48.7% | 48.2% | +0.20 (50%) | +0.06 | -6.9% (-14.4 to +0.8) |
| C1 | 2025-26 | 945 | 492-448-5 | 52.3% | 50.1% | +0.75 (56%) | +0.36 | -0.1% (-6.5 to +6.1) |
| C2 | 2022-23 | 41 | 20-19-2 | 51.3% | 51.2% | -0.02 (46%) | +0.06 | -2.0% (-38.0 to +27.5) |
| C2 | 2023-24 | 59 | 34-25-0 | 57.6% | 62.7% | +0.36 (53%) | +0.41 | +10.1% (-15.1 to +32.5) |
| C2 | 2024-25 | 28 | 14-14-0 | 50.0% | 42.9% | -0.09 (50%) | +0.02 | -4.5% (-36.4 to +29.5) |
| C2 | 2025-26 | 98 | 56-41-1 | 57.7% | 57.1% | +0.88 (57%) | +0.32 | +10.1% (-6.8 to +27.6) |
| C3 | 2022-23 | 365 | 193-169-3 | 53.3% | 53.3% | +0.30 (50%) | +0.18 | +1.8% (-7.7 to +11.9) |
| C3 | 2023-24 | 501 | 249-242-10 | 50.7% | 49.0% | +0.33 (50%) | +0.19 | -3.1% (-11.2 to +5.0) |
| C3 | 2024-25 | 582 | 269-305-8 | 46.9% | 46.9% | +0.20 (50%) | +0.06 | -10.4% (-18.8 to -2.3) |
| C3 | 2025-26 | 637 | 322-311-4 | 50.9% | 48.3% | +0.70 (54%) | +0.31 | -2.9% (-10.8 to +5.1) |
| C4 | 2022-23 | 171 | 94-75-2 | 55.6% | 54.5% | +0.76 (62%) | +0.64 | +6.1% (-9.1 to +20.6) |
| C4 | 2023-24 | 488 | 248-234-6 | 51.5% | 49.1% | +0.38 (51%) | +0.38 | -1.8% (-10.6 to +6.5) |
| C4 | 2024-25 | 142 | 78-59-5 | 56.9% | 53.5% | +0.43 (61%) | +0.23 | +8.4% (-6.4 to +23.2) |
| C4 | 2025-26 | 288 | 146-140-2 | 51.0% | 46.7% | +0.84 (60%) | +0.47 | -2.5% (-14.5 to +9.7) |
| C5 | 2022-23 | 84 | 37-45-2 | 45.1% | 45.8% | +0.45 (57%) | +0.34 | -13.6% (-38.5 to +9.5) |
| C5 | 2023-24 | 85 | 43-41-1 | 51.2% | 52.9% | +0.32 (53%) | +0.50 | -2.2% (-23.9 to +17.9) |
| C5 | 2024-25 | 27 | 10-16-1 | 38.5% | 37.0% | +0.65 (70%) | +0.44 | -25.7% (-57.4 to +6.8) |
| C5 | 2025-26 | 11 | 6-5-0 | 54.5% | 54.5% | +1.14 (55%) | +0.18 | +4.1% (-47.9 to +46.9) |
| C6 | 2022-23 | 633 | 331-295-7 | 52.9% | 52.1% | +0.29 (50%) | +0.22 | +0.9% (-6.3 to +8.3) |
| C6 | 2023-24 | 1,007 | 492-501-14 | 49.5% | 47.9% | +0.25 (49%) | +0.20 | -5.4% (-11.4 to +1.0) |
| C6 | 2024-25 | 763 | 359-393-11 | 47.7% | 47.6% | +0.22 (50%) | +0.07 | -8.7% (-15.9 to -1.4) |
| C6 | 2025-26 | 898 | 458-435-5 | 51.3% | 49.2% | +0.67 (55%) | +0.36 | -2.1% (-8.1 to +3.9) |
| K1 | 2022-23 | 640 | 332-301-7 | 52.4% | 51.7% | +0.32 (50%) | +0.24 | +0.1% (-7.0 to +7.6) |
| K1 | 2023-24 | 1,022 | 503-506-13 | 49.9% | 48.2% | +0.23 (48%) | +0.20 | -4.8% (-10.9 to +1.5) |
| K1 | 2024-25 | 768 | 367-389-12 | 48.5% | 48.0% | +0.20 (50%) | +0.06 | -7.2% (-14.7 to +0.5) |
| K1 | 2025-26 | 887 | 466-417-4 | 52.8% | 50.6% | +0.70 (55%) | +0.33 | +0.7% (-5.7 to +7.1) |
| K2 | 2022-23 | 97 | 61-34-2 | 64.2% | 63.8% | +0.96 (70%) | +0.80 | +22.1% (+4.9 to +38.6) |
| K2 | 2023-24 | 214 | 109-102-3 | 51.7% | 49.8% | +0.45 (52%) | +0.40 | -1.4% (-12.8 to +10.3) |
| K2 | 2024-25 | 112 | 59-49-4 | 54.6% | 51.8% | +0.39 (64%) | +0.27 | +4.1% (-13.3 to +22.0) |
| K2 | 2025-26 | 180 | 93-86-1 | 52.0% | 46.9% | +0.96 (60%) | +0.49 | -0.8% (-15.5 to +14.1) |

**Pooled:**

| rule | n | win % at L | win % at close | CLV pts (95% CI), share > 0 | CLV09 |
|---|---|---|---|---|---|
| C0 | 3,470 | 50.3% | 49.0% | +0.39 (+0.31 to +0.46), 51% | +0.23 |
| C1 | 3,479 | 50.8% | 49.5% | +0.39 (+0.31 to +0.46), 51% | +0.22 |
| C2 | 226 | 55.6% | 55.8% | +0.46 (+0.14 to +0.79), 53% | +0.26 |
| C3 | 2,085 | 50.1% | 49.0% | +0.40 (+0.31 to +0.49), 51% | +0.19 |
| C4 | 1,089 | 52.7% | 49.9% | +0.57 (+0.45 to +0.70), 57% | +0.42 |
| C5 | 207 | 47.3% | 48.1% | +0.46 (+0.19 to +0.76), 57% | +0.41 |
| C6 | 3,301 | 50.2% | 49.0% | +0.37 (+0.29 to +0.44), 51% | +0.22 |
| K1 | 3,317 | 50.8% | 49.5% | +0.37 (+0.29 to +0.44), 51% | +0.21 |
| K2 | 603 | 54.3% | 51.5% | +0.67 (+0.52 to +0.82), 59% | +0.46 |

All WH prices were present (no -110 fallbacks). Pooled break-even is 52.4% for every rule.

## Pre-registered secondary checks (not pass/fail)
**C0 at other books at T** (the same rule, with that book's line and price, in the same 4 seasons):

| book | n | win % | BE | ROI (95% CI) | by season (ROI) | CLV |
|---|---|---|---|---|---|---|
| `williamhill_us` (primary) | 3,470 | 50.3% | 52.4% | -3.9% (-7.2 to -0.7) | +0.6 / -4.9 / -8.3 / -2.5 | +0.39 |
| `draftkings` | 4,179 | 51.7% | 52.4% | -1.4% (-4.5 to +1.6) | -0.6 / -4.2 / -5.0 / +3.8 | +0.50 |
| `pinnacle` | 2,942 | 50.3% | 52.6% | -4.2% (-7.6 to -0.8) | -3.6 / -3.5 / -9.0 / -1.1 | +0.38 |

**Leak check** (games where either team played on D-1 removed, about 2% of bets): no conclusion changes. C0 goes
from -3.9% to -3.9% (n 3,390), C1 -2.8%, C4 +0.6%, K2 +3.8% (n 590). By season, C0 is +0.6 / -5.4 / -8.4 /
-1.9%. The late-D-1 results that walk-forward models can see did not prop anything up.

**Splits, pooled ROI** (n in brackets):

| rule | gp < 10 | gp >= 10 | over | under | avg 4-6 | avg 6+ |
|---|---|---|---|---|---|---|
| C0 | -5.6% (1,218) | -3.1% (2,252) | -1.5% (2,094) | -7.7% (1,376) | -3.0% (2,303) | -5.9% (1,167) |
| C1 | -4.2% (1,203) | -2.2% (2,276) | -0.5% (2,183) | -7.0% (1,296) | -0.9% (2,300) | -6.9% (1,179) |
| C2 | +6.1% (226) | n/a | +11.8% (118) | -0.1% (108) | n/a | +6.1% (226) |
| C3 | -7.2% (720) | -2.6% (1,365) | -1.0% (1,188) | -8.5% (897) | -4.1% (1,403) | -4.5% (682) |
| C4 | +2.1% (389) | -0.3% (700) | +5.5% (668) | -7.2% (421) | +2.0% (737) | -2.3% (352) |
| C5 | -3.7% (133) | -20.0% (74) | -7.1% (144) | -15.2% (63) | n/a | -9.5% (207) |
| C6 | -4.8% (1,151) | -3.6% (2,150) | -1.6% (1,989) | -7.8% (1,312) | -3.7% (2,195) | -4.8% (1,106) |
| K1 | -3.2% (1,140) | -2.8% (2,177) | -0.5% (2,082) | -7.0% (1,235) | -1.5% (2,197) | -5.6% (1,120) |
| K2 | +3.3% (198) | +3.7% (405) | +9.4% (350) | -4.5% (253) | +3.2% (422) | +4.5% (181) |

## Caveats
- **2025-26 is the tuning season** for et-v1's settings. It does not rescue C0 at the bet line (-2.5%). For C1,
  2025-26 DS and DS-alt come from different walk-forward runs (Amendment 1, item 3.5), so C1 against C0 there
  is not a clean altitude comparison.
- **Model numbers are walk-forward**: DS refits weekly and MB monthly, both no refit for this test. They are
  not the live daily refits, and the live models may be slightly sharper. The leak check shows no D-1 leak
  effect.
- **Volume is below the pre-registration's guess.** C0 has 669-1,069 bets per season against the ~1,300-1,600
  guessed from the opener. WH quotes only 65-85% of games at T, and the 21:00 line already sits closer to the
  models than the opener (the cell vs the opener isn't the cell vs L).
- **C5's fitted shrink** is small (b 0.04-0.12), so s >= 1.5 needs avg edges of about 7-15 pts, giving
  207 bets in total. C4 and K2 are limited by WH/DK coverage at 15:00, as the sanity report predicted.
- **`williamhill_us` is Caesars' out-of-state feed**, standing in for WH NV, as live.
- **One bug was found and fixed after the first scoring run.** In the per-row summaries, the bootstrap p-value
  overwrote the push count under the same key. The Holm input was the p-value both times. Renaming the key
  changed no rule, number or verdict; it only restored the push counts in the tables. The scoring code is
  unchanged otherwise.

## Exploratory (noticed after seeing outcomes; not evidence for any rule)
These need a new pre-registration and forward data before they mean anything:
1. **Every rule has positive CLV** (C0 +0.39 pts, 51% > 0) and still loses at L. Win % at the close is *lower*
   than at L. The market does move toward the models overnight, but by much less than the edge implies, and
   the 21:00 WH price already includes most of what the models know.
2. **Unders are the main drain in every rule** (C0 under -7.7% vs over -1.5%). Overs alone are near break-even
   in C0, C1 and K1.
3. **The market-momentum rules (C4, K2) are the only ones with positive pooled ROI**, and K2's overs are +9.4%
   (n 350). K2's pooled number leans on 2022-23 (+22% on 97 bets); 2023-24 and 2025-26 are flat or negative.
   This matches the 2026-11-22 edge-study finding that picks win when the market later follows the models, but
   it doesn't pass here.
4. **C0 at DraftKings** loses less than at WH (-1.4% vs -3.9%) and is positive in 2025-26 (+3.8%).
   Line shopping might matter more than the rule.

## Files
- **Code:** `src/deepsports/analysis/et_v2_score.py` (the rules, grading, bootstrap, Holm, PASS and
  tie-break), with tests in `tests/test_et_v2_score.py` (synthetic fixtures). Lines come from
  `et_v2_lines.py`.
- **Scripts and outputs:** `/Volumes/ExFATStorag/DeepSports/work/et-v2-2026-11-23/scoring/`
  - `s1_lines.py` -> `lines.json`, `s2_models.py` -> `models.json`, `s3_coverage.py` -> `coverage.json`
    (these three ran before outcomes).
  - `s4_outcomes.py` -> `outcomes.json`, `s5_score.py` -> `results.json` + `s5_score.out`.
  - `s6_tables.py` -> `tables.out`.
- **Commits:** pre-registration `3970720`, Amendment 1 `0458f6b` (before outcomes), and this results commit
  (branch `research/et-v2-scoring`).
