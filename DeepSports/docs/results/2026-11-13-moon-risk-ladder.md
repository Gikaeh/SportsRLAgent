# To The Moon (betting): risk ladder for $50 / $75 / $100 a month

**Not betting advice and watch-only.** The owner places every bet. This is a simulation of betting rules under the
assumption the data supports: **no edge, so every bet loses the vig on average**.

## Question
How likely is each betting style to turn $50, $75 or $100 a month into $1,000, $2,500 or $10,000 within 12 months,
and what does it cost when it fails?

## Method
- Code: `src/deepsports/moon/` (`tiers.py`, `sim.py`), run with `python -m deepsports.moon tiers --budget B --target T`.
  20,000 Monte Carlo runs per cell, seed 7, a deposit at the start of each month, 12 months.
- **Expected value per leg = −vig = −4.55%** (one side of a −110/−110 market). The closing line beats every model we
  have (`2026-11-06-sim-v1.1-prices.md`), so there is no measured edge. A leg at decimal odds d wins with
  p = (1 − 0.0455)/d. Parlay legs are independent (different games), so a parlay pays dⁿ, hits pⁿ, and its EV is
  0.9545ⁿ − 1: −8.9% for 2 legs, −13.0% for 3, −17.0% for 4.
- No pushes, no taxes, $1 minimum stake. **Every betting tier cashes out at the target** (stops betting once the
  balance touches it).
- Metrics: P(reach) = balance ≥ target after month 12; P(touch) = at any time (equal to P(reach) with cash-out);
  P(lose > ½) = ending balance under half of the deposits; p10/median/p90/mean ending balance; "months mostly lost"
  = share of months where more than half of that month's deposit was lost.
- Seed stability: P(reach) moves by under 0.5 points across seeds (save-then-bold $75→$1k: 88.3/88.2/88.2%;
  bold play: 54.4/53.9/54.0%). The standard error at 20,000 runs is at most 0.35 points.

The tiers (`python -m deepsports.moon tiers` prints them):

| # | Tier | Rule |
|---|---|---|
| 1 | Keep the cash | No bets (the benchmark) |
| 2 | Timid singles | 2% of balance per −110 single, ~30 a month |
| 3 | 10% singles | 10% of balance per −110 single, ~10 a month |
| 4 | Underdog moneylines | 10% of balance per +300 dog, ~10 a month |
| 5 | 2-leg parlays | 20% of balance per 2-leg (+264), ~5 a month |
| 6 | Monthly 3-leg ticket | The month's deposit on one 3-leg (+596); winnings banked |
| 7 | Monthly 4-leg ticket | The month's deposit on one 4-leg (+1228); winnings banked |
| 8 | Let it ride, 3-leg | The whole balance on one 3-leg each month |
| 9 | Bold play | Dubins–Savage: stake min(balance, what reaches the target), repeat until target or $0 |
| 10 | Save, then bold | Bank every deposit; bold play with all of it in month 12 |

## Headline: best tier per budget and target (at −vig)

| Budget (deposited) | Target $1,000 | Target $2,500 | Target $10,000 |
|---|---|---|---|
| $50 ($600) | Save, then bold: **57%** reach, 43% end at $0 | Save, then bold: **21%**, 79% at $0 | Save, then bold: **4.8%**, 95% at $0 |
| $75 ($900) | Save, then bold: **88%**, 12% at $0 | Save, then bold: **33%**, 67% at $0 | Save, then bold: **7.5%**, 92% at $0 |
| $100 ($1,200) | **Keep the cash: 100%** (deposits alone reach it) | Save, then bold: **45%**, 55% at $0 | Save, then bold: **10%**, 90% at $0 |

For save-then-bold, P(lose > ½) equals P(end at $0): it is all-or-nothing, decided in month 12 in about 2 bets.

Best tier that **bets every month**, for comparison:

| Budget | $1,000 | $2,500 | $10,000 |
|---|---|---|---|
| $50 | Bold play 38% (P(lose > ½) 62%) | Bold play 17% (83%) | Bold play 3.9% (96%) |
| $75 | Bold play 54% (46%); 3-leg ticket 45% (20%) | Bold play 24% (76%) | Bold play 6.1% (94%) |
| $100 | Timid singles 68% (0.9%) | Bold play 31% (69%) | Bold play 8.1% (92%) |

## Full tables (20,000 runs, seed 7, −vig, cash-out on)

### $75 a month ($900 deposited)
Target $1,000:

| # | Tier | P(reach) | P(lose>½) | p10 | Median | p90 | Mean | Months mostly lost |
|---|---|---|---|---|---|---|---|---|
| 1 | Keep the cash | 0% | 0% | $900 | $900 | $900 | $900 | 0% |
| 2 | Timid singles | 15% | 0.9% | $564 | $737 | $1,012 | $762 | 25% |
| 3 | 10% singles | 35% | 34% | $277 | $592 | $1,313 | $729 | 37% |
| 4 | Underdog moneylines | 44% | 45% | $153 | $548 | $1,550 | $781 | 42% |
| 5 | 2-leg parlays | 38% | 55% | $86 | $346 | $1,659 | $706 | 50% |
| 6 | Monthly 3-leg ticket | 45% | 20% | $0 | $522 | $1,569 | $796 | 73% |
| 7 | Monthly 4-leg ticket | 50% | 47% | $0 | $1,071 | $1,746 | $780 | 68% |
| 8 | Let it ride, 3-leg | 14% | 76% | $0 | $0 | $4,378 | $699 | 82% |
| 9 | Bold play | 54% | 46% | $0 | $1,075 | $1,750 | $788 | 68% |
| 10 | Save, then bold | 88% | 12% | $0 | $1,000 | $1,000 | $883 | 1.0% |

Target $2,500:

| # | Tier | P(reach) | P(lose>½) | p10 | Median | p90 | Mean | Months mostly lost |
|---|---|---|---|---|---|---|---|---|
| 1 | Keep the cash | 0% | 0% | $900 | $900 | $900 | $900 | 0% |
| 2 | Timid singles | 0% | 0.9% | $564 | $737 | $972 | $756 | 25% |
| 3 | 10% singles | 2.1% | 36% | $276 | $550 | $1,213 | $680 | 42% |
| 4 | Underdog moneylines | 9.9% | 56% | $147 | $390 | $2,241 | $715 | 49% |
| 5 | 2-leg parlays | 9.7% | 70% | $82 | $248 | $2,020 | $611 | 57% |
| 6 | Monthly 3-leg ticket | 0.9% | 20% | $0 | $522 | $1,566 | $774 | 88% |
| 7 | Monthly 4-leg ticket | 3.3% | 47% | $0 | $996 | $1,992 | $737 | 93% |
| 8 | Let it ride, 3-leg | 14% | 76% | $0 | $0 | $4,378 | $699 | 82% |
| 9 | Bold play | 24% | 76% | $0 | $0 | $3,025 | $702 | 87% |
| 10 | Save, then bold | 33% | 67% | $0 | $0 | $2,500 | $821 | 5.6% |

Target $10,000:

| # | Tier | P(reach) | P(lose>½) | p10 | Median | p90 | Mean | Months mostly lost |
|---|---|---|---|---|---|---|---|---|
| 1 | Keep the cash | 0% | 0% | $900 | $900 | $900 | $900 | 0% |
| 2 | Timid singles | 0% | 0.9% | $564 | $737 | $972 | $756 | 25% |
| 3 | 10% singles | 0% | 36% | $276 | $550 | $1,208 | $677 | 43% |
| 4 | Underdog moneylines | 0.5% | 57% | $147 | $385 | $1,361 | $679 | 50% |
| 5 | 2-leg parlays | 0.9% | 72% | $82 | $242 | $1,039 | $561 | 59% |
| 6 | Monthly 3-leg ticket | 0% | 20% | $0 | $522 | $1,566 | $774 | 88% |
| 7 | Monthly 4-leg ticket | 0% | 47% | $0 | $996 | $1,992 | $735 | 94% |
| 8 | Let it ride, 3-leg | 1.8% | 86% | $0 | $0 | $522 | $632 | 87% |
| 9 | Bold play | 6.1% | 94% | $0 | $0 | $0 | $638 | 97% |
| 10 | Save, then bold | 7.5% | 92% | $0 | $0 | $0 | $753 | 7.7% |

### $50 and $100 a month (P(reach) / P(lose > ½))

| # | Tier | $50→$1k | $50→$2.5k | $50→$10k | $100→$1k | $100→$2.5k | $100→$10k |
|---|---|---|---|---|---|---|---|
| 1 | Keep the cash | 0 / 0 | 0 / 0 | 0 / 0 | **100% / 0** | 0 / 0 | 0 / 0 |
| 2 | Timid singles | 0.2% / 0.9% | 0 / 0.9% | 0 / 0.9% | 68% / 0.9% | <0.1% / 0.9% | 0 / 0.9% |
| 3 | 10% singles | 12% / 36% | 0.4% / 36% | 0 / 36% | 59% / 28% | 5.7% / 36% | <0.1% / 36% |
| 4 | Underdog moneylines | 24% / 53% | 4.3% / 57% | 0.2% / 57% | 61% / 35% | 16% / 55% | 1.0% / 57% |
| 5 | 2-leg parlays | 22% / 65% | 5.0% / 72% | 0.5% / 72% | 53% / 44% | 15% / 68% | 1.5% / 72% |
| 6 | Monthly 3-leg ticket | 18% / 20% | 0 / 20% | 0 / 20% | 45% / 20% | 4.9% / 20% | 0 / 20% |
| 7 | Monthly 4-leg ticket | 17% / 47% | 0.4% / 47% | 0 / 47% | 53% / 47% | 17% / 47% | 0 / 47% |
| 8 | Let it ride, 3-leg | 14% / 76% | 14% / 76% | 1.8% / 86% | 14% / 76% | 14% / 76% | 1.8% / 86% |
| 9 | Bold play | 38% / 62% | 17% / 83% | 3.9% / 96% | 65% / 35% | 31% / 69% | 8.1% / 92% |
| 10 | Save, then bold | **57% / 43%** | **21% / 79%** | **4.8% / 95%** | 100% / 0 | **45% / 55%** | **10% / 90%** |

## Sensitivity checks ($75 a month)
**Cash-out at the target** (tier default on vs off, $1k target, P(reach)): timid 8.0% → 15%, 10% singles 16% → 35%,
underdog MLs 16% → 44%, 2-leg parlays 10.5% → 38%, 4-leg ticket 17% → 50%. As in DeepStocks, it is the single best
rule change, so every betting tier now uses it.

**Hypothetical edge per leg** (no model has shown this; P(reach) / P(lose > ½)):

| Tier | Target | −vig (−4.55%) | break-even (0%) | +2% |
|---|---|---|---|---|
| 10% singles | $1k | 35% / 34% | 53% / 20% | 61% / 15% |
| 3-leg ticket | $1k | 45% / 20% | 53% / 16% | 56% / 14% |
| Bold play | $1k | 54% / 46% | 61% / 39% | 64% / 36% |
| Bold play | $10k | 6.1% / 94% | 8.6% / 91% | 10% / 90% |
| Save, then bold | $1k | 88% / 12% | 90% / 10% | 91% / 9% |
| Save, then bold | $10k | 7.5% / 92% | 9.1% / 91% | 9.9% / 90% |

Even a real +2% edge, which nobody has shown, barely moves the bold tiers (the target, not
the edge, sets their odds); it matters most for the many-small-bets tiers, where the vig is paid on every bet.

## Honest takeaways
1. **With no edge, bold beats timid, exactly as Dubins–Savage says.** Timid singles almost never reach any target
   above the deposits, and they still lose money. Every reach chance comes from betting big and rarely.
2. **The best rule is the least fun one: save, then bet once.** Banking every deposit and playing bold only in
   month 12 maximizes P(target) in every cell, because it puts the fewest dollars through the vig. Its downside is
   not hidden but it is concentrated: when it misses, the whole year's money goes to $0 in about two bets.
3. **$1,000 is mostly reachable from deposits.** At $75 a month the deposits are already $900; the gamble is only
   for the last $100 (88%). At $100 a month you don't need to bet at all.
4. **$10,000 is a lottery at any budget:** 4.8% to 10% at best, with a 90–95% chance of ending at $0. No tier
   changes that; only a bigger budget or a longer horizon would.
5. **The riskiest tiers' downside is visible:** monthly tickets lose most of the month's money in 68–94% of months;
   let-it-ride ends at $0 in 76–86% of runs; bold play loses more than half in 46–96%.
6. **Parlays don't help.** They compound the vig (−13% for a 3-leg), so at equal stake they are worse than
   sequential singles. The 3-leg ticket's appeal is its low P(lose > ½) (20%), because it risks one deposit at a
   time and banks wins.

## Recommended default
**Tier 10, "Save, then bold"** (the `propose` default). At $75/month to $1,000 it reaches the target **88%** of the
time and ends at $0 the other **12%**. Its one-line odds: "bank $75 a month; in month 12, bet the $900 boldly on
−110 singles (about two bets): ~88% to reach $1,000, ~12% to lose it all."

If the owner wants a bet every month, the gentlest choice for $1,000 is **tier 6, "Monthly 3-leg ticket"**: 45% to
reach, 20% to lose more than half, and a $75 3-leg at about +596 hits ~12.5% of the time. For $2,500 or $10,000,
the honest answer is to lower the target or accept a 67–95% chance of ending at $0.

## Caveats
- Assumes a flat −4.55% per leg. Circa's −110 standard is close to that; underdog moneylines usually carry more vig
  (favorite–longshot bias), so tier 4 is a little optimistic. Line shopping (a better price) is the one real lever.
- No taxes, no pushes, and bets resolve independently. Same-game parlays are excluded (decided out of scope).
- "Bold play" assumes the owner can place as many bets as needed in a month and stakes of any size; real limits and
  minimums at Circa can bind.
- The models-only picks used by `propose` choose sides only. Their graded record is in
  `2026-11-13-model-picks-grade.md`; until they beat the close, the sim stays at −vig.

## Next steps
- Grade the moon ledger as it fills (`grade`, `status`), and compare it with tier 1 (keep the cash).
- Add an optional `--months` horizon to the ladder (e.g. 24 months) if the owner wants a $10k target to be
  realistic.
- Discord post on the 1st of each month (proposal + odds line) once the owner wants it.
