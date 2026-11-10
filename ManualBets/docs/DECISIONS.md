# DECISIONS.md — running log of why

Append new entries at the bottom. If a decision is reversed, strike it through
(keep it visible) and point to the reversal. Never delete entries.

---

## 2026-08-21 — Single-agent workflow; no subagents

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


## 2026-08-25 � data/ untracked from git EXCEPT odds_data

All of data/ is fetched/derived and regenerable, so it was untracked (593 files)
to stop git bloat (~530 MB of blobs). Exception carved out via .gitignore
negation: data/*/odds_data/** stays tracked. Why: odds snapshots are the only
data the pipeline CANNOT regenerate � they are point-in-time market observations
consumed at recommendation time; once a game passes, those prices are gone unless
paid historical endpoints are used. They double as future training data for
market-feature work (NOTES.md C3/C4) and CLV checks. Cost is trivial (~360
files, 4.2 MB).

## 2026-08-25 � models/metadata restructured to per-sport subfolders

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

## 2026-11-09 — Owner-placed bets are logged; college gets its own log

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

