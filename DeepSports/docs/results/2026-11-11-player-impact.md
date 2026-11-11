# DeepSports player impact ratings and injury impact in points: a negative result

**Question.** Can per-player on-court ratings, combined with each team's expected rotation and
who is likely OUT, (1) improve on model v1.1, (2) give a usable "injury impact in points"
number, and (3) beat or anticipate the market (closing line, opening line, open-to-close moves)?

**Answer: no edge, and nothing gets wired anywhere.**
- **v1.2 (v1.1 + impact features) is not significantly better than v1.1 on the locked 2025-26
  holdout:** margin MAE -0.049 (day-clustered 95% CI -0.159 to +0.061), Brier -0.0017 (-0.0049
  to +0.0014). The train-period gain (-0.082, CI -0.140 to -0.024) did not hold up.
- **The other two candidate methods are about 0 on the holdout** (pm48 +0.002, rapm40 -0.015
  margin MAE), so the chosen method's train edge is at least partly selection luck.
- **What gain there is comes from team strength, not injury information.** v1.1 + full strength
  only: -0.055 on the holdout; v1.1 + proxy missing impact only: -0.001. Available strength
  correlates 0.93 with Elo.
- **The ratings fail face validity for stars** (rapm10 as of 2026-04-01, players with at least
  1200 minutes): Kevin Huerter +6.5 is No. 1, Nikola Jokic +2.8, Anthony Edwards -1.4, LeBron
  James -1.4. A Jokic absence comes out at about 1.5-2 points of missing impact, while the market
  typically moves 5+. As an "injury impact in points" number it is not credible for the absences
  that matter most.
- **Market:** v1.2 is clearly worse than the closing line and only level with the opening line.
  The pre-registered opening-line rule hits 52.0% (train) and 53.2% (holdout); neither CI clears
  52.4%.
- **Pre-registered outcome = drop.** The fallback ("ensemble context only") needed the
  missing-impact vs line-move correlation to exclude 0 in both periods. It does with Fisher
  intervals (holdout r +0.056, +0.002 to +0.110) but **not** with the slate-cluster bootstrap
  (holdout -0.007 to +0.114). Games on one slate share news and market moves, so the clustered
  interval governs (DECISIONS 2026-11-11).
- **Headroom only with a real pre-tip injury feed:** the leaked oracle (who actually played)
  gains -0.137 margin MAE on the holdout. On 47 snapshot games, missing impact from the real
  `pregame_injuries` OUT lists tracks the oracle far better than the proxy (r 0.79 vs 0.60). The
  ratings would need fixing first.

## Method
Pre-registered (appendix) before any number was computed; the selection result was frozen in an
addendum before the holdout run.

- **Data:** read-only snapshot `warehouse-2026-11-10.duckdb`; NBA; the same `build_features`
  rows, `iter_folds` monthly walk-forward and burn-in as the v1.1 report. v1.1 reproduces that
  report (e.g. 2026 Brier 0.2068, margin MAE 11.38).
- **Periods:** train/selection = test seasons 2024 + 2025; **locked holdout = 2026**; "live" =
  2027 (154 games), reported separately and never used for a choice.
- **Ratings** (`src/deepsports/analysis/player_impact.py`), refit for every slate (one US
  evening: tip - 10h UTC date). As-of = the slate's earliest tip; only games with tip + 4h <=
  as-of (`FINISH_LAG`). Window 730 days, half-life 365 days; regular season, play-in, playoffs;
  both teams must be NBA teams. A rating follows the player across teams; his expected minutes
  at a new team start fresh.
  - `pm48`: on-court plus-minus per 48 / 5, shrunk by 500 prior minutes toward 0.
  - `rapm10` / `rapm40`: ridge of the game margin per 48 on both teams' minute shares (5 per
    side) plus an unpenalized home-edge column; lambda 10 / 40.
  - All recentred to a minutes-weighted mean of 0; unknown players and overflow minutes = -2.0.
- **Injury impact in points:** rotation = the team's last 10 games this season; weight = minutes
  per game played x min(1, games played / 3), allocated to 240 minutes with a 40-minute cap. OUT
  players' minutes are **redistributed**. Missing impact = full - available strength. OUT = an
  explicit list (live: `pregame_injuries`), the proxy (missed the team's previous game; all
  backtest features), or the oracle (did not play this game; LEAKED, ceiling only).
- **v1.2** = v1.1 win/margin features + `imp_avail_diff` + `imp_missing_diff`; totals unchanged;
  fixed C = 1, alpha = 10. Oracle = v1.1 + oracle features.
- **Uncertainty:** paired per-game deltas with day-clustered (CR1, one cluster per slate) 95%
  CIs; correlations with Fisher and slate-cluster bootstrap (2000 reps) CIs; hit rates Wilson.

## Leakage checks
1. **Unit tests** (`tests/test_player_impact.py`, synthetic, no network), for all 3 methods:
   rewriting the predicted game's own box score leaves its features (and every earlier game's)
   identical while the oracle and the next game change; the `FINISH_LAG` boundary (a game 2h
   before t is excluded, 5h before is included); same-slate games don't see each other; a rating
   as of t is unchanged when every later result is rewritten. Also: explicit OUT lists, oracle
   columns only on request, non-NBA scheduled games excluded, redistribution, RAPM recovering
   known values.
2. **Real data, scrambled box scores:** 40 random slates (2024-2026), every game on a slate
   rewritten together (DNP flipped, minutes 48 - m, plus-minus negated), one slate at a time.
   **0/293** rewritten games' own proxy features changed; 283/293 oracle features changed (leaked
   by design; the 10 others are season openers with no rotation yet); **583/583** of the teams'
   next games changed, so the check has teeth. One slate at a time because ratings pool all teams
   over two seasons: rewriting many dates at once legitimately moves other games' ratings (a
   first all-at-once version reported 44/45 "changed" for that reason, not leakage).
3. **Independent validator, future perturbation:** every result after a cutoff randomized (and,
   separately, all later games deleted), then the whole pipeline re-run. Cutoff 2025-01-01: 0
   feature diffs on 4447 earlier games, 0/1804 earlier walk-forward predictions changed (v1.2 and
   oracle), 2312/2312 later ones changed. Cutoff 2026-02-01: 0 diffs on 6013 games, 0/3370
   earlier predictions changed, 746/746 later ones changed. The validator also reproduced every
   headline number.
4. **Sanity:** v1.2 and even the oracle stay clearly behind the closing line.

**Post-hoc fix (nothing re-chosen):** scheduled games against non-NBA teams (All-Star) skipped
the `teams` check that finished games already had; fixed with a test. Re-running `select` and
`report --scramble` gave byte-identical selection and identical scores everywhere except the
diagnostic Oct-Nov / Dec-Jun split, which now uses the slate date instead of the UTC month (16
games moved; holdout v1.2 Oct-Nov -0.059 before, -0.065 after).

## Results

### Method selection (train period only, n = 2640)
| method | Brier | log loss | margin MAE | d margin vs v1.1 (95% CI) |
|---|---|---|---|---|
| v1.1 baseline | 0.2118 | 0.6121 | 11.081 | - |
| pm48 | 0.2115 | 0.6115 | 11.060 | -0.022 (-0.067 to +0.024) |
| **rapm10 (chosen)** | 0.2097 | 0.6071 | **10.999** | -0.082 (-0.140 to -0.024) |
| rapm40 | 0.2104 | 0.6087 | 11.027 | -0.054 (-0.114 to +0.006) |

### v1.2 - v1.1 per candidate method (multiplicity check; day-clustered 95% CI)
| method | period | Brier | margin MAE |
|---|---|---|---|
| pm48 | train | -0.0003 (-0.0021 to +0.0015) | -0.022 (-0.067 to +0.024) |
| pm48 | holdout | +0.0013 (-0.0009 to +0.0034) | +0.002 (-0.062 to +0.066) |
| **rapm10** | train | -0.0021 (-0.0038 to -0.0005) | -0.082 (-0.140 to -0.024) |
| **rapm10** | **holdout** | **-0.0017 (-0.0049 to +0.0014)** | **-0.049 (-0.159 to +0.061)** |
| rapm40 | train | -0.0014 (-0.0032 to +0.0004) | -0.054 (-0.114 to +0.006) |
| rapm40 | holdout | -0.0002 (-0.0030 to +0.0026) | -0.015 (-0.114 to +0.084) |

Live 2027 (154 games, rapm10): Brier -0.0035, margin MAE -0.053 (CI -0.49 to +0.38): noise.

### Oracle ceiling, oracle - v1.1 (LEAKED: who actually played; never a model input)
| period | Brier | margin MAE |
|---|---|---|
| train | -0.0033 (-0.0052 to -0.0013) | -0.124 (-0.197 to -0.050) |
| holdout | -0.0039 (-0.0077 to -0.0001) | -0.137 (-0.282 to +0.008) |

### Where the gain comes from (post-hoc diagnostic, not part of the decision)
| period | variant (paired vs v1.1) | Brier | margin MAE |
|---|---|---|---|
| train | + full strength only | -0.0017 (-0.0033 to -0.0002) | -0.053 (-0.105 to -0.000) |
| train | + missing impact only (proxy) | -0.0002 (-0.0006 to +0.0003) | -0.023 (-0.041 to -0.005) |
| holdout | + full strength only | -0.0016 (-0.0044 to +0.0011) | -0.055 (-0.152 to +0.042) |
| holdout | + missing impact only | -0.0001 (-0.0010 to +0.0008) | -0.001 (-0.045 to +0.042) |
| train | v1.2, Oct-Nov (n=566) / Dec-Jun (n=2074) | -0.0007 / -0.0025 | +0.057 / -0.120 |
| holdout | v1.2, Oct-Nov (n=299) / Dec-Jun (n=1023) | -0.0040 / -0.0010 | -0.065 / -0.044 |

### Face validity (validator; rapm10 as of 2026-04-01, at least 1200 minutes in 2025-26)
- Top: Kevin Huerter +6.5, Kawhi Leonard +4.8, Lauri Markkanen +4.6, Cameron Johnson +4.6,
  Jarrett Allen +4.3 (SD 2.1 across 218 players). Stars: Jokic +2.8, Edwards -1.4, James -1.4.
- pm48 looks more plausible at the top (Gilgeous-Alexander, Holmgren, Wembanyama) but is
  team-confounded (5 of its top 8 are Thunder players) and gains nothing.
- Game-level minute-share ridge can't separate teammates who share the floor; it needs stint data
  or a box-score prior.

### Against the market (model - market per game; day-clustered 95% CI)
| period | model | line | d Brier | d margin MAE |
|---|---|---|---|---|
| train | v1.1 | closing | +0.0114 (+0.0081 to +0.0148) | +0.428 (+0.296 to +0.561) |
| train | v1.2 | closing | +0.0093 (+0.0060 to +0.0126) | +0.346 (+0.220 to +0.473) |
| train | v1.2 | opening | +0.0041 (+0.0010 to +0.0072) | +0.090 (-0.039 to +0.218) |
| holdout | v1.1 | closing | +0.0094 (+0.0048 to +0.0141) | +0.370 (+0.187 to +0.553) |
| holdout | v1.2 | closing | +0.0077 (+0.0033 to +0.0121) | +0.323 (+0.154 to +0.492) |
| holdout | v1.2 | opening | +0.0034 (-0.0008 to +0.0076) | +0.123 (-0.036 to +0.281) |
| holdout | oracle (LEAKED) | closing | +0.0055 (+0.0013 to +0.0098) | +0.233 (+0.083 to +0.383) |

Holdout closing line: Brier 0.1968, spread MAE 11.01; v1.2: 0.2044 and 11.33.

### Open-to-close line move: r(feature, close - open spread_home); expected sign +
| period | feature | r | Fisher 95% CI | slate-bootstrap 95% CI (governs) |
|---|---|---|---|---|
| train | imp_missing_diff | +0.042 | +0.003 to +0.080 | +0.004 to +0.080 |
| **holdout** | **imp_missing_diff** | **+0.056** | +0.002 to +0.110 | **-0.007 to +0.114** |
| train | imp_avail_diff | -0.138 | -0.176 to -0.100 | -0.181 to -0.095 |
| holdout | imp_avail_diff | -0.080 | -0.134 to -0.026 | -0.125 to -0.039 |
| train | orc_missing_diff (LEAKED) | +0.224 | +0.187 to +0.261 | +0.187 to +0.262 |
| holdout | orc_missing_diff (LEAKED) | +0.252 | +0.200 to +0.302 | +0.183 to +0.319 |

Bootstrap columns are the validator's; the tool's own bootstrap (seed 0) agrees (holdout
imp_missing_diff -0.008 to +0.115). Actual absences do move lines (oracle r about 0.25).
Available strength predicts moves toward the team the ratings like in both periods (the opener
underrates it); this is post-hoc and did not turn into a winning bet rule.

### Pre-registered rule: v1.2 side vs the OPENING spread when |edge| >= 2.0 (-110)
| period | model | bets | hit | 95% CI | ROI | CLV |
|---|---|---|---|---|---|---|
| train | v1.1 (ref.) | 1265 | 51.6% | 48.9-54.4% | -1.5% | 59.3% |
| train | **v1.2** | 1227 | 52.0% | 49.2-54.8% | -0.7% | 63.0% |
| holdout | v1.1 (ref.) | 736 | 53.5% | 49.9-57.1% | +2.2% | 54.9% |
| holdout | **v1.2** | 662 | 53.2% | 49.4-56.9% | +1.5% | 59.7% |
| live 2027 | v1.2 | 62 | 41.9% | 30.5-54.3% | -19.9% | 65.3% |

No CI clears 52.4%. CLV above 50% vs openers is cheap (v1.1 gets it too). These are an upper
bound on timing: ESPN gives openers no posting time, and about 27% of these games involve a
back-to-back, where the opener may predate the previous game the proxy uses.

### Pre-tip snapshot games (real `pregame_injuries` OUT lists, Nov 4-11 2026; descriptive)
63 games with a pre-tip capture for both teams, 47 completed. Agreement of missing impact (home -
away) with the oracle: snapshot OUT list r +0.79 (+0.65 to +0.88), proxy r +0.60 (+0.38 to
+0.76). The proxy's big misses are players returning from an absence (e.g. IND @ MEM 11-04:
snapshot -0.32, proxy -10.28, oracle -2.86). Per-game table: the generated report.

## Caveats
- **Selection luck:** three methods tried; the chosen one's train gain is 1.7x its holdout point
  estimate and the other two are about 0 on the holdout.
- **Ratings are crude:** game-level minute shares, no stints, no box-score prior.
- **Rotation model:** a team's first game of a season has no rotation (coverage 98.5%); a traded
  player's minutes start fresh; departed players linger in their old team's rotation for up to 10
  games. "No box-score row" can't mean "off the roster": 73% of rotation-player absences with no
  row end with the player returning to the same team (documented in the module).
- **Opening lines:** one `opening` row per game, no posting time, none before 2023-24.
- **Small samples:** 47 snapshot games; 154 live 2027 games.
- **Untuned constants:** decay 365 d, window 730 d, replacement -2, cap 40, `FULL_GP` 3.

## Recommendation
**Drop as a model feature and as ensemble context.** Keep the code as research tooling
(`player_impact.py`, `player_impact_eval.py`, tests, `analysis/README.md` rows). Nothing is wired
into `predict`, `pretip`, the API or the ensemble.

## Next steps (ROADMAP)
1. **Better ratings first:** a box-score prior (BPM-style, as RAPM's prior mean) or stint-level
   RAPM from play-by-play, gated on a face-validity check (stars in the top tier; a Jokic absence
   at 4-6 points) before re-running this backtest.
2. **If revisited, a `v1.2i` shadow** using the real `pregame_injuries` OUT lists at prediction
   time (like v1.1i), graded live; backtest it once 2-3 months of snapshots exist. The oracle's
   -0.137 holdout margin MAE is the ceiling.
3. Optional: the available-strength vs open-to-close move signal as its own pre-registered
   question (post-hoc here).

## Reproduce
```bash
cd DeepSports
export DEEPSPORTS_DB=/Volumes/ExFATStorag/DeepSports/scratch/player-impact/warehouse-2026-11-10.duckdb
uv run --frozen python -m deepsports.analysis.player_impact select --out <dir>/select.md   # ~2 min
uv run --frozen python -m deepsports.analysis.player_impact report --scramble --out <dir>/report.md  # ~3 min
uv run --frozen pytest -q tests/test_player_impact.py
```
Generated reports of this run and the validator's scripts (`stats.py`, `leak_future.py`,
`scale.py`): `/Volumes/ExFATStorag/DeepSports/scratch/player-impact/` (`report-v2.md`,
`select-v2.md`, `validation/`).

## Appendix: pre-registration (verbatim)
Written 2026-11-10 (local), before running any walk-forward on the snapshot
`warehouse-2026-11-10.duckdb`. Everything below is fixed; anything not listed here that shows up
in the report is labelled "diagnostic".

**Data and folds.**
- NBA, `build_features(con, include_players=True)` rows, `iter_folds` monthly refit, burn-in 1
  season (2022), min 1 training season (2023). Same machinery and folds as the v1.1 report.
- Periods: **selection / train period = test seasons 2024 and 2025** (2023-24, 2024-25).
  **Locked holdout = season 2026** (2025-26), scored once after the choice is frozen.
  Season 2027 (2026-27, ~150 games so far) = "live", reported separately, never used for choices.

**Player ratings** (as-of each slate; slate = games whose (tip - 10h) UTC date matches; as-of =
earliest tip in the slate; only games with tip + 4h <= as-of; season types 2, 3, 5). Shared:
exponential time decay, half-life 365 days; window 730 days; ratings follow the player
(athlete_id) across teams; recentred so the decayed minutes-weighted mean is 0; unknown players
and overflow minutes get REPLACEMENT = -2.0 points per 48.
- **M1 `pm48`**: shrunk on-court plus-minus per 48, divided by 5 (one of five on court),
  shrunk by 500 prior minutes at 0.
- **M2 `rapm10`**: game-level ridge ("RAPM-lite"): margin per 48 ~ sum(home minute shares x r)
  - sum(away shares x r) + home edge; shares sum to 5 per side; ridge lambda = 10; decay weights.
- **M3 `rapm40`**: same, lambda = 40.

**Team impact** (per team-game, pre-tip).
- Rotation: players who played in the team's last 10 games this season (finished before as-of).
  Weight = (minutes per game played) x min(1, games played / 3). Allocated to 240 minutes with a
  40-minute cap (water-filling); leftover minutes at REPLACEMENT.
- Full strength = sum(minutes/48 x rating). OUT players removed, remaining weights re-allocated to
  240 (redistribution, not subtraction) = available strength. Missing impact = full - available.
- OUT (proxy, model features): rotation players who did not play the team's previous game.
  OUT (live): explicit list (e.g. `pregame_injuries` status Out). OUT (oracle, LEAKED, ceiling
  only): rotation players who did not play this game.
- Features (home - away): `imp_avail_diff`, `imp_missing_diff`. Oracle: `orc_avail_diff`,
  `orc_missing_diff`.

**Models** (fixed settings, C = 1, alpha = 10, no tuning).
- Baseline v1.1 (registered). **v1.2 candidate** = v1.1 win/margin features + the 2 impact
  features; total model = v1.1's. Oracle = v1.1 + the 2 oracle features (ceiling only).
- Diagnostic: v1.0 + impact features.

**Selection rule.** Pick the rating method with the lowest pooled 2024+2025 out-of-sample
**margin MAE of v1.2**; if two are within 0.005 points, the lower log loss wins.

**Decision rule** (holdout 2026, v1.2 - v1.1 paired, day-clustered 95% CI).
- "Ship as model v1.2 (graded live)": margin MAE delta < 0 with CI excluding 0, OR Brier delta < 0
  with CI excluding 0, and no metric significantly worse.
- Else "ensemble context only" if missing impact predicts open->close line movement
  (correlation CI excludes 0 with the expected sign in BOTH train period and holdout).
- Else "drop".

**Market tests.**
- vs closing: Brier vs devigged closing moneyline; margin MAE vs closing spread (same games).
- vs opening: margin MAE vs opening spread (paired, day-clustered CI); Brier vs devigged opening ML.
- Line movement: Pearson r (Fisher 95% CI) between `imp_missing_diff` and (closing spread_home -
  opening spread_home); expected sign positive (home missing more -> spread moves toward away).
- **Opening-line rule (single threshold):** bet v1.2's side against the opening spread when
  |pred margin - (-opening spread_home)| >= 2.0 points; graded against the opening spread
  (push refunded), -110; Wilson 95% CI vs 52.4%; also CLV share (closing line moved toward our
  side). Train period and holdout reported separately. v1.1 under the same rule for reference.

**Addendum 2026-11-11 00:05 PST: selection result, frozen before the holdout run.** `select` on
test seasons 2024-25 only: v1.1 margin MAE 11.081; pm48 11.060; rapm10 10.999; rapm40 11.027.
Chosen: **rapm10** (`CHOSEN_METHOD` in `player_impact.py`). The holdout (2026) and live (2027)
seasons are scored next, once, with no further changes to methods or rules.

Note (not part of the pre-registration): it names a Fisher CI for the line-move test. Fisher and
the slate-cluster bootstrap disagree on the holdout; the clustered interval governs, consistent
with the day-clustered CIs every other decision uses (DECISIONS 2026-11-11).
