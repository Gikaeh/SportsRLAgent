# To The Moon (betting): user guide

A small monthly budget, honest odds of reaching a target, a proposal for today's bet, and a ledger of the bets you
actually place. **Watch-only: you place every bet yourself.** Nothing here places, automates or transmits a wager.

Code: `src/deepsports/moon/`. Decisions: root `docs/DECISIONS.md` (2026-11-13, "To The Moon (betting)"). Numbers:
`docs/results/2026-11-13-moon-risk-ladder.md`.

## The one thing to know
No model here beats the closing line, so **every bet loses the vig on average**: −4.55% per −110 bet, and parlays
compound it (−13% for a 3-leg). With negative expected value, the way to maximize your chance of hitting a target is
to bet **big and rarely** (bold play), never many small bets. The tool shows how big a risk that is.

## Commands
Run from `DeepSports/`: `uv run --frozen deepsports moon ...` (same as `python -m deepsports.moon ...`). Common flags: `--budget` ($ a month,
default 75), `--target` (default 1000), `--ledger PATH` (before the subcommand; default `logs/moon/bets.csv` at the
repo root, or `DEEPSPORTS_MOON_LEDGER`).

| Command | What it does |
|---|---|
| `tiers [--budget 75 --target 1000]` | The risk ladder: every tier simulated side by side, best tier highlighted |
| `sim --tier bold [--edge 0.02] [--no-cash-out] [--json]` | One tier in detail; `--edge` adds a HYPOTHETICAL run next to the −vig one |
| `propose [--tier save-bold] [--balance X] [--month N] [--run DIR]` | Today's bet(s) for a tier, from the latest models-only picks run |
| `log deposit --amount 75` | Record money put into the moon account |
| `log bet ...` / `log parlay ...` | Record a bet you placed, at the price you got |
| `log result --ref ID --result win` | Settle a bet by hand (games the warehouse doesn't have) |
| `log void --ref ID --note "why"` | Cancel a mis-logged row (a new row; nothing is edited) |
| `log adjust --amount -5 --note "why"` / `log note --note ...` | Balance corrections / free text |
| `log init` | Create the ledger with only its header |
| `status` | Balance, deposits, P&L vs keeping the cash, record, open bets |
| `grade [--dry-run]` | Appends a result row for every open bet whose games are final (read-only warehouse) |

Tiers can be named by id or key: 1 `cash`, 2 `timid`, 3 `units`, 4 `dogs`, 5 `parlay2`, 6 `ticket3`, 7 `ticket4`,
8 `ride3`, 9 `bold`, 10 `save-bold`. Every betting tier stops betting once the balance touches the target.

## A month with the tool
1. Start of the month: deposit at the book, then `log deposit --amount 75`.
2. After the 14:00 model-picks run: `propose --tier <yours>`. Each proposal shows the stake, the legs, a one-line
   odds string, e.g. `3-leg parlay +596: ~12% to hit at -vig (EV -13.0%); Monthly 3-leg ticket reaches $1,000 in
   12 months ~45% (sim)`, and the `log` command to copy.
3. **Check Circa.** Circa isn't in The Odds API feed, so the price shown is the slate's reference (ManualBets' best
   price when better). Skip the bet if Circa's price or line is worse.
4. If you place it: copy the `log` command, fill in the price you actually got and your stake.
5. After the games: `grade`, then `status`.

Parlay legs are `GAME_ID:LEAGUE:MARKET:SIDE:LINE[:PRICE]`, with the line from the bet side's view and empty for a
moneyline, e.g. `--leg 401920123:ncaab:spread:home:-1.5:-110 --leg 401925820:ncaab:moneyline:away::280`.
Every leg must be a different game (no same-game parlays). Props and futures are out of scope.

## What the numbers mean
- **P(reach)**: the balance is at or above the target after 12 months. With cash-out this equals **P(touch)**
  (it was at the target at some point).
- **P(lose > ½)**: you end with less than half of what you deposited.
- **p10 / median / p90**: 1 in 10 runs ends below p10, half below the median, 1 in 10 above p90.
- **Months mostly lost**: the share of months where more than half of that month's deposit was lost.
- **at −vig**: the measured reality. **HYPOTHETICAL edge**: a what-if only. An edge counts only once a graded
  record beats the closing line.
- The sim is a seeded Monte Carlo (20,000 runs, seed 7; `propose` uses 5,000). Results move by under a point
  between seeds.

## The ledger
`logs/moon/bets.csv` is **append-only**: rows are added, never edited or deleted. A mistake is fixed by a `void` row
(it reverses the row's amount; a voided result re-opens its bet) or an `adjust` row with a note. Stakes in it never
leave the Mac; the read API and BetDesk don't serve it. Columns: `id, created_at, kind, ref, month, tier, book,
league, game_id, bet, market, side, line, price, legs, stake, result, payout, amount, note`. `amount` is the cash
change: +deposit, −stake, +payout.

A parlay with a pushed leg pays the taken price scaled down by that leg's odds (−110 if the leg has no price).
