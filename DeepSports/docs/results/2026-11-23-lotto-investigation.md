# Lotto parlays: totals vs spreads vs moneylines, college vs NBA, injuries (2026-11-23, exploratory)

Follow-up to `2026-11-23-lotto-parlay-backtest.md`, which found that et-v1's same-night legs swept 7-for-7 far
more often than independent legs would. Three read-only studies; scripts and outputs under
`/Volumes/ExFATStorag/DeepSports/work/lotto-investigation-2026-11-23/` (`totals/`, `spreads-ml/`, `nba-injuries/`).
About 280 comparisons in all; findings below are labeled solid or noise accordingly.

## Bottom line
No bet type has a parlay edge that survives a check on seasons it wasn't found in. The college totals sweep excess
is real in 2022-23 to 2024-25 (8 sweeps vs ~1 expected) but did not replicate in 2021-22 and 2025-26 (1 vs 1.0),
and et-v1's legs have no per-leg edge in history (49.9% vs 50.4% for random same-side legs, same nights). Lotto
tickets are entertainment money. The only honest test is forward and pre-registered.

## College totals (et-v1 legs, WH 21:00)
- Reproduced: 513 nights, 3,470 legs, 50.3%, top-7 sweeps 8/194 (8/195 counting pushed legs as the ticket does).
- **Not a market-wide effect:** across all D1 games the nightly over-share barely clusters (2023-26 at WH 21:00:
  dispersion 1.08, p=0.14). Random 7 overs every night lose ~16%. Random same-side 7-leg sets on the same nights
  sweep 1.05 times vs et-v1's 8.
- **Both tails are fat** (0-win nights 4 vs 1.5 expected): the legs move together, adding variance, not edge.
- By season, top-7 sweeps vs expected: 2022-23 2 vs 0.25; 2023-24 4 vs 0.4; 2024-25 2 vs 0.2; 2025-26 0 vs 0.54;
  2021-22 holdout 1 vs 0.37. Month, weekday and over/under slices: noise.
- Live (6 nights, legs 56.6%): no sweep; slates ran over the close 57-64% every night (early-season drift).
- Cards, ROI 2023-26 [95% CI, weeks resampled] / 2021-22 + 2025-26: 1 x top-7 +277% [+42, +545] / -2%;
  16 x $0.50 of 7-of-top-9 +136% [-35, +355] / +60% (from 54% legs in 2021-22, not clustering);
  36 x $0.25 +131% [-31, +346] / +54%; lotto-v1 4/7/10 +142% [-4, +372] / -13%. Dry runs reach $160-336.

## College spreads and moneylines
- Spread rule (both models same side of WH 21:00 spread, avg edge >= 2/3/4): 49.9-50.5%, ROI -3.5% to -4.6%; no
  clustering (top-7 sweeps 0-0.5% vs 0.8-0.9% independent); parlay cards -34% to -100%.
- Moneylines at the ESPN close: model picks -1.8% to -5.0% (mostly dogs); favorites -150..-400 67.8% vs 69.5%
  needed (-2.5%); dogs +150..+400 -9.6%. Upsets don't cluster (heaviest-7 sweep 9.5% vs 10.0% market-implied).
- Spread and total results on the same night are slightly negatively correlated; mixed tickets lost.
- ~30 tests, nothing survives Bonferroni.

## NBA
- Data: closing lines 2021-22 on, openers 2023-24 on (posting time unknown), no night-before history; v1.0/v1.1
  walk-forward re-run for 4,210 games (2023-24 on).
- Market-wide dispersion (1 = independent): NBA close totals 1.03 (p=.22), favorites covering 1.07 (p=.06). College
  close, all seasons incl. 2026-27: 1.16 (p=.006) / 1.13 (p=.02); tiny (ICC ~0.003-0.006), explains ~10% of the
  et-v1 sweep excess, partly this season's early drift.
- v1.1 totals rule (edge >= 4) **at the opener**: 1037-898, 53.6% [51.4, 55.8], ROI +0.8%, fading by season
  (55/55/51/49%); at the close 47.9%. Spreads 52.0% at the opener, 50.1% at the close.
- No clustering; only 44 of 602 nights have 7+ total legs; 7-leg cards -5% to -100%.

## Injuries
- NBA v1.1i vs v1.1, 94 graded games: margin MAE +0.16 worse (SE 0.13), totals unchanged; it moves the total ~0.2
  pts, too little to re-rank legs. No pre-tip injury history to backtest.
- College: no injury reports; box-score availability adds nothing (`2026-11-22-situational-factors.md`).

## Next
- Lotto stays totals-only, college-only. If kept: pre-register H = "on nights with 7+ et-v1 legs, the top-7 sweep
  rate exceeds 0.503^7" (one-sided Poisson), card = 1 x $1 top-7, check at 50/100/150 qualifying nights (~1 season
  for 80% power). Any bigger card ($5-10 a night) is the same bet with more variance.
- The NBA Odds API pull would test v1.1's opener edge at WH's night-before line, as singles only.
