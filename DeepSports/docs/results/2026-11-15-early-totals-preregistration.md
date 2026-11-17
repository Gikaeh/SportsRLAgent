# Pre-registration: night-before college totals (`et-v1`), watch-only forward test

Written 2026-11-14, before any night-before (21:00) Caesars line was grabbed or looked at. Nothing below
may change once the first bet is logged; a change is a new version (`et-v2`) with its own count.
Watch-only: the command logs recommendations; it never places, automates or sizes a bet.

## Why
A research pass on 2025-26 college games (both models walk-forward, out of sample; scripts and outputs in
`/Volumes/ExFATStorag/DeepSports/work/improve-2026-11-14/`, `timing_study.py`/`.out`, `edge_study.py`/`.out`)
found that **totals** where DeepSports (DS) and ManualBets (MB) agree on the side and their average edge
is >= 4 points against the **opening** total won 56.8% (n = 1,574, ROI +8.3% at the real opening prices,
95% day-clustered CI +3.7% to +12.9%), and the market moved toward the pick by +1.2 to +1.7 points on
average. Against the close the same bets won 53.4%, at or near break-even: whatever edge there is lives
in line timing. Spreads showed nothing (every CI spans 0).

Reasons to doubt it, all of which this test is meant to settle:
- Opening rows in the warehouse have no posting time, so 56.8% is an upper bound (the opener may have
  been stale, or posted before information the model saw).
- DS was tuned on December-January of that season; 12 cells (2 markets x 3 thresholds x 2 filters) were
  looked at, and this is the best total cell but not an outlier among them (avg >= 3: 55.0%, >= 6: 56.5%).
- The only live 2026-27 evidence is weak: vs the first 30-min pregame capture, avg edge >= 4 won 51.4%
  (n = 107) and the line moved +0.16 points toward the pick.

## The rule, `et-v1` (exact)
- **Run:** `deepsports early-totals log` at 21:00 local (America/Los_Angeles) the evening before the
  game day, after the night-before Caesars grab. Default game day: tomorrow (local date).
- **Games:** NCAA men's D1 (`ncaab`), not started, regular season or postseason, local game day = the
  game day, tipping at least 60 minutes after the log time.
- **Line and price:** Caesars (our `williamhill`, OddsPapi feed) full-game total from the night-before
  grab, `books/williamhill/early/<date>.json`. Each side uses its own quoted line and price.
- **DS number:** the latest `predictions` row made at or before the log time, `ncaab-v1` when the game
  has one, else `ncaab-v1-early` (the display order, `ensemble_bets.DISPLAY_VERSIONS`). `ncaab-v1p` is
  not used. This matches the study (no-prior model at >= 5 games, prior model below).
- **MB number:** `ncaab.games[].model.total` in the ManualBets export (`DeepSports/.sync/manualbets-export.json`,
  written by the day's model-picks run), made at most 36 h before the log time. Gated games (fewer
  than 5 games played) count, as in the study.
- **Edges (points):** over: `model - over_line`; under: `under_line - model`; for each model.
- **Bet:** the side where **both** models' edges are > 0 and **(DS edge + MB edge) / 2 >= 4.0**. At most
  one bet per game (only one side can qualify).
- **Price:** the logged Caesars price for that side. Graded at 1 notional unit; no stake is recorded.
- **Idempotent:** the first logged row per (rule version, game) is the bet; a re-run never adds,
  changes or removes rows. Bets are appended to `reports/early-totals/bets.jsonl`; every run (including
  the nights with no bet or missing inputs) is appended to `runs.jsonl`, so skipped nights are visible.
- **No rest filter.** In the study, "both teams rested 2+ days" was a leak check: with no posting time
  on the opener, a back-to-back opener might predate a game the model had seen. The result was the
  same without it (56.8% vs 57.0% with it), and in this test that leak cannot happen: the line is the
  real 21:00 quote and both model numbers are timestamped before it. Filtering would drop ~17% of bets
  and slow the verdict. Each bet records `min_rest_days` and the rest >= 2 days split is reported
  as a secondary metric.

## Start, sample size, verdict
- **Start:** the first 21:00 run that has a night-before Caesars file, for game day 2026-11-15 or later.
- **Verdict at 300 graded bets** (final score in the warehouse). At ~5-10 qualifying games a night that is
  about 5-8 weeks. Running numbers from `deepsports early-totals grade` before then are for watching,
  not deciding; no early stop and no rule tweaks.
- **Primary metrics:**
  1. **CLV** = points between the logged Caesars total and the warehouse closing total (latest
     `odds_snapshots` row with `source='closing'`, sane limits applied), from the bet side's view
     (over: close - line, under: line - close). Mean with a 95% day-clustered bootstrap CI (clusters =
     game days, 4,000 resamples, seed 0).
  2. **Win %** at the logged line (pushes excluded), with ROI at the logged price (1 unit, pushes 0) and
     its 95% day-clustered CI. Break-even = the mean break-even probability of the logged prices.
- **Pass:** at 300 bets, the CLV CI's lower bound > 0 **and** win % >= break-even (point estimate).
- **Fail:** mean CLV <= 0, **or** win % < 50.0%.
- **Inconclusive** (neither): extend once, same rule, to 600 graded bets, then apply the same pass test;
  anything short of pass at 600 is a fail.
- With n = 300 the win % has a standard error of about 2.9 points, so win % alone can't separate 56.8%
  from break-even (~52.4%); CLV is the sharper test and win % is the guard that the CLV turns into wins.
  A pass means "worth the owner's decision on real money", not a proven edge.

## Secondary metrics (reported, not part of pass/fail)
- CLV > 0 share; CLV vs Caesars' own day-of total (the game day's regular `books grab` file, when the
  same side is quoted).
- Win % graded at the closing total (should be ~50% if the edge is only line timing).
- Splits: over vs under; average edge 4-6 vs 6+; DS `ncaab-v1` vs `ncaab-v1-early`; rest >= 2 days vs not.

## Caveats
- Caesars' out-of-state line stands in for William Hill NV (DECISIONS 2026-11-14); the closing total is
  DraftKings' (ESPN), so CLV mixes a book difference with the move. The day-of Caesars CLV checks that.
- Circa isn't in this test: its college lines post around 7 AM on game day, after the 21:00 run.
- The test needs the night-before grab and a fresh ManualBets export; nights without either are logged
  in `runs.jsonl` as skipped, not as bets.

## Amendment 2026-11-16 (before any et-v1 bet was logged)
**Why:** the night-before Caesars grab for 2026-11-16 returned 0 lines (OddsPapi had no Caesars college
totals at 21:00), so et-v1 logged nothing; Caesars was only a stand-in for William Hill NV, whose opening
lines the owner can see in the app. No bet had been logged (`bets.jsonl` didn't exist) and no outcome
was looked at, so this changes the input, not a result.
**Change:** the line and price come from the owner's William Hill opening screenshots for the game day
(`/circa` page, William Hill, "Tomorrow (opening)"; read by `circa read --early --book williamhill` into
`williamhill/lines/early/<date>.json`), and from the Caesars feed file for any game and side the
screenshots lack. Each bet row records `line_source` (`screenshot` | `feed`) and `book_read_at`;
`runs.jsonl` records `line_sources`. The rule, thresholds, start condition, metrics and pass/fail are
unchanged. The secondary "CLV vs Caesars' own day-of total" stays on the Caesars feed. Rule version
stays `et-v1`; the grade can be split by `line_source` if the two sources behave differently.
