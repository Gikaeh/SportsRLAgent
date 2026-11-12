# SESSION-LOG.md: current state (exactly ONE live entry)

At the end of a session, move this entry verbatim to the top of `docs/SESSION-LOG-ARCHIVE.md`
(append-only, newest on top) and write a fresh, self-contained entry here. Carry every still-open
Next item forward, so this entry's Next list is always the full open list.

---

## 2026-11-11 — NBA totals model backtested: stays disabled

**Done**
- New `tools/total_walkforward.py` (+ `tests/test_total_walkforward.py`, no network or warehouse): monthly-refit
  walk-forward of the NBA total model against DeepSports' closing totals and prices, the recommender's own 8-point
  edge rule, slate-clustered bootstrap CIs. Pre-registered before scoring.
- Result (`docs/results/2026-11-11-nba-totals-walkforward.md`): the ship rule fails on the locked 2025-26 holdout on
  both conditions (win-rate CI lower bound 42.3% vs 52.3% break-even; model MAE 0.83 pts worse than the closing total).
  Development seasons 2021-22 to 2024-25 lose too (-8.3% ROI on 892 bets). Totals stay out of the menu, logging and
  the export. Why: `docs/DECISIONS.md` 2026-11-11.
- Edge 2 widened (read-only warehouse access for this tool, `NBA_WAREHOUSE_DB`): `../docs/DECISIONS.md` 2026-11-11.
- Historical nba.com logs (2000-01 to 2025-26) were fetched on the LAN Pi (nba.com blocks the Mac's VPN;
  `../DeepSports/docs/PIPELINE.md`, "Raspberry Pi helper") into a scratch folder, not into `data/`.

**Verify**
- `uv run pytest -q`: 68 passed, 2 failed (the known `test_opp_avg_win_pct` failures; this Mac has no 2024-25 team file).
- An independent validator re-ran the backtest from scratch (bit-identical), recomputed every number without the
  tool, and ran future-perturbation leakage tests (no change before the cutoff). Results doc section 3.

**Next** (all open items)
1. OWNER: run the NBA menu once late in the evening (on Windows) and confirm it lists tomorrow's games and that
   Betting Recommendations gets past the odds call to the predictions step (pandas 3.1 dtype fix, 2026-11-08).
   On the Mac, pause NordVPN first or run NBA fetches on the Pi.
2. Grade the 5 open Nov 9 bets by hand from final scores: Hawks +2 ($3), TOR -2.5 ($5), DEN @ HOU Over 216.5 ($5),
   NO @ GS Over 231.5 ($5), Illinois St @ Purdue Over 145 ($3). Rows are in `../logs/basketball/betting/spread_bets.csv`,
   `total_bets.csv` and `../logs/college_basketball/betting/bets.csv` (still ungraded on 2026-11-10).
3. M1 secrets cleanup (`docs/PROJECT.md`): move the Odds API key to an environment variable in every `odd_scraping.py`,
   keep it out of URLs printed in errors, and ask the owners about rotating it.
4. Batch 4 hardening (`basketball/NOTES.md`): A3, A5, C-R3, C3/C4, then the pending B bugs.
5. NBA totals: only revisit with new information the market doesn't already price (C3 market features, C4
   availability, injuries), and re-run `tools/total_walkforward.py` with a fresh pre-registration; the 2025-26
   holdout is now spent, so lock 2026-27 as the next holdout.

DeepSports-side follow-ups now live in `../DeepSports/docs/HANDOFF.md` (Next steps).
