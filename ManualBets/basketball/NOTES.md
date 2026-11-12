# Basketball: audit notes and open fixes

Audit of 2026-08-22, updated as items close. IDs (A1, B2, C1, ...) are cited in code comments
and `docs/DECISIONS.md`; keep them stable. Line numbers drift: re-check before editing. Full
history of the fixed items: `git log -p -- basketball/NOTES.md` and `docs/SESSION-LOG-ARCHIVE.md`.

## Owner rulings (2026-08-22)
1. **Injuries:** deferred by the owner. `data_pipeline/injury_data.py`
   (ESPN fetch + name matching, salvaged from `origin/injury`) exists but is not wired in. When
   revived, feed raw components (players out, production lost) to the model and let it learn
   the weights; no hand-tuned severity composite or probability multipliers.
2. **`total_l10`** means the average of the last 10 game totals; it equals `ppg_l10 + opp_ppg_l10`
   exactly, so it adds no information while both components are features (C-R1).
3. **Momentum and top-player ladders** were delegated to the agent (C-R2, C-R3). The ladders also
   serve future injury weighting, so keep the per-player slots.
4. **Market features** need no paid source: devig is arithmetic on prices already fetched, and
   timestamped snapshots accumulate in `data/basketball/odds_data/`. The limit is backfill depth.

## Fixed (kept so code references resolve)
| ID | Fix |
|---|---|
| A1 | Top-6 players chosen pre-game by `mpg_rolling` (`getTopPlayersAsOf`), same rule in training and prediction; missing slots zero-fill in both. Test: `tests/test_basketball_fixes.py::test_player_selection_is_pregame_only`. |
| A2 | Every training entry point splits by date, 80/10/10 (`shared/splitting.py::chronologicalSplit`). |
| A4 | Player-aggregate NaN-vs-zero skew closed by A1. Other NaN sources (team features) unreviewed. |
| A6 | `PTS_RANK`/`PLUS_MINUS_RANK` looked ahead; the rank features are no longer built and all models drop them (cached seasons still carry the columns). Models retrained 2026-11-08 on 27 seasons. |
| B1 | `odd_scraping.py` keeps only games not yet started (`upcomingGamesWindow`). |
| B2 | Spread/total line, price and book come from the same best-priced row (`bestOutcomeRow`). |
| B3 | `logRecommendations` works on a missing or empty log. |
| B4 | Exact spread/total landings grade `'P'` (stake-neutral). |
| B6 | `MIN_BET_AMOUNT = 1` drops $0 stakes before `calculateBetPriority` divides by them. |
| B13 | Grading reads each bet's own season (`getBetSeason`), not only the current one. |
| C1 | P(cover) = Φ(edge/σ), σ = validation `residual_std` in `models/metadata/basketball/retraining_*_metadata.json` (config fallbacks until present). |
| C2 | h2h edge is measured against the devigged two-way fair probability; the `market_prob` log column stores that fair probability. |

## Open ("Batch 4")
**Leakage / validity**
- **A4 (remainder)** The player-aggregate NaN skew is fixed (see A4 above), but the other NaN
  sources (team features) haven't been reviewed.
- **A3** Validation metrics double-dip: after tuning and early stopping on X_val,
  `evaluate(X_val)` is logged as `val_accuracy` (`model_retrainer.py`). Fix: hold out a final
  untouched window.
- **A7** (2026-11-11) Train/serve lag in team window stats: `createUpcomingMatchupData` takes each team's
  `groupby(...).last()` row of `calculateTeamWindowStats`, whose L10 values are shifted to exclude *that* game,
  so live features cover games N-11..N-2 while training covers N-10..N-1 (the latest result is left out).
  Affects every NBA model. Fix (changes model outputs, escalate): roll the window once more for the live row.
- **A8** (2026-11-11) Traded players: `getTopPlayersAsOf` (training) filters rows by team, so a traded
  player's old-team rows keep him in the old team's top 5 for the rest of the season; live
  (`use_game_date=False`) uses his latest row and puts him on the new team. Train/serve difference, not leakage.
- **A9** (2026-11-11) Neutral-site games where both nba.com rows say "@" (e.g. the 2025-26 NBA Cup final,
  0062500001) have no home row, so `createGameMatchupData` silently drops them from training and scoring.
- **A5** Per-model drop lists ("leakage_cols", mostly low-importance pruning) exist twice:
  `model_retrainer.retrainModel` and `live_data_updater.getPredictionReadyData`, synced by hand.
  Fix: one source of truth, e.g. the saved feature list next to each model.

**Bugs** (all in `betting/` unless noted)
| ID | Bug |
|---|---|
| B5 | `BettingRecommender(model_path=None)` crashes: `.split('_')` runs before the None default. |
| B7 | `getActiveBets` returns after the first existing file; the Active Bets menu re-prompts save and rewrites archive rows. |
| B8 | Stale config: Kelly confidence arg commented out, `UNDERDOG_KELLY_MULTIPLIER` unused, comments contradict values (`betting_config.py`). |
| B9 | Retrain status check (`countAvailableGames` → `getAllSeasonData`) refetches every season missing raw files just to count rows (`model_retrainer.py`). |
| B10 | `displayRecommendations` drops bets silently (totals skipped but counted in risk). |
| B11 | `displayModelWinRate` divides by zero on fresh logs. |
| B12 | `getCurrentSeason` flips on July 1, so mid-July runs target nonexistent files (`prepare_data.py`). |

**Feature plan** (decided, not yet applied; changes model outputs, so escalate first)
- **C-R1** Drop `home_total_l10`/`away_total_l10` (exactly `ppg_l10 + opp_ppg_l10`).
- **C-R2** Momentum: keep `plus_minus_diff`; drop `*_plus_minus_l10` and `*_top6_total_plusminus`.
- **C-R3** Collapse top3/top5/top6 ladders to one window per stat (top5), keep `*_top3_avg_ppg`;
  keep the `p1..p6_*` slot machinery so injury weights can apply per player before aggregating.
- **C3** Market features: devigged home probability plus spread/total lines as features, from
  persisted nightly snapshots (no historical backfill; XGBoost handles missing older rows).
- **C4** Availability features from player logs: top-6 players who missed the last 1/3 games,
  days since each top player played.
- Other ideas: aggregate makes/shots instead of averaging percentages (`fg_pct_l10`,
  `fg3_pct_l10`); schedule density (3-in-4) instead of a single back-to-back flag; pace-adjusted
  efficiency for totals; home/away split form; a season-stage index; re-check the h2h drop list
  (`opp_ppg_l10`, fg%) now that splits are clean; an odds freshness gate on `last_update`.
- Use `BasketballH2HModel.analyzeFeatureImportance()` (permutation importance + redundancy) for
  pruning on clean splits; pruning lists from the old side branches came from leaky validation.

**Injury module requirements ("Tier-2")** (before wiring `injury_data.py`)
1. Dated append-only snapshots (`injury_data/archive/injuries_YYYY-MM-DD.csv`, already written)
   so training has point-in-time history.
2. Weight statuses (QUESTIONABLE is not OUT).
3. Raw components to the model, no magic-constant composite.
4. A staleness gate: never use an old snapshot.

Smoke checks of `injury_data.py` must pass a temporary `data_dir`; the default writes into the
real `data/basketball/injury_data/`.
