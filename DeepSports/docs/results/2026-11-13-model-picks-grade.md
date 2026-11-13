# Daily models-only picks (`mp-v1`): first grade and a walk-forward reference (2026-11-13)

**Question.** Is rule `mp-v1` (`analysis/model_picks.py`, DECISIONS 2026-11-13) any good? Per game, for
spread and total, it takes DeepSports' (DS) and ManualBets' (MB) edge in points past the line, keeps
bets where both agree on the side (strong: both >= 4, lean: both >= 3), and lists a top 5 (one per game,
ranked by the smaller edge, college spreads beyond 15 left out).

**Answer.** No evidence that it is. The live record (2 graded slates, 42 picks) is far too small to say
anything (top 7-3, strong 14-17, every interval spans 50%). On the bigger walk-forward reference, college
2025-26 (5,633 games, both models out of sample, against the closing line), every group sits at or below
break-even: strong 50.6% (1,679 bets, ROI -3.5%, day-clustered CI -7.6% to +0.7%), top 5 52.2% (628 bets,
ROI -0.3%, CI -8.1% to +7.4%). **Model agreement doesn't create an edge: the strong tier, where both
models disagree with the market most, does worst.** The rule is fine as a watch-only list; it should not
be read as a betting signal. In the NBA it almost never fires (no NBA pick in the graded slates).

## 1. Method
**Live grade** (`deepsports model-picks grade --slates ...`, new in this change). The rule is replayed on
each saved slate that carries ManualBets numbers (`manualbets.available`): the two ensemble-bets slates
of 2026-11-11 22:35Z (`ctx-v1+mb1`) and 2026-11-12 22:03Z (`+tools1`), and today's 14:00 model-picks run
(2026-11-13 22:03Z; its replay equals the saved `picks.json` exactly). The five older ensemble slates have no
ManualBets block and are skipped. Picks use the slate's own pre-tip lines and prices (DraftKings via
ESPN `pregame` rows); the slate builder already drops games tipping < 60 min after `created_at`
(`ensemble_bets.MIN_LEAD`; the earliest tip in these slates is 84 min after creation). The slates don't
overlap (0 shared picks). Graded at the slate's price, 1 unit each. **CLV** = points between the pick's
line and the latest `closing` row in `odds_snapshots`, from the bet side's view (positive = beat the
close), via `betting.grading.clv` with `sane_lines`. Read on a warehouse copy taken 14:05 PT after the sync.

**Walk-forward reference** (college only, see section 4 for NBA). Both models out of sample:
- DS: the saved walk-forward holdout predictions (`work/ncaab_prior_holdout_preds.json`, Nov 3 2025 to
  Jan 31 2026, weekly refits; `work/ncaab_v1_holdout_preds.json`, Feb 1 to Apr 2026). Mimics the live
  display choice: no-prior college v1 where both teams have >= 5 games, else the prior model
  (`ncaab-v1-early`).
- MB: `ManualBets/tools/college_walkforward.py --start 2025-11-01 --end 2026-04-15` (monthly refits on
  earlier games, frozen default parameters, which were tuned on 2024-25 only), run with `uv` inside
  `ManualBets/` against the warehouse copy (`COLLEGE_WAREHOUSE_DB`).
- 2026-27 so far (Nov 4-13): DS = the actual live pre-tip `predictions` rows (`created_at < tip`; all are
  `ncaab-v1-early`), MB = the same walk-forward tool with one refit before 2026-11-01.
- Lines: the closing spread and total (all half-points, so no pushes), price -110. The rule code is reused
  unchanged: each day's games become a pseudo-slate and go through `find_picks` / `top_picks` (so the top 5
  is per day, college only). CIs: ROI, day-clustered bootstrap (4,000 resamples).
- Script: `/Volumes/ExFATStorag/DeepSports/scratch/mp-grade/college_both_models.py` (one-off, imports
  only DeepSports; MB enters as a CSV). Outputs in the same folder.

## 2. Live record (2 graded slates; today's 42 picks pending)
All graded picks are college: the NBA got no pick (see section 4). CLV coverage 100% (every pick has a closing row).

| group | bets | W-L-P | win % (Wilson 95%) | units | ROI | mean CLV | CLV > 0 |
|---|---|---|---|---|---|---|---|
| top 5 | 10 | 7-3-0 | 70% (40-89%) | +3.20 | +32.0% | +0.20 | 40% |
| strong | 31 | 14-17-0 | 45% (29-62%) | -4.37 | -14.1% | +0.35 | 35.5% |
| lean | 11 | 7-4-0 | 64% (35-85%) | +2.35 | +21.4% | +0.18 | 27.3% |

| run | picks | top 5 | all picks | mean CLV (all) |
|---|---|---|---|---|
| 2026-11-11 22:35Z | 30 | 3-2, +0.67 u | 12-18, -7.07 u | +0.33 |
| 2026-11-12 22:03Z | 12 | 4-1, +2.54 u | 9-3, +5.05 u | +0.25 |
| 2026-11-13 22:03Z | 42 (5 top) | pending | pending | - |

CLV values are whole points (-1 to +4), and about half are 0: the 14:00 line usually equals the close. A
mean of +0.2 to +0.35 points on 42 picks is not distinguishable from 0. Note that the pregame and closing
rows come from the same feed (ESPN/DraftKings), so this CLV measures one book's line move, not the market.

## 3. Walk-forward reference: college, both models vs the closing line
**2025-26** (5,633 games, all matched in both models; 139 days). Break-even at -110 is 52.4%.

| group | bets | W-L | win % | units | ROI (95% day CI) |
|---|---|---|---|---|---|
| top 5 per day | 628 | 328-300 | 52.2% | -1.8 | -0.3% (-8.1 to +7.4) |
| top: spread | 142 | 70-72 | 49.3% | -8.4 | -5.9% (-19.1 to +7.7) |
| top: total | 486 | 258-228 | 53.1% | +6.5 | +1.3% (-7.3 to +9.9) |
| strong | 1,679 | 849-830 | 50.6% | -58.3 | -3.5% (-7.6 to +0.7) |
| strong: spread | 741 | 368-373 | 49.7% | -38.5 | -5.2% (-12.1 to +1.3) |
| strong: total | 938 | 481-457 | 51.3% | -19.8 | -2.1% (-7.7 to +3.9) |
| lean | 867 | 460-407 | 53.1% | +11.1 | +1.3% (-5.8 to +8.2) |
| lean: spread | 337 | 190-147 | 56.4% | +25.7 | +7.6% (-3.0 to +18.3) |
| lean: total | 530 | 270-260 | 50.9% | -14.6 | -2.7% (-11.3 to +5.6) |
| strong + lean | 2,546 | 1,309-1,237 | 51.4% | -47.1 | -1.9% (-5.6 to +1.9) |

**2026-27 to date** (Nov 4-13, 329 games with both models and a close, 9 days): strong + lean 130-125
(-2.7%, CI -10.9% to +7.8%), top 5 21-20 (-2.2%, CI -36% to +29%), strong 94-94, lean 36-31.

Reading: the lean-spread cell (+7.6%) is the only positive point estimate of size, its CI includes 0, and
it is one of 9 cells looked at, so it is a multiple-comparison candidate, not a finding. The tiers run the
wrong way (strong < lean), which is what you'd expect if large shared disagreements with the close are
mostly both models missing the same information (injuries, early-season roster changes). For context, DS
alone on the same season (`2026-11-06-ncaab-prior.md`): edge >= 3 spread 51.0-51.4%, edge >= 4 total
50.4-51.1%, all below break-even. Requiring MB to agree doesn't move that.

## 4. NBA
- **Spread only.** The ManualBets export has no NBA total (`export_predictions.exportNba` sends the h2h and
  spread models), so NBA totals can never be picked.
- **It rarely fires.** DS NBA edges are small (|edge| >= 3 in 7 of 23 NBA games across the three slates, none above 4.1); MB's are larger. In the
  two graded slates no NBA game had both >= 3 on the same side; today's run has 3 NBA leans (pending).
- **No both-models walk-forward.** ManualBets has no NBA spread walk-forward tool, and the NBA history it
  needs (`--data-dir` seasons before 2026-27) isn't on this Mac (only `2026-27_game_stats.csv` locally; the
  totals study ran on another data dir). Building one is a ManualBets task (adapt `tools/total_walkforward.py`
  to the spread target), more than the ~1 hour budget.
- **DS-only half, already answered** (cite, not re-run; `2026-11-06-sim-v1.1-prices.md`, 4,069 OOS NBA games
  Oct 2023 to Nov 2026, vs the close): spread edge >= 3, 757-749-8 (50.3%, CI 47.7-52.8%); total edge >= 4,
  932-1,002-6 (48.2%, CI 46.0-50.4%). Below break-even.

## 5. Caveats
- Live: 42 graded bets from 2 days, all college. Nothing can be concluded either way.
- The reference grades against the close at -110; live picks are at 14:00 lines and real prices. Live CLV
  is small and positive, so the close is a fair, slightly conservative proxy.
- DS's Dec-Jan 2025-26 was its own tuning window (v1 settings), and the Feb-Apr file is a different (no-prior)
  fit than the Nov-Jan arm; both are walk-forward, but DS numbers there are mildly optimistic. MB's default
  settings were tuned on 2024-25 only.
- MB in the reference is a monthly-refit model, not the exact model the live export used on a given day.
- The top 5 in the reference is per ET day over college only; live slates also include NBA (which rarely
  qualifies) and use the 14:00 slate's games only.

## 6. Verdict and next steps
- **Verdict:** keep `mp-v1` as a watch-only list; there is no sign of an edge. A year of college games
  says "both models agree by 3-4+ points" bets win about 51%, the same as either model alone.
- Grade it as data accrues: `model-picks grade` now reports CLV and coverage per tier, per league and
  per run. A forward claim needs a few hundred graded picks; pre-register the test before looking.
- If anything is worth a pre-registered forward test, it is the lean-spread cell (college), not the strong tier.
- NBA both-models reference: needs a ManualBets spread walk-forward (ManualBets task; needs the NBA history dir).
- Message wording: "Neither model has beaten the closing line" stays accurate; the strong/lean labels may
  suggest more confidence than the data supports.
