# Pre-registration: lotto-v2, the same-night sweep test (2026-11-23)

Written and committed before the first `lotto-v2` card (game date 2026-11-24). Background:
`2026-11-23-lotto-investigation.md` (et-v1's top-7 legs swept 8 times in 2022-23 to 2024-25 vs ~1 expected; 1 vs
1.0 in 2021-22 + 2025-26; no per-leg edge).

## Card (fixed; code `src/deepsports/moon/lotto.py`, `RULE = "lotto-v2"`)
- Legs: the night's et-v1 bets (first row per game, `reports/early-totals/bets.jsonl`), ranked by `avg_edge`
  (ties: tip time, game id). Built once at the 21:00 run; the first card per game date is final.
- Test ticket: legs 1-7, $1, on nights with 7+ legs. Spread tickets: $0.25, 7 legs; 9+ legs: the 18 tickets from
  legs 1-9 leaving out pairs (i, i+1) and (i, i+2) on a circle of 9; 8 legs: the 8 leave-one-out tickets.
- Grading: a leg that loses loses the ticket; a pushed leg drops out at its price. Finals from the warehouse.

## Hypothesis and test
- **H:** same-night et-v1 legs win together more often than independent legs would.
- **Statistic:** S = number of test tickets that win (no losing leg) over the qualifying nights.
- **Null:** independent legs at the observed win rate p of the test tickets' graded legs (pushes excluded):
  expected E = N * p^7, and a permutation null that shuffles leg results across the qualifying nights (10,000
  shuffles, seed 0). **PASS** if the one-sided permutation p < 0.05 at the verdict. Card ROI is reported, not tested.
- **Verdict:** at 150 qualifying nights or after the 2026-27 national title game, whichever is first. Check-ins at
  50 and 100 nights are descriptive only (no early stop either way). Power is low: a 3x sweep excess at p ~ 0.5
  needs roughly 100-150 nights for 80% power.
- PASS: the card continues, and a stake change can be discussed with the owner. FAIL: the clustering is dropped as
  a lead and the card becomes plain entertainment (or stops, owner's call). The rule is not re-tested on the same
  nights with a changed card.

## Caveats
Same-night sweeps are rare events (about 1 in 128 at coin flips), so a few nights decide the result. This season's
legs started hot (56.6% over 6 nights); the null uses the observed p, so a hot leg rate alone can't pass the test.
