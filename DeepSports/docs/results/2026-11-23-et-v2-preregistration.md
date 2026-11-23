# Pre-registration: et-v2 candidates for night-before college totals (backtest on The Odds API history)

Written 2026-11-23, **before** any timestamped historical line was pulled: the owner is buying one month of
The Odds API's historical plan, and no snapshot from it exists yet. Every rule, threshold and pass test below
is fixed now. Changes after the pull go in a dated "Amendment" section at the end (what, why, and whether any
outcome had been seen), never by editing the text above it. Watch-only research: nothing here places, sizes or
automates a bet. et-v1 (`2026-11-15-early-totals-preregistration.md`) and its live test are not changed.

## Why a v2
1. et-v1's backtest edge is measured against the ESPN opener (posted by ~16:00 PT the day before), and live CLV
   from the bet line is ~0 (`2026-11-22-line-move-prediction.md`).
2. Its cell won 52.6% / 51.2% vs the opener in 2023-24 / 2024-25 and 57.0% only in 2025-26, the season the
   settings were tuned on (`2026-11-20-college-walkforward-older-seasons.md`).
A v2 must win at the line actually available at bet time (21:00 PT, William Hill NV / Caesars; Odds API key
`williamhill_us`) and hold in every season, not only the tuning one.

## Data (pulled after this commit)
- `deepsports odds-api-history pull`, college (`basketball_ncaab`), markets `totals,spreads`, about 10 named
  books including `williamhill_us`, `draftkings`, `pinnacle`; snapshots `-1@18:00`, `-1@21:00`, `0@09:00` PT
  (possibly `-1@15:00`); seasons 2021-22 .. 2025-26. Only totals are scored here; spreads get no candidate.
- Model numbers: the existing walk-forward totals, out of sample, no refit for this test. DS = the 2026-11-20
  rebuild (`ncaab-v1` at rt_n >= 5, else `ncaab-v1-early`, as live); DS-alt = the 2026-11-22 `gd` walk-forward
  (`ncaab-v1.1alt`, `ncaab-v1-early` below 5 games, as the live shadow); MB = monthly refits
  (`ManualBets/tools/college_walkforward.py`). DS starts 2021-12-01, so 2021-22 is December onward.
- Results and closing totals: warehouse (copy, read-only), close = latest `odds_snapshots` row with
  `source='closing'`, sane limits applied, as in et-v1.

## Shared definitions (every candidate)
- **Game day D**, log time **T = 21:00 America/Los_Angeles on D-1**. Games: D1 `ncaab`, tip >= T + 60 min.
- **Line L, price P:** `williamhill_us` full-game total and each side's own price from the snapshot requested at
  T (the latest Odds API snapshot at or before T). Missing price -> -110. Missing WH quote -> no bet.
- **Edges:** over `model - L_over`, under `L_under - model`, per model. **avg** = (DS edge + MB edge) / 2.
- **Base cell:** the side where both edges > 0 and avg >= 4.0 (one side at most), i.e. et-v1 at L.
- **gp** (games played) = min over the two teams of the count of that team's current-season games (any
  opponent) with tip + `FINISH_LAG` <= T, the same visibility rule as `ridge_features`' `rt_n`, cut at T.
- **Move toward the pick** from line a to line b: over `b - a`, under `a - b` (+ = the market moved our way;
  AGENTS.md "Reading line moves").
- **Grading:** 1 unit at P; pushes are 0 and are left out of win %. Break-even = mean implied probability of P.

## Candidates (each is the base cell unless stated; all inputs known at T)
| id | rule (exact) |
|---|---|
| C0 | Baseline: the base cell with DS = `ncaab-v1` / `-early`. et-v1 re-scored at the 21:00 WH line. |
| C1 | The base cell with DS-alt (`ncaab-v1.1alt` `gd` total) in place of DS. MB, line, price unchanged. |
| C2 | Base cell AND avg >= 8.0 AND gp < 10. |
| C3 | Base cell AND Pinnacle quotes the total in the snapshot at T AND Pinnacle's line is on our side of or equal to WH's: over `L_pin >= L`, under `L_pin <= L` (the sharp book has moved at least as far toward our side). No Pinnacle quote -> no bet. |
| C4 | Base cell AND move toward the pick from the opener reference O to L >= 0. O = `williamhill_us`'s total in the earliest pulled snapshot on D-1 (15:00 if pulled, else 18:00); if WH has no quote there, O and L both come from `draftkings` (earliest D-1 snapshot and T). Neither -> no bet. |
| C5 | Base cell AND shrunk edge s >= 1.5, where s = b_DS x DS edge + b_MB x MB edge. For test season S, (b_DS, b_MB) come from OLS without intercept of (final total - L) on (DS - L, MB - L) over **all** games of seasons < S with a WH line at T and a final score; each b clipped to [0, 1]. Not scored in 2021-22 (no earlier season). |
| C6 | Base cell, skipped when WH is off-market in our favor: over skip if `median(others) - L >= 1.0`, under skip if `L - median(others) >= 1.0`; others = every other pulled book quoting the total at T. Fewer than 2 others -> not skipped. |
| K1 | C1 AND C6: the better model number plus the off-market guard. Both keep almost all volume and target different failures (altitude bias; stale WH line, the live Circa 1-9 lesson). |
| K2 | C3 AND C4: two market-confirmation signs. The edge study's finding 5 says picks win when the market later follows the models; these are the only pre-bet signs of that which looked alive live (momentum r = +0.27, n = 249; book disagreement). |

The 1.5 in C5 is fixed from first principles, not from data: with a result SD of ~17 points about the line,
P(win) ~ Phi(s/17), and s = 1.5 gives ~53.5%, about 1 point above -110 break-even. No other combinations count.

## Expected bets per season (from existing walk-forward data, vs the ESPN opener; counts only, no outcomes)
Openers exist for 2023-24 .. 2025-26 only; earlier seasons from the cell vs the close. The 21:00 WH line sits
within ~1 point of the opener live (mean -0.26, |0.97|), so counts at L should be similar.

| id | 2021-22 | 2022-23 | 2023-24 | 2024-25 | 2025-26 | basis |
|---|---|---|---|---|---|---|
| C0 | ~1,140 | ~1,300 | 1,350 | 1,386 | 1,589 | the cell vs opener (close for 21-23) |
| C1 | ~C0 | ~C0 | ~C0 | ~C0 | ~C0 | altitude study: 4,309 vs 4,304 bets over 2023-26; ~45 swap per season |
| C2 | | | 77 | 101 | 159 | gp proxied by rt_n; **~110/season, below the ~150 practical floor** |
| C3 | ? | ? | ? | ? | ? | depends on Pinnacle's night-before coverage (13 of 29 games mid-afternoon live); guess 30-60% of C0 |
| C4 | | | ~0.65 x C0 | | | live: opener -> screenshot move >= 0 for 47 of 68 picks |
| C5 | n/a | ? | ? (needs 2022-23 fit) | 495 | 594 | proxy fit vs opener on earlier seasons (b ~0.08-0.14 DS, 0.11-0.15 MB) |
| C6 | | | ~0.95 x C0 | | | WH vs DraftKings same-time mean abs 0.23-0.28 pts; 1-pt gaps are rare |
| K1 | | | ~0.95 x C1 | | | |
| K2 | | | ~0.2-0.4 x C0 | | | product of C3 and C4 shares; may fall below 150 |
Blank = same order as the season next to it. "?" = not knowable before the pull.

## Data sanity checks (on lines only, before any grading; outcomes not opened)
1. **Coverage** per season x book x snapshot: share of games with both model numbers that the book quotes. If
   `williamhill_us` at T covers < 60% of them in a season, that season is graded at `draftkings` at T instead
   (flagged in every table); if both are < 60%, the season is dropped for all candidates.
2. **Timestamps:** each response's `timestamp` within 30 min before the requested T (PT, DST-aware); every book
   `last_update` <= the snapshot time. Snapshot spacing before Sept 2022 is coarser (vendor), so 2021-22 gets
   the same check, not a pass.
3. **Event matching** to ESPN `game_id` by mapped team names + commence time within 3 h of ESPN's start:
   >= 95% of quoted events matched, unmatched listed.
4. **Line agreement** (mean, mean abs, % identical): DraftKings at the earliest D-1 snapshot vs the ESPN opener
   (2023-24 .. 2025-26), DraftKings at 0@09:00 vs the ESPN close, WH vs DraftKings at T. A mean abs > 2.0 pts on
   any of these means a mapping or timezone bug: fix it before scoring; the fix is logged, the rules don't move.
5. Totals outside the warehouse's sane limits are dropped and counted.
The sanity report is written and committed before the grading script is run.

## Metrics and pass test
- **Primary:** ROI at P per season and pooled, 1 unit, 95% day-clustered bootstrap CI (clusters = game days,
  10,000 resamples, seed 0).
- **Reported for every candidate:** n per season; W-L-P and win % at L; win % at the close (same side graded at
  the closing total, -110); CLV = move toward the pick from L to the close (mean, CI, share > 0); CLV to WH at
  0@09:00; break-even.
- **PASS** requires all of:
  1. ROI > 0 at L in **every** season with >= 100 bets, and >= 100 bets in at least 3 seasons;
  2. pooled win % > pooled break-even after **Holm** correction across the 9 hypotheses C0-C6, K1, K2
     (family-wise alpha 0.05, one-sided; p = share of the day-clustered resamples with win % <= break-even).
- **Practical:** >= 150 bets in each scored season (the owner bets ~5-15 a night). A passer below this is
  reported but can only be a secondary filter, not et-v2 on its own.
- **Tie-break among practical passers:** the highest pooled ROI lower 95% bound; within 0.5 ROI points, the
  rule with fewer conditions (C0 < single filters < combos).
- **Secondary (not pass/fail):** splits by gp < 10 vs >= 10, over vs under, avg 4-6 vs 6+; a leak check
  without games where either team played on D-1 (walk-forward models can see D-1 evening results that finish
  after T, ~8% of bets); C0 graded at DraftKings and at Pinnacle at T.

## What each outcome means
- **A practical passer (not C0):** it becomes the et-v2 proposal: a new pre-registered watch-only forward test
  at the live 21:00 WH line beside et-v1, the owner's decision. et-v1 keeps running to its 300-bet verdict.
- **Only C0 passes:** et-v1's premise survives at the bet line; no v2, et-v1 continues.
- **None pass:** et-v1 continues as pre-registered; no et-v2 from this data. The result is filed in
  `docs/results/` with all numbers; filters found by looking afterwards are exploratory only and need a new
  pre-registration plus forward data.

## Caveats
- `williamhill_us` is Caesars' out-of-state feed, a stand-in for WH NV (as live). Whether it exists in older
  seasons is unknown until check 1.
- Model numbers are walk-forward fits with weekly (DS) / monthly (MB) refits, not the live daily ones; 2025-26
  is still the season the settings were tuned on, so a pass that leans on it is weaker than one that doesn't.
- C2 and K2 are expected to be impractical by volume; they are tested because they are the hypotheses the
  2026-11-22 studies left open.

## Commit record
This document was committed before the Odds API pull; its commit hash is recorded on the line below in a
follow-up commit.

Pre-registration commit: `3970720d8be88f83f59a04fb196ebac245b557db` (branch `research/et-v2-preregistration`,
2026-11-23, before any Odds API historical snapshot was pulled).
