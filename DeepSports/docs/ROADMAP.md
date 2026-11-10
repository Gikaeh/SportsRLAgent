# Roadmap

## Phase 1: NBA data collection + calendar (in progress)
- [x] ESPN source, polite client, raw landing zone, DuckDB warehouse
- [x] Games, team and player box scores, pregame line history, closing lines
- [x] `update`, `backfill`, `upcoming`, `status` CLI; ingest run log
- [x] Fixture-based tests
- [x] `/sync-game-calendar` skill + `config/calendar.toml`
- [x] 2026-27 season backfilled to date
- [x] Followed teams chosen (LAL, LAC, GS, BOS); first calendar sync
- [x] Backfill history 2021-22 → present + historical odds (7,267 games; closing lines ~100% per season)
- [x] Automate `update` + calendar sync at 08:00/14:00 (fixed 2026-11-04: warehouse steps run in the script, Claude reads `.sync/`)
- [x] Data-quality checks as a command (`deepsports check`)
- [x] Known ESPN gaps reported as warnings: 8 summary 404s, 29 team-games whose points don't add up (preseason boxes without points; an unidentified Chicago player in 2025-26)
- [x] Calendar events link to the game page in the web app (confirmed on NBA events 2026-11-06; college links added via `?league=ncaab`)

## Phase 2: Live scores + mobile web app
- [x] Live data without a poller: the API fetches ESPN on request with a TTL cache (30s while games
      are live, 5 min otherwise), so it never contends for the DuckDB lock
- [x] Read API (FastAPI, `deepsports serve`, docs/API.md): scoreboard, box score, standings, team page, glance
- [x] Mobile web app (`web/`, Vite + React + TS PWA): Today, Game, Standings, Team; stat explainers;
      busy/empty/error states; light and dark mode
- [x] Hosting: this Mac on port 8787 (LAN)
- [x] Test on the owner's phone (2026-11-03: "feels good so far")
- [x] Keep `deepsports serve` running across reboots: launchd agent installed 2026-11-03
- [x] Owner: grant launchd processes the macOS "Removable Volumes" permission (granted 2026-11-03)
- [x] Remote access: the Mac is reachable from anywhere through the owner's existing Tailscale setup (rpi400)

## Phase 3: Even Realities G2 glasses app
Research: [docs/research/even-realities-g2.md](research/even-realities-g2.md) (2026-11-03).
The path is an official **Even Hub plugin**: a TypeScript web page that runs in the Even phone app's
WebView and draws text on the G2 (576×288, green, about 400–500 characters per screen).
- [x] Research the developer path (Even Hub, SDK `@evenrealities/even_hub_sdk` 0.0.x)
- [x] CORS on the API (GET, any origin) so the WebView can call it
- [ ] **Owner setup:** Even app ≥ 2.2.10, sign in at hub.evenrealities.com to unlock Developer Mode
- [x] `glasses/` plugin (Even Hub SDK 0.0.16): polls `/api/scoreboard` (more structure than
      `/api/glance`); header + up to 5 lines, live first; tap = game detail, swipe = page,
      double-tap = exit; redraws only changed text; "stale" header; 12 tests; verified in the
      official simulator and against the real backend in a browser
- [x] Served by the API at `/glasses/` (same origin)
- [x] **Owner:** loaded on the G2 by QR; works on real glasses (2026-11-03)
- [x] Packaged build `glasses/deepsports-glasses.ehpk` (`npm run pack:lan`, API base `http://172.16.0.61:8787`) for an Even Hub private upload
- [x] Glasses plugin: uses `next_followed_game` (7-day lookahead kept only as a fallback for old servers)
- [x] Packaged private build works on the G2 through Even Hub (2026-11-03)
- [ ] Keep the Mac's address stable (DHCP reservation for 172.16.0.61); the packaged build has it built in
- [x] Backend: `next_followed_game` on today's `/api/scoreboard`
- [ ] Test early on the owner's phone: does it keep updating with the phone locked or the app in the background?
      (The docs contradict each other; assume foreground-only until tested.)

## Phase 4: Analysis
- [x] First report ([results/2026-11-03-analysis.md](results/2026-11-03-analysis.md)): home court 54–58% / +2 pts; closing-line favorite wins 68%; Elo vs market
- [x] Analysis restricted to games between two NBA teams (All-Star/exhibition teams were entering Elo)
- [ ] `analysis/` notebooks (DuckDB → polars/pandas)
- [ ] Derived tables: possessions, pace, offensive/defensive rating, four factors, rest days, back-to-backs, travel
- [ ] Team strength ratings (Elo → adjusted net rating)
- [x] Parse injuries from summaries (who's out, by game): pre-tip snapshots since 2026-11-03 (`injury_captures`/`injury_reports`)

### Fundamental data (from [research/fundamental-data-sources.md](research/fundamental-data-sources.md), 2026-11-03)
- [x] Rest/travel features (`team_game_context` view)
- [ ] Re-test the "back-to-back after eastward travel" effect on recent seasons; add time zones
- [ ] Team strength from **available players** (M, high value): player impact ratings from our box scores, adjusted for who's out
- [ ] Official NBA injury report ingestion (M, high value): point-in-time "who was listed before tip". Review NBA.com terms first (cdn.nba.com returned 403 for us)
- [ ] Referee crews vs totals (S backtest, from cached summaries)
- Skip for now: news/social sentiment scoring, Reddit, NewsAPI, GDELT (no evidence of an edge over the closing line). Revisit
  a beat-reporter watchlist only for *speed* on injury news, once we store line snapshots over time.

### From the SportsRLAgent review ([research/sportsrlagent-review.md](research/sportsrlagent-review.md))
- [x] Availability features (`analysis/players.py`): top-3/6 by pre-game mpg missing recent games, missing-minutes share, games since played → model **v1.1**
- [x] Top-N aggregates incl. top-6 plus-minus; ablation: plus-minus adds nothing beyond team form (r≈0.96), all v1.1 gain is from availability
- [x] Live injury-aware predictions: model **v1.1i** (v1.1 with the pre-tip `Out` list replacing "played last game") + `deepsports pretip` (launchd `com.deepsports.pretip`, :20/:50) refreshing NBA injury reports and v1.1i 5-100 min before tip; app prefers v1.1i, calendar/paper/ensemble stay on v1.1 (DECISIONS 2026-11-10)
- [ ] **Owner:** install the pre-tip job (`tools/launchd/install.sh install com.deepsports.pretip`) after a manual `tools/pretip.sh`
- [ ] Review v1.1i vs v1.1 **paired on the same games** once a few hundred NBA games are graded (winner accuracy, margin MAE, log loss; day-clustered CI); promote or drop v1.1i then
- [ ] Questionable / Day-To-Day late scratches: v1.1i counts only ESPN `Out`; consider a later capture or another source for game-time decisions
- [ ] Injury-impact score over `pregame_injuries` (weights learned, not hand-set)
- [ ] Rolling SRS/SOS beside Elo (with home-court term), measured incrementally
- [x] Calibration check for v1 win probabilities ([results/2026-11-06-calibration.md](results/2026-11-06-calibration.md)): NBA v1.1 and ncaab-v1 are calibrated to within sampling noise (holdout ECE 0.031 / 0.034, slope 1.06 / 0.88); the moneyline pick gap is the winner's curse (model weight next to the close ≈ 0). The declared rule passed only via a negligible ECE drop, so `v1.1c` (L2 C 0.03) / `ncaab-v1c` (C 0.1) exist but aren't wired in
- [ ] "Within N points" metrics in the backtest
- [x] Train/predict column-parity test (models now fail loudly on a missing feature column)
- [ ] Model-run metadata + retrain triggers
- [x] Ensemble v2 (Elo + v1.0 + v1.1 + boosted trees) scored once on a **locked holdout** (all of 2025-26; tuned on 2023-25 only) ([results/2026-11-04-ensemble-v2.md](results/2026-11-04-ensemble-v2.md)): no better than v1.1 (log loss +0.0006, CI −0.0017 to +0.0029; margin MAE −0.007, CI −0.046 to +0.032); trees alone worse. **Not shipped**
- [x] College (NCAAB) v1 backtest ([results/2026-11-04-ncaab-v1.md](results/2026-11-04-ncaab-v1.md)): locked holdout Feb–Apr 2026 (1,949 games, scored once). Beats Elo (log loss −0.008, margin −0.65, CIs exclude 0), ECE 0.024; behind the close (log loss +0.013, margin +0.14, total +0.28, CIs exclude 0); flat bets 50.7% ATS / 49.5% totals. Closer to its close than NBA v1.1 is, but no edge. Ship rule: ship as context
- [x] Wire college v1 into `deepsports predict --league ncaab` (version `ncaab-v1`), the scheduled sync, and the API's `prediction` on college cards/game detail, as context: ratings for scheduled games, league-aware line limits in `PREDICTION_RESULTS_SQL`, per-league `/api/predictions/record`. Gate: both teams D1 with >= 5 games this season (DECISIONS 2026-11-04)
- [x] Edge hunt (DeepSeek, pre-registered; `collab/deepseek/EDGE_REPORT.md`): no betting edge survives the family placebo and holdout (DECISIONS 2026-11-04)
- [x] Port the edge study's reusable code: `analysis/betting/` (grading, CI, CLV, audit), `parse_pbp.py`, `analysis/feature_test.py`, `analysis/fatigue.py`
- [x] Forward paper-trade log: `paper_bets` + `paper_results`, `deepsports paper log|report`, in the scheduled sync; rules `ncaab-total-t7`, `nba-total-t4`, `nba-load-under` frozen (DECISIONS 2026-11-04)
- [x] Ensemble betting (`/ensemble-betting`, `deepsports ensemble-bets`): N independent bettor agents, strict-majority picks, watch-only, graded per run (2026-11-06)
- [ ] Review the ensemble-betting record after ~200 graded majority picks
- [ ] College ensemble backtest on 2026-27 games with real names (option 2), once ~10 post-cutoff college game days are final (about 2026-11-20); compare with the anonymized 2025-26 run
- **Direction: ensemble betting is an evolving tool; its lever is the context.** Bettors decide only from
  their context file, so what we give them (and how) bounds their votes. The first run showed it: all
  agents keyed on the one strong signal offered (model vs line gap). Improve the context in versions
  (`CONTEXT_VERSION` in `analysis/ensemble_bets.py`, logged in DECISIONS), each with its own graded
  record (`ensemble-bets grade` → `by_context_version`); a change counts only if its record beats the
  previous version's, not because it reads better. Candidate additions:
  - [ ] Injury impact in points (who's out × their on-court value), not just names and mpg
  - [ ] Line-movement timing from the 30-min captures (when it moved, how far, against the public side?)
  - [ ] Opponent-adjusted ratings and recent efficiency (offense/defense, pace) beside raw margins
  - [ ] Each market's historical context (e.g. how often 30+ pt college spreads cover) from our warehouse
  - [ ] Diversity: different lenses or models per bettor, so votes are less correlated
  - [ ] Feedback: show bettors the graded record of past picks by type (watch for overfitting to noise)
- [ ] Review the paper-trade record at the end of the 2026-27 regular season (pre-declared; no rule edits before then, only new versions)
- [ ] Store play-by-play events in the warehouse if a play-by-play feature is ever wanted (`parse_pbp.py` is ready)
- [x] College cross-season prior ([results/2026-11-06-ncaab-prior.md](results/2026-11-06-ncaab-prior.md)): Elo carry-over 0.75 + ridge prior from last season (ρ 1.0, λp 8), tuned on early 2024-25, locked holdout early 2025-26 (3,417 games, scored once). Beats no-prior (log loss −0.022, margin −0.49, CIs exclude 0; 1–2 games: −0.10 / −1.9); still behind the close; no edge. Ships by the rule; the declared gate test leaves the gate at 5 (3–4 bucket ECE 0.056)
- [x] Wire the college prior into `deepsports predict`: new version `ncaab-v1p` (>= 5 games, graded beside `ncaab-v1`, not displayed) and the opt-in `ncaab-v1-early` now from the prior model (switch 2026-11-06 09:00 UTC), one fit per run, in the scheduled sync
- [ ] Compare the `ncaab-v1p` and `ncaab-v1` graded records once a few hundred gated games are final; re-test the early gate on 2026-27 (pooled rt_n 1–4 rule, declared in advance, score after Jan 31, 2027)
- [x] `deepsports check`: the 7 listed college boxes > 2 pts off are known gaps (warn), keyed by team-game
- [x] College closing moneyline gap investigated: upstream (DraftKings `OFF`, mostly 20+ point spreads), per-field coverage in DATA_SOURCES.md
- [ ] Optional (owner): fill missing college closing moneylines from ESPN BET's core-API close where DraftKings is `OFF` (61 games in 2025-26 Nov–Jan; offline from cache)
- Skip: reinforcement learning for bet policy, genetic/mutation search (backtest overfitting on ~1,200 games/season)
- [ ] Owner decision: paid multi-sportsbook odds API (the-odds-api.com)?

## Phase 5: Predictions
- [x] v1.1 backtest ([results/2026-11-04-backtest-v1.1.md](results/2026-11-04-backtest-v1.1.md)): margin MAE 11.22→11.20 (paired CI excludes 0), Brier 0.2107→0.2103 (within noise); still behind the closing line. Daily: v1.0 + v1.1 both predicted and graded; the apps show v1.1
- [x] $100 betting simulation of v1 ([results/2026-11-04-sim-v1-100usd.md](results/2026-11-04-sim-v1-100usd.md)): closing line → $0 on every market (mostly the −110 cut); opening-line totals → $172 (hit 53.4%, CI 51.1–55.6%: not proof; openings have no posting time, so it's a best case). Kelly not justified
- [x] Re-run the simulation on v1.1 at real spread/total prices ([results/2026-11-06-sim-v1.1-prices.md](results/2026-11-06-sim-v1.1-prices.md)): closing line still → $0 on every market (real closing prices ≈ -110, cost < $0.003 per $2 bet); opening totals $171.63 → $111.44 (v1.0) / $136.89 (v1.1), because the model's opening picks sit on the dearer side (≈ -113/-114, break-even ~53.4%); no hit-rate CI clears its break-even. `simulate.py --pricing real|-110` (+ `--until`); v1.0 at -110 reproduces the old report exactly. Spread/total prices are stored going forward; opening-line posting times are now captured going forward too (30-min pregame captures since 2026-11-06), so a timestamped opening-line re-run is possible once a season has accrued
- [x] Model v1 (`analysis/model.py`): logistic win prob + ridge margin/total, features without odds, walk-forward backtest; 21 tests
- [x] `predictions` table + `Store.add_predictions`
- [x] Injury snapshots design: historical ESPN injuries leak (fetch-time), so only pre-tip snapshots are used (`injury_captures`/`injury_reports`, `pregame_injuries` view)
- [x] Backtest on real data ([results/2026-11-03-backtest-v1.md](results/2026-11-03-backtest-v1.md)): v1 beats Elo and home-always but **not** the closing line (Brier 0.211 vs 0.199; margin MAE 11.2 vs 10.8). ATS 48–50%: no edge
- [x] `deepsports predict` in the scheduled sync (103 NBA predictions on the first run); `prediction_results` grading view; `/api/predictions/record`
- [x] Predictions on API game cards (pre-tip only, graded once final) and in calendar events
- [x] Predictions + model record in the web app (Model tab) and glasses (game detail)
- [x] Baselines: home-court + Elo; market closing line as the benchmark to beat
- [x] Models for win probability, margin, and total; walk-forward backtests by season
- [x] Metrics: log loss / Brier, MAE vs closing spread, closing-line value
- [x] Predictions stored per game before tip-off; shown in calendar events, the web app, and the glasses

## Phase 5b: College basketball (men's D1), starting with the Nevada Wolf Pack
ESPN `basketball/mens-college-basketball` uses the same site API shape (362 D1 teams; Nevada = team 2440,
Mountain West). Checked 2026-11-03: the 2026-27 season started today.
- [x] League-aware keys + `Store.migrate()` (tested: identical row counts, no-op when re-run); `--league` across the CLI
- [x] API and analysis scoped to `league = 'nba'` (regression test: team id 5 is CLE and UAB)
- [x] Migration applied 2026-11-03 (backup: /Volumes/ExFATStorag/DeepSports/backups/); row counts identical
- [x] Follow Nevada in the calendar config (`[ncaab] teams = ["NEV"]`); the skill and scheduled sync are league-aware
- [x] College in the live API (`league=ncaab`): scoreboard, game detail, glance (Nevada first)
- [x] College in the web app (NBA · College switch) and glasses ("NCAA" marker); glasses v0.2.0 packaged
- [x] Collect all D1 games for the current season (needed for opponent strength), then backfill history
- [x] College Elo/ratings: Elo tuned for college (K 60, home 60, non-D1 pooled) + opponent-adjusted ridge (Massey-style) ratings, refit before every tip (`analysis/ncaab.py`); 2025-26 only, so no preseason prior yet
- [x] Backfill earlier college seasons (2023-24 and 2024-25; used by the cross-season prior)

## Phase 6: More sports
- [ ] Generalize the source/parser interface; add `league` to every key path
- [ ] NHL via the official `api-web.nhle.com` (keyless); **capture OT/shootout, period scores, and empty-net goals at ingest** (unrecoverable later)
- [ ] NFL
