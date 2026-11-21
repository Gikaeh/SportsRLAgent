# College walk-forward on older seasons, and et-v1's cell per season (2026-11-20)

**Question.** With college 2021-22 and 2022-23 now in the warehouse, how do both models (DeepSports
(DS) and ManualBets (MB)) score out of sample on 2021-22 → 2024-25, and does et-v1's study cell (totals,
both models on the same side, average edge >= 4) hold up outside 2025-26?

**Answer. The 2025-26 edge doesn't show up in any earlier season.** Against the opener it wins 57.0%
in 2025-26 (this run reproduces the 56.8% study), but only 52.6% in 2023-24 and 51.2% in 2024-25, with
ROI around 0 or negative and every CI spanning 0. Against the close it sits at 50.6-52.8% in all five
seasons. Both models trail the closing total's MAE by 0.2-0.4 points every season. et-v1's
forward test continues as pre-registered (watch-only, verdict at 300 bets). This weakens the reason to
buy timestamped history: untimestamped openers already favor the rule, and on two more seasons it
shows nothing even with that help.

## Method
- Warehouse copy taken 2026-11-20 10:57 PT (no writer active). Work folder:
  `/Volumes/ExFATStorag/DeepSports/work/walkforward-2026-11-20/` (`ds_walkforward.py`, `evaluate.py`,
  outputs, logs).
- DS: `ncaab_prior.holdout_predictions` with the frozen configs (`models/ncaab_v1`, `models/ncaab_prior`)
  and the window moved to 2021-12-01 → 2025-11-01; weekly refits on all earlier games. Both arms are kept;
  the DS number is chosen as live (ncaab-v1 at >= 5 games, else ncaab-v1-early). It starts Dec 1 because
  no game has 5 prior games in November 2021 (nothing to train on). 21,137 games, 75 s.
- MB: `ManualBets/tools/college_walkforward.py --start 2021-12-01 --end 2025-11-01` (monthly refits,
  frozen default parameters), `COLLEGE_WAREHOUSE_DB` = the copy. 21,189 games.
- 2025-26: the existing study inputs (`work/ncaab_*_holdout_preds.json`, `scratch/mp-grade/mb_college_2026.csv`).
- Grading: et-v1's cell (both edges > 0 on one side, (DS + MB)/2 >= 4) vs the opening total at its real
  price, and vs the closing total at -110. ROI CI: day-clustered bootstrap, 4,000 resamples.

## Results (games with DS + MB + a closing total)
| season | n | MAE close / DS / MB / avg | cell vs open: W-L-P, win %, ROI (95% CI) | cell vs close (-110) |
|---|---|---|---|---|
| 2021-22 | 4,325 | 12.84 / 13.09 / 13.32 / 13.10 | no openers | 598-534-11, 52.8%, +0.8% (-4.7 to +6.4) |
| 2022-23 | 5,551 | 12.94 / 13.14 / 13.29 / 13.11 | no openers | 675-620-5, 52.1%, -0.5% (-5.7 to +4.6) |
| 2023-24 | 5,609 | 12.97 / 13.30 / 13.41 / 13.27 | 704-634-12, 52.6%, +0.2% (-5.3 to +5.6) | 773-750-12, 50.8%, -3.1% (-7.8 to +1.9) |
| 2024-25 | 5,642 | 12.65 / 13.05 / 13.07 / 12.99 | 709-677, 51.2%, -4.5% (-9.4 to +0.3) | 714-698, 50.6%, -3.5% (-9.2 to +2.0) |
| 2025-26 | 5,616 | 13.36 / 13.73 / 13.82 / 13.70 | 906-683, 57.0%, +8.8% (+4.3 to +13.1) | 816-763, 51.7%, -1.3% (-5.8 to +3.1) |

Games-played filters vs the opener (rt_n >= 5 / >= 10): 2023-24 51.8% / 51.4%, 2024-25 51.2% / 51.0%,
2025-26 57.6% / 56.7%. The filter doesn't rescue the earlier seasons.

## Caveats
- Settings were picked on later data (v1: Dec 2025-Jan 2026; the prior: Nov 2024-Jan 2025). Games in the
  older seasons are never in a fit before they're predicted, but 2025-26 is the season the settings were
  tuned on, which is one candidate explanation for its edge. 2021-24 are the cleanest seasons.
- Opener sources differ by season: 2023-24 mostly DraftKings (mean |open - close| 1.80), 2024-25 ESPN BET
  (1.55), 2025-26 "Draft Kings" (2.01). 2025-26's openers moved most, so they may have been staler. The
  2023-24 DraftKings openers show no edge either.
- 2021-22 begins Dec 1 with only one month of history to train on; read it as warm-up.

## Follow-up: does the line move toward the models' side? (`movement.py`, `movement.out`)
Yes, every season: the bigger the average model edge vs the opener, the further the total moves toward that side
by the close. So the models carry real information about where the line goes. In 2023-24 and 2024-25 that
information was too small to win bets at the opener; 2025-26 had a larger move and the wins.

| season | et-v1 cell n | mean move toward pick | moved our way / against | win % at open |
|---|---|---|---|---|
| 2023-24 | 1,350 | +1.02 | 59% / 28% | 52.6% |
| 2024-25 | 1,386 | +1.01 | 56% / 25% | 51.2% |
| 2025-26 | 1,589 | +1.39 | 62% / 24% | 57.0% |

Reading: not pure luck, but 2025-26 was the strong end. A ~1-point CLV is not enough on its own in a typical
season; whatever edge exists depends on getting lines before they move.
