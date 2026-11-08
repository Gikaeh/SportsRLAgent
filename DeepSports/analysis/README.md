# Analysis

Code: `src/deepsports/analysis/` (importable, tested in `tests/test_analysis.py`,
`tests/test_model.py` and `tests/test_players.py`). Everything opens the warehouse **read-only**.
The descriptive reports read `games`, `teams`, and `odds_snapshots`; model v1 also reads
`team_game_stats`, the `team_game_context` view, and (only if switched on) `injury_reports`;
model v1.1 adds `player_game_stats` (and, only if switched on, the `pregame_injuries` view).

```bash
# plain-text report to the terminal, plus a Markdown copy
uv run python -m deepsports.analysis.report --out /Volumes/ExFATStorag/DeepSports/reports/analysis.md
# a different warehouse file
DEEPSPORTS_DB=/path/to/copy.duckdb uv run python -m deepsports.analysis.report

# model v1 walk-forward backtest (monthly refit by default; --refit season for yearly)
uv run python -m deepsports.analysis.backtest --out /Volumes/ExFATStorag/DeepSports/reports/backtest.md
# the same for v1.1, or both side by side on the same folds (+ permutation importance)
uv run python -m deepsports.analysis.backtest --model-version v1.1
uv run python -m deepsports.analysis.compare --out /Volumes/ExFATStorag/DeepSports/reports/backtest-v1.1.md
```

| Function | Module | What it returns |
|---|---|---|
| `home_court(con, seasons=None)` | `market.py` | Per season: n games, home win %, average home margin |
| `market_accuracy(con)` | `market.py` | Per season: closing-line favorite win %, home cover %, pushes, spread/total MAE; opening → closing movement |
| `elo_ratings(con, k=20, home_adv=100, carry_over=0.75)` | `elo.py` | Pre-game Elo and home win probability for every game, plus current ratings |
| `evaluate_elo(con)` | `evaluate.py` | Brier / log loss per season for Elo vs coin flip, home-team-always, and the closing market |
| `brier`, `log_loss`, `devig_probability`, `american_to_decimal` | `metrics.py` | Scoring rules and odds conversions |
| `build_features(con, include_injuries=False)` | `features.py` | One row of pre-game features per game (finished and scheduled) |
| `ModelV1().fit(rows)` / `.predict(rows)` | `model.py` | Win probability, home margin, total points |
| `predict_upcoming(con, model_version)` | `model.py` | Rows for the `predictions` table for every scheduled game (does not write) |
| `pretip_predictions(con, now=None, days=14)` | `record.py` | Rows for `predictions` for games tipping off in (now, now+days]; started games skipped (used by `deepsports predict`) |
| `prediction_record(con, league="nba", days=30)` | `record.py` | The `/api/predictions/record` payload, graded from the `prediction_results` view |
| `prediction_card(pred, home_abbr, away_abbr)` | `record.py` | The API `Prediction` object for one game |
| `walk_forward(rows)`, `evaluate_backtest(preds)`, `run_backtest(con, model_version=...)` | `backtest.py` | Out-of-sample predictions and their scores vs baselines and the market |
| `PlayerHistory`, `player_box(con)`, `PLAYER_FEATURES` | `players.py` | Model v1.1 rotation / availability / top-N player features (`build_features(include_players=True)`) |
| `make_model(version)`, `resolve_version(version)` | `model.py` | The model for `v1.0` or `v1.1` (any label other than `v1.1[-...]` means v1.0) |
| `compare(con)`, `permutation_importance(rows)`, `paired_deltas(a, b)` | `compare.py` | v1 vs v1.1 on the same folds, per-game differences with 95% CIs, out-of-sample importance |
| `TreeModel`, `oof_predictions`, `Blend`, `validate`, `holdout_predictions`, `holdout_report` | `ensemble.py` | Ensemble v2: boosted trees + Elo/v1.0/v1.1 blends, tuned on 2023-25, scored once on the 2025-26 locked holdout (`python -m deepsports.analysis.ensemble validate/holdout/report`; config in `models/ensemble_v2/`) |
| `RidgeRatings`, `ridge_features`, `college_rows`, `validate`, `holdout_predictions`, `holdout_report` | `ncaab.py` | College (men's D1) v1: Elo tuned for college + opponent-adjusted ridge ratings + the v1 linear models, tuned on Dec–Jan 2025-26, scored once on the Feb–Apr 2026 locked holdout (`python -m deepsports.analysis.ncaab validate/holdout/report`; config in `models/ncaab_v1/`). Results: `docs/results/2026-11-04-ncaab-v1.md` |
| `grade(bets, games, lines)`, `audit(...)`, `load_games`, `load_lines` | `betting/` | Bet grading: refunded pushes, -110 default, ROI with a day-clustered bootstrap CI, CLV, price sensitivity, drawdown; the 3x line-move audit; loaders shaped for both (from the edge study) |
| `nba_feature_test`, `ncaab_feature_test`, `paired_gap_comparison` | `feature_test.py` | Add candidate pre-tip columns to v1.x / ncaab-v1 and measure the change in the gap to the close (baseline must reproduce bit-for-bit) |
| `top8_load(games, player_stats)` | `fatigue.py` | Minutes by each team's top-8 in a time window before tip (edge study B3) |
| `select_bets`, `log_bets`, `paper_report`, `RULES` | `paper.py` | Forward paper-trade log of the three frozen watch-only rules (`deepsports paper log|report`) |

Seasons follow ESPN: `2026` means the 2025-26 season.

**Leagues.** `build_features`, `elo_ratings`, `closing_lines`, `player_box` and `market.final_sql` take `league` (`nba` default, `ncaab`). Line sanity limits are per league (`market.SANE_LIMITS`): NBA |spread| ≤ 40, totals 150–320; college |spread| ≤ 60 (real lines reach ±44.5), totals 100–220.

## What the numbers mean (plain language)

**Home court.** Teams win more often at home (familiar arena, no travel, crowd). "Home win %"
is the share of games the home team won; "average home margin" is how many points the home
team won by on average (negative means it lost on average). Only regular-season games at a
real home arena count (neutral-site games and playoffs are left out).

**Spread (point spread).** The betting market's guess of the margin. It is written from the
home team's side: `spread_home = -6.5` means the home team is expected to win by about 6.5 points
(it is the "favorite"); `+3` means the home team is expected to lose by about 3 (it is the
"underdog"). Spread 0 is a "pick'em" (a toss-up).

**Cover.** A team "covers" when it beats the spread, not just the other team. The home team
covers when `home margin + spread_home > 0`. Example: spread -6.5, home wins by 10 → 10 - 6.5 =
3.5 > 0, covered. If the sum is exactly 0 it's a **push** (bets are refunded); pushes are counted
separately and left out of the cover %. A well-set line has a home cover rate near 50%.

**Total (over/under).** The market's guess of the combined points of both teams. "Over %" is how
often the real total came in higher.

**MAE (mean absolute error).** The average size of a miss, ignoring direction. A spread MAE of
10 means the actual margin differed from the spread by 10 points on a typical game. Lower is
better. NBA closing spreads typically miss by around 9-11 points: single games are noisy.

**Opening vs closing line.** Books post an "opening" line days before the game; it moves as money
and news (injuries, rest) arrive until the "closing" line at tip-off. We report how far it moved
and whether the closing line was the better guess.

**Moneyline and vig.** A moneyline is the price to bet on a team just to win. American odds:
`-150` means risk 150 to win 100; `+130` means risk 100 to win 130. Converting both sides to
probabilities gives numbers that add up to *more* than 100% (e.g. 60% + 43.5% = 103.5%). The
extra is the **vig** (the bookmaker's cut). We remove it by scaling both sides so they sum to
100%: `p_home = (1/dec_home) / (1/dec_home + 1/dec_away)`, where `dec` is decimal odds.

**Elo.** A rating system from chess. Every team starts at 1500. Before each game, the rating gap
(plus about 100 points for home court) gives a win probability: a 100-point edge is about 64%.
After the game, the winner takes points from the loser: more for an upset, more for a bigger
win (the "margin-of-victory multiplier", FiveThirtyEight's NBA formula). Between seasons each
rating is pulled 25% back toward 1500, because rosters change. The rating used to predict a game
is always the one from *before* that game; its own result is never peeked at.

**Brier score.** For probability forecasts: the average of (forecast - outcome)², where the
outcome is 1 if the home team won and 0 if not. 0 is perfect; always saying 50% scores 0.25.
Lower is better.

**Log loss.** Another probability score that punishes confident misses much harder (saying 95%
and being wrong costs a lot). 0 is perfect; always saying 50% scores 0.693. Lower is better.

**Baselines.** A model only matters if it beats something simple:
- *50/50*: every game is a coin flip.
- *Home always*: the home team wins with the home win rate seen in **earlier** seasons only.
- *Market*: the vig-free closing moneyline probability.

## Why the closing line is the benchmark to beat

The closing line is the price after the whole betting market has had its say: sharp bettors,
injury news, lineups, rest. People with real money on the line have pushed it toward the most
accurate number anyone can produce. It is hard to beat, and beating it consistently is the
standard test for a sports model. If our model can't match the closing line's Brier score / MAE,
it isn't adding information the market lacks. Elo uses only past scores, so expect it to be
**worse** than the market. It's a yardstick for later models, not a betting tool.

## Model v1: what it predicts

Three small models, each trained on past games and asked about the next ones:

| Model | Predicts | Type | Compared with |
|---|---|---|---|
| Win probability | Chance the home team wins | Logistic regression | Elo alone, "home always" rate, the closing moneyline |
| Home margin | Home points minus away points (negative = home loses) | Ridge regression | Elo-implied margin ((Elo gap + 100) / 28), the closing spread |
| Total | Both teams' points added up | Ridge regression | Recent league-average total, the closing total |

"Regression" here just means a weighted sum of the features below; the backtest report prints
the weights so you can see what the model leans on. They are deliberately simple models.

**Features** (all known before tip-off):
- `elo_diff`: home Elo minus away Elo, before the game.
- `home_court`: 1 at a normal home game, 0 at a neutral site.
- `rest_diff`, `b2b_home`, `b2b_away`, `g7_home`, `g7_away`: days of rest (capped at 4),
  back-to-backs (playing on consecutive days), games in the last 7 days. Tired teams play worse.
- `travel_home`, `travel_away`, `road_trip_away`: thousands of km travelled since the last game,
  and how many road games in a row the away team has played.
- `form_net_diff`: last 10 games' average (points scored minus points allowed), home minus away.
- `eff_net_diff`: the same per 100 possessions (offensive rating minus defensive rating), which
  removes the effect of fast or slow game pace. Possessions ≈ FGA − OREB + TOV + 0.44·FTA.
- For totals: `lg_total` (recent league-wide average total), `form_total`, `pace_sum`, `eff_sum`
  (how much both teams have scored and allowed lately, and how fast they play).

Recent-form numbers only use **earlier games of the same season**. Early in a season they are
pulled toward the league average (as if each team had already played 3 average games), so one
blowout in game 1 doesn't dominate. A game only counts as "known" 4 hours after its tip-off, so
two games on the same evening never see each other.

**Not features, on purpose:** betting lines. The market is what we compare against; feeding it
in would make the model look good while adding nothing of its own. **Injuries** have a hook
(`build_features(include_injuries=True)` adds "players listed Out" per team) but it is off:
older injury rows may have been recorded after the game started, which would be cheating.

## Model v1.1: player availability

v1.1 is v1 plus features about **which of a team's important players are likely to play**. Same
three models, same fixed settings; `predict_upcoming(con, model_version="v1.1")` (or
`deepsports predict --model-version v1.1`) uses it. Results: `docs/results/2026-11-04-backtest-v1.1.md`.

**Who counts as important (the "rotation").** Each team's players are ranked by minutes per
game over the team's last 10 games this season (a game a player missed counts as 0 minutes).
The top-6 are the core rotation, the top-3 the stars. Only games that had already finished
before tip-off are used, never the game being predicted: picking "top players" using the
minutes they went on to play in that game would quietly tell the model who played, which is
cheating (a mistake we saw in another project).

**What "availability" means here.** We have no injury history, so we use a **proxy**: a player
who did not play the team's previous game (missing from the box score or marked "did not play")
is probably still out. From that:
- `top6_out_last`, `top3_out_last`: how many of the top-6 / top-3 sat out the previous game.
- `top6_out_2of3`: how many of the top-6 missed at least 2 of the last 3 games (a longer absence).
- `miss_share`: the share of the top-6's usual minutes that belong to players who sat out last
  game. Losing a 36-minute star counts more than losing a 22-minute sixth man.
- `top3_since`: games since each top-3 player last played, added up (each capped at 5).

It's a proxy because "sat out last game" is not "will sit out tonight": players return from
injury, get rested on one night, or get hurt in the morning shootaround. The betting market
knows about those; we don't. That's why this can't be expected to beat the closing line.

**Player quality.** `top6_pm` adds up the top-6 players' recent plus-minus per game (the team's
score margin while each was on the court); `avail_top6_pm` does the same for only those who
played last game; `top3_pts` is the stars' points per game; `top6_pts_std` is how uneven the
top-6's scoring is (low = deeper team). Per-game numbers are pulled toward a neutral value when a
player has played only a few games. The win and margin models get home-minus-away differences;
the total model gets `miss_share_sum` and `top3_pts_sum` for both teams together.

**What we found.** The availability features help a little (margin error down about 0.03
points, win probability barely better); the plus-minus sums add nothing because they mostly
rebuild the team-form numbers v1 already has. v1.1 is still clearly behind the closing line.

**Injury hook (off by default).** From 2026-11-03 on, the pipeline stores pre-tip injury
reports. With `predict_upcoming(..., injury_override=True)`, an upcoming game that has a
pre-tip report uses it instead of the proxy: a top-6 player counts as missing if (and only
if) he is listed Out. It is always off in the backtest (there is no history to test it on)
and never applies to completed games.

## How to read the backtest

A **backtest** replays history: for each month of each season, the model is trained only on
games that happened *before* that month, then predicts that month's games. Its predictions are
then scored against what actually happened. That is "walk-forward": the model never sees the
future, just as it won't in real use. The first season is skipped (Elo needs a season to
warm up) and the second season is only used for training. The report's "Fold check" line
confirms no training game tipped off after its test month began.

- **Win probability table:** Brier and log loss (lower is better; see above) for v1, Elo alone,
  and "always give the home team its usual win rate". The right-hand columns repeat v1 next to
  the market on the games that had closing moneylines (`n mkt`).
- **Margin and total tables:** MAE in points. The "closing spread" column is how far the
  market's own guess missed on the same games.
- **Against the spread (ATS):** if v1 thinks the home team is at least `t` points better than
  the market does, we "bet" the home team to cover; if at least `t` worse, the away team.
  `hit rate` is wins / (wins + losses); pushes are refunded and left out.
- **Over/under:** the same idea on the total: bet the over when v1's total is at least `t`
  above the closing total, the under when at least `t` below.

**Break-even is about 52.4%, not 50%.** A standard bet is priced at −110: you risk 110 to win
100, so you need to win 110 / 210 = 52.4% of bets just to not lose money. `ROI at -110` is the
profit per unit bet. The **95% CI** column is the range the true hit rate plausibly lies in
given the number of bets. With 500 bets that range is about ±4.4 points wide, so a 54% hit
rate over 500 bets is still consistent with no real skill. Look for the whole interval above
52.4%, across several seasons, before believing an edge. And the more thresholds you look at,
the more likely one of them looks good by luck.

## Beating the closing line (and why most models don't)

"Beating the closing line" means our predictions are more accurate than the final market
number (lower Brier / MAE), or that betting where we disagree with it wins more than 52.4% of
the time. The closing line already reflects every public statistic we use (Elo-like ratings,
rest, travel, form) *plus* things we don't have: confirmed lineups, late injury news, and the
money of professional bettors who are paid to find mistakes. So a model built only from box
scores will usually be close to the market but a bit worse, and that is a normal, honest
result. v1's job is to be a well-measured starting point. Real edges, if any, usually come
from information that arrives late (injuries, rest decisions) or that the market weighs badly,
and they are small.

If a backtest ever shows v1 clearly beating the closing line, the report flags it as a probable
bug. The usual culprits are leakage: a feature that accidentally uses the game's own result,
the market's numbers, or data recorded after tip-off.

## Method notes and assumptions
- **Games used:** `completed AND status = 'STATUS_FINAL'`. Home court uses regular season
  only; market accuracy and Elo use regular season, play-in, and playoffs (`season_type` 2, 3, 5;
  preseason left out). `neutral_site` NULL is treated as not neutral. Neutral games get no Elo home edge.
- **One line per game:** the latest `closing` row and the earliest `opening` row.
- **Bad values are dropped:** spreads with |x| > 40 and totals outside 150-320 are excluded
  (ESPN's core API sometimes puts a decimal price where the total should be). The report shows
  how many were dropped.
- **Walk-forward:** Elo updates game by game in tip-off order, so every probability is made
  before the game. The first season is an Elo warm-up (everyone starts at 1500) and is left
  out of the "overall" row. Comparisons use the same games for every model (the `n` columns).
- **Model v1 settings are fixed in advance**, not tuned on the backtest (logistic C = 1, ridge
  alpha = 10 on standardized features; Elo K = 20, home edge 100). Tuning them on the same
  games we report would flatter the results. Missing values (e.g. no rest days before a
  team's first game) are filled with the training-set average.
- **Leakage tests** (`tests/test_model.py`): changing every result after a date leaves all
  earlier features and predictions identical; folds never train on a later game; the
  logistic model recovers the known Elo slope (ln 10 / 400) on synthetic data.
- **Player-feature leakage tests** (`tests/test_players.py`): rewriting the predicted game's own
  minutes / DNPs leaves its features identical; a game 1 hour later sees no player history;
  the columns a model trains on are exactly the ones `predict_upcoming` builds (a missing column
  raises an error instead of being silently filled); v1's predictions are identical with or
  without the player columns present.
- **Not yet:** tuning K / home advantage and model settings on early seasons only, injury
  features once enough pre-tip snapshots exist, and lineup-level (who plays with whom) strength.

## College v1 (NCAAB): what's different

College has ~360 D1 teams, about 30 games each, and very uneven schedules. A team can beat four weak
opponents by 30 and still be average. So v1's raw "last 10 games" form mostly measures who a team
played. College v1 keeps the v1 models and adds two things:

- **Opponent-adjusted ratings ("ridge" or Massey ratings).** Every team gets an offense number and a
  defense number such that, over the games played so far, *points scored ≈ league average + my offense +
  opponent's defense + home edge*. They're solved by least squares, refit before every tip-off on the games
  finished by then, and pulled toward 0 as if each team had also played one game against an
  average opponent (ridge λ = 1), so a team with two games isn't rated on two games. They give a
  predicted margin (`rt_margin`) and total (`rt_total`) for every game.
- **College Elo:** a higher K (60: there's no previous season to start from, so ratings must move
  fast) and a smaller home edge (60 Elo points), both picked on Dec–Jan games only.

**Non-D1 opponents** (Division II, NAIA schools ESPN lists only as opponents) play just 1–3 D1 games
each, too few to rate. They're pooled into one "non-D1" team. Their games count toward the D1 team's
history but are never predicted or scored. **Neutral sites** (tournaments, early-season events)
get no home edge. **Early season:** models train only on games where both teams have played at least 5
games, so mid-November noise doesn't drive the weights.

Result: clearly better than Elo, well calibrated, still behind the closing line (by less than the NBA
model is), and no profitable flat bets. See `docs/results/2026-11-04-ncaab-v1.md`.
