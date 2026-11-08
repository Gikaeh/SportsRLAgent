# Are the displayed win probabilities calibrated? (NBA v1.1, college ncaab-v1)

**Question.** The app shows a home-win probability from NBA `v1.1` and college `ncaab-v1`. The
$100 simulation found that on the model's moneyline picks it said ~49% where the closing line said ~41%
and the picked side won ~40%. Are the displayed probabilities miscalibrated, and does a simple,
pre-declared fix help on a locked holdout? Or is the pick gap the winner's curse of selecting
disagreements with the market, which no recalibration can remove?

_Results below the "Protocol" section were added after it was written. The protocol was written before
any calibrator was fit and before the holdout was scored._

**Answer.** **The displayed probabilities are calibrated, about as well as these samples can show.**
The pick gap is the winner's curse, not miscalibration. On the locked holdouts (NBA 2025-26, 1,322 games;
college Feb–Apr 2026, 1,955 games), the current models' ECE is 0.031 (NBA) and 0.034 (college). A perfectly
calibrated model would score a median of 0.028 / 0.023 at those sample sizes (95th percentile 0.042 / 0.034).
The calibration slope is 1.06 ± 0.08 (NBA, not overconfident) and 0.88 ± 0.05 (college; slightly
overconfident this spring, but earlier seasons range from 0.92 to 1.09 with no consistent pattern).
On the moneyline picks, the model said 48.6% where the close said 41.3% and the picked side won 41.0% (NBA
holdout). A simulated model that is **perfectly calibrated but knows nothing beyond the closing line** shows
the same picture: 49.0% / 41.9% / 42.1%. An encompassing regression gives the model's probability a weight of
0.02 ± 0.16 next to the close (college −0.10 ± 0.16). On disagreements the line already knows what the model
knows, so the outcome follows the line. Recalibrating p cannot fix that.

**By the declared rule, both pre-declared fixes ship, but only through the ECE branch and by margins
inside the noise.** NBA: stronger L2 (C 0.03) changes log loss by −0.0014 (CI −0.0028 to +0.0001) and ECE from
0.0315 to 0.0311. College: L2 (C 0.1) changes log loss by −0.0001 (CI −0.0002 to +0.0000) and ECE from 0.0338 to 0.0320. They are built as
`v1.1c` and `ncaab-v1c` and **not wired in**. Platt and temperature scaling did not help in the NBA
(temperature log loss +0.0006, CI +0.0002 to +0.0011). Their fitted corrections were essentially identity (b ≈ 0.98–1.06).

**In plain words (for a sports newcomer): what "70%" on the app means.** Take every game where the app
said the home team had about a 70% chance (70–80% bin). In 2025-26 NBA games the model averaged 74.8% there and
those teams won 72.5%. In college (Feb–Apr 2026) it averaged 75.0% and they won 72.7%. So "70%" means "wins about 7
times in 10", give or take a few points. The 60–70% bin missed by more, in opposite directions: NBA said 64.7%
and won 70.2%, college said 65.2% and won 59.8%. That is the size of one season's luck, and it is about as
precise as one season can measure. Two caveats. The
betting line's percentage is *more* accurate than the app's (log loss 0.575 vs 0.600 NBA). And when the app is
more optimistic than the line about a team, believe the line: those teams win at the line's rate, not the app's.
The app's number is a fair estimate to follow along with, not a reason to bet.

## Protocol (declared 2026-11-06, before tuning or holdout scoring)
- **Out-of-sample predictions** (`src/deepsports/analysis/calibration.py`, step `oos`):
  - **NBA:** v1.1's monthly walk-forward (`backtest.iter_folds`, the v1.1 backtest's folds: every training
    game tipped off before the test month). The logistic win model is refit for each C in the L2 grid; C = 1
    is exactly v1.1 (reproduces the v1.1 backtest's Brier/log loss for 2024 and 2025 to 4 decimals).
  - **College:** ncaab-v1 as it runs live (`ncaab.live_rows`: Elo restarts each season, per-season ridge
    ratings, training on every earlier completed D1 row of every season with rt_n >= 5), weekly walk-forward
    from 2023-12-01. Only displayed games are kept: both teams D1, rt_n >= 5.
- **Candidates (declared, no others):**
  1. **Platt:** p' = sigmoid(a + b · logit p).
  2. **Temperature:** p' = sigmoid(b · logit p) (a = 0).
  3. **Stronger L2** on the logistic win model: C ∈ {0.3, 0.1, 0.03, 0.01} (current C = 1); the best C on
     tuning log loss is the L2 candidate.
  Platt and temperature are refit at the start of every calendar-month block on **all OOS predictions of
  games that tipped off before the block** (expanding window; < 300 earlier games = left uncalibrated). In
  the holdout this includes earlier holdout months, as production would.
- **Tuning windows (pre-holdout only):** NBA season 2025 (2024-25; 2024's OOS predictions only feed the
  calibrator). College 2024-11-01 → 2026-01-31 (all of 2024-25 plus Nov–Jan 2025-26; 2023-24 Dec–Apr OOS feeds
  the calibrator). The `tune` step drops every holdout row before fitting anything.
- **Choice rule:** the candidate (Platt, temperature, best-C L2) with the lowest tuning log loss; ties
  (to 1e-6) go to temperature, then L2, then Platt. It is frozen in `models/calibration/<league>.json`
  (with the OOS file's sha256) before the holdout.
- **Locked holdout (same as the earlier studies):** NBA all of 2025-26 (season 2026); college
  2026-02-01 → 2026-04-30 (ncaab-v1's holdout). Scored once (marker `models/calibration/<league>.holdout-scored`).
- **Ship rule (per league):** ship the chosen candidate if the holdout log loss difference (candidate −
  current) has a 95% day-clustered paired bootstrap CI (2,000 resamples) entirely below 0, **or** its ECE is
  lower than the current model's and the log loss CI's upper end is ≤ +0.001. Otherwise: **calibrated enough,
  no change.** ECE = 10 equal-width bins. The other candidates are reported but do not decide anything.
- **Diagnostics (tuning and holdout):** reliability bins, ECE, log loss, Brier, calibration slope/intercept
  (logistic regression of the outcome on logit p; perfect = slope 1, intercept 0), the same folded to the
  favorite by |p − 0.5| bucket (0–0.1, 0.1–0.2, 0.2–0.3, 0.3–0.5), and the **selection effect**: the moneyline
  picks table (side where model p beats the vig-free close by ≥ t), an encompassing regression
  y ~ logit(p_model) + logit(p_close), and a simulation of a perfectly calibrated model that knows nothing
  beyond the close (noise matched to the real model's disagreement with the close).
- **Contamination, stated plainly:** NBA 2025-26 was the ensemble-v2 holdout and v1.1's backtest season
  (its raw numbers are published); college Feb–Apr 2026 was ncaab-v1's holdout. Nothing about calibration
  was tuned on either, so the holdout is clean for this question.
- **Frozen choices (recorded before the holdout was scored):** NBA **L2 C = 0.03** (tuning log loss 0.60730
  vs current 0.60871; Platt 0.60843, temperature 0.60887). College **L2 C = 0.1** (0.54698 vs current 0.54700,
  a near-tie; temperature 0.54746, Platt 0.54765).

## Tuning results (pre-holdout only)
| league | window | games | current LL | Platt | temperature | L2 grid (C 0.3 / 0.1 / 0.03 / 0.01) | chosen |
|---|---|---|---|---|---|---|---|
| NBA | 2024-25 | 1,321 | 0.60871 | 0.60843 | 0.60887 | 0.60830 / 0.60773 / **0.60730** / 0.60788 | L2 C 0.03 |
| College | 2024-11 → 2026-01 | 7,665 | 0.54700 | 0.54765 | 0.54746 | 0.54698 / **0.54698** / 0.54711 / 0.54778 | L2 C 0.1 |

Tuning-window diagnostics for the current models: NBA ECE 0.022, slope 1.029 (SE 0.079), intercept −0.088
(SE 0.063). College ECE 0.013, slope 1.024 (SE 0.029), intercept −0.028 (SE 0.029). The last walk-forward
calibrator fits before the holdout were Platt a −0.11 / b 1.04 and temperature b 1.00 (NBA), and Platt a −0.02 /
b 0.99 and temperature b 0.98 (college). The data asked for almost no correction. Moneyline picks in tuning
(t = 0): NBA model 49.3% / close 42.0% / actual 42.3%; college 54.6% / 47.8% / 47.5%. Same pattern, before the
holdout was opened. Full tuning tables: `/Volumes/ExFATStorag/DeepSports/reports/calibration/{nba,ncaab}_tune.md`.

## Holdout results (scored once)
**Ship rule, applied mechanically:**
- **NBA (L2 C 0.03):** log loss CI upper end +0.00005, not below 0, so the log-loss branch fails. ECE 0.0311 < 0.0315 with
  CI upper end ≤ +0.001, so the ECE branch passes: **ship (by ECE).** The ECE change is −0.0003 with a CI of −0.014 to +0.011.
- **College (L2 C 0.1):** log loss −0.00012, CI upper end +0.00002, so the log-loss branch fails. ECE 0.0320 < 0.0338, so the
  ECE branch passes: **ship (by ECE).** The ECE change is −0.002 (CI −0.004 to +0.001).

**How much the "ship" means.** Not much. The ECE branch counts any ECE decrease, however small. Both
decreases sit well inside their bootstrap CIs and inside the spread a perfectly calibrated model shows at this
sample size. The NBA L2 log-loss gain (−0.0014) matched tuning (−0.0014) and nearly cleared 0, so it is probably
a small real improvement in *discrimination* from shrinking v1.1's redundant player coefficients (see the v1.1
report: `top6_pm_diff` and `avail_top6_pm_diff` correlate 0.99). It is not a calibration fix: its slope moves
*away* from 1 (1.06 → 1.11). The college change is a rounding error.

**Is college spring overconfidence a pattern?** (pre-holdout seasons, current model, outside the rule)
| season | Nov–Jan slope (SE) | Feb–Apr slope (SE) |
|---|---|---|
| 2023-24 | 0.917 (0.050) | 0.953 (0.054) |
| 2024-25 | 1.052 (0.050) | 1.087 (0.058) |
| 2025-26 | 0.977 (0.045) | **0.883 (0.054)** (holdout) |

No: the slope moves ±0.1 from year to year in both halves of the season. A fixed seasonal correction would
have pointed the wrong way in 2024-25.

### Null reference: ECE of a perfectly calibrated model at the holdout sizes (outcomes simulated from the current p, 1,000 draws)
| league | games | current ECE | perfectly calibrated: median / 95th pct |
|---|---|---|---|
| NBA | 1,322 | 0.031 | 0.028 / 0.042 |
| College | 1,955 | 0.034 | 0.023 / 0.034 |


## Selection effect, in one paragraph
The $100 simulation's "~49% vs ~41% vs ~40%" is what selecting disagreements does to *any* noisy forecaster.
The model's logit differs from the close's by about 0.47 (NBA) / 0.34 (college) in standard deviation. When you
keep only the games where the model is higher than the line, you keep the games where its noise happened to
point up. The picked side then wins at the line's rate. The simulation reproduces this exactly with a model that is
perfectly calibrated by construction (NBA: 49.0% / 41.9% / 42.1%; the real model: 48.6% / 41.3% / 41.0%).
Recalibration only rescales the model's own numbers. After Platt, temperature or L2 the gap is unchanged
(e.g. L2 47.8% / 40.4% / 40.0%). For Kelly sizing this means: size by the market's probability, or don't bet
the moneyline on this model at all.

## Caveats
- **One holdout season per league.** The NBA holdout has 1,322 games, so ECE differences of ±0.01 are noise.
- **The ECE branch of the ship rule is weak.** It passes on any ECE decrease with a log loss that is not worse.
  A future rule should require an ECE CI below 0, or a minimum size.
- **College numbers differ from the ncaab-v1 study** (ECE 0.034 here vs 0.024 there). This study trains like
  the live path (every earlier season, rt_n >= 5); the original study trained on 2025-26 only. Both run on the same holdout games.
- **College OOS starts 2023-12-01**, so the first calibrator fits use 2023-24's thin early-season models.
- **v1.1c/ncaab-v1c differ from v1.1/ncaab-v1 only in the win model's C.** Margins and totals are identical.

## Recommendation (for the orchestrator; nothing live was changed)
1. **Display: no change needed.** The current probabilities are calibrated to within sampling noise. The
   rule's "ship" rests on ECE changes far smaller than their noise.
2. If you follow the rule anyway, `v1.1c` is the one worth it: it tied or beat v1.1 on log loss in both tuning and
   holdout (−0.0014 each). It should run side by side as a hidden graded version (like `ncaab-v1p`) before it
   replaces `v1.1` on display. `ncaab-v1c` is equivalent to `ncaab-v1`; skip it.
3. **Kelly / moneyline:** use the vig-free closing probability for sizing. The model's p adds nothing next to it
   (encompassing weight about 0).
4. Re-run the study after 2026-27 (NBA 2026-27, college Feb–Apr 2027) with a stricter ECE rule declared in advance.

## Reproduce
```bash
R=/Volumes/ExFATStorag/DeepSports/reports/calibration
DB=/Volumes/ExFATStorag/DeepSports/copies/analyst-2026-11-06.duckdb   # copy taken 2026-11-06
for L in nba ncaab; do
  uv run python -m deepsports.analysis.calibration oos --league $L --db $DB --out $R/${L}_oos.json
  uv run python -m deepsports.analysis.calibration tune --league $L --preds $R/${L}_oos.json \
    --config models/calibration/$L.json
done
# holdout refuses to run twice (markers models/calibration/{nba,ncaab}.holdout-scored); re-render with:
uv run python -m deepsports.analysis.calibration report --league nba --preds $R/nba_oos.json \
  --config models/calibration/nba.json --out $R/nba_holdout.json
```
NBA OOS ~5 s, college ~3 min. Frozen configs: `models/calibration/nba.json` (sha256 `737d026b…ec0b9129`),
`models/calibration/ncaab.json` (sha256 `94d405f5…f54b6`). Code: `src/deepsports/analysis/calibration.py`;
versions in `model.py` (`v1.1c`, `VERSION_WIN_C`) and `ncaab.py` (`CALIBRATED_VERSION`,
`predict_upcoming_calibrated`); tests `tests/test_calibration.py`. `make_model("v1.1c")` reproduces the study's C 0.03
predictions exactly (max difference 0.0 on two folds checked).

---
_Generated holdout tables follow._

### NBA holdout (2025-26)
1322 games (1316 with a closing moneyline).

| model | Brier | log loss | ECE | slope b (SE) | intercept a (SE) |
|---|---|---|---|---|---|
| current | 0.2068 | 0.6003 | 0.031 | 1.059 (0.079) | -0.022 (0.062) |
| platt | 0.2074 | 0.6016 | 0.035 | 1.033 (0.077) | +0.071 (0.061) |
| temperature | 0.2070 | 0.6009 | 0.033 | 1.073 (0.080) | -0.021 (0.062) |
| l2_c0.03 | 0.2062 | 0.5989 | 0.031 | 1.110 (0.082) | -0.033 (0.063) |
| closing line (n 1316) | 0.1968 | 0.5753 | 0.027 | 1.074 (0.073) | -0.002 (0.064) |

Same games as the closing line:

| model | Brier | log loss | ECE |
|---|---|---|---|
| current | 0.2062 | 0.5990 | 0.034 |
| platt | 0.2068 | 0.6000 | 0.037 |
| temperature | 0.2064 | 0.5996 | 0.036 |
| l2_c0.03 | 0.2056 | 0.5976 | 0.033 |
| closing line | 0.1968 | 0.5753 | 0.027 |

Paired differences vs current (95% day-clustered bootstrap, 212 days; negative = better):

| candidate | log loss | Brier | ECE (info) |
|---|---|---|---|
| platt | +0.0013 (-0.0007 to +0.0033) | +0.0006 (-0.0002 to +0.0015) | +0.004 (-0.013 to +0.018) |
| temperature | +0.0006 (+0.0002 to +0.0011) | +0.0002 (+0.0001 to +0.0004) | +0.002 (-0.006 to +0.006) |
| l2_c0.03 (declared choice) | -0.0014 (-0.0028 to +0.0001) | -0.0006 (-0.0012 to +0.0000) | -0.000 (-0.014 to +0.011) |

Reliability (current model; equal-width bins of P(home win)):

| bin | games | model avg | home won |
|---|---|---|---|
| 0.0-0.1 | 3 | 7.7% | 0.0% |
| 0.1-0.2 | 44 | 16.6% | 13.6% |
| 0.2-0.3 | 100 | 25.6% | 21.0% |
| 0.3-0.4 | 160 | 35.6% | 31.2% |
| 0.4-0.5 | 198 | 45.3% | 45.5% |
| 0.5-0.6 | 234 | 55.0% | 57.7% |
| 0.6-0.7 | 235 | 64.7% | 70.2% |
| 0.7-0.8 | 200 | 74.8% | 72.5% |
| 0.8-0.9 | 124 | 84.3% | 80.6% |
| 0.9-1.0 | 24 | 91.6% | 91.7% |

By confidence: games bucketed by the current model's |p - 0.5|, folded to its favorite; each model's mean probability for that side vs how often it won:

| |p - 0.5| | games | current pred | platt pred | temperature pred | l2_c0.03 pred | won | current LL | platt LL | temperature LL | l2_c0.03 LL |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.0-0.1 | 432 | 54.9% | 54.8% | 54.8% | 54.7% | 56.2% | 0.6877 | 0.6901 | 0.6874 | 0.6843 |
| 0.1-0.2 | 395 | 64.6% | 64.5% | 64.4% | 64.1% | 69.6% | 0.6197 | 0.6222 | 0.6208 | 0.6212 |
| 0.2-0.3 | 300 | 74.7% | 74.5% | 74.3% | 74.0% | 74.7% | 0.5595 | 0.5593 | 0.5610 | 0.5569 |
| 0.3-0.5 | 195 | 85.1% | 84.9% | 84.7% | 84.5% | 83.6% | 0.4302 | 0.4285 | 0.4305 | 0.4289 |

Moneyline picks (side where the model's p beats the vig-free close by >= t):

| model | t | picks | model p | market p | actual |
|---|---|---|---|---|---|
| current | 0.00 | 1316 | 48.6% | 41.3% | 41.0% |
| current | 0.05 | 733 | 48.7% | 37.4% | 37.2% |
| current | 0.12 | 254 | 52.4% | 34.7% | 34.6% |
| platt | 0.00 | 1316 | 48.6% | 41.1% | 39.7% |
| platt | 0.05 | 725 | 48.8% | 37.2% | 37.5% |
| platt | 0.12 | 255 | 52.1% | 34.4% | 33.3% |
| temperature | 0.00 | 1316 | 48.1% | 40.7% | 40.3% |
| temperature | 0.05 | 732 | 48.0% | 36.6% | 36.2% |
| temperature | 0.12 | 261 | 52.0% | 34.5% | 33.7% |
| l2_c0.03 | 0.00 | 1316 | 47.8% | 40.4% | 40.0% |
| l2_c0.03 | 0.05 | 731 | 47.2% | 35.9% | 36.0% |
| l2_c0.03 | 0.12 | 251 | 51.5% | 33.9% | 33.9% |

Encompassing regression y ~ a + b_model logit(p_model) + b_market logit(p_close):

| model | n | b_model (SE) | b_market (SE) |
|---|---|---|---|
| current | 1316 | 0.016 (0.158) | 1.062 (0.141) |
| platt | 1316 | -0.002 (0.154) | 1.076 (0.141) |
| temperature | 1316 | 0.005 (0.160) | 1.070 (0.141) |
| l2_c0.03 | 1316 | 0.072 (0.163) | 1.021 (0.141) |

Winner's-curse simulation (perfectly calibrated model with no information beyond the close, noise sd 0.467 in logit units, 200 draws): picks at t = 0 show model p 49.0%, market p 41.9%, actual 42.1%; its ECE 0.024.


### College holdout (Feb–Apr 2026)
1955 games (1949 with a closing moneyline).

| model | Brier | log loss | ECE | slope b (SE) | intercept a (SE) |
|---|---|---|---|---|---|
| current | 0.2009 | 0.5832 | 0.034 | 0.884 (0.054) | +0.051 (0.054) |
| platt | 0.2009 | 0.5832 | 0.030 | 0.896 (0.055) | +0.069 (0.054) |
| temperature | 0.2007 | 0.5829 | 0.029 | 0.905 (0.055) | +0.052 (0.054) |
| l2_c0.1 | 0.2008 | 0.5831 | 0.032 | 0.889 (0.054) | +0.049 (0.054) |
| closing line (n 1949) | 0.1963 | 0.5719 | 0.021 | 1.043 (0.062) | +0.021 (0.055) |

Same games as the closing line:

| model | Brier | log loss | ECE |
|---|---|---|---|
| current | 0.2012 | 0.5840 | 0.034 |
| platt | 0.2012 | 0.5840 | 0.030 |
| temperature | 0.2010 | 0.5836 | 0.030 |
| l2_c0.1 | 0.2011 | 0.5839 | 0.032 |
| closing line | 0.1963 | 0.5719 | 0.021 |

Paired differences vs current (95% day-clustered bootstrap, 60 days; negative = better):

| candidate | log loss | Brier | ECE (info) |
|---|---|---|---|
| platt | -0.0000 (-0.0006 to +0.0005) | -0.0000 (-0.0002 to +0.0002) | -0.004 (-0.009 to +0.004) |
| temperature | -0.0003 (-0.0007 to +0.0000) | -0.0002 (-0.0003 to -0.0000) | -0.004 (-0.008 to +0.002) |
| l2_c0.1 (declared choice) | -0.0001 (-0.0002 to +0.0000) | -0.0000 (-0.0001 to +0.0000) | -0.002 (-0.004 to +0.001) |

Reliability (current model; equal-width bins of P(home win)):

| bin | games | model avg | home won |
|---|---|---|---|
| 0.0-0.1 | 19 | 6.8% | 5.3% |
| 0.1-0.2 | 75 | 15.0% | 18.7% |
| 0.2-0.3 | 124 | 25.0% | 30.6% |
| 0.3-0.4 | 169 | 35.2% | 36.7% |
| 0.4-0.5 | 241 | 45.3% | 50.6% |
| 0.5-0.6 | 255 | 55.2% | 58.0% |
| 0.6-0.7 | 323 | 65.2% | 59.8% |
| 0.7-0.8 | 341 | 75.0% | 72.7% |
| 0.8-0.9 | 287 | 84.7% | 82.9% |
| 0.9-1.0 | 121 | 93.6% | 95.9% |

By confidence: games bucketed by the current model's |p - 0.5|, folded to its favorite; each model's mean probability for that side vs how often it won:

| |p - 0.5| | games | current pred | platt pred | temperature pred | l2_c0.1 pred | won | current LL | platt LL | temperature LL | l2_c0.1 LL |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.0-0.1 | 496 | 54.9% | 54.9% | 54.8% | 54.9% | 53.8% | 0.6914 | 0.6922 | 0.6913 | 0.6914 |
| 0.1-0.2 | 492 | 65.1% | 64.8% | 64.8% | 65.0% | 61.0% | 0.6707 | 0.6702 | 0.6701 | 0.6706 |
| 0.2-0.3 | 465 | 75.0% | 74.6% | 74.5% | 75.0% | 71.8% | 0.5963 | 0.5959 | 0.5956 | 0.5961 |
| 0.3-0.5 | 502 | 87.2% | 86.8% | 86.8% | 87.2% | 86.3% | 0.3784 | 0.3785 | 0.3784 | 0.3782 |

Moneyline picks (side where the model's p beats the vig-free close by >= t):

| model | t | picks | model p | market p | actual |
|---|---|---|---|---|---|
| current | 0.00 | 1949 | 58.2% | 53.1% | 52.9% |
| current | 0.05 | 796 | 61.7% | 52.6% | 52.6% |
| current | 0.12 | 140 | 62.5% | 47.3% | 47.9% |
| platt | 0.00 | 1949 | 57.0% | 52.0% | 51.4% |
| platt | 0.05 | 782 | 60.3% | 51.3% | 50.8% |
| platt | 0.12 | 137 | 60.5% | 45.3% | 46.7% |
| temperature | 0.00 | 1949 | 56.7% | 51.8% | 51.1% |
| temperature | 0.05 | 792 | 60.1% | 51.2% | 50.8% |
| temperature | 0.12 | 134 | 60.7% | 45.6% | 47.8% |
| l2_c0.1 | 0.00 | 1949 | 58.0% | 52.9% | 52.5% |
| l2_c0.1 | 0.05 | 805 | 61.3% | 52.3% | 52.4% |
| l2_c0.1 | 0.12 | 140 | 62.3% | 47.1% | 47.9% |

Encompassing regression y ~ a + b_model logit(p_model) + b_market logit(p_close):

| model | n | b_model (SE) | b_market (SE) |
|---|---|---|---|
| current | 1949 | -0.100 (0.158) | 1.148 (0.177) |
| platt | 1949 | -0.107 (0.160) | 1.154 (0.177) |
| temperature | 1949 | -0.104 (0.162) | 1.150 (0.177) |
| l2_c0.1 | 1949 | -0.097 (0.159) | 1.145 (0.177) |

Winner's-curse simulation (perfectly calibrated model with no information beyond the close, noise sd 0.335 in logit units, 200 draws): picks at t = 0 show model p 48.8%, market p 43.6%, actual 43.8%; its ECE 0.021.

