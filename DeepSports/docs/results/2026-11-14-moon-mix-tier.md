# 2026-11-14: To The Moon tier 12 `mix` (straights + a parlay)

Question: the owner's request (2026-11-13): "this month the budget is the $50 ... some straight bets, and some
parlays with calculated risk". How should singles and one parlay a day be sized and paced so the month's
deposit is the hard cap? All numbers are at -vig (-4.55% per -110 leg, independent legs), one month, from
`deepsports moon sim --tier mix --months 1` (20,000 runs, seed 7) unless noted.

## Rule (tiers.py `pace_allowance`, `mix_card`; sim.py `_mix_month`)
- Budget = this month's deposits minus this month's stakes (every tier, manual included; results never refill it).
- Each day may stake `left x gap / (days_left + gap - 1)`: an even share of what is left over the days left,
  plus the shares of the idle days since the last bet (`gap`). On the last day that is all of what is left.
- ~~A day bets a whole *card* once that share covers it, else nothing.~~ (Replaced 2026-11-14.) A day bets as
  much of the card (N singles at `unit` x deposit, one 2-leg parlay at `parlay_unit` x deposit, whole dollars)
  as that share covers: singles first, then the parlay.
- The sim gives a month 30 slate days. Stakes never exceed the deposit (tested on every path).

## Grid at $50 (one month)
| Single / parlay unit | Singles a card | Card | P(up) | P(lose > 1/2) | Mean end | Bets |
|---|---|---|---|---|---|---|
| 4% / 2% ($2/$1) | 3 | $7 | 45% | 1.0% | $47.5 | 28 |
| 6% / 2% ($3/$1) | 2 | $7 | 42% | 2.5% | $47.4 | 21 |
| **6% / 4% ($3/$2)** | **2** | **$8** | **41%** | **4.2%** | **$47.4** | **18** |
| 10% / 2% ($5/$1) | 2 | $11 | 45% | 6.2% | $47.5 | 14 |
| 10% / 4% ($5/$2) (tonight's pattern) | 2 | $12 | 37% | 6.3% | $47.4 | 12 |
| 20% / 4% ($10/$2) | 2 | $22 | 48% | 6.2% | $47.8 | 6 |
| Reference: `ticket2` (all $50 on one 2-leg parlay) | | $50 | 25% | 75% | $45.2 | 1 |
| Reference: `units` (10% of the balance, 10 singles) | | | 37% | 1.2% | $47.7 | 10 |

- Every row stakes about the whole $50, so the mean end is about $47.4 (the vig on ~$48-50) whatever the sizing.
  The sizing changes only the shape: P(up) moves 37-48% largely through dollar rounding (which totals land just
  above $50), and P(lose > 1/2) grows with the unit.
- Chosen: **6% singles, 4% parlay, 2 singles a card** ($3 + $3 + $2 at $50). Its P(up) is a steady 41% across
  seeds 7-9 and at $50/$75/$100 (41-42%); the worst day is $8 (16% of the deposit), and it keeps a real parlay
  like the owner's $2 one. Larger units (10%, 20%) more than double P(lose > 1/2) to buy no mean and unstable P(up).
- `sim --tier mix --months 1 --budget 50`: P(up) 40.8%, P(lose > 1/2) 4.3%, p10/median/p90 $31/$47/$64, mean
  $47, 18 bets and $48 staked a month. At $75 ($5 + $5 + $3): P(up) 44.4%, P(lose > 1/2) 2.4%, mean $71.
- No 3-leg "moon day": it adds a 12.5% long shot at -13% EV for no gain in P(up) at this budget.

## This month (ledger 2026-11, read-only)
$50 deposited, $27 staked on the 2026-11-13 manual picks, $23 left for 18 days. With whole cards only, pacing gave
no bet until about Nov 19. The owner wants straights and parlays most days, so the orchestrator changed `mix_card`
(2026-11-14) to bet whatever part of the card the day's share covers: about $2-3 a day for the rest of November.

### Partial-card rule (current)
`sim --tier mix --months 1 --budget 50`: P(up) 40.8% (40.3% at seed 11), P(lose > 1/2) 5.5%, mean end $47,
20 bets and $50 staked a month. The table above is the earlier whole-card rule; the unit choice stands.

Caveats: assumes independent legs and no edge (the first model-picks grade found none), every day has a slate,
and Circa prices like the reference. Hit chances in `propose` are the slate's no-vig probabilities.
