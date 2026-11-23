# Pre-registration: live forward test of the momentum leads (night-before college totals)

Written 2026-11-23, **before the new live Odds API job has written any capture** (it is still being built; the
only file under `data/raw/oddsapi/live/` is one ad hoc college totals pull from 2026-11-19, which predates the
job and is excluded). Every rule below is fixed now. Changes go in dated "Amendment" sections at the end (what,
why, and whether any outcome had been seen), never by editing the text above. Watch-only research: nothing here
places, sizes or automates a bet. et-v1 (`2026-11-15-early-totals-preregistration.md`) and its live test are
not changed.

## Why
et-v2 (`2026-11-23-et-v2-results.md`) passed nothing: et-v1's cell at the 21:00 WH line lost -3.9% (n 3,470).
Seen **after** outcomes, so only leads: the market-momentum rules were the only positive ones (C4 +0.6% n 1,089;
K2 +3.6% n 603, K2 overs +9.4% n 350, mostly 2022-23); unders drained every rule; DraftKings lost less than WH.
The live context log (describe-only, 73 bets) has momentum >= 0 at 31-18 and < 0 at 9-13-1. These leads must be
tested on data that did not exist when they were found: the live captures from now on.

## Data
- **Live captures:** the new launchd Odds API job, every 30 min 12:00-21:30 PT plus 09:00 PT, college + NBA,
  totals + spreads, 10 books incl. `williamhill_us`, `draftkings`, `pinnacle`, files under
  `/Volumes/ExFATStorag/DeepSports/data/raw/oddsapi/live/`, until about 2026-12-23. Only college totals are used.
  The 10 books are the job's `bookmakers` list at its first run; a book added later is not used.
- **A capture** = one response file; its time is the request time (PT, DST-aware). A quote counts if the event's
  `commence_time` is after the capture time, the total is in 100-220, over and under points are equal, and the
  book's `last_update` <= the capture time. Events map to ESPN `game_id` with `et_v2_lines` (names + commence
  within 3 h).
- **Model inputs at T (the leak-critical part).** `predictions` is upserted per (game, model, version), and the
  08:00/14:00 syncs on D rewrite it; `.sync/manualbets-export.json` is overwritten by each run. So the D-1 19:00
  values are **not** recoverable later. Before night 1 counts, a read-only step at T must freeze, append-only, for
  every ESPN college game on D: the DS row (et-v1's `load_predictions`: latest `model='v1'` row with
  `created_at` <= T, `ncaab-v1` first, else `ncaab-v1-early`; version, `pred_total`, `created_at`) and a copy of
  the MB export with its `created_at` (fresh = `created_at` <= T and age <= 36 h, et-v1's `MB_MAX_AGE`;
  MB total = `ncaab.games[].model.total`). A night with no frozen inputs is excluded; the only allowed fallback is
  a warehouse DS row whose `created_at` is still <= T (provably unchanged). Requested from `data-engineer`.
- **Grading:** final totals (`STATUS_FINAL`, home + away) and the ESPN close (latest `odds_snapshots`
  `source='closing'` total in 100-220), warehouse read-only. The context log (`reports/early-totals/context.jsonl`)
  and et-v1's 21:00 `bets.jsonl` are cross-checks only, never inputs.

## Definitions (all known at T)
- **Game day D** (ESPN date), **night D-1**. **T = the scheduled 19:00 PT capture on D-1** (request made
  19:00-19:10 PT). Why 19:00: the owner screenshots and bets at William Hill NV mostly 18:00-20:00 PT (live
  screenshot reads at 18:04 and 19:03 on the last two nights); 19:00 is the middle of that window and a capture
  slot. If the 19:00 capture is missing, use the 18:30 one, else the 19:30 one (flagged); else the night is out.
  T is that capture's request time, and every model cut uses the same T. Games: D1 `ncaab` on D, tip >= T + 60 min.
- **L, P:** `williamhill_us` total and each side's own price in the T capture. Missing price -> -110. No WH quote
  -> no bet in any arm.
- **Base cell (= et-v1 at T):** over edge `DS - L`, under edge `L - DS` (same for MB); bet the side where both
  edges > 0 and (DS edge + MB edge) / 2 >= 4.0. One side at most. Needs DS, fresh MB and L.
- **Opener O (book b):** b's total in the earliest capture on D-1 (09:00 PT on) that quotes the game, only if that
  capture is at or before T - 60 min (normally the 18:00 slot). b = `williamhill_us` when it has such an O;
  else b = `draftkings` if it has such an O and a quote at T; else momentum is undefined.
- **Momentum** m = s x (b's total at T - O_b), s = +1 over, -1 under (+ = the market moved toward the pick;
  root AGENTS.md "Reading line moves"). m = 0 (no move) counts as >= 0, as in C4.
- **Best line (H3):** among the 10 books quoting at T, the best number for the side (over: lowest total; under:
  highest), ties broken by the best price, then by book name. Graded at that book's line and price.

## Arms and hypotheses (Holm across H1-H3, family-wise alpha 0.05, one-sided)
| id | bets (each a subset of the base cell at T) | graded at |
|---|---|---|
| REF | the base cell, every bet (et-v1 at T). Reference only, not tested | WH L, P |
| H1 | base cell AND m defined AND m >= 0 (C4 analogue at T) | WH L, P |
| H2 | H1 AND side = over | WH L, P |
| H3 | exactly the H1 bets (selection still at WH) | best line and price among the 10 books |
H3 is an upper bound on line shopping: most of the 10 books cannot be bet from Nevada. A pass there says the
number matters, not that the owner can get it.

## Metrics
- **Primary:** ROI = units / bets, 1 unit at the graded price, pushes 0. 95% CI by day-clustered bootstrap
  (clusters = D, 10,000 resamples, seed 0). **p** (one-sided) = share of resamples with ROI <= 0.
- **Reported:** n, W-L-P, win % (decided bets) vs break-even (mean implied probability of the prices), CLV in
  points to the ESPN close (s x (close - L); mean, CI, share > 0), CLV to WH at 0@09:00 on D, nights covered.
- **Secondary (no test):** momentum < 0 complement; over/under split; O from WH vs DK; m = 0 vs m > 0; avg edge
  4-6 vs 6+; data segment (Odds API vs continuation sources, below); et-v1's own 21:00 bets on the same nights.

## Sample size: one month will very likely be inconclusive
et-v1 logged 97 bets in its first 7 nights (0-22 a night, about 14 on full nights). Assume 10-14 base-cell bets
a night at T (the December slate thins, especially Dec 19-25), ~65% with m >= 0, ~60% of those overs.
| horizon | nights | base (REF) | H1 | H2 |
|---|---|---|---|---|
| live job only, to ~D = 2026-12-23 | ~28 | 280-390 | 180-250 | 110-150 |
| to the end of the regular season (~D = 2027-03-07) | ~100 | 1,000-1,400 | 650-900 | 400-550 |
Detectable ROI (80% power, alpha 0.0167 = Holm's first step, per-bet SD ~0.95 units, cluster design effect
~1.2): n 200 -> +22% (win 64% at -110); n 400 -> +15% (60%); n 1,000 -> +10% (58%). 95% CI half-width at
n 400: about +-10% ROI. A realistic +3-5% edge needs ~6,000 bets. So this test can only find a large edge; a
fail does not show that a small one is absent. Backtest sizes for scale: C4 +0.6%, K2 overs +9.4%.

## Continuation and verdict (fixed now)
- **Continuation after the credits run out** is the owner's call, logged in DECISIONS.md by **2026-12-16**,
  before any interim number is computed: (a) a renewed Odds API key keeps the same instrument; or (b) free
  sources: L = OddsPapi Caesars feed from a 19:00 grab (a new grab, within the free tier), momentum from ESPN
  scoreboard (DraftKings) captures already in `odds_snapshots` (O = the first DK capture on D-1 at or before
  T - 60 min, b = DK always), DS/MB as above. Under (b) H3 cannot be graded and stops at the last Odds API night.
  Segment (b) is reported separately as well as pooled.
- **Verdict (one look):** at the first D on which H1 reaches >= 400 graded bets (that whole night included) or
  D = 2027-03-07, whichever comes first (about mid-January if collection continues), or at the last night with
  data if collection stops for good. No early stop, no
  interim test. An interim status (coverage, counts, CLV) may be written; ROI/win % are not computed before the
  verdict except as et-v1's existing describe-only context log already shows them.
- **PASS (per hypothesis):** Holm-adjusted p < alpha AND ROI > 0 in both date halves of its own bets AND
  n >= 150. H3 counts only if H1 also has ROI > 0.

## What each outcome means
- **H1 or H2 passes:** propose a new watch-only rule version (e.g. `mom-v1`) logged live at T beside et-v1, with
  its own pre-registered verdict; real money only by the owner's decision after that.
- **Only H3 passes:** line shopping, not momentum, is the lead; report which books supplied the best numbers and
  whether any is reachable from Nevada (Circa); no rule.
- **None pass:** momentum is dropped as a lead; a fail below 400 is labeled "inconclusive (underpowered)". The
  same nights are never re-tested with a changed rule. et-v1 continues to its 300-bet verdict either way.

## Build before night 1 (no back-filling; the first counted night is the first with all three)
1. The live job running with request times and next-day events in its captures (`data-engineer`).
2. The frozen model inputs at T (above) (`data-engineer`).
3. Grading code as an importable module with tests (`data-analyst`, reusing `et_v2_lines` / `et_v2_score`);
   it may land later but must implement this text.

## Caveats
`williamhill_us` is Caesars' out-of-state feed standing in for WH NV. H1-H3 overlap (Holm holds under any
dependence). Live DS/MB are daily refits, sharper than the et-v2 walk-forward numbers.

## Commit record (committed before any capture from the new live job existed; hash added in a follow-up commit)
