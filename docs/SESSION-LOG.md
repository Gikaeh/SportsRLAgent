# SESSION-LOG.md — current state (exactly ONE live entry)

When a session ends, move the old entry verbatim into `docs/SESSION-LOG-ARCHIVE.md`
(append-only, newest on top) and write a fresh self-contained entry here.

---

## 2026-08-22 — Basketball remediation Batches 1–3 complete; retrain pending

**Done**
- Batches 1+2 (see archive for detail): A2 chronological splits
  (`shared/splitting.py`), A1 leak-free player selection + zero-fill alignment
  (`prepare_data.py::getTopPlayersAsOf`), B1 odds window filter, B2 same-book
  line/price pairing, B3 fresh-log crash, B4 push grading `'P'`.
- **Batch 3 — C1:** `betting_recommender.py` cover probabilities are now
  `normalCoverProbability(edge, sigma)` = Φ(edge/σ), replacing the old logistics
  that returned ≥0.5 for any positive edge. σ comes from
  `models/metadata/retraining_*_metadata.json['residual_std']`, which
  `model_retrainer.py` now writes after each spread/total retrain (val-based);
  until the next retrain, config fallbacks apply (spread 11.8 / total 14.0,
  league-typical placeholders).
- **Batch 3 — C2:** h2h edges are devigged (`devigTwoWay`: fair = implied /
  overround of both best prices). The `market_prob` column in bet logs now stores
  the DEVIGGED fair probability (semantic change going forward). MIN_EDGE_H2H=0.02
  now means 2% vs fair prob; expect ~2% more headroom than the old vig-inclusive
  numbers.
- Owner is handling the full data refetch + rebuild of training CSVs and a single
  big retrain (old training files were built with leak-era feature semantics;
  `prepareAllSeasons` skips existing season files unless they are deleted first).
- pytest: 11 passed.

**Next** (after owner's refetch + retrain)
1. Sanity-check retrain output: metadata `residual_std` populated and printed as
   "(measured)"; val/test metrics on clean chronological splits (expect lower than
   historical logs); split date ranges strictly ordered train < val < test.
2. Batch 4 hardening per `basketball/NOTES.md` §Suggested fix order: A5 single
   source of truth for drop lists, A4 remainder, C-R3 ladder collapse +
   availability gating, C3/C4 feature additions.
(M1 secrets cleanup remains queued if not done sooner.)

**Blocked-open (awaiting owner, not code)**
- Odds API key rotation: key is public in git history regardless of code cleanup.
- Injury system revisit: deferred by owner until after remediation batches.
- Hockey mirror debt: identical issues likely exist in hockey's pipeline; out of
  scope until owner says so.
