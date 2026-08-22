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
  `models/metadata/retraining_*_metadata.json`; BettingRecommender loads it at
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
