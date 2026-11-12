# Roadmap

Basketball only (NBA + NCAA men's D1). Open items first; tick them as they land. The done summary
at the end links to the dated results; the "why" for each step is in DECISIONS.md.

## Open

### Glasses and app
- [ ] **Owner setup:** Even app ≥ 2.2.10, sign in at hub.evenrealities.com to unlock Developer Mode
- [ ] Keep the Mac's address stable (DHCP reservation for 172.16.0.61); the packaged glasses build has it built in
- [ ] Test on the owner's phone: does the glasses plugin keep updating with the phone locked or the app in the
      background? (The docs contradict each other; assume foreground-only until tested.)

### Features and ratings
- [ ] Derived tables: possessions, pace, offensive/defensive rating, four factors
- [ ] Team strength ratings (Elo → adjusted net rating)
- [ ] Re-test the "back-to-back after eastward travel" effect on recent seasons; add time zones
- [x] Team strength from **available players**: tried 2026-11-11, negative (no edge vs v1.1 or the lines; the gain is
      team strength, not injury info; star ratings not face-valid): [results/2026-11-11-player-impact.md](results/2026-11-11-player-impact.md)
- [ ] Better player ratings (box-score prior or stint-level RAPM from play-by-play), gated on a face-validity check
      (stars in the top tier; a Jokic absence worth 4-6 points) before re-running the player-impact backtest
- [ ] Official NBA injury report ingestion (M, high value): point-in-time "who was listed before tip". Review NBA.com terms first (cdn.nba.com's 403 was caused by NordVPN's datacenter IP; it works with the VPN off, 2026-11-10)
- [ ] Referee crews vs totals (S backtest, from cached summaries)
- [ ] Injury-impact score over `pregame_injuries` (weights learned, not hand-set)
- [ ] Maybe: a `v1.2i` shadow (v1.1 + impact features with the real pre-tip snapshot OUT lists, like v1.1i), graded
      live; only after better ratings, and backtest once 2-3 months of snapshots exist
- [ ] Rolling SRS/SOS beside Elo (with home-court term), measured incrementally
- [ ] Store play-by-play events in the warehouse if a play-by-play feature is ever wanted (`parse_pbp.py` is ready)
- Skip for now: news/social sentiment scoring, Reddit, NewsAPI, GDELT (no evidence of an edge over the closing
  line). Revisit a beat-reporter watchlist only for *speed* on injury news.
- Skip: reinforcement learning for bet policy, genetic/mutation search (backtest overfitting on ~1,200 games/season)

### Models
- [x] **Owner:** install the pre-tip job (`com.deepsports.pretip`; installed 2026-11-10)
- [ ] Review v1.1i vs v1.1 **paired on the same games** once a few hundred NBA games are graded (winner accuracy,
      margin MAE, log loss; day-clustered CI); promote or drop v1.1i then
- [ ] Questionable / Day-To-Day late scratches: v1.1i counts only ESPN `Out`; consider a later capture or another source for game-time decisions
- [ ] Compare the `ncaab-v1p` and `ncaab-v1` graded records once a few hundred gated games are final; re-test the
      early gate on 2026-27 (pooled rt_n 1–4 rule, declared in advance, score after Jan 31, 2027)
- [ ] Grade the SportsRLAgent comparison's forward freeze (21 games, Nov 8-10;
      `/Volumes/ExFATStorag/DeepSports/reports/srla-comparison-2026-11-07/forward_freeze.csv`)
- [ ] "Within N points" metrics in the backtest
- [ ] Model-run metadata + retrain triggers
- [ ] Re-test opening-line totals forward with real posting times (30-min captures since 2026-11-06) once a few hundred bets exist

### Betting research (watch-only)
- [ ] Review the paper-trade record at the end of the 2026-27 regular season (pre-declared; no rule edits before then, only new versions)
- [ ] Review the ensemble-betting record after ~200 graded majority picks
- [ ] Grade ensemble picks by closing-line value (points for spread/total, no-vig probability for ML; closing
  rows in `odds_snapshots`), majority and agent picks, by `context_version`, with bootstrap CIs. CLV gives a
  signal after ~50-100 picks; W-L needs hundreds. Check college closing-row coverage first
- [ ] Model-only baseline: on the same slates, grade "bet the model side when |model - line| > k". Bettors often
  echo the model's gap; if the vote doesn't beat this rule on CLV, the agents add nothing
- [ ] Settle the bettor count (10 vs 20) from the 2026-11-12 run's logged cost/time and the agreement between
  the 20-bettor majority and 10-bettor subsets
- [ ] Optional `sources` field per pick (kept by `validate_picks`) to audit whether research changes picks
- [ ] Decide whether a failed ManualBets export (`ctx-v1+tools1` vs `ctx-v1+mb1+tools1`) should share a record
- [ ] Run the launchd jobs from a worktree pinned to `main` (after the +tools1 PR merges), so dev branch
  switches never change what the scheduled jobs run
- [ ] College ensemble backtest on 2026-27 games with real names (option 2), once ~10 post-cutoff college game
      days are final (about 2026-11-20); compare with the anonymized 2025-26 run
- **Ensemble context is the lever.** Bettors decide only from their context file, so what we give them bounds
  their votes (the first run: every agent keyed on the model-vs-line gap). Improve it in versions
  (`CONTEXT_VERSION` in `src/deepsports/analysis/ensemble_bets.py`, logged in DECISIONS), each with its own graded
  record (`ensemble-bets grade` → `by_context_version`); a version counts only if its record beats the previous
  one. Candidates:
  - [ ] Injury impact in points (who's out × their on-court value), not just names and mpg. Not shipped 2026-11-11:
        the ratings aren't face-valid ([results](results/2026-11-11-player-impact.md)); prerequisite = box-score prior
        or stint-level RAPM
  - [ ] Line-movement timing from the 30-min captures (when it moved, how far, against the public side?)
  - [ ] Opponent-adjusted ratings and recent efficiency (offense/defense, pace) beside raw margins
  - [ ] Each market's historical context (e.g. how often 30+ pt college spreads cover) from our warehouse
  - [ ] Diversity: different lenses or models per bettor, so votes are less correlated
  - [ ] Feedback: show bettors the graded record of past picks by type (watch for overfitting to noise)

### Data
- [ ] Optional (owner): fill missing college closing moneylines from ESPN BET's core-API close where DraftKings is `OFF` (61 games in 2025-26 Nov–Jan; offline from cache)
- [ ] Owner decision: paid multi-sportsbook odds API (the-odds-api.com)?

### Integration with ManualBets
- [ ] Merge step by step into one data source and one app; each step is proposed and logged in `../docs/DECISIONS.md` before it's built

## Done (summary)
- **Data pipeline + calendar (2026-11-03/04):** ESPN source with `PoliteClient` and raw landing zone, DuckDB
  warehouse (games, box scores, pregame/opening/closing lines with prices, ingest log), CLI, fixture tests,
  NBA history 2021-22 → today (closing lines ~100%), `deepsports check` with known ESPN gaps as warnings,
  `/sync-game-calendar` with followed teams, scheduled sync at 08:00/14:00, calendar events link to the web app.
- **Live scores + web app (2026-11-03):** read API (`deepsports serve`, live ESPN with a TTL cache, never
  touching the DuckDB lock), mobile PWA (Today, Game, Standings, Team, Model), launchd server, remote access.
- **G2 glasses (2026-11-03):** Even Hub plugin served at `/glasses/`, packaged private build works on the G2
  ([research/even-realities-g2.md](research/even-realities-g2.md)).
- **College basketball (2026-11-03/05):** league-aware keys and `migrate()`, all D1 games 2023-24 → today,
  Nevada followed, college in the API, web app and glasses; college Elo + ridge ratings.
- **Analysis (2026-11-03):** home court, market accuracy, Elo vs market
  ([results/2026-11-03-analysis.md](results/2026-11-03-analysis.md)); rest/travel (`team_game_context`); pre-tip
  injury snapshots. Analysis lives in importable modules under `src/deepsports/analysis/` (guide:
  [analysis/README.md](../analysis/README.md)), not notebooks.
- **Predictions:** NBA v1.0 ([results/2026-11-03-backtest-v1.md](results/2026-11-03-backtest-v1.md)) and v1.1 with
  player availability ([results/2026-11-04-backtest-v1.1.md](results/2026-11-04-backtest-v1.1.md)) beat Elo but
  not the closing line; v1.1i adds pre-tip injury reports via `deepsports pretip` (2026-11-10, graded live).
  College `ncaab-v1` ([results/2026-11-04-ncaab-v1.md](results/2026-11-04-ncaab-v1.md)) and the cross-season
  prior `ncaab-v1p` / `ncaab-v1-early` ([results/2026-11-06-ncaab-prior.md](results/2026-11-06-ncaab-prior.md)):
  beat Elo, behind the close. Predictions are stored pre-tip, graded (`prediction_results`) and shown in the
  calendar, web app and glasses.
- **Experiments not shipped:** Ensemble v2 ([results/2026-11-04-ensemble-v2.md](results/2026-11-04-ensemble-v2.md));
  calibrated `v1.1c` / `ncaab-v1c` ([results/2026-11-06-calibration.md](results/2026-11-06-calibration.md): the
  displayed probabilities are already calibrated; the pick gap is the winner's curse); DeepSeek edge hunt (no
  edge survives; its reusable code ported to `analysis/betting/`, `feature_test.py`, `fatigue.py`, `parse_pbp.py`);
  player impact ratings + injury impact in points as v1.2 ([results/2026-11-11-player-impact.md](results/2026-11-11-player-impact.md):
  no edge vs v1.1 or the lines, dropped; kept as research tooling in `player_impact*.py`).
- **Betting simulations:** $100 sim of v1 ([results/2026-11-04-sim-v1-100usd.md](results/2026-11-04-sim-v1-100usd.md))
  and at real prices ([results/2026-11-06-sim-v1.1-prices.md](results/2026-11-06-sim-v1.1-prices.md)): closing
  line → $0 on every market; opening totals positive but the CI includes break-even. Kelly not justified.
- **SportsRLAgent comparison** ([results/2026-11-07-srla-comparison.md](results/2026-11-07-srla-comparison.md)):
  v1.1 beats its honest version; neither beats the close.
- **Watch-only betting tools (2026-11-04/06):** forward paper-trade log with three frozen rules
  (`deepsports paper log|report`); ensemble betting (`/ensemble-betting`, daily 10-bettor vote at 14:00).
- **Line capture (2026-11-06):** 30-min pregame odds snapshots (`com.deepsports.odds`); historical prices
  backfilled from cache (`deepsports prices-backfill`).
