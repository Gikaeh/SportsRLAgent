# Lotto parlays on et-v1's legs: backtest (2026-11-23, exploratory)

**Follow-up the same day: `2026-11-23-lotto-investigation.md`. The sweep excess did not replicate outside 2022-23 to 2024-25; read that first.**

**Question:** how would $1 parlay tickets built from et-v1's nightly legs have done, and does the card design matter?
**Data:** C0 from the et-v2 scoring (`2026-11-23-et-v2-results.md`): et-v1's cell at the 21:00 PT William Hill
(`williamhill_us`) line, 2022-23 to 2025-26, 3,470 legs on 513 nights, legs ranked by average edge. Tickets pay
the product of the leg prices; a push drops the leg. Scripts: `/Volumes/ExFATStorag/DeepSports/work/lotto-backtest-2026-11-23/`.

## Results
Single legs win 50.3% (−3.9% ROI). Parlays did far better, because **same-night legs win together more often than
independent legs would**:

| Top-k legs of a night all win | Observed | If independent |
|---|---|---|
| 4 | 26/327 = 8.0% | 6.4% |
| 6 | 9/231 = 3.9% | 1.6% |
| 7 | 8/194 = 4.1% | 0.8% |
| 8 | 2/154 = 1.3% | 0.4% |

Nightly win counts vary 1.13× as much as independent legs would. A permutation test (leg results shuffled across
nights within a season) gives p = 0.0005 for 8+ seven-leg sweeps. 7 of the 8 sweep nights were mostly overs.

| Card ($1 tickets) | Nights | Staked | Returned | ROI | Nights with a hit | By season (22-23 … 25-26) |
|---|---|---|---|---|---|---|
| lotto-v1: nested 4/7/10 | 449 | $760 | $1,836 | +142% | 12.2% | +87% / +426% / +49% / −42% |
| one 7-leg (top 7) | 195 | $195 | $736 | +277% | 4.1% | +478% / +534% / +298% / −100% |
| one 10-leg (top 10) | 116 | $116 | $630 | +443% | 0.9% | one hit (2023-24) |
| 10 × 7-leg from top 9 | 195 | $1,569 | $3,310 | +111% | 6.2% | +10% / +389% / +22% / −59% |
| 8 × 7-leg from top 10 | 195 | $1,301 | $1,972 | +52% | 5.1% | −55% / +209% / +14% / −26% |
| 8 × 7-leg from top 12 | 195 | $1,301 | $1,019 | −22% | 4.1% | |
| 8 × 8-leg from top 11 | 158 | $1,096 | $349 | −68% | 1.3% | |

## Caveats (read before acting)
- **Few events:** every positive ROI rests on about 8 sweep nights in 4 seasons. One or two fewer and most rows turn
  negative. 2025-26, the most recent season (and et-v1's tuning season), had no 7-leg sweep.
- **Many designs were tried** on the same data. The ranking between designs is noise; only the clustering is a
  finding, and it is exploratory.
- **Mechanism unknown.** A shared nightly scoring factor (most sweeps were over-heavy nights) or correlated model
  errors would both cluster results. A book prices parlays as if legs were independent, so clustering is the one
  thing that could make parlays of 50% legs pay.
- Only 38% of nights (195/513) had 7+ legs; this season et-v1 averages ~14 legs a night.

## Next
Pre-register before any real-money rule: H = "same-night et-v1 legs cluster (top-7 sweep rate above the
independent rate)", tested forward on the lotto cards, plus a fixed card design. Do not tune legs or sizes on these
4 seasons.
