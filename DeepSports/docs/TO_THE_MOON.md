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
| `tiers [--budget 75 --target 1000] [--months 1]` | The risk ladder: every tier simulated side by side, best tier highlighted. `--months 1` = this month only (default 12); also on `sim` and `propose` |
| `sim --tier bold [--edge 0.02] [--no-cash-out] [--json]` | One tier in detail; `--edge` adds a HYPOTHETICAL run next to the −vig one |
| `propose [--tier mix] [--months 1] [--circa auto\|PATH\|off] [--format text\|discord] [--date YYYY-MM-DD] [--balance X] [--run DIR]` | Today's bet(s) for a tier, from the latest models-only picks run, repriced at Circa's lines when a lines file exists; `--format discord` is the short phone text |
| `log deposit --amount 75` | Record money put into the moon account |
| `log bet ...` / `log parlay ...` | Record a bet you placed, at the price you got |
| `log result --ref ID --result win` | Settle a bet by hand (games the warehouse doesn't have) |
| `log void --ref ID --note "why"` | Cancel a mis-logged row (a new row; nothing is edited) |
| `log adjust --amount -5 --note "why"` / `log note --note ...` | Balance corrections / free text |
| `log init` | Create the ledger with only its header |
| `status` | Balance, deposits, P&L vs keeping the cash, record, open bets |
| `grade [--dry-run]` | Appends a result row for every open bet whose games are final (read-only warehouse) |

Tiers can be named by id or key: 1 `cash`, 2 `timid`, 3 `units`, 4 `dogs`, 5 `parlay2`, 6 `ticket3`, 7 `ticket4`,
8 `ride3`, 9 `bold`, 10 `save-bold`, 11 `ticket2`, 12 `mix` (the default). `manual` is not a tier: it tags hand-placed
daily picks in the ledger. Every betting tier stops betting once the balance touches the target.

## The plan: one month at a time (decided 2026-11-13, root `docs/DECISIONS.md`)
- Each month you choose the deposit ($50-100). That deposit is the month's whole risk: no month stakes more
  than it, and winnings are never re-staked (set them aside with `log adjust --amount -X --note "withdrawn"`).
- **Default play (2026-11-14): `mix`, straights + a parlay.** A *card* is 2 singles at 6% of the month's
  deposit plus one 2-leg parlay at 4% (at $50: $3 + $3 + a $2 parlay, $8 at most a day; at $75: $5 + $5 + $3).
  Units and the sim use the plan's money: the deposit less manual stakes placed before the month's latest
  deposit (a top-up resets the base; later manual bets only cut what is left). 2026-11: $77 deposited,
  $27 of manual picks before the top-ups, so $50.
  The card is paced: each day may stake an even share of what is left of the month's deposit over the days left
  (plus the shares of idle days since the last bet). A day bets as much of the card as its share covers (singles
  first, then the parlay), so most days get a small bet instead of a full card every few days; the month's last
  day plays what is left. Sim at $50 for one month: ahead ~41%, loses more than half ~6%, mean end ~$47, ~20 bets
  (`docs/results/2026-11-14-moon-mix-tier.md`).
- **Every bet counts against the month's deposit, hand-placed `manual` ones too.** `propose` counts only the
  tier's own bets toward its card limits, but manual stakes shrink what is left (and make the next days smaller).
- The one-ticket plays stay available: `--tier ticket2` (the deposit on one 2-leg parlay, ~25% to hit) and
  `--tier ticket3` (the "moon month", ~12.5%).
- Avoid correlated legs (the odds assume independent legs) and check Circa's actual parlay price.

## Circa lines
`propose --circa auto` (the default) reads `<DEEPSPORTS_CIRCA_DIR or /Volumes/ExFATStorag/DeepSports/circa/lines>/
<today>.json`, which the Circa screenshot reader writes (`{"date", "read_at", "files", "lines": [{game_id, league,
away, home, market, side, line, price, rotation}]}`, line from the bet side's view). For each proposed leg, matched
by game id (else league + team names), market and side:
- same line and Circa's price at least the slate's price: **Circa's price** is used;
- a better line for you (+8.5 vs +8, Over 137.5 vs 138): **Circa's line and price**;
- a worse line, or the same line at a worse price: the leg is **dropped**, with a note;
- no Circa entry: the leg stays, marked "not on Circa screenshots: check by hand".
Parlay prices are recomputed from the leg prices (check Circa's own parlay price). A missing or unreadable file
falls back to the reference prices with one note line; `--circa PATH` reads another file, `--circa off` skips it.

## A month with the tool
1. Start of the month: deposit at the book, then `log deposit --amount 75`.
2. After the 14:00 model-picks run: `propose --months 1` (the 14:00 Discord message is `--format discord`). Each proposal shows the stake, the legs, a one-line
   odds string, e.g. `2-leg parlay +264: ~25% to hit at -vig (EV -8.9%), returns $273.00 on $75.00; Monthly 2-leg
   ticket reaches $250 in 1 month ~25% (sim)`, and the `log` command to copy.
3. **Check Circa.** Circa isn't in The Odds API feed. Legs found on the day's Circa screenshots are repriced
   (section above); the rest show the slate's reference price (ManualBets' best when better). Skip a bet if
   Circa's price or line is worse.
4. If you place it: copy the `log` command, fill in the price you actually got and your stake.
5. After the games: `grade`, then `status`.

Parlay legs are `GAME_ID:LEAGUE:MARKET:SIDE:LINE[:PRICE]`, with the line from the bet side's view and empty for a
moneyline, e.g. `--leg 401920123:ncaab:spread:home:-1.5:-110 --leg 401925820:ncaab:moneyline:away::280`.
Every leg must be a different game (no same-game parlays). Props and futures are out of scope.

## What the numbers mean
- **P(reach)**: the balance is at or above the target at the end of the horizon (`--months`, default 12).
- **P(up)**: you end ahead of keeping the cash (above everything deposited). With cash-out this equals **P(touch)**
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
