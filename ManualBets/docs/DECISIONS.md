# DECISIONS.md — running log of why

Append new entries at the bottom. If a decision is reversed, strike it through
(keep it visible) and point to the reversal. Never delete entries.

---

## ~~2026-08-21 — Single-agent workflow; no subagents~~

Reversed 2026-11-10: see "Development is agent-driven" below.

Solo owner, small mirrored codebase, one context is faster and safer than
role-splitting. Fabricating reviewer/builder subagents would add process without
changing outcomes. Revisit only if a genuinely separable concern appears (e.g.
sandboxed scraper fleet) — and record that revisit here.

## 2026-08-21 — pytest smoke tests as the verification gate

No tests existed, so "verify before done" had no teeth. Chose minimal smoke tests
(imports + bet-log integrity) over deep unit coverage because the codebase has no
test seams yet and heavy model training can't run in CI-style checks. Deepen later
around betting logic (edge math, Kelly sizing) once seams exist.

## 2026-08-21 — First deliverable: secrets cleanup

The Odds API key was found hardcoded in `hockey/data_pipeline/odd_scraping.py`,
`basketball/data_pipeline/odd_scraping.py`, and `baseball/odd_scraping.py`, and is
already in git history, so it cannot be made secret retroactively. Moving it to an
env var stops new exposure; key rotation is recommended to the owner but is their
call (it may cost quota or break daily use).

## 2026-08-21 — Bet logs treated as immutable append-only history

The CSVs in `logs/**/betting/` are the only record of what was recommended vs what
happened; silently editing them would corrupt the system's ground truth for grading
models. Corrections happen by appending rows or explaining in commit messages.

## 2026-08-21 — Bootstrap docs structure (AGENTS.md + docs/*)

Created AGENTS.md (constitution), docs/PROJECT.md, docs/DECISIONS.md,
docs/SESSION-LOG.md (+ARCHIVE), tests/, and documented tool invocations so any
future session starts cold with no external context.

## 2026-08-22 — Basketball audit recorded in basketball/NOTES.md; owner scoping rulings

Full basketball code audit (leakage, bugs, feature plan) written to
`basketball/NOTES.md` as the remediation spec. Owner rulings captured there:
injuries deferred (owner believed implemented; none exists for basketball — hockey's
is fully commented out); `total_l10` semantics clarified (owner's reading of the
feature was correct; removal rationale is exact collinearity with ppg_l10 +
opp_ppg_l10, not a misunderstanding); momentum and player-ladder restructuring
delegated to agent with injury-weighting intent preserved; market-feature concern
resolved as "devig is free math on odds already fetched" with historical-backfill
depth as the honest limitation. Rationale for a per-area NOTES file instead of
inline AGENTS.md content: findings are basketball-specific and long; AGENTS.md must
stay short and fully readable.



## 2026-08-22 — Basketball remediation Batches 1+2: implementation choices

- **Chronological split over season-list split** (`shared/splitting.py`): kept the
  repo's existing 80/10/10 proportions but ordered by date (earliest=train,
  latest=test). Season-boundary splitting would be marginally cleaner but a pure
  date split is simpler, sport-independent, and removes the leakage; walk-forward
  can come later without changing callers.
- **Pushes grade 'P', not refund rows or edits** (B4): grading now writes 'P' on
  exact spread/total landings. Bankroll and win-rate code only counts W/L, so
  pushes are automatically stake-neutral — no historical rows rewritten.
- **Player slots zero-fill in training too** (A1/A4): prediction always zero-filled
  missing top-6 slots; training previously left NaN. Aligning both to zero-fill
  makes train/predict distributions identical. Chosen during Batch 1 because it is
  the same code path as the leak fix and avoids burning a retrain later.
- **Best-price pairing for odds** (B2): when books disagree on lines, we take the
  single best-priced row and use ITS line/price/book together. Line-first
  shopping (best line, then best price at that line) may be better long-term but
  changes strategy — deferred to owner rather than snuck in.
- Regression tests live in `tests/test_basketball_fixes.py`; basketball modules
  are imported in subprocesses with PYTHONPATH because hockey/basketball share
  package names (`model`, `data_pipeline`) and cannot co-exist in one interpreter.

## 2026-08-22 — Batch 3 (C1+C2): normal-approx cover probs and devigged edge

- **σ source of truth:** ModelRetrainer computes validation residual std after
  each spread/total retrain and publishes it as top-level `residual_std` in
  `models/metadata/<sport>/retraining_*_metadata.json`; BettingRecommender loads it at
  init and falls back to `SPREAD_RESIDUAL_SIGMA_FALLBACK=11.8` /
  `TOTAL_RESIDUAL_SIGMA_FALLBACK=14.0` (league-typical placeholders) until the
  first post-fix retrain measures real values. Chosen over storing σ inside the
  model JSON because metadata already exists and is human-inspectable.
- **Normal approx over empirical binning:** Φ(edge/σ) with a measured σ is smooth,
  needs no bin choices, and degrades gracefully; empirical per-line frequencies
  would need years of clean data per line bucket. Push mass at integer lines is
  ignored — pushes grade 'P' and refund, so the effect is second-order.
- **Devig method:** proportional/multiplicative normalization of the two best
  available Nevada prices (fair = implied / overround). Mixing books' prices
  slightly misestimates the joint vig, but it matches the line-shopping reality of
  actually betting the best side price. `market_prob` in bet logs now stores the
  devigged fair probability — semantic change to that column going forward.
- Consequence, intended: devigged edges are ~2% higher than before and honest
  cover probabilities are lower than the old heuristics claimed — fewer, better-
  founded recommendations. MIN_EDGE_H2H=0.02 now means 2% vs FAIR prob.

## 2026-08-22 — Salvage from side branches instead of merging or rewriting

Reviewed origin/injury, origin/working, origin/new_player_data in depth. Verdict:
merge nothing (all predate the A1/A2 fixes and would reintroduce leak-era
assumptions); rewrite the injury system fresh per NOTES Tier-2 spec; transplant
three proven pieces by hand:
- ESPN fetch/matching layer → basketball/data_pipeline/injury_data.py (new file,
  unwired). Kept verbatim where safe; added dated archive snapshots (Tier-2
  requirement) and dropped the severity composite + probability/margin
  multipliers — the owner had already disabled those live on the source branch.
- Permutation-importance analyzer → additive BasketballH2HModel method,
  generalized so spread/total regressors can use it (scoring by model type) and
  returning a DataFrame for scripted use. Old branch's pruning LISTS are invalid
  (leaky val); only the tool survives.
- Vectorized rolling + cache: discovered main already contains identical
  shared/base_data_preparer.py helpers — no copy needed; wiring deferred until
  after the pending retrain to keep feature semantics frozen during rebuild.
no_injuries and fullstack-app have zero unique commits vs main; candidates for
deletion (owner call).


## 2026-08-25 — data/ untracked from git EXCEPT odds_data

All of data/ is fetched/derived and regenerable, so it was untracked (593 files)
to stop git bloat (~530 MB of blobs). Exception carved out via .gitignore
negation: data/*/odds_data/** stays tracked. Why: odds snapshots are the only
data the pipeline CANNOT regenerate — they are point-in-time market observations
consumed at recommendation time; once a game passes, those prices are gone unless
paid historical endpoints are used. They double as future training data for
market-feature work (NOTES.md C3/C4) and CLV checks. Cost is trivial (~360
files, 4.2 MB).

## 2026-08-25 — models/metadata restructured to per-sport subfolders

models/metadata/basketball/ and models/metadata/hockey/ now hold each sport's
retraining_*_metadata.json. Why: hockey's retrainer already auto-derived a
hockey/ subfolder while basketball wrote flat files with sport-ambiguous names;
the flat layout also made cross-sport glob accidents possible. BettingRecommender
residual-sigma loader and both main.py menus updated; hockey folder materializes
in git on first hockey metadata write.

## 2026-11-07 — Initial-model splits aligned to 80/10/10 chronological

`initial_*_setup.py` still used `train_test_split(random_state=42)` (60/20/20)
after the A2 retrainer fix. Converted to `chronologicalSplit` at 80/10/10 — the
same rule as `ModelRetrainer` and `tools/pipeline_smoke_test.py`. Why: a single
split rule across every training entry point removes the cross-season leak and
keeps "initial model" vs "retrained model" metrics on the same kind of holdout.
Cost: initial-model metrics will drop vs the old leak-inflated numbers; that is
the expected correction, not a regression.

## 2026-11-08 — College basketball added, reading the DeepSports warehouse

`college_basketball/` trains h2h, spread and total XGBoost models on men's D1 games from
DeepSports' warehouse, read-only. Why: that data already exists (about 17,000 D1 games), so a
second fetcher would only duplicate it. Cost: college here depends on the DeepSports warehouse
and the external drive, and duckdb is pinned below 2 to match DeepSports. One feature builder serves
training and prediction, with no betting lines and no rank features (NOTES A6).

Settings were picked on the 2024-25 walk-forward only (log loss .5570, margin MAE 9.36, total MAE
13.14). Scored once on DeepSports' holdout, 3,417 games, Nov 2025 to Jan 2026, paired:
- This model: Brier .1850, log loss .5481, margin MAE 9.60, total MAE 13.98.
- DeepSports prior model: .1798, .5325, 9.39, 13.89. Better on Brier, log loss and margin (CIs exclude 0).
- Closing line: .1696, .5067, 8.94, 13.46. Better than both.
- A 50/50 blend with DeepSports is no better than DeepSports alone.

Betting thresholds copy the NBA recommender. `MIN_GAMES_PLAYED = 5` is new: with one game played,
season margin can be one blowout over a non-D1 team, and in the holdout, spread gaps with under 3
games played won less as they grew (gap >= 3: 49.5%, >= 12: 44.8%). 5 matches DeepSports' gate.
This gate was chosen after seeing the holdout. Known limit, left alone so the holdout stays clean:
non-D1 blowouts still feed early-season form. The recommender writes no bet log; add logging only with
the owner's approval, since the logs are immutable records.

## 2026-11-08 — $50 bankroll with a start date; Kelly sizing on college

Owner is starting with $50. NBA `STARTING_BANKROLL` is 50 and new `BANKROLL_START_DATE` is 2026-11-08.
Why a date: `setBankroll` adds every graded log row, so the January rows (net -$3.40) would make $50 read
$46.60, and the logs are immutable. Older rows stay in the files and still count in archive views.

College uses the same sizing through `shared/bankroll.py`: 20% Kelly, 5% cap, 50% daily risk, whole dollars.
`MIN_BET_AMOUNT = 1` drops smaller stakes, which also fixes a divide-by-zero in `calculateBetPriority` when an
NBA stake rounded to $0. College bets aren't logged, so its menu asks for the current balance.

Warning: simulated from $50 at closing prices (leak-free NBA predictions; college with the 5-game gate), this
sizing fell to about $9 in all three full NBA seasons and in college 2025-26, then stalled because 5% of under
about $10 rounds below $1. Kelly assumes accurate probabilities, and these cover probabilities are overstated:
without a proven edge, correct Kelly size is $0. Scripts and inputs:
`/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/college-model/`.

## 2026-11-08 — NBA rank features removed; all three models retrained

`PTS_RANK` and `PLUS_MINUS_RANK` change as later games are played (NOTES A6), which breaks non-negotiable #4, so the
owner approved removing them. Cached seasons keep the columns because older raw files are absent; the models drop
them by name. Retrained with the normal Optuna path on 29,308 games across 27 seasons, without a keep-if-better
gate, because honest metrics are expected to look worse than the leaked ones.

Test split, previous metadata to now: Brier .2125 to .2198, margin MAE 11.50 to 11.87, total MAE 14.45 to 15.04.
The previous figures carried look-ahead, and the old total figure also predates the chronological split.

## 2026-11-08 - Bet grading is keyed on each bet's own season, not the current one

`updateBetResults` used to read only `{getCurrentSeason()}_game_stats.csv`, so any
bet left ungraded when the season rolled over (July) could never be graded again -
the ID simply is not in the new season's file, and the loop failed silently.
Grading now derives the season from the bet's date (`getBetSeason`) and loads that
season's CSV through a per-instance cache; a missing season file warns and skips.
Why: bet logs are append-only history and must be gradeable forever, and a silent
no-op looked like "the update works" for months. Side effect: logs are written
only when a `result` actually changes, so repeat runs leave the CSVs untouched.

## 2026-11-09 - Owner-placed bets are logged; college gets its own log

The owner approved logging their real bets from the $50 bankroll, starting with the Nov 8 results and Nov 9 slip.
College bets go in `logs/college_basketball/betting/bets.csv`, a simpler schema than the NBA logs, because they include
markets the NBA columns can't hold (first-half spreads). Same immutability rule as every bet log.

Known limits:
- The NBA rows use ESPN game ids, because `stats.nba.com` timed out and `cdn.nba.com` returned 403. The NBA grader matches
  on NBA ids, so it skips them and leaves their results alone. They're graded by hand from final scores.
- The NBA grader never reads `total_bets.csv`, so totals need hand grading whatever their id.
- ~~The NBA menu's bankroll adds up the NBA logs only, so it omits college results: $77.27 when the owner's balance was
  $86.36. Sizing code wasn't changed, because that's the owner's call.~~ Reversed the same day, below.
- The opposite-side price and book weren't recorded. Opposite-side odds are placeholders and `book` is `unrecorded`,
  since blank odds would break the menu's integer formatting. Each row's `reason` says so.

## 2026-11-09 — NBA bankroll counts college results

The owner approved this: it's one bankroll, and leaving out college undersized NBA stakes. `setBankroll` now also reads
`COLLEGE_BETS_LOG`, so NBA stakes follow the real balance, up or down. The archive view stays NBA-only. The college menu
still asks for the balance by hand.

## 2026-11-09 — Bet labels in the app show the pick, never the stake

The DeepSports API allows any origin to read it, so `/api/bets` and the card `bets` field carry only a short label
("TOR -2.5") and no stake, odds or balance. The logs stay read-only: the app reads rows with no result and never writes them.
A bet is matched to a game by its ESPN `game_id`, which is what the owner's rows use; older NBA-API ids never match a card.

## 2026-11-09 - Repo split: ManualBets/ and DeepSports/ with a shared root

Two projects with different owners of change (handmade pipeline vs agent-driven warehouse) were sharing one flat
root, one env, one pyproject and one ignore file. Split them: every betting artifact lives in `ManualBets/`, DeepSports
stays in `DeepSports/`, and each has its own `pyproject.toml` and `.venv`.

`logs/` stays at the repo root on purpose. It is the one artifact both projects touch (DeepSports reads open rows
read-only to label game cards), so it is the shared interface rather than betting-private data. Putting it inside
`ManualBets/` would force DeepSports to know a sibling's internal layout. Consequence: betting code uses `../logs/...`
and `college_basketball/` uses `ROOT.parent/DeepSports/...`; both are the only cross-boundary paths in the repo.

Rejected: a `logs/` symlink into `ManualBets/` (Windows symlinks need elevation) and duplicating the journals
(violates the single append-only record).


## 2026-11-10 - Upcoming games = the next single slate, not today + tomorrow together

The NBA/NHL menus now show the earliest date (US Eastern game date, today or tomorrow) that still has games
which haven't tipped. At 10 PM PT that is tomorrow; at noon it is today. Returning both dates at once was rejected:
a team playing tonight and tomorrow would get stale features for tomorrow's game (rest days, L10 stats without
tonight's result), and odds are matched to games by team names only, not by date. Cost: tomorrow's games appear
only after today's last game tips (about 7:30 PM PT).

## 2026-11-10 — Development is agent-driven; repo-wide agents at the root

Reverses the 2026-08-21 single-agent entry. Development is now mostly done by AI agents, using the
repo-wide dev agents in `../.claude/agents/` (registry and rules in `../AGENTS.md`). Why: the owner
decided it, and ManualBets and DeepSports are being merged, so one set of agents and rules serves
both. Full rationale: `../docs/DECISIONS.md` 2026-11-10. ManualBets' `AGENTS.md` now keeps only
ManualBets specifics and points to the root for repo-wide rules; `CLAUDE.md` imports it.

## 2026-11-10 — Basketball only; hockey and baseball out of focus

Work covers the NBA and NCAA men's D1 only. `hockey/` and `baseball/` stay in the tree but get no
new work, and docs leave them out. The old NBA and MLB roadmaps (`basketball/nba_betting_project_roadmap.md`,
`baseball/mlb_betting_project_roadmap.md`) moved to `docs/archive/` as history. Repo-wide entry: `../docs/DECISIONS.md` 2026-11-10.

## 2026-11-11 — NBA totals stay disabled (walk-forward backtest fails the ship rule)

Nobody had recorded why the NBA total model was commented out of the menu, logging and export. A pre-registered
walk-forward backtest (`tools/total_walkforward.py`; method and numbers in
`docs/results/2026-11-11-nba-totals-walkforward.md`) now gives the reason. It uses monthly refits and the
recommender's own rule: bet when the prediction is 8+ points from the line (`MIN_TOTAL_EDGE` isn't in
`betting_config.py`, so the code default of 8 applies, and the 0.55 probability gate never binds at sigma ~19).
Closing lines and prices come from DeepSports. On the locked 2025-26 holdout the bets went 92-96 (48.9%,
slate-clustered 95% CI 42.3% to 55.6%, break-even 52.3%, ROI -6.6%), and the model's total MAE was 0.83 pts worse
than the closing total's. Both ship conditions fail, and 2021-22 to 2024-25 lose as well (892 bets, -8.3%). The line
moved toward the model's side from open to close on only 11-26% of bets (mean CLV -2 to -3 pts), so its large
disagreements mostly mean the market knows something the features don't.
Totals stay disabled and thresholds are unchanged. Revisit only with new information (C3 market features, C4
availability, injuries) and a fresh pre-registration with 2026-27 as the holdout. The tool reads the warehouse
read-only (boundary edge 2, `../docs/DECISIONS.md` 2026-11-11).

## 2026-11-20 - NBA: h2h paused, market-shrunk sizing, edge bands, A7 fix, CLV

Owner-approved change after the live record review: NBA h2h 23 bets, 11-12, -$15.47, with claimed
edges averaging 11.4 probability points and landing 47.8%; DeepSports' 4,069-game price simulation
shows a moneyline edge rule busts at the close, and its calibration study puts the model's weight next
to the market at about 0. So:

1. `ENABLED_MARKETS = ('spread',)` in `basketball/betting/betting_config.py`. h2h stays runnable from
   the menu (with a warning) for research, but the "All" run skips it and it is no longer a default bet.
2. Sizing: `SIZING_MODE = 'flat'` at `$2` (5% cap) is the default. Kelly mode exists but is 1/10 Kelly
   with a 2% cap and sizes on `p_eff = 0.25*p_model + 0.75*p_market`, not the raw model probability.
   `MAX_RISK_PCT` 0.50 -> 0.15.
3. Edge bands: spread 3-5 points, total 8-12, h2h 5-8% probability. Cap the top of the band because the
   live big-edge buckets did worst (spread 5+ went 13-12, h2h 10-20% went 5-7). No price worse than
   -150. Odds rows older than 60 minutes are dropped; stale lines make phantom edges.
4. NOTES.md A7 fixed: live team features now cover the same last-`window` games as training rows
   (`latestWindowStats`). No leakage: only completed games before tip are used.
5. Feature pruning is now ignore-list only (columns stay in the training frame): C-R1 exact duplicate,
   C-R3 one top ladder, averaged percentages, redundant home-away diffs. C-R2 keeps `plus_minus_diff`.
6. CLV: `tools/clv.py capture|record|report` writes `../logs/basketball/betting/clv.csv` (a new derived
   file; the bet logs themselves are untouched). CLV is measured against a snapshot taken after the bet
   and before tip, not against the morning line.

Why: at 20-45 bets nothing is decidable, and the tool had no way to tell skill from luck. CLV is the
cheapest forward signal. Reversals: re-enable h2h or widen the bands only on a pre-registered sample.

## 2026-11-20 (later) - Spread pruning reversed; model v6 uses all 54 features

The entry above added features to the hand prune list. A same-day ablation then tested that list
against keeping every feature on a chronological holdout (train through 2024-02, test 2024-02 to
2026-11-08; fixed params, 3 seeds; `docs/results/2026-11-20-nba-spread-feature-ablation.md`):

- current hand prune (27 features): test MAE 11.819
- all non-leakage features (54): test MAE 11.711, day-clustered CI for the gap +0.058..+0.155
- data-driven prune (36): test MAE 11.737

14 of the 27 pruned features had positive permutation importance (`home_wins_l10`,
`away_wins_l10`, `home_top5_avg_ppg`, `away_top5_avg_ppg`, `home_top5_avg_blk`, ...). So the
spread `low_importance_cols` is now empty, and the model was retrained on all 30,350 games with the
validated fixed params (396 trees, validation MAE 11.688, residual std 14.862) and saved as version
6. Old model backed up outside the repo. h2h and total keep their lists (paused/disabled). The
betting rules in the entry above are unchanged; only the spread feature-prune part is reversed.
Tool: `tools/retrain_spread.py`.

## 2026-11-21 - CLV comes from the warehouse close; injuries accumulate daily

CLV is graded against the warehouse's `source='closing'` row (read-only, boundary
edge 2), not against per-wave Odds API captures. One joining rule (ET date + ESPN
home/away codes) and zero extra credits; `tools/clv.py record --source warehouse`.
Live snapshots remain the fallback when the warehouse is unavailable.

ESPN's injury feed is current-only: the `dates=` parameter is ignored, and the
archive has one day. A report-based model cannot be trained on that history, so
`tools/injuries.py` captures one day at a time into a season file for next season,
while the model keeps using participation (games played) features. No hand-tuned
injury adjustment was added.

## 2026-11-21 (later) - Reverted the warehouse CLV, daily injuries and extra tools

The warehouse CLV path, the daily injury feed, `tools/feature_ablation.py` and
`tools/retrain_spread.py` were removed at the owner's request. The derived training data is not
kept as a separate append step: deleting `data/training_data/basketball` and running the
retrainer's `prepareAllSeasons` rebuilds it from the raw data with the new core/rotation player
features. The feature definitions and the ablation result stand; the extra tools did not.

## 2026-11-21 - Spread model ships the core-availability and current-rotation features

The rebuilt training frame (30,439 games, 96 columns) was tested with four feature sets on
one chronological holdout. Baseline 54 features: test MAE 11.7174. Adding core availability
(68): 11.5492. Adding current rotation (72): 11.6659. Both (86): 11.5418. The paired
day-clustered delta for both vs baseline is +0.1976 MAE [0.1209, 0.2756]. Availability does
most of the work; rotation is a small addition. The spread model was retrained on all games
with the fixed params and saved as version 7 (86 features, 478 trees, validation MAE 11.4865,
residual std 14.6982). h2h and total are unchanged. Details:
`docs/results/2026-11-21-nba-availability-ablation.md`.

## 2026-11-21 - Current injuries adjust the core availability features at prediction time

The spread model learned the effect of lost core minutes/points from historical
participation. At prediction time the upcoming game's report is known, so
`betting/injury_adjustment.py` maps status to an expected participation probability
(OUT 0, DOUBTFUL 0.25, QUESTIONABLE 0.5, PROBABLE 0.9) and recomputes the 3/5-game core
features with the upcoming game treated as the most recent expected game. This is a
probability on a feature the model already learned, not a hand-tuned point adjustment.
The live path refreshes the ESPN current feed once per run and falls back to the saved
snapshot. Training data and the model are unchanged; the adjustment is live-only until
historical reports are available to validate the window choice.

## 2026-11-21 - Injury adjustment is a three-arm forward comparison

The live spread path logs three predictions per game: `raw` (no injury report), `binary`
(OUT only, no in-betweens) and `prior` (OUT 0, DOUBTFUL 0.25, QUESTIONABLE 0.5, PROBABLE
0.9). Recommendations use `prior`. The log is
`data/basketball/injury_data/forward_predictions.csv` with the predicted margin, model
version and each team's injuries. This separates two questions: raw vs prior (does injury
news help at all?) and binary vs prior (do the in-between statuses help?). Grading joins
the log to actual margins; the line/price can be joined from the bet log or odds snapshot.
