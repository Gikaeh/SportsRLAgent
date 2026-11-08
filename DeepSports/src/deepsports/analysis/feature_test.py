"""Feature-injection walk-forward harness: does a candidate pre-tip feature bring a shipped
model (NBA v1.x, college ncaab-v1) closer to the closing line?

Ported from the DeepSeek edge study (collab/deepseek/lab/v11_rerun/), which re-tested its Track B
candidates this way after reproducing the shipped v1.1 and ncaab-v1 walk-forward predictions
bit-for-bit. Method:

1. Baseline: the shipped walk-forward (same rows, same folds) before any column is added.
2. Attach the candidate columns to every row (NaN where a game has no value; the pipeline's
   mean imputer fills them) and re-run the baseline: its predictions must be bit-identical to
   step 1 (`compare_predictions`), or nothing downstream counts.
3. Variant: the same walk-forward with the candidate columns appended to the feature lists.
4. Score both on the common rows where the feature exists and the closing line exists:
   per-game gap difference |pred_with - y| - |pred_base - y| (the close cancels), with a
   day-clustered bootstrap CI (2,000 resamples, seed 42). Negative = closer to the close.
   Win probabilities get paired Brier / log-loss differences the same way.

Inputs: feature rows from `features.build_features` (NBA) or `ncaab.college_rows` /
`ncaab.live_rows` (college); candidate values as {column: {game_id: value}}, computed from
information available before tip-off (the caller's responsibility). Read-only, no I/O.
"""

from __future__ import annotations

import copy
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from deepsports.analysis import ncaab
from deepsports.analysis.backtest import walk_forward
from deepsports.analysis.metrics import log_loss
from deepsports.analysis.model import MODEL_VERSIONS, ModelV1, make_model, resolve_version

EASTERN = ZoneInfo("America/New_York")
PRED_KEYS = ("p_home_win", "pred_home_margin", "pred_total")
REPS, SEED = 2000, 42


# ---------- candidate values ----------


def to_float(v: Any) -> float | None:
    """CSV-style cell -> float; '', 'None', 'nan' and NaN -> None."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if v in ("", "None", "nan", "NaN"):
            return None
    f = float(v)
    return None if math.isnan(f) else f


def game_values(rows: Iterable[Mapping[str, Any]], cols: Sequence[str]) -> dict[str, dict]:
    """{col: {game_id: value}} from per-game rows; a game is kept only when every col has a
    value (so a multi-column candidate always covers the same games)."""
    out: dict[str, dict[str, float]] = {c: {} for c in cols}
    for r in rows:
        vals = {c: to_float(r.get(c)) for c in cols}
        if all(v is not None for v in vals.values()):
            for c, v in vals.items():
                out[c][str(r["game_id"])] = v
    return out


def home_minus_away(team_rows: Iterable[Mapping[str, Any]], col: str) -> dict[str, float]:
    """{game_id: home - away} from one-row-per-team-game rows with a `home_away` column."""
    sides: dict[str, dict[str, float]] = defaultdict(dict)
    for r in team_rows:
        v = to_float(r.get(col))
        if v is not None:
            sides[str(r["game_id"])][r["home_away"]] = v
    return {g: s["home"] - s["away"] for g, s in sides.items() if "home" in s and "away" in s}


def attach_columns(
    rows: list[dict[str, Any]], values: Mapping[str, Mapping[str, float]]
) -> dict[str, set[str]]:
    """Add every candidate column to each row's `features` (NaN where unknown), in place.
    Returns {col: game_ids with a value}."""
    covered: dict[str, set[str]] = {c: set() for c in values}
    for r in rows:
        gid = str(r["game_id"])
        for col, m in values.items():
            v = m.get(gid)
            r["features"][col] = float(v) if v is not None else float("nan")
            if v is not None:
                covered[col].add(gid)
    return covered


# ---------- paired scoring ----------


def paired_day_bootstrap(
    days: Sequence[str], diffs: Sequence[float], reps: int = REPS, seed: int = SEED
) -> dict[str, float]:
    """Mean of per-game `diffs` with a day-clustered percentile (2.5-97.5) bootstrap CI."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for d, v in zip(days, diffs, strict=True):
        by_day[d].append(float(v))
    keys = sorted(by_day)
    if not keys:
        nan = float("nan")
        return {"mean": nan, "lo": nan, "hi": nan, "n": 0, "n_days": 0}
    pool = [np.asarray(by_day[k]) for k in keys]
    rng = np.random.default_rng(seed)
    stats = np.empty(reps)
    for b in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        stats[b] = np.mean(np.concatenate([pool[i] for i in pick]))
    return {
        "mean": float(np.mean(np.asarray(diffs, dtype=float))),
        "lo": float(np.percentile(stats, 2.5)),
        "hi": float(np.percentile(stats, 97.5)),
        "n": len(diffs),
        "n_days": len(keys),
    }


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    x, y = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 2 or np.std(x[ok]) == 0 or np.std(y[ok]) == 0:
        return float("nan")
    return float(np.corrcoef(x[ok], y[ok])[0, 1])


def paired_gap_comparison(
    rows: Sequence[Mapping[str, Any]],
    pred_key: str,
    base_pred_key: str,
    close_key: str,
    truth_key: str,
    close_sign: int = 1,
    reps: int = REPS,
    seed: int = SEED,
) -> dict[str, Any]:
    """Baseline vs with-feature MAE gap to the close on one common row set (rows need `day`).
    close_sign: +1 when the close predicts the truth directly (totals), -1 for spread vs
    margin. delta_gap < 0 = the feature moved predictions closer to the truth."""
    base = np.array([abs(r[base_pred_key] - r[truth_key]) for r in rows], dtype=float)
    feat = np.array([abs(r[pred_key] - r[truth_key]) for r in rows], dtype=float)
    close = np.array([abs(close_sign * r[close_key] - r[truth_key]) for r in rows], dtype=float)
    diff = feat - base
    ci = paired_day_bootstrap([r["day"] for r in rows], list(diff), reps=reps, seed=seed)

    def mean(a: np.ndarray) -> float:
        return float(np.mean(a)) if len(a) else float("nan")

    return {
        "n": len(rows),
        "base_mae": mean(base),
        "close_mae": mean(close),
        "base_gap": mean(base - close),
        "feat_mae": mean(feat),
        "feat_gap": mean(feat - close),
        "delta_gap": mean(diff),
        "ci_lo": ci["lo"],
        "ci_hi": ci["hi"],
        "n_days": ci["n_days"],
    }


def paired_prob_comparison(
    rows: Sequence[Mapping[str, Any]],
    pred_key: str,
    base_pred_key: str,
    market_key: str,
    reps: int = REPS,
    seed: int = SEED,
) -> dict[str, Any]:
    """Brier / log loss of with-feature vs baseline win probabilities (and the market's) on
    one row set (rows need `home_win`, `day`). Negative d_* = better with the feature."""
    y = np.array([r["home_win"] for r in rows], dtype=float)
    p1 = np.clip(np.array([r[pred_key] for r in rows], dtype=float), 1e-15, 1 - 1e-15)
    p0 = np.clip(np.array([r[base_pred_key] for r in rows], dtype=float), 1e-15, 1 - 1e-15)
    pm = [r[market_key] for r in rows]

    def ll(p):
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    days = [r["day"] for r in rows]
    return {
        "n": len(rows),
        "base_brier": float(np.mean((p0 - y) ** 2)),
        "feat_brier": float(np.mean((p1 - y) ** 2)),
        "mkt_brier": float(np.mean((np.asarray(pm) - y) ** 2)),
        "base_ll": float(np.mean(ll(p0))),
        "feat_ll": float(np.mean(ll(p1))),
        "mkt_ll": log_loss(pm, [int(v) for v in y]),
        "d_brier": paired_day_bootstrap(
            days, list((p1 - y) ** 2 - (p0 - y) ** 2), reps=reps, seed=seed
        ),
        "d_ll": paired_day_bootstrap(days, list(ll(p1) - ll(p0)), reps=reps, seed=seed),
    }


def compare_predictions(
    a: Iterable[Mapping[str, Any]],
    b: Iterable[Mapping[str, Any]],
    keys: Sequence[str] = PRED_KEYS,
    tol: float = 1e-9,
) -> dict[str, Any]:
    """Per-game reproduction check between two prediction lists (by game_id). Returns
    {n_a, n_b, n_mismatch, mismatches[:10]}; None == None counts as a match."""
    am = {str(p["game_id"]): p for p in a}
    bm = {str(p["game_id"]): p for p in b}
    bad: list[tuple] = [(g, "missing from b") for g in am.keys() - bm.keys()]
    bad += [(g, "missing from a") for g in bm.keys() - am.keys()]
    for g in am.keys() & bm.keys():
        for k in keys:
            x, y = am[g].get(k), bm[g].get(k)
            if (x is None) != (y is None) or (x is not None and abs(x - y) > tol):
                bad.append((g, k, x, y))
    return {"n_a": len(am), "n_b": len(bm), "n_mismatch": len(bad), "mismatches": bad[:10]}


def _eastern_day(t: datetime | str) -> str:
    if isinstance(t, str):
        t = datetime.fromisoformat(t)
    return t.astimezone(EASTERN).date().isoformat()


def _score(
    base: Mapping[str, Mapping[str, Any]],
    feat: Mapping[str, Mapping[str, Any]],
    common: set[str],
    keep: Any,
    *,
    margin: bool,
    total: bool,
    reps: int,
    seed: int,
) -> dict[str, Any]:
    """Gap/prob comparisons on the common rows that pass `keep(pred)` and have the line."""
    out: dict[str, Any] = {}
    ids = sorted(g for g in common if g in base and g in feat and keep(base[g]))

    def rows(pred_key: str, need: str) -> list[dict[str, Any]]:
        return [
            {
                **base[g],
                "base_pred": base[g][pred_key],
                "pred": feat[g][pred_key],
                "day": _eastern_day(base[g]["start_time_utc"]),
            }
            for g in ids
            if base[g].get(need) is not None
        ]

    if margin:
        out["margin"] = paired_gap_comparison(
            rows("pred_home_margin", "spread_home"),
            "pred",
            "base_pred",
            "spread_home",
            "home_margin",
            close_sign=-1,
            reps=reps,
            seed=seed,
        )
        out["prob"] = paired_prob_comparison(
            rows("p_home_win", "market_p_home"), "pred", "base_pred", "market_p_home", reps, seed
        )
    if total:
        out["total"] = paired_gap_comparison(
            rows("pred_total", "over_under"),
            "pred",
            "base_pred",
            "over_under",
            "total",
            close_sign=1,
            reps=reps,
            seed=seed,
        )
    return out


def _common(covered: Mapping[str, set[str]], cols: Sequence[str]) -> set[str]:
    return set.intersection(*(covered[c] for c in cols)) if cols else set()


# ---------- NBA (model v1.x, monthly walk-forward) ----------


def nba_variant_model(
    base_version: str = "v1.1",
    extra_win_margin: Sequence[str] = (),
    extra_total: Sequence[str] = (),
) -> ModelV1:
    """The shipped `base_version` model with candidate columns appended."""
    _, win, total = MODEL_VERSIONS[resolve_version(base_version)]
    return ModelV1(
        win_features=list(win) + list(extra_win_margin),
        margin_features=list(win) + list(extra_win_margin),
        total_features=list(total) + list(extra_total),
    )


def nba_feature_test(
    rows: list[dict[str, Any]],
    values: Mapping[str, Mapping[str, float]],
    extra_win_margin: Sequence[str] = (),
    extra_total: Sequence[str] = (),
    *,
    base_version: str = "v1.1",
    seasons: Sequence[int] | None = None,
    refit: str = "monthly",
    reference: Iterable[Mapping[str, Any]] | None = None,
    reps: int = REPS,
    seed: int = SEED,
) -> dict[str, Any]:
    """Run the four steps in the module docstring for NBA rows (`build_features`, with
    include_players for v1.1). `seasons` limits scoring (not training) to those seasons;
    `reference` (e.g. cached walk-forward predictions) is checked against the baseline too.
    `rows` are not modified."""
    rows = copy.deepcopy(rows)
    base = walk_forward(rows, refit=refit, model_factory=lambda: make_model(base_version))
    covered = attach_columns(rows, values)
    again = walk_forward(rows, refit=refit, model_factory=lambda: make_model(base_version))
    feat = walk_forward(
        rows,
        refit=refit,
        model_factory=lambda: nba_variant_model(base_version, extra_win_margin, extra_total),
    )
    base_by = {p["game_id"]: p for p in base["predictions"]}
    feat_by = {p["game_id"]: p for p in feat["predictions"]}
    out: dict[str, Any] = {
        "baseline_check": compare_predictions(base["predictions"], again["predictions"]),
        "coverage": {c: len(v) for c, v in covered.items()},
    }
    if reference is not None:
        out["reference_check"] = compare_predictions(reference, base["predictions"])

    def keep(p):
        return seasons is None or p["season"] in seasons

    if extra_win_margin:
        out.update(
            _score(
                base_by,
                feat_by,
                _common(covered, extra_win_margin),
                keep,
                margin=True,
                total=False,
                reps=reps,
                seed=seed,
            )
        )
    if extra_total:
        out.update(
            _score(
                base_by,
                feat_by,
                _common(covered, extra_total),
                keep,
                margin=False,
                total=True,
                reps=reps,
                seed=seed,
            )
        )
    return out


# ---------- college (ncaab-v1, weekly walk-forward) ----------


def ncaab_walk_forward(
    rows: list[dict[str, Any]],
    choice: Mapping[str, Mapping[str, Any]],
    start: datetime,
    end: datetime | None = None,
    extra_win_margin: Sequence[str] = (),
    extra_total: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """College v1 weekly walk-forward (`ncaab.weekly_folds`) with candidate columns appended
    to each target's feature set from `choice` (the frozen config's {target: {feature_set,
    min_games}}). With no extra columns the predictions equal `ncaab.walk_forward`'s
    p_model / m_model / t_model. Returns per-game rows with PRED_KEYS, the line and truth."""
    key = {"win": "p_home_win", "margin": "pred_home_margin", "total": "pred_total"}
    out = []
    for _, train, test in ncaab.weekly_folds(rows, start, end):
        preds: dict[str, list[float]] = {}
        for tgt, c in choice.items():
            win, total = ncaab.feature_lists(c["feature_set"])
            cols = list(total) + list(extra_total) if tgt == "total" else win + [*extra_win_margin]
            model = ModelV1(win_features=cols, margin_features=cols, total_features=cols)
            fitted = model.fit([r for r in train if r["rt_n"] >= int(c["min_games"])])
            preds[key[tgt]] = [p[key[tgt]] for p in fitted.predict(test)]
        for i, r in enumerate(test):
            mk = r["market"]
            out.append(
                {
                    "game_id": r["game_id"],
                    "season": r.get("season"),
                    "start_time_utc": r["start_time_utc"],
                    **{k: v[i] for k, v in preds.items()},
                    "market_p_home": mk.get("p_home"),
                    "spread_home": mk.get("spread_home"),
                    "over_under": mk.get("over_under"),
                    "home_win": r["home_win"],
                    "home_margin": r["home_margin"],
                    "total": r["total"],
                }
            )
    return out


def ncaab_feature_test(
    rows: list[dict[str, Any]],
    values: Mapping[str, Mapping[str, float]],
    choice: Mapping[str, Mapping[str, Any]],
    start: datetime,
    end: datetime | None = None,
    extra_win_margin: Sequence[str] = (),
    extra_total: Sequence[str] = (),
    *,
    reference: Iterable[Mapping[str, Any]] | None = None,
    reps: int = REPS,
    seed: int = SEED,
) -> dict[str, Any]:
    """The four steps for college rows (`ncaab.college_rows`), folds in [start, end)."""
    rows = copy.deepcopy(rows)
    base = ncaab_walk_forward(rows, choice, start, end)
    covered = attach_columns(rows, values)
    again = ncaab_walk_forward(rows, choice, start, end)
    feat = ncaab_walk_forward(rows, choice, start, end, extra_win_margin, extra_total)
    base_by = {p["game_id"]: p for p in base}
    feat_by = {p["game_id"]: p for p in feat}
    out: dict[str, Any] = {
        "baseline_check": compare_predictions(base, again),
        "coverage": {c: len(v) for c, v in covered.items()},
    }
    if reference is not None:
        out["reference_check"] = compare_predictions(reference, base)
    kw = {"reps": reps, "seed": seed}

    def keep(_: Any) -> bool:
        return True

    if extra_win_margin:
        common = _common(covered, extra_win_margin)
        out.update(_score(base_by, feat_by, common, keep, margin=True, total=False, **kw))
    if extra_total:
        common = _common(covered, extra_total)
        out.update(_score(base_by, feat_by, common, keep, margin=False, total=True, **kw))
    return out
