# Pre-registration: NBA v1.1 totals at William Hill's night-before line (`nt-v1`, 2026-11-23)

Written and committed **before** any NBA Odds API historical snapshot exists on disk (none had been pulled).

## Why
A read-only study the same day (`2026-11-23-lotto-investigation.md`, NBA section) found the v1.1 walk-forward totals
rule (|model - line| >= 4) went 1037-898 (53.6%, 95% CI 51.4-55.8, ROI +0.8%) against ESPN's opener, 2023-24 to now,
fading by season (55 / 55 / 51 / 49%), and 47.9% against the close. The opener's posting time is unknown. The
question is whether the edge exists at a line the owner can actually bet the night before: William Hill's
(`williamhill_us`, Caesars' feed standing in for WH NV) total at 21:00 PT on D-1. Already seen: opener and close
results above. Not seen: any Odds API NBA line.

## Data (fixed now)
- **Predictions:** `/Volumes/ExFATStorag/DeepSports/work/nba-totals-prereg-2026-11-23/wf_v1.1.json`
  (sha256 `2569a64ea97c979e82ee0035738804427343c0cfc30a498cf5ddc1db386fb446`), made by `wf.py` in the same folder:
  `run_backtest(refit='monthly', model_version='v1.1')` on a read-only warehouse copy of 2026-11-23. Each game's
  `pred_total` comes from a model fit only on games before its month. Only `pred_total` is used; the file's outcome
  columns are not inputs.
- **Lines:** The Odds API historical snapshots, NBA, market `totals`, books betmgm, betonlineag, betrivers, bovada,
  draftkings, espnbet, fanduel, lowvig, pinnacle, williamhill_us, at -1@21:00, 0@09:00 and 0@15:00 PT, seasons
  2023-24, 2024-25, 2025-26 and 2026-27 to date (`deepsports odds-api-history pull`). Event matching to ESPN game ids
  by date and team names, as in `analysis/et_v2_lines.py`; a match rate below 95% in a season is reported.
- **Outcomes (grading only):** final scores from the warehouse.

## Rule nt-v1
For each regular-season or postseason game with a `pred_total` and a `williamhill_us` total at time T that starts
at least 60 minutes after T: side = over if `pred_total` > line, under if lower; bet if |`pred_total` - line| >= 4.0,
at WH's price for that side (-110 if missing). One bet per game. No other filter.

**T (primary):** -1@21:00 PT. If WH has a line at -1@21:00 for fewer than 60% of a season's games with a prediction,
that season uses 0@09:00 instead (decided per season from coverage alone, before grading). 0@09:00 and 0@15:00 are
also reported for every season as secondary, descriptive results.

## Grading and pass/fail
- Win/loss/push vs the final total at the bet line; P&L per $1 at the bet price. CIs: bootstrap resampling game days,
  10,000 reps, seed 0.
- **Primary seasons:** 2023-24, 2024-25, 2025-26 pooled. 2026-27 to date is reported but not part of the verdict.
- **PASS** if pooled ROI > 0 with the 95% CI lower bound > 0 **and** ROI > 0 in at least 2 of the 3 seasons.
  Otherwise FAIL. One look; the rule, threshold, books, time and seasons above are not changed after the pull.
- Also reported (descriptive, no test): win % and CLV vs the ESPN close, overs vs unders, bets per season,
  edge >= 3 and >= 5, and the same rule at Pinnacle and DraftKings.

## What happens next
- PASS: a watch-only live forward test of nt-v1 from the Odds API live capture (NBA totals every 30 min until
  2026-12-24), then a decision with the owner on NBA night-before singles. Parlays are out of scope (too few NBA
  nights have 7+ legs).
- FAIL: NBA night-before totals are dropped; no re-test on these seasons with a changed rule.

## Caveats
Monthly refits are staler than the live daily model, which makes the test conservative. `williamhill_us` is
Caesars' out-of-state feed, not WH NV. NBA totals may post late, so -1@21:00 coverage is uncertain; the coverage
fallback above handles it.

## Amendment 1 (2026-11-23, before the pull; only 13 probe snapshots on disk, none graded)
Probe snapshots (8 game days) showed WH NBA totals on most days, but the probe's coverage print lists at most 8 books,
so a missing WH couldn't be ruled out. Added rule: if a season's WH coverage is below 60% at both -1@21:00 and
0@09:00, that season is graded at `draftkings` at -1@21:00 (or 0@09:00 by the same 60% rule), and is reported as a
DraftKings season. Nothing else changes.
