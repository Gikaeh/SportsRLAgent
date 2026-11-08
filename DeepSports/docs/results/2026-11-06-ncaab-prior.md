# DeepSports college (NCAAB) v1 with a cross-season prior: locked-holdout result

**Question.** College v1 restarts every season (Elo carry-over 0, ridge ratings from scratch), so it is
gated to games where both teams have >= 5 games. Does a prior from last season make early-season
predictions trustworthy, and can the gate come down?

**Answer.** The prior is a large, real improvement, and by the declared rule it **ships**. On the locked
holdout (2025-26, Nov 1 to Jan 31, 3,417 D1-vs-D1 games with full closing lines, scored once), the prior model
beats today's no-prior model on log loss (−0.022, 95% CI −0.037 to −0.009) and margin MAE (−0.49 points,
CI −0.77 to −0.27). It is not worse at 10+ games (in fact slightly better there: margin −0.14, CI −0.24 to
−0.03). The gain is concentrated where the gate sits: at 1–2 games log loss improves by 0.10 and margin MAE by 1.9 points.
**The declared gate rule does not lower the gate:** the 3–4 game bucket's ECE is 0.056, just over the
0.05 bar, so the mechanical proposal stays at **5 games**. Supplementary context, outside the rule: at
~300 games per bucket, a perfectly calibrated model has a median ECE of about 0.050, and the closing line
itself scores 0.057 in that bucket. The bar can't separate good from bad calibration at this sample size.
The prior model is still behind the closing line on every target. Flat bets lose. No betting edge.

## Protocol (docs/DECISIONS.md 2026-11-06, written before any fitting)
- **Prior model** = college v1's frozen linear models and feature sets (`models/ncaab_v1/config.json`)
  fed by:
  - **Elo carry-over:** at a team's first game of a new season, r = c·r + (1 − c)·start (1500; 1200 for the
    pooled non-D1 team).
  - **Ridge (Massey) prior** (`PriorRidgeRatings`): each team's offense and defense are shrunk toward ρ × last
    season's final rating with weight λp games (v1 shrinks toward 0 with weight 1). The prior's share is
    λp / (λp + games played), so it fades during the season. Teams with no rating last season use v1's
    shrinkage toward 0. League mean and home edge start at last season's values (negligible weight).
  - **Training filter** per target: v1's rt_n ≥ 5, or `prior_rows` (rt_n ≥ 5 in the first season, which
    has no prior, plus every row of a season that has one).
  - Conference regression was skipped (`team.groups` isn't stored).
- **No prior (today):** exactly the live path: Elo K 60 / home 60 / carry 0, per-season ridge λ = 1, trained
  on every earlier D1 row of every season with rt_n ≥ 5.
- **Tuning:** 2024-25 D1-vs-D1 games Nov 1 → Jan 31 (3,529 games; 3,414 with full lines), weekly walk-forward,
  prior from 2023-24. Rows at or after 2025-02-01 were dropped before anything was fit.
- **Locked holdout:** 2025-26 D1-vs-D1 games Nov 1 → Jan 31 (3,678 games; 3,417 with full lines, 87 game days),
  prior from 2024-25, weekly walk-forward with frozen settings (each week trains on every earlier D1 row,
  2023-24 onward). Rows at or after 2026-02-01 (v1's holdout, 2026-27) were dropped before anything.
  Config `models/ncaab_prior/config.json` (sha256 `58757403…021455eb`); the marker
  `models/ncaab_prior/config.holdout-scored` blocks a second run.
- **Contamination, stated plainly:** Dec–Jan 2025-26 was v1's validation window for Elo K, home edge, ridge λ
  and the feature-set / min-games choices. **Both arms share those settings**, so the absolute numbers for both
  are a bit optimistic, but the paired prior-vs-no-prior comparison is clean. The window was also the edge
  hunt's college dev window (strategies, not priors). The holdout is clean for the prior question only.
- **Ship rule:** ship if prior − no prior has CIs entirely below 0 on log loss **and** margin MAE over the
  holdout, and in the 10+ bucket neither CI is entirely above 0. **Gate:** a bucket qualifies if the prior
  model's ECE ≤ 0.05 and its log loss and margin MAE point estimates beat the carry-over Elo; the proposed gate is
  the lowest bucket floor from which every bucket qualifies.
- **Buckets** by rt_n, the lower of the two teams' completed games this season (any opponent, non-D1
  included): 0, 1–2, 3–4, 5–9, 10+.

## Tuning (2024-25, Nov–Jan)
- **Elo:** K ∈ {30, 40, 60} × carry ∈ {0, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9}, by raw Elo log loss. Round 1's best
  (K 60) sat on the grid edge, so round 2 added K 80 and 100 (tuning data only). The winner stayed **K 60,
  carry 0.75** (log loss 0.5367; no carry-over at K 60: 0.5627; K 80 / 0.6: 0.5375), now interior.
- **Ridge prior:** ρ ∈ {0.4, 0.55, 0.7, 0.85, 1.0} × λp ∈ {2, 4, 8, 16, 32}, by raw margin MAE: **ρ 1.0, λp 8**
  (9.666; ρ 0.85 / λp 8: 9.746; no prior: 10.74). ρ = 1.0 is the top of the grid, but also a natural bound:
  it means "start from last season's rating" with no extra pull toward average. λp still sets how fast it fades
  (after 8 games, half prior and half this season). On totals a smaller ρ was better (ρ 0.55 / λp 8: 13.156 vs 13.344), but the rule picks by margin.
- **Training filter:** `prior_rows` won all three targets by tiny margins (log loss 0.5372 vs 0.5374, margin
  9.357 vs 9.377, total 13.1146 vs 13.1148).

Tuning-set result with the frozen choices (3,414 games, 87 days):

| model | Brier | log loss | ECE | margin MAE | total MAE |
|---|---|---|---|---|---|
| Prior model | 0.1814 | 0.5372 | 0.018 | 9.36 | 13.11 |
| No prior (today) | 0.1895 | 0.5642 | 0.025 | 9.98 | 13.27 |
| Elo, carry-over | 0.1871 | 0.5524 | 0.048 | 9.65 | - |
| Closing line | 0.1725 | 0.5119 | 0.015 | 8.90 | 12.72 |

Prior − no prior on tuning: log loss −0.027 (CI −0.044 to −0.015), margin −0.63 (−1.01 to −0.36).

## Holdout results (scored once)
3,417 games with a closing moneyline, spread and total. Every model is scored on the same games.

| model | Brier | log loss | ECE | margin MAE | total MAE |
|---|---|---|---|---|---|
| **Prior model** | 0.1798 | 0.5325 | 0.024 | 9.39 | 13.89 |
| No prior (today) | 0.1866 | 0.5546 | 0.026 | 9.88 | 14.02 |
| Elo, carry-over (K 60, c 0.75) | 0.1858 | 0.5484 | 0.036 | 9.76 | - |
| Elo, no prior (K 60) | 0.1946 | 0.5726 | 0.060 | 10.13 | - |
| Ratings, prior (raw) | - | - | - | 9.67 | 14.13 |
| Ratings, no prior (raw) | - | - | - | 10.63 | 14.40 |
| Closing line | 0.1696 | 0.5067 | 0.014 | 8.94 | 13.46 |

### Paired differences (95% day-clustered bootstrap CI, 87 days, 2,000 resamples; negative = prior model better)
| comparison | Brier | log loss | margin MAE | total MAE |
|---|---|---|---|---|
| Prior − No prior | −0.0069 (−0.0110 to −0.0030) | −0.0221 (−0.0372 to −0.0094) | −0.491 (−0.773 to −0.265) | −0.133 (−0.231 to −0.042) |
| Prior − Elo carry-over | −0.0060 (−0.0082 to −0.0040) | −0.0159 (−0.0213 to −0.0109) | −0.373 (−0.468 to −0.278) | - |
| Prior − Closing line | +0.0102 (+0.0073 to +0.0134) | +0.0258 (+0.0187 to +0.0339) | +0.452 (+0.303 to +0.618) | +0.429 (+0.284 to +0.576) |

### By games played (the lower of the two teams' completed games this season)
| bucket | n | prior LL | no-prior LL | Elo-c LL | close LL | prior ECE | prior margin | no-prior margin | Elo-c margin | close margin | prior total | no-prior total | close total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 125 | 0.3551 | 0.4924 | 0.4115 | 0.2933 | 0.058 | 11.52 | 14.58 | 12.63 | 9.16 | 15.90 | 16.26 | 14.61 |
| 1-2 | 294 | 0.4781 | 0.5788 | 0.5043 | 0.4236 | 0.037 | 10.22 | 12.11 | 10.56 | 9.30 | 14.85 | 15.71 | 13.72 |
| 3-4 | 316 | 0.4675 | 0.5119 | 0.5006 | 0.4222 | 0.056 | 8.98 | 9.90 | 9.25 | 8.48 | 14.29 | 14.51 | 13.71 |
| 5-9 | 719 | 0.5355 | 0.5381 | 0.5510 | 0.5054 | 0.037 | 9.89 | 10.14 | 10.25 | 9.40 | 13.46 | 13.53 | 12.85 |
| 10+ | 1963 | 0.5612 | 0.5678 | 0.5704 | 0.5468 | 0.029 | 9.02 | 9.15 | 9.37 | 8.78 | 13.71 | 13.73 | 13.53 |

Early buckets have low log loss for every model because November is full of mismatches (big
favorites at home against weak non-conference teams). Compare models within a row, not rows with each other.

Per-bucket paired differences (95% day-clustered CI):

| bucket | comparison | log loss | Brier | margin MAE | total MAE |
|---|---|---|---|---|---|
| 0 | Prior − No prior | −0.137 (−0.231 to +0.018) | −0.027 (−0.064 to +0.007) | −3.06 (−3.70 to −0.74) | −0.36 (−0.63 to +1.33) |
| 0 | Prior − Elo carry-over | −0.057 (−0.097 to −0.016) | −0.020 (−0.038 to −0.005) | −1.11 (−2.58 to −0.80) | - |
| 0 | Prior − Closing line | +0.062 (+0.004 to +0.213) | +0.022 (−0.001 to +0.085) | +2.36 (+1.92 to +4.01) | +1.29 (+0.91 to +3.36) |
| 1-2 | Prior − No prior | −0.101 (−0.149 to −0.033) | −0.031 (−0.047 to −0.010) | −1.89 (−2.71 to −0.93) | −0.85 (−1.20 to −0.16) |
| 1-2 | Prior − Elo carry-over | −0.026 (−0.042 to −0.009) | −0.010 (−0.017 to −0.004) | −0.34 (−0.79 to +0.21) | - |
| 1-2 | Prior − Closing line | +0.055 (+0.024 to +0.088) | +0.021 (+0.009 to +0.032) | +0.92 (+0.61 to +1.25) | +1.14 (+0.49 to +1.69) |
| 3-4 | Prior − No prior | −0.044 (−0.086 to +0.017) | −0.017 (−0.032 to +0.005) | −0.92 (−1.24 to −0.57) | −0.22 (−0.50 to +0.16) |
| 3-4 | Prior − Elo carry-over | −0.033 (−0.052 to −0.016) | −0.012 (−0.020 to −0.004) | −0.28 (−0.61 to +0.06) | - |
| 3-4 | Prior − Closing line | +0.045 (+0.025 to +0.067) | +0.016 (+0.006 to +0.026) | +0.49 (+0.02 to +0.92) | +0.58 (+0.24 to +0.93) |
| 5-9 | Prior − No prior | −0.003 (−0.018 to +0.015) | −0.001 (−0.008 to +0.007) | −0.25 (−0.58 to +0.11) | −0.07 (−0.29 to +0.16) |
| 5-9 | Prior − Elo carry-over | −0.016 (−0.025 to −0.003) | −0.006 (−0.010 to −0.000) | −0.36 (−0.52 to −0.14) | - |
| 5-9 | Prior − Closing line | +0.030 (+0.017 to +0.044) | +0.013 (+0.008 to +0.019) | +0.49 (+0.25 to +0.78) | +0.61 (+0.34 to +0.94) |
| 10+ | Prior − No prior | −0.007 (−0.013 to +0.001) | −0.003 (−0.005 to +0.000) | −0.14 (−0.24 to −0.03) | −0.02 (−0.10 to +0.07) |
| 10+ | Prior − Elo carry-over | −0.009 (−0.015 to −0.003) | −0.004 (−0.006 to −0.001) | −0.35 (−0.45 to −0.25) | - |
| 10+ | Prior − Closing line | +0.015 (+0.007 to +0.022) | +0.006 (+0.003 to +0.009) | +0.24 (+0.11 to +0.39) | +0.18 (+0.01 to +0.33) |

Bucket 0 spans only 7 game days (the first days of the season), so its day-clustered CIs rest on 7
clusters and are unreliable. Some point estimates sit near a CI edge for that reason.

### Ship rule, applied mechanically
- Prior − no prior: log loss CI −0.037 to −0.009 and margin CI −0.77 to −0.27, both below 0. 10+ bucket: log
  loss CI −0.013 to +0.001, margin CI −0.24 to −0.03, neither above 0: **ship: yes.**
- Gate: buckets qualifying (ECE ≤ 0.05 and beats the carry-over Elo on log loss and margin): 0 **no** (ECE 0.058),
  1–2 yes (0.037), 3–4 **no** (ECE 0.056), 5–9 yes, 10+ yes. Lowest floor from which every bucket qualifies:
  **5, the current gate.** The rule does not support lowering it.

### Supplementary: how much can ECE say at these sample sizes? (outside the declared rule)
ECE per bucket for each model, and the ECE a perfectly calibrated model would get at that sample size
(outcomes simulated from the prior model's own probabilities, 1,000 draws):

| bucket | n | prior | no prior | Elo carry-over | closing line | perfectly calibrated: median / 95th pct |
|---|---|---|---|---|---|---|
| 0 | 125 | 0.058 | 0.094 | 0.137 | 0.067 | 0.052 / 0.082 |
| 1-2 | 294 | 0.037 | 0.080 | 0.081 | 0.048 | 0.051 / 0.075 |
| 3-4 | 316 | 0.056 | 0.078 | 0.088 | 0.057 | 0.050 / 0.075 |
| 5-9 | 719 | 0.037 | 0.032 | 0.051 | 0.030 | 0.036 / 0.052 |
| 10+ | 1963 | 0.029 | 0.029 | 0.038 | 0.019 | 0.022 / 0.033 |

Below 5 games, the prior model's ECE is in the range of pure sampling noise, and it is lower than no-prior's and
Elo's in every early bucket. Pooled over 1–4 games (610 games) its ECE is 0.037. The 3–4 miss comes
from a few small middle bins (e.g. 15 games predicted 0.36 that won 0.67 of the time). The 0.05 bar was
set by analogy with v1's ~2,000-game holdout, and it is too strict to judge a ~300-game bucket. This is an
observation, not a re-decision: the declared rule says the gate stays at 5.

### Flat bets at −110 vs the close (backtest, not a betting record)
| model | market | edge ≥ t | bets | hit rate | day-clustered 95% | ROI |
|---|---|---|---|---|---|---|
| Prior model | spread | 0 | 3,417 | 50.7% | 49.1–52.3% | −3.1% |
| Prior model | spread | 3 | 1,227 | 51.0% | 48.2–53.8% | −2.6% |
| Prior model | total | 0 | 3,417 | 50.5% | 48.9–52.2% | −3.5% |
| Prior model | total | 4 | 1,103 | 51.1% | 48.3–54.2% | −2.4% |
| No prior (today) | spread | 0 | 3,417 | 51.2% | 49.7–52.7% | −2.2% |
| No prior (today) | spread | 3 | 1,624 | 51.4% | 48.6–53.9% | −1.8% |
| No prior (today) | total | 0 | 3,417 | 49.6% | 48.1–51.2% | −5.4% |
| No prior (today) | total | 4 | 1,238 | 50.4% | 47.5–53.5% | −3.8% |

Break-even is 52.4%; every line is below it. A better model isn't a betting edge: the prior moves the
model's numbers toward the close (fewer edge ≥ 3 bets), not past it.

## Caveats
- **One holdout season, one tuning season.** The holdout is the first three months of 2025-26, and early-season
  results swing with roster turnover (the transfer portal), which varies by year. ρ = 1.0 (no regression)
  won on 2024-25 and held on 2025-26, but a heavy-turnover year could favor a smaller ρ. The prior
  doesn't use returning-minutes or recruiting data.
- **Shared v1 settings.** Both arms use K, home edge, λ and feature choices validated on Dec–Jan 2025-26
  (see Protocol). The paired difference is the clean quantity.
- **Grid edges.** K was widened once (round 2, tuning data only). ρ = 1.0 is the top of its grid by design.
  On totals alone a smaller ρ was better in tuning. A separate ρ for totals wasn't declared, so it wasn't tried.
- **2023-24 player boxes** (~360 team-games with a dropped player line) feed only training rows' player
  features (margin/total), identically in both arms. They are never scored and never summed into team stats.
- **Market subset.** 261 of 3,678 holdout D1 games lack one closing number, mostly the moneyline only (212 games;
  spread and total present). They are excluded from every comparison. All 3,678 were predicted.
- **The "Elo" for the gate** is the carry-over Elo tuned on the same 2024-25 data (the stronger of the two
  Elos). Against the no-prior Elo every bucket's comparison would be easier.
- **rt_n** counts games against non-D1 opponents too (as the live gate does).

## Recommendation (for the orchestrator; nothing live was changed)
1. **Adopt the prior for college predictions** (passes the ship rule). The live path (`ncaab.live_rows` /
   `predict_upcoming`) would build Elo with `carry_over = 0.75` (K 60, home 60) and the ridge features with
   `PriorRidgeRatings` from last season's final ratings (ρ 1.0, λp 8), and train with the `prior_rows` filter.
   It's a new model, so it should be a new version label (e.g. `ncaab-v1p`) with its own record, not
   a silent change to `ncaab-v1`. The building blocks are in `analysis/ncaab_prior.py` (`season_ridge`,
   `PriorRidgeRatings`, `train_ok`); scheduled games need `include_scheduled` in the season-games input, as
   `live_rows` does today.
2. **Gate: keep 5** for the main version, per the declared rule.
3. **Owner decision:** point the opt-in `ncaab-v1-early` predictions (1–4 games) at the prior model.
   This needs no gate change and is a strict improvement on what that switch shows today: log loss −0.10 / −0.04 and
   margin −1.9 / −0.9 points at 1–2 / 3–4 games, ECE 0.037 / 0.056 vs 0.080 / 0.078.
4. **Re-test the gate on 2026-27** with a rule declared in advance that fits the sample size: e.g., pooled rt_n 1–4 (~600
   games), ECE ≤ 0.05 and log loss and margin CIs vs the carry-over Elo below 0. Score it after Jan 31, 2027.

## Reproduce
```bash
W=/Volumes/ExFATStorag/DeepSports/work
cp data/deepsports.duckdb $W/deepsports-ncaab-prior.duckdb   # outside 07:55-08:40 / 13:55-14:40
uv run python -m deepsports.analysis.ncaab_prior tune --db $W/deepsports-ncaab-prior.duckdb \
  --config models/ncaab_prior/config.json   # ~60 s
# the holdout step refuses to run again (marker models/ncaab_prior/config.holdout-scored); re-render with:
uv run python -m deepsports.analysis.ncaab_prior report --config models/ncaab_prior/config.json \
  --preds $W/ncaab_prior_holdout_preds.json
```
Copy taken 2026-11-06 00:33 PT (data through 2026-11-04). Code: `src/deepsports/analysis/ncaab_prior.py`, plus
an optional ratings factory in `ncaab.ridge_features` and `RidgeRatings.empty()` (v1 behavior unchanged);
tests `tests/test_ncaab_prior.py`. Work files in `/Volumes/ExFATStorag/DeepSports/work/`: tuning logs (both
rounds), round-1 config, holdout predictions and the rendered holdout report.
