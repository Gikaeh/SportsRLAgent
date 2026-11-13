# To The Moon: sports-betting version (proposal, not started)

Owner request (2026-11-13): build a sports-betting version of DeepStocks' "To The Moon" in this
repo. Status: **idea only**. Before building, it needs a decided integration step logged in
`docs/DECISIONS.md` (AGENTS.md "Direction").

## What it is (carried over from DeepStocks)
Reference implementation: `~/Projects/DeepStocks` → `docs/MOON.md` (engine/method),
`docs/TO_THE_MOON.md` (user guide), `src/deepstocks/moon/` (api.py contract, tiers, sim, picks,
ledger, Textual TUI), `docs/results/2026-11-13-moon-risk-ladder.md`.
- A small real budget each month ($50–100). The owner places every bet (non-negotiable 1);
  the app proposes, sizes, simulates and keeps score. It never places, automates or transmits a
  wager.
- **Risk tiers + simulator with honest odds:** P(reach $X), P(touch $X), P(lose > half),
  median/p10/p90, and the share of months where the new money is mostly lost.
- **Append-only ledger** of real bets (rule 3), and a benchmark (stocks used SPY DCA; here use
  "just keep the cash", or flat 1-unit bets on the model).
- **Monthly proposal** with a one-line odds string, plus a Discord post on the 1st.
- **Lessons from the stock build:**
  - Quantify hindsight bias; the first momentum numbers were inflated about 2x.
  - Check the riskiest tier for "too good" downside stats. The first options sim hid that 90% of
    monthly lottery tickets go to zero.
  - A "cash-out at target" rule was the best default tier.

## Why betting is different (what the sim must model)
- **The expected value is negative unless we have an edge, and our own results say we don't.**
  DeepSports' sims: closing line → $0 on every market
  (`DeepSports/docs/results/2026-11-06-sim-v1.1-prices.md`). No model beats the close, and the
  ensemble record is still being graded. So the default assumption is EV = −vig per bet. Any
  positive edge has to come from a graded record (CLV), never from model output alone.
- **With negative EV, bold play maximizes the chance of hitting a target** (Dubins–Savage): put
  the whole month's budget on few, big-odds bets rather than many small ones. That is the
  honest math behind "gambling-like". The sim should show bold vs timid play side by side.
- **Parlays compound the vig per leg,** and same-game parlays are priced with correlation, so
  either model the correlation or keep same-game parlays out of the sim.
- **Line shopping is the one real lever.** The best price across books (Odds API) cuts the vig
  and should be built into every proposal. Spend the Odds API quota sensibly and report
  `x-requests-remaining`.

## Candidate tiers (basketball only, NBA + NCAA)
1. Flat straight bets on the model side when |model − line| > k (baseline, about −vig)
2. Moneyline underdogs at +200 to +400
3. 2–3 leg parlays (different games)
4. 4–6 leg parlays / longshot player props
5. Futures (title, MVP, conference) when available
6. "Bold play": the whole month on one longshot. Variants: roll winnings forward, or cash out
   at the target.

## Data already in the repo
- DeepSports `odds_snapshots`: opening, closing and 30-min pregame captures; prices backfilled.
- Frozen models: v1.1 / v1.1i, `ncaab-v1`; calibrated probabilities.
- Paper-trade log and ensemble-vote records, graded by CLV.
- ManualBets: XGBoost per bet type, Kelly sizing, graded bet logs in `logs/`, and the Odds API
  (multi-book, live). Props and futures coverage need checking; DeepSports has no props data.

## Owner decisions before building
1. **Where it lives.** Options: a local TUI like DeepStocks' `tothemoon`, a BetDesk tab
   (BetDesk is this repo's app), or a ManualBets menu. Which project owns it?
2. **The ledger.** Either a new append-only CSV under `logs/<sport>/betting/moon_*.csv`, or a tag
   on the existing bet logs. `logs/` carries real stakes, which never leave the Mac except as
   open-bet labels.
3. **Code reuse from DeepStocks.** It's a separate repo, so copy and adapt the engine pattern
   (`moon/api.py` contract + sim + ledger), or extract a shared package later. No imports
   across repos.
4. **Bet types and books.** Which books the owner uses (best-price shopping), and whether to
   include props, futures and same-game parlays. Betting must be legal where the owner places it.
5. **Budget and targets.** Default $75/month; targets like $1k / $10k.
