# 2026-11-13: To The Moon, one month at a time

Question: the owner plays one month at a time ($50-100 deposit, the month's whole risk). Which single
play should be the default? All numbers are at -vig (-4.55% per -110 leg), from
`deepsports moon sim --months 1 --budget 75` (20,000 runs, seed 7) unless noted.

| Play ($75) | Returns if it hits | Hits | EV per $1 | Mean end |
|---|---|---|---|---|
| One 2-leg parlay (`ticket2`) | $273 | 24.8% (exact 25.0%) | -8.9% | $68 |
| One 3-leg parlay (`ticket3`) | $522 | 12.5% | -13.0% | $64 |
| One 4-leg parlay (`ticket4`) | $996 | 6.0% | -17.0% | $60 |
| Bold play on -110 singles to $273 | $273 | 24.6% | (chained bets) | about $68 |

- Bold play to the same multiple has the same odds as the 2-leg ticket within noise (data-analyst check,
  200k runs: 25.1% to 3.64x, about 1.5 bets and $146 staked a month). It isn't the default because it
  chains bets and puts about twice the money in play.
- Over 12 monthly 2-leg tickets: about 3 hits expected, 3.2% chance of none.
- Assumes independent legs, true parlay odds and no edge (the first model-picks grade found none).

Decision: root `docs/DECISIONS.md` 2026-11-13, "played one month at a time".
