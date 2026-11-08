# Lessons from a friend's sports-betting project (review, 2026-11-03)

A DeepSeek research agent surveyed a friend's project (a private repo with NBA/NHL/MLB pipelines,
XGBoost models, and a betting recommender with ~2.5 months of logged bets), read-only, at the
owner's request. Another Claude session spot-checked its claims. This page is **our own
summary of the ideas and lessons**. No code, data, or credentials from that project are copied
here. The raw working notes stay local in `collab/` (git-ignored).

## Headline evidence
- **397 logged bets (Nov 2025 – Jan 2026) showed no statistically significant edge in any market.**
  NBA spreads hit 56.5%, but the 95% interval (49.6–63.2%) includes the 52.4% break-even. Moneyline
  picks the model rated ≥ 55% won only 42.6%, so its probabilities were miscalibrated.
- **Leakage inflates results by about 2 points of spread error.** With random (non-chronological)
  splits their spread MAE looked like ~9.7. Fixed to chronological, it's 11.49. Our v1 walk-forward
  margin MAE is 11.22 against a closing spread of 10.78. Same ballpark, so our backtest looks honest.

Both match our own finding: public-data models don't beat the closing line without something
the market lacks or prices late.

## Worth adopting (all go through our walk-forward backtest; nothing is trusted on their numbers)
| Idea | Why | Effort |
|---|---|---|
| **Player-availability features without an injury feed:** whether each team's top-6 players by minutes per game (pre-game rolling) missed the last 1–3 games; days since each last played | The best free proxy for "who's actually playing"; works on all our history | S–M |
| **Top-N player aggregates, especially plus-minus:** pre-game rolling stats of each team's top-3/top-6 players by minutes, and the spread of their scoring | In their importance analysis, top-6 total plus-minus was the #1 feature for win and spread models. Select players by **pre-game** stats only (their early version selected by the current game's minutes, which leaks) | M |
| **Injury-impact score** over our pre-tip `pregame_injuries` view: points and minutes lost from listed-out players plus a star-out flag; learn weights instead of hand-tuning | A direct form of availability-adjusted team strength | S |
| **Rolling SRS/SOS** (margin adjusted for opponent strength, re-solved daily, strictly pre-game) next to Elo | A shorter memory than Elo; add a home-court term and guard against a missing opponent | M |
| **Calibration check** on v1's win probabilities (reliability by probability bin) | Their miscalibrated ≥55% picks are the cautionary tale | S |
| **Train/predict column-parity test** | Catches the classic bug where a saved model expects different features than the live builder (live on their latest branch) | S |
| **"Within N points" accuracy** for margin and total in the backtest report | Easier to read than MAE for a newcomer | S |
| **Model-run metadata + retrain triggers** (e.g. retrain after ≥50 new games or 7 days; record version, training window, metrics) | Our `predictions.model_version` covers part of this | S |
| **Boosted-tree model tier** (XGBoost/LightGBM) as `v2` beside v1, judged only by our harness | May capture interactions (fatigue × travel); must earn its place | S–M |
| **NHL via the official `api-web.nhle.com`** (keyless). **Capture OT/shootout, period scores, and empty-net goals at ingest** | Their NHL data kept only final scores, so OT/SO can never be recovered: a one-way door | M |
| **Multi-sportsbook odds history** (the-odds-api.com, needs our own paid key) | Line shopping and market-disagreement features. **Owner decision:** cost vs value | S |

## Pitfalls we already avoid (keep it that way)
- Random train/test splits on time-series data (we're walk-forward).
- Selecting "top players" with information from the game being predicted.
- Measuring edge against vigged prices (we de-vig), or feeding hand-made probabilities into bet sizing.
- Grading pushes as losses.
- Scrapers with spoofed browser headers.
- Hardcoded API keys: theirs is in git history, so rotate it (see below).
- Models whose saved feature list drifts from the live feature code.
- Hand-tuned "magic multipliers" for injuries (they were disabled live).

## Notes to pass on to the friend (owner's call)
- Their odds-API key is hardcoded in three scraper files and in git history, so it should be rotated.
- On their latest branch, the saved models predate a feature-schema change (SRS/SOS added), so live
  prediction would hit a feature-name mismatch. Two tests fail, and the total model was never
  retrained after the leak fixes.
