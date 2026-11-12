# Decision log

Append-only. Newest at the bottom. Format: date, decision, why, alternatives.
Find an entry: `grep -n '^### ' docs/DECISIONS.md` (one heading per decision, dated).

### 2026-11-03: Start with the NBA, data collection first
**Why:** The NBA, NHL, and NFL are all in season; the NBA has the most games per team and the best free
data, and every later phase depends on a reliable dataset.

### 2026-11-03: ESPN public site API as the NBA source
**Why:** Responded without a key or any header tricks; covers schedule, scores, box scores, and
pregame + closing odds in two endpoints.
**Alternatives:** `stats.nba.com`/`nba_api` (timed out), `cdn.nba.com` (403). We don't get around
blocks with spoofed browser headers.
**Risk:** It's unofficial and can change. Mitigated by the raw landing zone + fixture tests.

### 2026-11-03: Raw landing zone + DuckDB warehouse
**Why:** Raw gzipped JSON makes parsing reproducible and backfills one-time. DuckDB is a single
file built for analytical queries that works with pandas/polars.
**Trade-off:** One writer at a time, so jobs run one after another.

### 2026-11-03: Python 3.12 + uv; dependencies resolved at least ~2 weeks after release
**Why:** One toolchain; `exclude-newer` in pyproject avoids brand-new releases.
**Note:** TypeScript is reserved for a future UI. Serena is configured for both languages.

### 2026-11-03: Calendar sync is done by the agent, not the Python code
**Why:** Google Calendar access lives in Claude's connector, so no OAuth app or credentials go
in the repo. Python produces `upcoming --json`; the `/sync-game-calendar` skill reconciles
events, matching them by the key `deepsports:nba:<game_id>`.
**Trade-off:** Syncs need a Claude run (interactive or scheduled).

### 2026-11-03: Store pregame odds only when the line moves
**Why:** Keeps a line-movement history without a row per refresh.

### 2026-11-03: Initial followed teams: LAL, LAC, GS, BOS
**Why:** The owner is new to sports and asked Claude to choose: the three Pacific/local teams
plus the most famous (Celtics). About 14 calendar events a week. Change `config/calendar.toml` anytime.

### 2026-11-03: Main session is an orchestrator with specialist subagents
**Why:** The owner wants an agent-driven project. AGENTS.md defines the orchestrator role, four
subagents (data-engineer, data-analyst, calendar-agent, architect), and permission to create
reusable agents, skills, and tools. Imported into CLAUDE.md so every session loads it.

### 2026-11-03: Live scores, a mobile web app, and an Even Realities glasses app are on the roadmap
**Why:** The owner cares most about keeping up with scores and stats while doing other things.
These come before the prediction work; the TypeScript side of the stack goes to the web app.

### 2026-11-03: Historical backfill 2021-22 → present
**Why:** Predictions need several seasons to train on and to backtest walk-forward. Box scores are
consistent back to at least 2016, but 2019-20 (bubble) and 2020-21 (no fans) distort home court,
so we start at 2021-22. Older seasons stay available if a model needs them.

### 2026-11-03: Historical odds from the ESPN core API
**Why:** The summary `pickcenter` is empty for 2023-24 and 2024-25, and the betting market is the benchmark
our predictions must beat. The core API has per-book open/close lines with explicit per-side spreads.
A summary closing line, when present, is kept; the core API only fills gaps (and opening lines).

### 2026-11-03: Live data bypasses the warehouse
**Why:** DuckDB allows one writer and no readers from other processes while it writes. The API serves
live scoreboards and box scores straight from ESPN (in-memory TTL 30s while games are live, 5 min
otherwise) and only reads DuckDB for standings and team pages, returning 503 `warehouse_busy`
during jobs. A shared service layer can come later if this gets limiting.
**Alternatives:** a SQLite live table (adds a second store), or a long-lived API process that
also runs the jobs (couples the server to collection).

### 2026-11-03: Web app = FastAPI + Vite/React/TS PWA on this Mac, port 8787
**Why:** The owner chose local hosting. One process serves the API and the built app, reachable
from the phone at `http://<mac-lan-ip>:8787`.

### 2026-11-03: Data lives on the external drive
**Why:** The owner's request; the internal disk has ~14 GB free. `data/` is a symlink to
`/Volumes/ExFATStorag/DeepSports/data`. DuckDB and its cross-process locking were tested on that exFAT
volume before the move. Commands fail clearly if the drive isn't mounted.

### 2026-11-03: Automation through local launchd agents
**Why:** The warehouse lives on this Mac's external drive and the owner hosts the app locally, so a
cloud routine couldn't reach the data. One agent keeps the server up; another runs update + a headless
Claude calendar sync twice a day, limited to the tools it needs. The owner installs them
(`tools/launchd/install.sh`); agent sessions aren't allowed to create login items.

### 2026-11-03: Men's college basketball next, starting with the Nevada Wolf Pack
**Why:** The owner wants college games; ESPN serves them in the same shape as the NBA. Starting with one
followed team (Nevada, ESPN 2440) keeps calendar and app scope small, but ratings need all D1 games for
opponent strength. Team ids collide across leagues, so keys become league-aware first.

### 2026-11-03: Historical ESPN injury lists are not used as model inputs
**Why:** The data-engineer showed that the summary `injuries` array is the team's injury report at *fetch*
time (a 2021 game fetched in 2026 lists a player who was in college in 2021; 100% of pre-2026 entries
are dated after tip-off). Using them would leak the future. Only pre-tip snapshots
(`captured_before_tip = true`) feed models, so injury features start accumulating from now on.

### 2026-11-03: Model v1 has no market inputs and fixed settings
**Why:** The closing line is the benchmark. Feeding odds in would hide whether the model adds anything.
Model settings (C=1, alpha=10) are fixed in advance rather than tuned on the backtest, to avoid an
optimistic result.

### 2026-11-03: Skip news/social sentiment for now
**Why:** research/fundamental-data-sources.md finds no rigorous evidence that sentiment beats the NBA
closing line, which prices injury news before tip-off. Priority goes to rest/travel, availability-adjusted
team strength, and point-in-time injury reports.

### 2026-11-03: Model v1 baseline result
**Result:** On 4,069 out-of-sample games (2023-24 → now), v1 beats Elo and home-always on every target but
does not beat the closing line (win-prob Brier 0.211 vs market 0.199; margin MAE 11.2 vs 10.8; total MAE
15.1 vs 14.3; ATS 48–50%). That's expected for public box-score data, and it confirms the backtest isn't leaking.
**Next:** availability-adjusted team strength (who's actually playing) and pre-tip injury snapshots are
the most promising ways to close the gap.

### 2026-11-03: SportsRLAgent review: keep our own summary only
**Why:** A DeepSeek research pass over a friend's private betting project produced detailed notes
that quote that project. We keep a summary in our own words (`docs/research/sportsrlagent-review.md`)
and the roadmap items; the raw notes in `collab/` stay local and git-ignored. Headline: their 397 logged
bets showed no significant edge, and fixing their leakage worsened spread MAE by ~2 points, which matches
our own "doesn't beat the closing line" result.

### 2026-11-03: Permission to use the friend's SportsRLAgent data and methods
**Why:** The owner of the friend's project granted full permission. We read their already-collected data
locally (read-only) and record provenance on anything imported. We won't run their collectors: the odds
key is theirs, and their stats/injury scrapers rely on blocked or spoofed access.

### 2026-11-03: Lift the no-spoofing / no-workaround rule (owner)
**Why:** The owner wants the option to use browser automation (Playwright/Selenium) or browser-like
headers when a source blocks plain clients, for example stats.nba.com or cdn.nba.com. Not used yet. When it's
needed: propose it to the owner, keep rate limits, and document the method per source. Supersedes the
"no header tricks" notes in the earlier entries above.

### 2026-11-04: Show model v1.1 in the apps; keep v1.0 running alongside
**Why:** v1.1 adds player-availability features (top-3/6 by pre-game minutes who missed recent games,
missing-minutes share). Backtest: a small, statistically real margin gain (MAE −0.03, paired CI excludes 0),
and a Brier change within noise; still behind the closing line, so it's presented as context, not an edge.
Both versions are predicted daily and graded, so live records can confirm or reject the gain. Top-6
plus-minus duplicated team form (r≈0.96) and added nothing in the ablation.

### 2026-11-04: Modeling methods: ensemble yes (with a locked holdout); RL and genetic search no
**Why:** The gap to the market is information, not algorithm (v1→v1.1 Brier −0.0004 vs a 0.011 gap to the
close). Ensembles give small, reliable gains. RL learns a bet policy from very noisy, scarce rewards, and with no
edge it overfits or learns "don't bet". Genetic/mutation search over a single backtest finds chance winners.
Any search is validated once on a holdout it never saw.

### 2026-11-04: $100 simulation result: no betting use; opening-line totals worth watching
**Result:** At the closing line every v1 strategy busts (mostly the −110 cut). At the opening line, totals grew
$100→$172 (53.4%, CI 51.1–55.6%), but openings lack posting timestamps, so the model may have had later information.
It's a hypothesis to test live (predictions logged before the opening line exists), not an edge. Kelly is off.

### 2026-11-04: Scheduled sync: the script touches the warehouse, headless Claude only touches the calendar
**Why:** Both 2026-11-04 scheduled runs left the calendar unchanged. The script's own update/predict steps
succeeded, but the skill's `deepsports update`/`upcoming` calls hung (or hit EINTR) inside headless
Claude's Bash sandbox, which can't reach `/Volumes/ExFATStorag`. Now the script exports the upcoming games
to `.sync/` (git-ignored) and invokes `/sync-game-calendar prefetched .sync`. This also stops the
double update per run. Verified by hand at 14:32: 14 events updated, 1 unchanged.

### 2026-11-04: Ensemble v2 locked holdout = all of 2025-26 (season 2026), declared before fitting
**Holdout:** every completed NBA game of season_year 2026 (2025-26): regular season, NBA Cup, play-in
and playoffs (season types 2, 3, 5; ~1,326 games), scored **once**, after every choice below is frozen.
**Validation (all tuning, model choice, blend weights):** walk-forward monthly folds on 2023-24 and
2024-25 (seasons 2024, 2025); 2021-22 stays the Elo burn-in, 2022-23 is training only. 2026-27 games are
not used at all (too few, and not complete). Holdout predictions are still walk-forward (each month's
base models train only on games before that month, including earlier 2025-26 games), but with the
hyperparameters and blend weights frozen from validation.
**Why this season:** it's the most recent complete season (the "rest of 2026-27" idea in the roadmap
means waiting until mid-2027). **Known contamination:** v1.0/v1.1 feature lists were fixed before
their backtests, but their reports (which we've read) included 2026; the trees, the blend method and
its weights have never been fit or scored on 2026. Closing lines are the benchmark only, not inputs.
**Ship rule (declared with the holdout):** ship ensemble v2 over v1.1 only if, on the holdout, it is better on
log loss *or* margin MAE with a 95% day-clustered bootstrap CI that excludes 0, and not worse (CI-wise) on
the other. Beating the closing line is not expected and not required.

### 2026-11-04: Ensemble v2 result: don't ship; keep v1.1
**Result (holdout scored once):** ensemble − v1.1 log loss +0.0006 (CI −0.0017 to +0.0029), margin MAE −0.007
(CI −0.046 to +0.032): fails the ship rule. Boosted trees (sklearn HistGradientBoosting, no new dependency) are
worse than the linear models on their own and got ~0 weight on win probability. Still behind the close by
0.024 log loss / 0.36 margin points. The tree grid was searched in two rounds, both on validation only.
Frozen config: `models/ensemble_v2/config.json`; the holdout marker next to it blocks re-scoring.

### 2026-11-04: College (NCAAB) v1 locked holdout = 2025-26 games from Feb 1 on, declared before fitting
**Holdout:** every completed men's D1 game of season_year 2026 (2025-26) that tips off on or after
2026-02-01 00:00 US/Eastern (05:00 UTC) with **both teams D1** (`teams.listed`): the rest of the regular
season, conference tournaments and the postseason (season types 2 and 3; ~2,000 games). Scored **once**,
after every choice below is frozen in `models/ncaab_v1/config.json`; a marker file blocks a second run.
**Validation (all tuning and model choice):** weekly walk-forward folds testing 2025-12-01 → 2026-01-31
(each week's model trains only on games that tipped off before that week); November is training/burn-in
only. Tuned there: Elo K and home edge, the ridge (Massey-style) rating's shrinkage, whether to drop
early-season rows from training, and team-only vs team + player features. 2026-27 games aren't used.
Holdout predictions are walk-forward too (weekly refits on all earlier games, frozen settings).
**Non-D1 opponents:** their games feed history (Elo, ratings, form) with every non-D1 school pooled as one
"non-D1" team (each plays only 1–3 D1 games, too few to rate alone); they are never scored or trained on.
**Declared breakdowns (no others):** closing |spread| ≤ 5 / 5–12 / > 12; conference vs non-conference
regular season vs postseason (season type 3); neutral site vs not. Flat-bet check at −110: against the
closing spread and total at edge thresholds 0 and 3 points (spread) / 0 and 4 (total), labeled a backtest.
**Ship rule (as context in the apps, like NBA v1.1):** ship if, on the holdout, the college model beats Elo
on log loss **and** margin MAE with 95% day-clustered bootstrap CIs excluding 0, and its ECE ≤ 0.05.
Claim a betting edge only if the model − closing line CI excludes 0 in the model's favor (log loss or
margin/total MAE) **and** a declared flat-bet lower 95% bound is above 52.4%. Closing lines are the
benchmark only, never a feature; historical injury lists aren't used (they leak).
**Also reported, outside the ship rule:** a closing-line + model blend (one weight per target, fit on the
validation weeks, frozen) to test whether the model adds anything beyond the close.

### 2026-11-04: College (NCAAB) v1 result: ship as context (not wired yet); no betting edge
**Result (holdout scored once, 1,949 games):** college v1 − Elo log loss −0.0081 (CI −0.0158 to −0.0010), margin
MAE −0.65 (CI −0.86 to −0.46), ECE 0.024: passes the ship rule. College v1 − closing line: log loss +0.013
(CI +0.007 to +0.020), margin +0.14 (+0.06 to +0.24), total +0.28 (+0.15 to +0.42); flat bets 50.7% ATS, 49.5%
totals: no edge. The validation-fit model + close blend gave the model weight 0 on win and margin.
Settings tuned on Dec–Jan only, in two rounds (round 1's best Elo K / home edge / ridge λ sat on the grid edges;
round 2 widened them and the same values won, now interior). Frozen: `models/ncaab_v1/config.json` + marker.
Wiring into `deepsports predict` needs scheduled-game ratings, a cross-season prior and a league-aware
total filter in `PREDICTION_RESULTS_SQL` (the NBA 150–320 filter would NULL college totals).

### 2026-11-04: College v1 in daily use: predict only D1-vs-D1 games with >= 5 games per team this season
`deepsports predict --league ncaab` (model `v1`, version `ncaab-v1`) trains college v1 with the frozen
`models/ncaab_v1/config.json` on every completed D1-vs-D1 game (all seasons; rows with >= `min_games`
rated games per target, as in validation) and predicts the scheduled games in the next 14 days. **Gate:** a
game gets a prediction only when both teams are D1 and each has **>= 5 completed games this season**
(`ncaab.MIN_GAMES_TO_PREDICT`). **Why:** the model was validated on one season where every team started
level; cross-season carry-over (Elo x0.75, a ridge prior from last season) is untested, so ratings restart
each season (Elo `carry_over = 0`, the pooled non-D1 team back to 1200; ridge ratings per season) exactly
as validated, and rows with < 5 games are outside what the model trained on. Cost: no college predictions
until about late November. Revisit when a cross-season prior can be validated on early 2026-27 games.
The validation-fit market blend is not applied (no closing line before tip): the stored numbers are the
model's own. Grading and `/api/predictions/record` are per league (one league and one version per call;
default version per league: `v1.1` NBA, `ncaab-v1` college), so college games never mix into the NBA
record. Closing-line limits in `prediction_results` are per league (`store.SANE_LIMITS`, shared with
`analysis.market`), so college totals of ~120-195 are no longer blanked.

### 2026-11-04: Early-season college predictions as an opt-in (`ncaab-v1-early`)
**Why:** The owner wants college predictions before both teams have 5 games. The 5-game gate stays for
`ncaab-v1` (the validated setting, its record and the calendar). The same frozen model also writes `ncaab-v1-early`
for D1 games where each team has at least 1 game. It's a separate version so it never mixes into the `ncaab-v1`
record. The API marks it `early: true`; the web app hides it behind an "Early-season predictions" switch (off by
default), the glasses never show it, and `upcoming` (the calendar) ignores `*-early`. These predictions aren't
validated (the holdout started in February), so they're labeled "Early prediction" with a "expect bigger misses" note.

### 2026-11-04: Edge hunt verdict: no betting edge; forward paper test instead
**Why:** A DeepSeek session ran a pre-registered search (`collab/deepseek/EDGE_REPORT.md`, local). It covered 11
strategy families (~350 variants) and 9 feature groups, using one shared grader. It checked each family against a
placebo of 1,000 random side-flips, and allowed at most 6 holdout tests (Holm–Bonferroni). No strategy survived.
The only one to pass the dev gate (college streak-fade S7, a control) went 50.7% on its holdout. Claude
re-computed that result and NBA rest-mismatch independently from the warehouse copy and got the same answer
(50.5% / 56.8%). Two lessons: the family-level placebo rejected every attractive dev result, so it is mandatory
for any future strategy search; and dev ROI near +8% on ~500 bets is not evidence. Availability, opponent-3P% luck
and games-remaining predict the closing residual but don't shrink the model's gap to the close, so the models stay
unchanged. Next: log the top 3 candidates as frozen, watch-only paper bets during 2026-27, and backfill
2023-24/2024-25 college data (the college dev window was one season's Nov–Jan).

### 2026-11-04: Port the edge study's reusable code into `src/`
**What:** `collab/deepseek/lab/harness.py` + `audit.py` + `context.py` → `analysis/betting/` (`grading`,
`audit`, `loaders`); `pbp.py` → `parse_pbp.py` (pure, tested on one trimmed real summary per league in
`tests/fixtures/espn_{nba,ncaab}_summary_pbp_*.json.gz`; no warehouse table yet); `v11_rerun/` →
`analysis/feature_test.py` (generic NBA/college feature-injection walk-forward; the bit-exact
baseline-reproduction check is a test on synthetic NBA and college rows); B3's load feature →
`analysis/fatigue.py` (reproduces B3's dev values exactly: 0 mismatches over 4,922 NBA games). Tests ported
with them. **Why:** one tested grader for any future simulation or paper record, instead of re-deriving it.
**Changes in the port:** odds conversions come from `analysis/metrics.py` (no copies); the loaders take any
connection (no hard-coded lab path) and `read_raw_summary` defaults to `config.RAW_DIR`; the audit now also
drops moneyline bets on flagged games (the lab version flagged ML moves under `ml` but compared them with
the bet market `moneyline`, so it never dropped one). **Dropped (one-off study scaffolding):** the
family-specific strategy code (a1–a10, b1–b9), `overlap_matrix.py`, `smoke_harness.py`, the v11_rerun
`run_*.py` scripts and their B4/B5/B8/B9 CSV readers, `games_played_delta`, and the lab-DB-only loaders
(`load_predictions`, `load_teams`, `load_team_game_context`). **Not changed:** `simulate.py` keeps its own
engine: it sizes stakes from the start-of-day bankroll across thousands of vectorized runs, which the flat
grader doesn't model, so swapping it in isn't low-risk.

### 2026-11-04: Forward paper-trade log with three frozen rules (watch-only)
**What:** `paper_bets` (insert-only; PK rule, game, market) + `paper_results` view; `deepsports paper log`
(in the scheduled sync right after the predict steps, non-fatal) and `deepsports paper report [--json]`.
Review date: end of the 2026-27 regular season. None of these is an edge claim; no real money.
**Shared rules (frozen):** regular-season games only (`season_type = 2`, as in the dev studies); only games
that haven't started (state `pre`, tip after now) whose US/Eastern game day is today; the line is the latest
`pregame` odds snapshot captured at or before logging (total within `SANE_LIMITS`); flat 1 unit at -110;
the first log of a (rule, game, market) is frozen, later lines or predictions never change it. Logging on
game day (not days ahead) keeps the model inputs as complete as in the walk-forward dev runs; the 08:00 run
sees the morning line, the closest live proxy to the dev "opening" line (opening rows have no posting time).
CLV is graded against the closing line.
- **`ncaab-total-t7` v1:** `predictions.model = 'v1'`, `model_version = 'ncaab-v1'` exactly (the gated
  version; `ncaab-v1-early` is never used). edge = `pred_total - line`; over if edge >= 7, under if edge <= -7.
  Dev (edge study A1, college 2025-26 before Feb 1, vs the opening total): 223 bets, 57.0%, ROI +8.7%,
  CI -3.6%..+19.1%; failed the family placebo. Live note: no college predictions exist until both teams
  have 5 games (about late November), so the rule logs nothing before then.
- **`nba-total-t4` v1:** `model_version = 'v1.1'`; same rule with 4 points. Dev (A1, NBA 2023-24 + 2024-25,
  vs the opening total): 1,087 bets, 53.2%, ROI +1.5%, mean CLV +1.42; holdout-contaminated by construction
  (the sim-v1 hypothesis), so paper only.
- **`nba-load-under` v1:** for each team, the B3 `min3n` load: minutes by its top-8 (season-to-date minutes
  in earlier regular-season games of the season, ties by athlete_id) in its games tipping in
  [tip - 72 h, tip - 27 h) (the "3-day load excluding the last 24 h": 24 h + 3 h game length). Bet the
  under when home + away load >= **470** minutes. A game is skipped when either team has no top-8 yet
  (season opener) or a finished game in [tip - 72 h, tip) without player box scores. **How 470 was picked
  (exploratory, say so):** the rule "dev mean + 1 SD of the combined load, rounded to 5" was chosen before
  looking at ROI by threshold, but it was computed in the same pass as the grid on the same B3 dev data (NBA
  2021-22 → 2024-25 regular season, n = 4,859: mean 318.3, SD 153.8 → 472.2 → 470). There is no holdout and
  B3's signal was itself exploratory (not pre-registered; slope -0.64 pts/SD vs the closing total, p = 0.012).
  In-sample vs the closing total at 470: 514 bets, 275-234-5, 54.0%, ROI +3.1%, CI -6.0%..+11.8%; by season
  +5.5% / -2.2% / +6.9% / +2.3%. The grid for reference: mean + 0.5 SD 51.7% (-1.3%), + 1.5 SD 55.1%
  (+5.2%, n 326), + 2 SD 55.3% (+5.5%, n 133). Expect this to regress.

### 2026-11-06: College cross-season prior: design, tuning set and locked holdout, declared before fitting
**Question:** does a prior from last season make college v1 trustworthy before both teams have 5 games?
**Candidates (one combined "prior model"; a component tuned to "off" just drops out):**
- **Elo carry-over:** at a team's first game of a new season r = c·r + (1 − c)·start (1500; 1200 for the
  pooled non-D1 team). Grid c ∈ {0, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9} × K ∈ {30, 40, 60}; home edge stays 60
  (v1). Chosen by raw Elo log loss on the tuning games.
- **Ridge (Massey) prior:** each team's offense/defense is shrunk toward ρ × its final rating from last
  season (last season's completed games, v1's λ = 1, no chaining) with weight λp games, instead of toward 0
  with weight 1. Teams with no rating last season keep v1's λ = 1 toward 0. League mean and home edge are
  centered on last season's values with negligible weight (they matter only before the first game).
  The prior's share is λp / (λp + n), so it decays with games played. Grid ρ ∈ {0.4, 0.55, 0.7, 0.85, 1.0} ×
  λp ∈ {2, 4, 8, 16, 32}, chosen by raw rating margin MAE (v1's rule).
- **Conference regression:** skipped (`team.groups` isn't stored).
- **Model:** v1's frozen linear models and per-target feature sets (`models/ncaab_v1/config.json`), fed the
  prior Elo and ratings. Training filter, per target, by the v1 metric: (i) v1's rt_n ≥ 5, or (ii) rt_n ≥ 5
  in the first season (2023-24, no prior exists) and every row of a season that has a prior.
**Arms:** (a) **no prior** = today's live behavior (Elo K 60 / home 60 / carry 0, per-season ridge λ = 1,
trained on all earlier D1 rows of every season with rt_n ≥ 5); (b) Elo: v1's no-prior Elo and the tuned
carry-over Elo (the gate compares with the carry-over Elo, the stronger one); (c) the closing line.
**Tuning set:** 2024-25 D1-vs-D1 games tipping off 2024-11-01 05:00 UTC → 2025-02-01 05:00 UTC, weekly
walk-forward (each week trains on every earlier D1 row, 2023-24 included); prior from 2023-24. Rows at or
after 2025-02-01 05:00 UTC are dropped before anything is fit.
**Locked holdout (scored once, marker `models/ncaab_prior/config.holdout-scored`):** 2025-26 D1-vs-D1 games
2025-11-01 05:00 UTC → 2026-02-01 05:00 UTC, prior from 2024-25, weekly walk-forward with frozen settings;
rows at or after 2026-02-01 05:00 UTC (v1's holdout, 2026-27) are dropped before anything. **Contamination:**
Dec–Jan 2025-26 was v1's validation window for K, home edge, λ and the feature/filter choices that both arms
share, and the edge hunt's college dev window; it is clean for the prior question only.
**Data caveat:** 2023-24 player boxes have ~360 team-games with a dropped line; they enter only as training
rows (player features of margin/total), identically in both arms, and are never scored or summed into team stats.
**Report:** buckets by rt_n (the lower of the two teams' completed games this season, any opponent): 0, 1–2,
3–4, 5–9, 10+, and overall; games with a closing moneyline, spread and total. Log loss, Brier, margin MAE,
total MAE, ECE (10 equal-width bins). Paired 95% day-clustered bootstrap CIs (2,000 resamples): prior − no
prior, prior − carry-over Elo, prior − close. Flat bets at −110 vs the close (spread t 0/3, total t 0/4), both
arms, labeled a backtest.
**Ship rule:** the prior ships if, over the holdout, prior − no prior has CIs entirely below 0 on log loss
**and** margin MAE, and in the 10+ bucket neither CI is entirely above 0. **Gate proposal:** a bucket
qualifies if the prior model's ECE ≤ 0.05 and its log loss and margin MAE point estimates beat the carry-over
Elo; the proposed gate is the lowest bucket floor (0, 1, 3, 5, 10) from which every bucket qualifies. Only
a recommendation: the live gate and `deepsports predict` are not changed by this study.

### 2026-11-06: Store spread/total prices; a price-only move is a line move; 30-min pregame captures
**Why:** Betting results at -110 assumed flat juice, and the opening-line simulation lacked posting
times. ESPN already sends spread and total prices on every odds path (scoreboard `pointSpread`/`total`,
summary `pickcenter` flat `spreadOdds`/`overOdds`, core API `<open|close>.spread/over/under`), so
`odds_snapshots` gains nullable `spread_home_price`, `spread_away_price`, `over_price`, `under_price`.
**Decision:** a pregame row is written when the line **or any price** changes: juice moving from -110
to -120 at the same number is real market movement and changes a bet's value. Cost: more rows (bounded
by the 30-min cadence). The first snapshot after the migration writes one extra row per upcoming game
(old rows have NULL prices).
**Captures:** `deepsports odds-snapshot` (launchd `com.deepsports.odds`, every 30 min at :15/:45) fetches
today's and tomorrow's scoreboards (NBA + college) and writes only pregame odds. It yields to every
other job (skips with exit 0 if the writer lock is held) and holds the lock only for the write, so the
08:00/14:00 sync's 15 s lock wait covers any overlap. The first pregame row per game now bounds when a
line became visible (within ~30 min for lines posted inside the 2-day window).
**Not done:** no history refetch; old rows keep NULL prices. Cached summaries and core-API responses
do hold closing/opening prices, so an offline price backfill is possible later (match on game_id +
source, keep `captured_at`). Paper-trade rules are unchanged (they read the latest pregame row at or
before logging).

### 2026-11-06: College cross-season prior result: ships by the rule; gate stays at 5
**Result (holdout 2025-26 Nov 1 → Jan 31, 3,417 D1-vs-D1 games with full lines, scored once):** prior − no prior
log loss −0.022 (CI −0.037 to −0.009), margin MAE −0.49 (CI −0.77 to −0.27), total MAE −0.13 (CI −0.23 to −0.04);
10+ bucket not worse (log loss −0.007, CI −0.013 to +0.001; margin −0.14, CI −0.24 to −0.03): **passes the ship
rule.** Biggest gains below the gate: 1–2 games log loss −0.10, margin −1.9. Still behind the close (log loss
+0.026, margin +0.45, total +0.43, CIs exclude 0); flat bets 50.5–51.1%, no edge. **Gate:** buckets 0 (ECE
0.058) and 3–4 (ECE 0.056) miss the declared ECE ≤ 0.05 bar, so the mechanical proposal is **5, unchanged**.
Outside the rule: at ~300 games a perfectly calibrated model's median ECE is ~0.050 and the close scores 0.057
in 3–4, so the bar is underpowered for small buckets. A re-test on 2026-27 with a pooled rt_n 1–4 rule is
suggested, declared in advance. **Frozen:** Elo K 60, home 60, carry-over 0.75; ridge prior ρ 1.0, λp 8; training
filter `prior_rows` for all targets (`models/ncaab_prior/config.json` + marker). Tuning took two rounds: round 1's
K grid (30–60) had its best on the edge, round 2 added K 80/100 on tuning data only and K 60 stayed best. ρ = 1.0 is
the grid's top by design. **Not changed:** the live gate, `ncaab-v1`, `ncaab-v1-early` and `deepsports predict`.
Adopting the prior is an orchestrator/owner step: use a new version label, and optionally point the opt-in early
predictions at it. Details: docs/results/2026-11-06-ncaab-prior.md.

### 2026-11-06: College prior model live as `ncaab-v1p`; `ncaab-v1-early` switched to it
**Why:** The prior passed its ship rule (entry above) and the owner approved shipping it. **What:** the frozen
`models/ncaab_prior/config.json` (Elo K 60 / home 60 / carry 0.75, ridge prior ρ 1.0 λp 8, `prior_rows`) is
trained on every completed D1-vs-D1 game of every season, priors carried across seasons exactly as in the
study's walk-forward (`ncaab_prior.live_rows` reproduces the saved holdout predictions to 0 difference on
781 games checked). One fit per run serves two versions: **`ncaab-v1p`** (both teams D1 with >= 5 games,
v1's gate), written beside `ncaab-v1` with its own graded record and never displayed (cards, glasses and the
calendar skip `config.HIDDEN_MODEL_VERSIONS`), and **`ncaab-v1-early`** (same label, same scope: D1 games where
each team has >= 1 game, no upper bound; 0-game games were never included). **Switch time: 2026-11-06 09:00:13
UTC.** Early predictions created before it came from college v1 (no prior); split the early record on
`created_at` there. `ncaab-v1` stays the display and paper-trade version (paper.py untouched); the gate stays 5.

### 2026-11-06: Known college points gaps by team-game; closing moneyline gap is upstream
**Why:** `deepsports check` exited 1 on 7 college team-games whose ESPN raw box is > 2 pts off the score
(verified upstream 2026-11-05). They are now warnings via an explicit `(game_id, team_id)` list
(`quality.KNOWN_POINTS_MISMATCH`), so any new mismatch, including the other team of a listed game, still fails.
The analyst's missing closing moneylines (2025-26 Nov–Jan D1: 233 games without one) are upstream: DraftKings
shows `OFF`, mostly on 20+ point spreads. Not filled from another book: mixing books inside one closing row
would change the benchmark. 61 of those games have an ESPN BET close in the cache if the owner wants that
(ROADMAP, optional). Numbers per field in DATA_SOURCES.md.

### 2026-11-06: Calibration check for displayed win probabilities: calibrated enough; rule-passing fixes built, not wired
**Protocol (declared in docs/results/2026-11-06-calibration.md before tuning or holdout):** walk-forward OOS
predictions of NBA v1.1 (monthly folds) and ncaab-v1 (weekly, live training path, displayed gate rt_n >= 5).
Three candidates: Platt and temperature scaling (refit monthly on every earlier OOS prediction), and stronger
L2 on the logistic win model (C ∈ {0.3, 0.1, 0.03, 0.01}). The best candidate on tuning log loss (NBA 2024-25; college
2024-11 → 2026-01) was frozen: NBA L2 C 0.03, college L2 C 0.1. Holdouts as before: NBA all of 2025-26, college Feb–Apr 2026, each scored once
(`models/calibration/*.holdout-scored`). Ship rule: log loss CI < 0, or ECE lower and log loss CI upper end ≤ +0.001.
**Result:** NBA L2 log loss −0.0014 (CI −0.0028 to +0.0001), ECE 0.0315 → 0.0311. College −0.0001 (CI −0.0002 to
+0.0000), ECE 0.0338 → 0.0320. **Both pass via the ECE branch.** Both ECE changes are far inside their noise: a perfectly
calibrated model's median ECE is 0.028 / 0.023 at these sizes. Platt and temperature corrections were ≈ identity. The moneyline
pick gap (model 48.6% / close 41.3% / actual 41.0%) is the winner's curse. A perfectly calibrated simulated model with no
information beyond the close shows 49.0 / 41.9 / 42.1, and the encompassing weight on the model next to the close is 0.02 ± 0.16.
**What was built:** `v1.1c` (`model.VERSION_WIN_C`; `resolve_version` now maps any registered name) and `ncaab-v1c`
(`ncaab.predict_upcoming_calibrated`; deliberately not in `ncaab.VERSIONS`, so `--model-version all` and the sync
are unchanged). **Not changed:** `deepsports predict` defaults, the scheduled sync, the API and the display versions.
**Recommendation:** keep the display as is. If adopting by the rule, run `v1.1c` hidden and graded first. Use the close,
not the model, for any Kelly sizing. The ECE branch of this rule is too weak: future rules should need an ECE CI below 0.


### 2026-11-06: Offline price backfill for historical opening/closing lines (`deepsports prices-backfill`)
**Why:** Betting simulations assumed -110 juice; the raw cache already holds the real prices (the "Not done"
paragraph of the price-columns entry above). **Decision:** each stored row takes prices only from the cached
response it was parsed from, never from "any response with the same line": opening rows and closing rows stamped
with the tip time from `core_odds/`, other closing rows from the summary `pickcenter`. The two sources can quote the
same number at different prices from different books (NBA 401358773: summary `consensus` -1.5 at -112/-108, core
DraftKings -1.5 at -115/-105). A row is filled only when the cached provider, spread, total and moneylines all equal
the stored ones; `captured_at`, lines and any non-NULL price are never changed, and no rows are inserted. The write
re-checks those conditions, so it is idempotent and safe if a row changed after planning. No network: it reads the
cache and holds the writer lock only for one `UPDATE`. **Result (2026-11-06 live run):** 46,340 rows filled
(NBA 11,386, college 34,954). Skipped: 48 NBA 2025-26 opening rows whose cached core response now picks a different
book (stored ESPN BET vs cached Draft Kings): their prices stay NULL. Every other NULL price is on a row whose line is
also NULL. Closing spreads are exactly -110/-110 on only 34% of NBA and 27% of college games (falling from 50% in
2021-22 to 16-19% in 2025-26); average two-sided hold is still ~4.7%, the same as -110/-110. **Not done:** `pregame`
rows written before the migration (56 NBA, 128 college, all 2026-27) keep NULL prices; their scoreboard responses
were overwritten by later fetches.

### 2026-11-06: Simulation prices each spread/total bet from its own odds row; -110 only as a counted fallback
**Why:** The $100 simulation assumed -110 for every spread/total bet; the price backfill made real prices available.
**Decision:** `simulate.py --pricing real` (new default) pays a bet at the stored American price of its side on the
**same** odds row that supplies the line (latest closing / earliest opening). It never borrows a price from another row,
book or capture time, because a price only means something next to its own number. A NULL/invalid price falls back to
-110 and is counted in the report. `--pricing=-110` keeps the old behavior and, with `--until 2026-11-04`, reproduces
docs/results/2026-11-04-sim-v1-100usd.md exactly. The price never affects which side is picked (tested). **Result:** at the
close real prices ≈ -110 (no change); at the open the model's picks carry worse prices (≈ -113/-114; ≈ -120 at 5+ point
disagreements), which cuts v1's opening-totals run from $171.63 to $111.44 (v1.1 $136.89). Details:
docs/results/2026-11-06-sim-v1.1-prices.md. **Chart:** the new bankroll chart swaps the old chart's red series for purple
(#7b1fa2), because the validator failed the old orange/red pair on normal-vision separation (ΔE 10.3 < 15).


### 2026-11-06: Ensemble betting: independent LLM bettors, strict majority, watch-only
**Why:** The owner asked for N subagents to pick bets for the next 3 days independently and to see what a
majority agrees on. **How independence is kept:** every bettor gets the same facts in its own context file
(games shuffled with a per-agent seed so list position can't drive agreement), has only the Read tool
(`bettor` agent; general-purpose + the same instructions until a new session loads the agent type), and all
are launched in one message; replies are saved only after all finish. **Fairness:** the line and price of
every pick come from the slate, never the agent; picks on games that tipped before the tally are dropped;
games tipping within 60 min are left out; a run is tallied once. Consensus = votes > N/2 of all agents
(a pass counts in the denominator). **Storage:** run files on the external drive
(`reports/ensemble-bets/`), not the warehouse: no schema change and no writer lock. **Caveat recorded
in the brief and the skill:** bettors reading the same facts are correlated, so agreement is not evidence of
an edge; the project's models don't beat the close. Graded with `ensemble-bets grade`.

### 2026-11-06: Daily ensemble vote at 14:00 with 10 bettors, 1-day window
**Why:** owner asked for a daily run with 10 agents. **How:** `tools/ensemble-daily.sh` at the end of the 14:00
scheduled sync (afternoon only: most of that night's lines are posted). Window = games tipping 1 h to 24 h out, so
consecutive daily runs never vote on the same game. The script does every `deepsports` step (headless Claude can't
open the warehouse); headless Claude on Sonnet only launches the bettors and writes their replies. Measured
2026-11-06: ~30k Sonnet tokens per bettor with a 31-game slate (≈$0.06 list each), on the owner's claude.ai
subscription (no API key). Coordinator moved from the default Opus to Sonnet (it cost more than two bettors).

### 2026-11-06: Ensemble betting evolves through versioned context
**Why:** bettors see nothing but their context file, so the context is the tool's main lever (owner's
direction). **Decision:** the brief + facts carry a `CONTEXT_VERSION` (`ctx-v1` = the first run's context);
bump it whenever the brief or the facts change and log what changed here. `slate.json` and `tally.json`
record it and `ensemble-bets grade` reports each version separately (runs without one count as ctx-v1).
A new version replaces the old only when its graded majority record beats the old one, so a context change
can't look like progress just by being richer. Candidate improvements are listed in ROADMAP Phase 4.

### 2026-11-06: Ensemble backtest context `ctx-v1-sim1` (one pick a day, closing lines)
**Why:** owner asked for a 10-bet historical test. **Design:** NBA only, 10 game days 2026-10-23 → 11-04 (after
the bettor models' training cutoff, so results can't be remembered); decision time 1 h before the first tip;
`load_historical_slate` is point-in-time (form from finished games only, walk-forward v1.1, injuries captured
before `now`); lines are the closing (final pre-tip) lines, opening = "first seen"; each bettor makes exactly
one pick; the day's bet is the plurality pick (ties: confidence, then game_id). Known leak: closing-line
movement can carry news from after `now`. **Result (5 bettors × 10 days):** ensemble 5-5, −0.25 units; model's
biggest edge 5-5, −0.40; all 50 agent picks 24-26, −4.0. Ten bets can't distinguish skill from luck.
Files: `/Volumes/ExFATStorag/DeepSports/reports/ensemble-bets-sim/` (`results.txt`).

### 2026-11-06: Ensemble context ctx-v2 (more pre-tip data), live default stays ctx-v1 until tested
**Why:** owner: use all data that could improve the picks, measured by the versioned-context rule. **ctx-v2 adds**
(point-in-time, `analysis/ensemble_context_v2.py`): last-season record/margin/final rating; rating now (college
ridge net rating + D1 rank; NBA Elo + net rating per 100); pace and off/def per 100; NBA injury impact (share of
minutes/points missing, v1.1 availability terms); live-only line timing from the 30-min captures; base-rate table
(home ATS, favorite cover by spread bucket, over by total bucket) from earlier seasons only, labelled descriptive.
Brief otherwise unchanged. ~1.46x v1 tokens on 25-game college slates, ~1.67x on small NBA slates. **Test:** 10 fresh
anonymized 2025-26 college days, v1 and v2 arms on identical games, 5 bettors each, plan pre-declared in
`reports/ensemble-ctx-test/PLAN.md` (primary: units on all 50 picks per arm; paired day-clustered bootstrap).
Underpowered (MDE ~0.5-1.2 units/pick), so v2 goes live only if its CI excludes 0, or after ≥200 live picks show it
isn't worse. Live flag: `ensemble-bets context --context v1|v2` (default v1). Known non-point-in-time bits: today's
D1 list; prior-model config tuned on 2024-25.

### 2026-11-07: Scheduled jobs touch the external drive only through uv's Python
**Why:** the first scheduled ensemble vote (2026-11-07 14:02) saved 0 of 10 replies. Under launchd, macOS refuses
`/bin/bash` globs, `ls`, `cp` and `/usr/bin/python3` on the drive (`Operation not permitted`; a plain `-e` test still
passes), while uv's Python 3.12 can read and write it. A throwaway launchd job confirmed this. **Change:**
`tools/ensemble-daily.sh` does its drive file work through `uv run python` and skips the vote (with a Discord alert) if
the context files didn't all copy. Also fixed an f-string that is a SyntaxError on the system Python 3.9. Chosen over
granting more macOS permissions: it needs no owner action on the Mac's screen and doesn't widen access. **Rule:** new
launchd scripts must not read or write the drive with shell tools or the system `python3`.

### 2026-11-08: Live game detail polls ESPN every 10s and infers possession conservatively
**Why:** the Gamecast-style live screen needs play-by-play soon after it happens. 10s is compliant: requests still go
through `PoliteClient` (1 req/s), it costs ~6 requests a minute per live game someone is viewing and nothing otherwise,
and `src.summary` only reuses a completed game from disk, so the TTL is the only delay. **Possession:** whether ESPN sends a live
value for basketball is unverified (finished summaries say `false` for both teams; a saved live scoreboard has none), so
the API uses ESPN's value if present, else infers from the latest play, labels it `"inferred"`, and returns `null` rather
than guess (timeouts, ordinary fouls, tips, period ends). Plays' scores use a
running max without parse_pbp's anchor to the header's final, because a live header can run ahead of the plays.
Parsing lives in `api/views.py` and reuses parse_pbp's helpers; parse_pbp itself is unchanged because models depend on it.

### 2026-11-10: Drive access errors fail fast and alert; only a real lock counts as "busy"
**Why:** on 2026-11-08 from about 13:57 until the macOS 27.2 update restarted the Mac (15:37), every launchd open of
the warehouse failed with `Operation not permitted`. The 14:00 sync ran all six update/predict steps anyway (each waited
15 s, because `Store` retried every IOException) and sent no alert. The odds job and the API reported the same error as
"warehouse busy". After the restart it worked again with no permission change, so the fix is in how jobs fail, not in macOS
settings. **Change:** `store.is_lock_conflict()`; `Store` retries only lock conflicts; `odds-snapshot` exits 1 with
`FAILED, cannot open the warehouse` on other errors; the API returns `warehouse_unavailable` for them; `scheduled-sync.sh`
preflights a read-only open (3 tries, 60 s apart), then alerts on Discord and exits 4.

### 2026-11-10: Injury-aware NBA model v1.1i as a separate graded version, refreshed by a pre-tip job
**Why:** live NBA predictions ignored the injury report: v1.1 only knows who played the previous game. The pre-tip
snapshots (`injury_captures`/`injury_reports`, since 2026-11-03) and the players.py `injury_override` hook already existed
but were off everywhere. **Change:** `v1.1i` = v1.1's frozen model and features with the override on (a team's latest
pre-tip snapshot: top-6 players listed `Out` count as missing, instead of "played last game"). A team without a capture
keeps the box-score rule; a game where neither team has one gets no v1.1i row. The override is tied to the label
(`model.INJURY_OVERRIDE_VERSIONS`; `predict_upcoming` no longer takes an `injury_override` flag), so a stored label and
its behavior can't disagree. New `deepsports pretip` (launchd `com.deepsports.pretip` at :20 and :50, `Nice` 10, low-priority
I/O): for NBA games tipping in 5-100 minutes it fetches one fresh summary each with no lock held, then in one short writer
session stores the snapshots and writes v1.1i for exactly those games; it yields to every other writer like
`odds-snapshot`. The 08:00/14:00 sync also predicts v1.1i (after v1.0 and v1.1) for games whose report `update` captured.
**Why a separate version, not a replacement for v1.1:** snapshots only start 2026-11-03, so there's no history to
backtest on (training rows are identical to v1.1: completed games never use snapshots). The live record is the test.
**Where it shows:** the app prefers v1.1i, then v1.1 (labelled by `model_version`); `/api/predictions/record` stays on
v1.1 by default (`?model_version=v1.1i` for its record). The calendar (`config.CALENDAR_EXCLUDED_VERSIONS`), the paper
log and the ensemble vote stay on v1.1, so frozen rules and calendar text don't change underneath them.
**How to judge it:** compare v1.1i with v1.1 **paired on the same games** (both versions exist for every v1.1i game).
Their overall records cover different games (v1.1i only where a report was captured) and are not comparable.
**Known limits:** only ESPN status `Out` counts, so Questionable/Day-To-Day players who are scratched late are missed
(and a listed Day-To-Day player who sits is still "available"); the last run is 5-35 minutes before tip, so later news
is missed; college has no injury source (ESPN lists none), so there is no college equivalent.

### 2026-11-10: Dev agents move to the repo root; runtime agents and skills stay; basketball only
**Change:** `architect`, `data-engineer`, `data-analyst` and `frontend-dev` moved from `DeepSports/.claude/agents/`
to the repo root's `.claude/agents/` (registry and orchestrator rules in `../AGENTS.md`). `bettor`, `calendar-agent`,
`/sync-game-calendar` and `/ensemble-betting` stay in `DeepSports/.claude/`. DeepSports' CLAUDE.md, AGENTS.md and
docs now hold only DeepSports specifics and point to the root for repo-wide rules; README.md's Docs table is the one doc index.
**Why:** a session started at the repo root can't see `DeepSports/.claude/`, while a session started in `DeepSports/`
still sees the root agents (verified), so the root is the one place every dev session finds them. The runtime agents and
skills are called by DeepSports' headless scheduled jobs, which run from `DeepSports/`.
**Scope:** basketball only (NBA + NCAA men's D1). The other-sport plans were removed from PRODUCT, ROADMAP, HANDOFF and
DATA_SOURCES; DeepSports and ManualBets will be integrated step by step, each step logged in `../docs/DECISIONS.md`.

### 2026-11-10: web/ frozen; BetDesk mirrors the read API (pusher replaced by a tunnel 2026-11-11, below)
**Why:** both owners need the app away from the home Wi-Fi; the owner chose a separate Cloudflare-hosted
project, `../BetDesk`, which copied `web/` and now gets all new UI work. `web/` stays as the LAN build
(fixes only). BetDesk's pusher reads this API over HTTP every minute (`../AGENTS.md`, edge 3), so the
API contract in `API.md` now has a second consumer: changes to it should be mirrored in BetDesk's
pusher plan and Worker allowlist. Repo-wide entry: `../docs/DECISIONS.md`.

### 2026-11-11: Player impact ratings dropped; slate-clustered intervals govern correlation tests
**What:** NBA player ratings (game-level ridge "RAPM-lite") and injury impact in points, tested as a v1.2
candidate (v1.1 + `imp_avail_diff` + `imp_missing_diff`) under a pre-registration (docs/results/2026-11-11-player-impact.md).
**Why dropped:** the pre-registered ship rule fails on the locked 2025-26 holdout (margin MAE -0.049, CI -0.159 to
+0.061); the train gain is team strength, not injury information; there is no edge vs opening or closing lines; and the
star ratings fail face validity (a Jokic absence comes out at ~1.5-2 points), so the output isn't usable as an "injury
impact in points" number either. The "ensemble context only" fallback needed the missing-impact vs open-to-close
correlation to exclude 0 in both periods; it does with Fisher intervals but not with the slate-cluster bootstrap.
**Rule from here on:** for this and future correlation (and other per-game) tests, the slate- or day-clustered
interval governs over Fisher or other independence-assuming intervals: games on one slate share news and market moves,
so they aren't independent. Report both when a pre-registration names Fisher, and say which one decided.
**Scope:** analysis only. `player_impact.py` / `player_impact_eval.py` stay as research tooling with tests; nothing is
wired into `predict`, `pretip`, the API or the ensemble context. Revisit only with better ratings (box-score prior or
stint-level RAPM) that pass a face-validity check first (ROADMAP).

### 2026-11-11: ensemble bettors see ManualBets and the Odds API (`+mb1`)
**Why:** the owner found the daily vote used only DeepSports facts, against the standing rule that betting
analysis uses all of the repo's tools (`../AGENTS.md`). The bettors stay Read-only on one context file (their
independence is the experiment), so the tools reach them as facts: `tools/ensemble-daily.sh` runs
`../ManualBets/tools/export_predictions.py` (2 Odds API credits/day, +3 for college once teams have 5 games)
and `ensemble-bets context --manualbets` attaches it. Runs with it carry `context_version` `ctx-v1+mb1`, so
`grade`'s `by_context_version` keeps their record apart. A failed export doesn't block the vote. Repo-wide
entry (edge 4): `../docs/DECISIONS.md`.
**Pi (same day):** nba.com blocks NordVPN even on a dedicated IP, so the NBA half runs on the owner's Raspberry Pi
(`tools/manualbets-export.py`, PIPELINE.md). The owner asked that access there stay inside one folder,
`~/SportsRLAgent`, uv included.

### 2026-11-11: BetDesk reads this API live through a Cloudflare Tunnel
Replaces the pusher of the 2026-11-10 entry above: BetDesk's Worker forwards allowlisted GETs to
`localhost:8787` through `cloudflared` on this Mac, so `serve` must stay up for the phone app to work.
No change to the API itself; contract changes the app uses go into BetDesk's Worker allowlist.
Repo-wide entry: `../docs/DECISIONS.md`.

### 2026-11-11: ensemble bettors may research (`+tools1`); Discord gets a table
**Why:** the owner wants the 14:00 vote to use every tool of the repo (DeepSports and ManualBets) and to
arrive on Discord as a table of what to bet. Bettors now have Read/Grep/Glob, `curl -s` on the read API
(`localhost:8787`), WebSearch/WebFetch, and ManualBets' folder (`--add-dir`). Kept out on purpose: other
shell commands (one DuckDB writer: the pretip/odds jobs write during the vote; the API handles the lock),
per-bettor Odds API calls (20× the quota; the context already carries the 14:00 lines and ManualBets'
best prices, and picks are graded at the slate's price anyway), and reading other bettors' picks or
earlier runs (permission deny rules plus the bettor brief: independence is the experiment). Runs carry
`context_version` `…+tools1` (`ensemble-bets context --tag`), so `grade` keeps their record apart.
The Discord post is `ensemble-bets table`. Owner asked for 20 bettors on 2026-11-12 only:
`.sync/ensemble-agents.<date>` is a one-day override read by `tools/ensemble-daily.sh`.

### 2026-11-11: ensemble run hardening (two-reviewer pass)
**Why:** the owner asked for recommendations agreed between Claude and a second agent before the +tools1 PR.
Done now: (1) 0 replies → "blocked" alert and the run is left untallied, since a tally would freeze it as "no
majority" and `grade` would count it (run `20261107T220208Z` was exactly that); fewer than N replies is stated in
the post. (2) `timeout` on `claude -p` (2400 s; 20 researching bettors have no timing yet) and cost/duration in the
log. (3) `parse_reply` takes the last JSON object with a `picks` list, and the coordinator must save replies
verbatim (on 11-11 it "corrected" a reply with two objects, which hid a bettor mistake). (4) Discord's record line
covers the run's context version only, not all versions pooled. (5) Bettors date their web queries and ignore
pages older than 48 h (a test search returned 2024 injury pages). Later items (CLV grading, model-only baseline,
bettor count, worktree on `main`, `sources`, version tag) are in ROADMAP.

### 2026-11-12: ensemble run hardening, round 2
**Why:** a second two-reviewer pass over the first `+tools1` runs. Done now:
(1) Picks carry a `bet` text (`TOR +5.5`, `Over 214.5`, `TOR ML`) that `validate_picks` checks against `side`: a clear
contradiction drops the pick, a missing `bet` only logs a problem. Run `20261111T223533Z` agent a01 picked `side: away`
(BOS) with the reason "TOR +5.5"; nothing caught it. The check is lenient ("TOR +5.5 at -108" passes) and old replies
(no `bet`) are unaffected. The opponent's abbreviation must match in exact case, since college codes `WIN`, `NO` and
`OU` are ordinary words ("Duke to win" against Winthrop is not a contradiction). The BRIEF change also reaches the backtest/sim contexts (same `render_context`).
(2) A confidence below the price's break-even is logged as a problem, pick kept: it shows a bettor betting against
its own number, but dropping it would second-guess the vote.
(3) Bettor brief: about 8 tool calls / 10 min of research, then answer: the run has a hard cap and a late answer is lost.
(4) `ensemble-daily.sh`: the one-day override accepts only a number 1-30 (the old `tr -dc 0-9` turned "1 5" into 15);
a failed `ensemble-bets context` is retried once after 60 s (a writer may hold the lock briefly), then a "blocked" alert.
(5) The ManualBets export is capped at 1200 s (a hung ssh/nba.com call must not eat the vote; the vote still runs
with `--manualbets none`), and the `claude` cap is now 3000 s (more headroom for researching bettors; the export cap keeps the total bounded).
(6) The picks copy to the drive is counted: fewer files than replies → "blocked" alert and no tally, since a tally
would freeze the run without them.
(7) Bettors may not read `.sync/ensemble-sim/` or `~/Library/Logs/DeepSports/` (other runs' picks and the sync log).

### 2026-11-12: ensemble replies are saved outside any deny rule
**Why:** the 14:00 run (`20261112T220340Z`, 20 bettors) saved 0 of 20 replies. `cdd93d7` added the deny rule
`Read(./.sync/ensemble/picks-*)` to keep bettors from reading each other's picks, but `--disallowedTools` covers
the whole session, coordinator included, and a Read deny also blocks Write to that path. The coordinator now
saves replies to `.sync/ensemble/replies/` with no deny rule, and only after all N bettors have finished, so no
bettor can still be running to read them (the folder is emptied at the start of each run; earlier runs on the
drive stay denied). The bettor brief still forbids opening it. The run was recovered by hand: the 20 replies,
taken verbatim from the blocked writes recorded in `.sync/ensemble-claude.json`, were tallied at 14:31 PT,
before any picked game tipped (the earliest at 16:00 PT).
