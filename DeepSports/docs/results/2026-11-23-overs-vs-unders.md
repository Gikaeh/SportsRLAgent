# Overs vs unders in et-v1 (2026-11-23, exploratory)

**Question:** et-v2 found et-v1's overs lose -1.5% and unders -7.7% (2022-23 to 2025-26). Real, and usable?
**Answer: no.** The gap is the market's slight lean to overs plus noise. Nothing to bet on.
Scripts and outputs: `/Volumes/ExFATStorag/DeepSports/work/overs-unders-2026-11-23/`. CIs bootstrap nights.

| et-v1 legs (WH 21:00) | Overs | Unders | Gap, 95% CI |
|---|---|---|---|
| All, 2022-23 to 2025-26 | -1.5% (2,094) | -7.7% (1,376) | [-0.1, +12.6] pp |
| By season | +5.2 / -5.6 / -3.3 / +1.3 | -7.7 / -3.3 / -17.1 / -5.4 | overs ahead 3 of 4 |
| December | -1.1% | -24.2% (184) | data-mined cell |
| Live 2026-27 (84) | 28-18, +15.9% | 19-18, -1.7% | [-17, +53] |

- **Market:** games went over the WH 21:00 line 50.9% [50.1, 51.7] (finals average +0.9 pts above the line, a skew),
  50.4% vs the close. No November over bias (49.0 / 51.0 / 47.6 / 49.3%). This season's 57-64% over nights were one
  week (Nov 17-22); season to date 49.7% vs the close.
- **Skill net of the market's lean:** overs +1.0 pp [-1.4, +3.3], unders -1.2 pp [-3.7, +1.2]: both zero.
- **Models:** the selected legs overshoot on both sides about equally (selection on edge). One real bias: November
  2025, MB ran 3.0 and DS 1.75 pts below the line, so 79% of that month's legs were unders.
- Prices (98% at -110) and 21:00 to close movement (+0.44 overs, +0.30 unders, both toward the pick) don't explain it.
- **NBA v1.1:** no gap (opener: overs +0.1%, unders +1.7%).
- An overs-only et-v1 (chosen after seeing data): -1.5% [-5.9, +2.9], not above break-even.
- About 60 comparisons (Bonferroni ~0.0008): the pooled gap (p=0.028) and December unders (p=0.002) don't survive.
  Low-prior hypothesis if wanted later: "2026-27 Dec 1 - Mar 15, et-v1 unders return less than overs".
