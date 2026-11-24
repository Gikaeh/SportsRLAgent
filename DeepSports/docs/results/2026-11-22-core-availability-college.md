# Core-player availability vs et-v1 college totals: no signal (2026-11-22)

**Question.** ManualBets' NBA branch `feature/injury-adjustment` (Gikaeh, 2026-11-21) adds "core
availability" features: top-5 players by minutes per game who missed recent games. On NBA spreads they
cut test MAE by 0.20 (CI 0.12 to 0.28; `ManualBets/docs/results/2026-11-21-nba-availability-ablation.md`
on that branch). Does the same idea explain which et-v1 college totals win, or why big edges don't
win more (`2026-11-22-edge-size-vs-results.md`)?

**Answer: no.**
- **Pre-tip signals don't change the win rate.**
  - A team's top player missed its previous game: 52.2% at the opener (n=324) against 53.7% (n=3,524). By season it was 41.7%, 51.7% and 61.8%, so the sign flips.
  - Core players missed the last game, or were out for 2 of the last 3: every bucket is between 52 and 54%, with overlapping CIs.
- **Even a sit you can only know afterwards barely matters.** When a team's top player did not play this game, et-v1 won 52.4% (n=334) against 53.7%, with the sign flipping by season. When the top player played the previous game but sat this one (a surprise), it won 50.8% (n=126, CI 42 to 60).
- **Big edges are not absence artefacts.** Picks with an average edge of 8+ had fewer pre-tip absences (6.0% top player out) than picks at 4-6 (9.0%). So "the market knows about an injury the models miss" does not explain the flat edge-vs-win curve in college.

**Data.** The et-v1 cell from the edge study's `games.csv` (walk-forward DS + MB, opening and closing
totals), 2023-24 to 2025-26, with 3,848 bets carrying features. Core lists come from college
`player_game_stats`, using only games before each game; "did not play" means a DNP flag or 0 minutes.
Graded at the opener and the close, -110.

**Caveats.**
- The college box-score DNP flags are noisy: 47% of bets have at least one core player missing the previous game.
- College has no injury-report feed, so OUT or QUESTIONABLE status is unavailable.
- About 10 cuts were tried, with no correction applied. Nothing passed even uncorrected.

**Takeaway.** The branch's idea is sound for NBA spreads (stars matter, and the reports exist). For college
totals, availability that can be inferred from box scores adds nothing. No change.

Script and output: `/Volumes/ExFATStorag/DeepSports/work/factors-2026-11-22/injury/core_avail.py` (`.out`).
