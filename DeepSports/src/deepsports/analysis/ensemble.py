"""Ensemble v2: Elo + model v1.0 + v1.1 + boosted trees, blended, with a locked holdout.

    # 1. validation only (seasons <= 2025): tune the trees, pick + fit the blends, freeze
    uv run python -m deepsports.analysis.ensemble validate --db COPY --config CFG.json
    # 2. score the locked holdout (season 2026) ONCE with the frozen config
    uv run python -m deepsports.analysis.ensemble holdout --db COPY --config CFG.json --preds P.json

Protocol (docs/DECISIONS.md, 2026-11-04): the holdout is every completed game of season 2026
(2025-26). `validate` drops every row from season >= HOLDOUT_SEASON before folding, so no tree
setting, blend method or blend weight can see it. `holdout` reads the frozen config, refuses
to run twice (a marker file next to the config), and produces walk-forward predictions for
2026 (base models refit monthly on games before each block) blended with the frozen weights.

Leakage: base models use build_features rows (pre-tip only). Closing lines are never inputs;
they are carried along only to score the market as a benchmark.
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression

from deepsports import config
from deepsports.analysis.backtest import iter_folds
from deepsports.analysis.features import FEATURES, build_features, feature_matrix
from deepsports.analysis.model import make_model
from deepsports.analysis.players import PLAYER_FEATURES

HOLDOUT_SEASON = 2026
VALIDATION_SEASONS = (2024, 2025)
EPS = 1e-6
TREE_FEATURES = FEATURES + PLAYER_FEATURES
BASES = ("elo", "v10", "v11", "tree")  # prefixes: p_<base>, m_<base>, t_<base>
TOTAL_BASES = ("v10", "v11", "tree")  # Elo has no total


# ---------- boosted trees ----------


@dataclass
class TreeParams:
    learning_rate: float = 0.05
    max_iter: int = 200
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 50
    l2_regularization: float = 1.0
    mono_elo: bool = True  # win/margin non-decreasing in elo_diff (a prior, not tuned)

    def label(self) -> str:
        return (
            f"lr={self.learning_rate} it={self.max_iter} leaves={self.max_leaf_nodes} "
            f"min_leaf={self.min_samples_leaf}"
        )


@dataclass
class TreeModel:
    """HistGradientBoosting win classifier + margin / total regressors on every pre-game
    feature (team + player). NaNs are handled natively; no early stopping (it would use a
    random split of the training rows), fixed seed."""

    params: TreeParams = field(default_factory=TreeParams)
    features: list[str] = field(default_factory=lambda: list(TREE_FEATURES))

    def _kw(self, mono: bool) -> dict[str, Any]:
        p = self.params
        kw = {
            "learning_rate": p.learning_rate,
            "max_iter": p.max_iter,
            "max_leaf_nodes": p.max_leaf_nodes,
            "min_samples_leaf": p.min_samples_leaf,
            "l2_regularization": p.l2_regularization,
            "early_stopping": False,
            "random_state": 0,
        }
        if mono and p.mono_elo and "elo_diff" in self.features:
            kw["monotonic_cst"] = [1 if f == "elo_diff" else 0 for f in self.features]
        return kw

    def fit(self, rows: list[dict[str, Any]]) -> "TreeModel":
        rows = [r for r in rows if r["home_margin"] is not None]
        x = np.array(feature_matrix(rows, self.features), dtype=float)
        self.win = HistGradientBoostingClassifier(**self._kw(True)).fit(
            x, np.array([r["home_win"] for r in rows])
        )
        self.margin = HistGradientBoostingRegressor(**self._kw(True)).fit(
            x, np.array([r["home_margin"] for r in rows], dtype=float)
        )
        self.total_model = HistGradientBoostingRegressor(**self._kw(False)).fit(
            x, np.array([r["total"] for r in rows], dtype=float)
        )
        return self

    def predict(self, rows: list[dict[str, Any]]) -> list[dict[str, float]]:
        x = np.array(feature_matrix(rows, self.features), dtype=float)
        p = self.win.predict_proba(x)[:, 1]
        m, t = self.margin.predict(x), self.total_model.predict(x)
        return [
            {"p_home_win": float(a), "pred_home_margin": float(b), "pred_total": float(c)}
            for a, b, c in zip(p, m, t, strict=True)
        ]


# ---------- out-of-sample base predictions ----------


def _eastern_date(t: datetime) -> str:
    # US/Eastern game day without a tz database: UTC-5 is close enough for day clustering.
    return (t.astimezone(UTC) - timedelta(hours=5)).date().isoformat()


def oof_predictions(
    rows: list[dict[str, Any]],
    test_seasons: tuple[int, ...],
    max_season: int,
    tree_params: TreeParams | None = None,
    bases: tuple[str, ...] = BASES,
) -> list[dict[str, Any]]:
    """Walk-forward (monthly refit) predictions of every base model for the games of
    `test_seasons`. Rows from seasons > max_season are removed *before* folding, so they
    cannot be trained on or scored. Each output row: truth, closing-line benchmark, and
    p_/m_/t_<base> predictions."""
    if max(test_seasons) > max_season:
        raise ValueError("test seasons beyond max_season")
    rows = [r for r in rows if r["season"] <= max_season]
    tree_params = tree_params or TreeParams()
    out = []
    for _, train, test in iter_folds(rows, refit="monthly"):
        if test[0]["season"] not in test_seasons:
            continue
        assert max(r["start_time_utc"] for r in train) < min(r["start_time_utc"] for r in test)
        preds: dict[str, list[dict[str, float]]] = {}
        if "v10" in bases:
            preds["v10"] = make_model("v1.0").fit(train).predict(test)
        if "v11" in bases:
            preds["v11"] = make_model("v1.1").fit(train).predict(test)
        if "tree" in bases:
            preds["tree"] = TreeModel(tree_params).fit(train).predict(test)
        for i, r in enumerate(test):
            mk = r["market"]
            row = {
                "game_id": r["game_id"],
                "season": r["season"],
                "season_type": r["season_type"],
                "start_time_utc": r["start_time_utc"],
                "day": _eastern_date(r["start_time_utc"]),
                "home_win": r["home_win"],
                "home_margin": r["home_margin"],
                "total": r["total"],
                "market_p_home": mk.get("p_home"),
                "spread_home": mk.get("spread_home"),
                "over_under": mk.get("over_under"),
                "p_elo": r["elo_p_home"],
                "m_elo": r["elo_margin"],
            }
            for b, ps in preds.items():
                row[f"p_{b}"] = ps[i]["p_home_win"]
                row[f"m_{b}"] = ps[i]["pred_home_margin"]
                row[f"t_{b}"] = ps[i]["pred_total"]
            if mk.get("spread_home") is not None:
                row["m_close"] = -mk["spread_home"]
            out.append(row)
    return out


# ---------- blends ----------


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def _softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max())
    return e / e.sum()


@dataclass
class Blend:
    """Combine base predictions for one target.

    kind 'prob' (win probability, inputs p_<base>) or 'point' (margin m_ / total t_).
    method:
      - 'mean': plain average (of probabilities, or of points). No fitting.
      - 'convex': non-negative weights summing to 1 (on logits for 'prob'; fit by log loss /
        MAE). No intercept, so it can't shift the level.
      - 'stack': logistic regression on the logits (with intercept, light L2) / OLS on the
        points with intercept.
    """

    kind: str
    method: str
    inputs: list[str]
    weights: list[float] = field(default_factory=list)
    intercept: float = 0.0

    def _x(self, rows: list[dict[str, Any]]) -> np.ndarray:
        x = np.array([[r[c] for c in self.inputs] for r in rows], dtype=float)
        return _logit(x) if self.kind == "prob" else x

    def fit(self, rows: list[dict[str, Any]]) -> "Blend":
        k = len(self.inputs)
        if self.method == "mean":
            self.weights, self.intercept = [1 / k] * k, 0.0
            return self
        x = self._x(rows)
        if self.kind == "prob":
            y = np.array([r["home_win"] for r in rows], dtype=float)
        else:
            tgt = "home_margin" if self.inputs[0].startswith("m_") else "total"
            y = np.array([r[tgt] for r in rows], dtype=float)
        if self.method == "stack":
            if self.kind == "prob":
                est = LogisticRegression(C=1.0, max_iter=1000).fit(x, y.astype(int))
                self.weights = est.coef_[0].tolist()
                self.intercept = float(est.intercept_[0])
            else:
                est = LinearRegression().fit(x, y)
                self.weights, self.intercept = est.coef_.tolist(), float(est.intercept_)
            return self
        if self.method == "convex":

            def loss(z: np.ndarray) -> float:
                s = x @ _softmax(z)
                if self.kind == "prob":
                    p = np.clip(1 / (1 + np.exp(-s)), EPS, 1 - EPS)
                    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
                return float(np.mean(np.abs(s - y)))

            best = min(
                (
                    minimize(loss, z0, method="Nelder-Mead", options={"maxiter": 4000})
                    for z0 in [np.zeros(k)] + [np.eye(k)[i] * 2 for i in range(k)]
                ),
                key=lambda r: r.fun,
            )
            self.weights, self.intercept = _softmax(best.x).tolist(), 0.0
            return self
        raise ValueError(f"unknown blend method {self.method}")

    def predict(self, rows: list[dict[str, Any]]) -> np.ndarray:
        w = np.array(self.weights)
        if self.method == "mean":
            x = np.array([[r[c] for c in self.inputs] for r in rows], dtype=float)
            return x @ w
        s = self._x(rows) @ w + self.intercept
        return 1 / (1 + np.exp(-s)) if self.kind == "prob" else s


BLEND_METHODS = ("mean", "convex", "stack")
INPUT_SETS = {
    "prob": [["p_elo", "p_v10", "p_v11", "p_tree"], ["p_v11", "p_tree"]],
    "margin": [["m_elo", "m_v10", "m_v11", "m_tree"], ["m_v11", "m_tree"]],
    "total": [["t_v10", "t_v11", "t_tree"], ["t_v11", "t_tree"]],
}


# ---------- scoring ----------


def _ll(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-15, 1 - 1e-15)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def target_loss(kind: str, pred: np.ndarray, rows: list[dict[str, Any]]) -> float:
    """Selection loss: log loss for probabilities, MAE for margin / total."""
    if kind == "prob":
        return float(np.mean(_ll(pred, np.array([r["home_win"] for r in rows], dtype=float))))
    tgt = "home_margin" if kind == "margin" else "total"
    return float(np.mean(np.abs(pred - np.array([r[tgt] for r in rows], dtype=float))))


def reliability(p: list[float], y: list[int], bins: int = 10) -> dict[str, Any]:
    """Equal-width reliability bins on P(home win) and expected calibration error."""
    out, ece, n = [], 0.0, len(p)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, q in enumerate(p) if lo <= q < hi or (b == bins - 1 and q == 1.0)]
        if not idx:
            out.append({"lo": lo, "hi": hi, "n": 0, "pred": None, "obs": None})
            continue
        mp = sum(p[i] for i in idx) / len(idx)
        ob = sum(y[i] for i in idx) / len(idx)
        ece += len(idx) / n * abs(mp - ob)
        out.append({"lo": lo, "hi": hi, "n": len(idx), "pred": mp, "obs": ob})
    return {"bins": out, "ece": ece}


def per_game_losses(rows: list[dict[str, Any]], p_key: str, m_key: str | None):
    """Per-game Brier, log loss, |margin error|, correct-pick arrays for one model."""
    y = np.array([r["home_win"] for r in rows], dtype=float)
    p = np.array([r[p_key] for r in rows], dtype=float)
    d = {"brier": (p - y) ** 2, "log_loss": _ll(p, y), "acc": ((p >= 0.5) == (y == 1)) * 1.0}
    if m_key:
        mg = np.array([r["home_margin"] for r in rows], dtype=float)
        d["margin_mae"] = np.abs(np.array([r[m_key] for r in rows], dtype=float) - mg)
    return d


def cluster_bootstrap(
    rows: list[dict[str, Any]], diff: np.ndarray, reps: int = 2000, seed: int = 0
) -> dict[str, float]:
    """Mean of a per-game difference with a 95% percentile CI, resampling whole game days
    (games on the same day share news/injury shocks, so days are the safer unit)."""
    by_day: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_day[r["day"]].append(i)
    days = list(by_day.values())
    sums = np.array([diff[ix].sum() for ix in days])
    cnts = np.array([len(ix) for ix in days], dtype=float)
    rng = np.random.default_rng(seed)
    stats = np.empty(reps)
    for b in range(reps):
        pick = rng.integers(0, len(days), len(days))
        stats[b] = sums[pick].sum() / cnts[pick].sum()
    return {
        "mean": float(diff.mean()),
        "lo": float(np.percentile(stats, 2.5)),
        "hi": float(np.percentile(stats, 97.5)),
        "n": len(rows),
        "days": len(days),
    }


# ---------- validation: tune trees, choose blends ----------

TREE_GRID = [
    TreeParams(learning_rate=lr, max_iter=it, max_leaf_nodes=lv, min_samples_leaf=ml)
    for lr, it in ((0.03, 200), (0.05, 400), (0.1, 100))
    for lv in (7, 15)
    for ml in (40, 120)
] + [
    # Round 2 (validation only): round 1's best sat at the most regularized corner.
    TreeParams(learning_rate=lr, max_iter=it, max_leaf_nodes=lv, min_samples_leaf=ml)
    for lr, it in ((0.02, 150), (0.01, 300))
    for lv, ml in ((4, 120), (7, 250), (4, 250))
]


def tune_trees(rows: list[dict[str, Any]], grid=TREE_GRID, log=print) -> dict[str, Any]:
    """Walk-forward over the validation seasons only; per target pick the best setting."""
    results = []
    for tp in grid:
        oof = oof_predictions(
            rows,
            VALIDATION_SEASONS,
            max_season=max(VALIDATION_SEASONS),
            tree_params=tp,
            bases=("tree",),
        )
        res = {
            "params": asdict(tp),
            "log_loss": target_loss("prob", np.array([r["p_tree"] for r in oof]), oof),
            "margin_mae": target_loss("margin", np.array([r["m_tree"] for r in oof]), oof),
            "total_mae": target_loss("total", np.array([r["t_tree"] for r in oof]), oof),
            "n": len(oof),
        }
        log(
            f"  trees {tp.label()}: LL {res['log_loss']:.4f} margin {res['margin_mae']:.3f} "
            f"total {res['total_mae']:.3f}"
        )
        results.append(res)
    best = {
        k: min(results, key=lambda r: r[k])["params"]
        for k in ("log_loss", "margin_mae", "total_mae")
    }
    return {"grid": results, "best": best}


def _combine_tree_oofs(rows, best: dict[str, dict], log=print) -> list[dict[str, Any]]:
    """Validation OOF for all bases, with each target's tree prediction from its own tuned
    setting (trees per target are independent models, so this is just bookkeeping)."""
    base = oof_predictions(
        rows, VALIDATION_SEASONS, max(VALIDATION_SEASONS), TreeParams(**best["log_loss"])
    )
    for key, col in (("margin_mae", "m_tree"), ("total_mae", "t_tree")):
        if best[key] != best["log_loss"]:
            alt = oof_predictions(
                rows,
                VALIDATION_SEASONS,
                max(VALIDATION_SEASONS),
                TreeParams(**best[key]),
                bases=("tree",),
            )
            by = {r["game_id"]: r for r in alt}
            for r in base:
                r[col] = by[r["game_id"]][col]
    log(f"  validation OOF rows: {len(base)}")
    return base


def choose_blends(oof: list[dict[str, Any]], log=print) -> dict[str, Any]:
    """Per target: fit each candidate on the first validation season, score it on the second
    (forward in time), pick the best, then refit the pick on both seasons and freeze it."""
    s1, s2 = VALIDATION_SEASONS
    fit_rows = [r for r in oof if r["season"] == s1]
    eval_rows = [r for r in oof if r["season"] == s2]
    out: dict[str, Any] = {"candidates": {}, "chosen": {}, "single": {}}
    for kind, sets in INPUT_SETS.items():
        cands = []
        for inputs in sets:
            for m in BLEND_METHODS:
                b = Blend("prob" if kind == "prob" else "point", m, list(inputs)).fit(fit_rows)
                loss = target_loss(kind, b.predict(eval_rows), eval_rows)
                cands.append(
                    {
                        "method": m,
                        "inputs": list(inputs),
                        "loss": loss,
                        "weights": b.weights,
                        "intercept": b.intercept,
                    }
                )
                log(f"  blend {kind} {m} {inputs}: {loss:.4f}")
        out["candidates"][kind] = cands
        out["single"][kind] = {
            c: target_loss(kind, np.array([r[c] for r in eval_rows]), eval_rows) for c in sets[0]
        }
        pick = min(cands, key=lambda c: c["loss"])
        final = Blend("prob" if kind == "prob" else "point", pick["method"], pick["inputs"]).fit(
            oof
        )
        out["chosen"][kind] = {
            "method": final.method,
            "inputs": final.inputs,
            "weights": final.weights,
            "intercept": final.intercept,
            "val_loss_s2": pick["loss"],
        }
    return out


def validate(rows: list[dict[str, Any]], log=print) -> dict[str, Any]:
    rows = [r for r in rows if r["season"] < HOLDOUT_SEASON]  # the holdout never enters
    log("tuning trees on validation seasons", VALIDATION_SEASONS)
    tuned = tune_trees(rows, log=log)
    oof = _combine_tree_oofs(rows, tuned["best"], log=log)
    log("choosing blends")
    blends = choose_blends(oof, log=log)
    return {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "holdout_season": HOLDOUT_SEASON,
        "validation_seasons": list(VALIDATION_SEASONS),
        "max_season_seen": max(r["season"] for r in rows),
        "trees": tuned,
        "blends": blends,
    }


# ---------- holdout ----------


def _blend_from(cfg: dict[str, Any], kind: str) -> Blend:
    c = cfg["blends"]["chosen"][kind]
    return Blend(
        "prob" if kind == "prob" else "point",
        c["method"],
        c["inputs"],
        weights=c["weights"],
        intercept=c["intercept"],
    )


def holdout_predictions(rows: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk-forward predictions for the holdout season with the frozen config."""
    best = cfg["trees"]["best"]
    hs = cfg["holdout_season"]
    base = oof_predictions(rows, (hs,), hs, TreeParams(**best["log_loss"]))
    for key, col in (("margin_mae", "m_tree"), ("total_mae", "t_tree")):
        if best[key] != best["log_loss"]:
            alt = oof_predictions(rows, (hs,), hs, TreeParams(**best[key]), bases=("tree",))
            by = {r["game_id"]: r for r in alt}
            for r in base:
                r[col] = by[r["game_id"]][col]
    for kind, col in (("prob", "p_ens"), ("margin", "m_ens"), ("total", "t_ens")):
        pred = _blend_from(cfg, kind).predict(base)
        for r, v in zip(base, pred, strict=True):
            r[col] = float(v)
    return base


MODELS = [  # (label, prob key, margin key)
    ("Elo", "p_elo", "m_elo"),
    ("v1.0", "p_v10", "m_v10"),
    ("v1.1", "p_v11", "m_v11"),
    ("Trees", "p_tree", "m_tree"),
    ("Ensemble v2", "p_ens", "m_ens"),
]


def holdout_report(preds: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """Every number the write-up needs, as a dict (rendered by render_markdown)."""
    mkt = [r for r in preds if r["market_p_home"] is not None and r.get("m_close") is not None]
    sp = [r for r in preds if r.get("m_close") is not None]
    out: dict[str, Any] = {"n": len(preds), "n_market": len(mkt), "n_spread": len(sp)}
    tbl = []
    for lab, pk, mk in MODELS + [("Closing line", "market_p_home", "m_close")]:
        rows = mkt if lab == "Closing line" else preds
        d = per_game_losses(rows, pk, mk)
        dm = per_game_losses(mkt, pk, mk)  # same subset for everyone
        tbl.append(
            {
                "model": lab,
                "n": len(rows),
                "brier": float(d["brier"].mean()),
                "log_loss": float(d["log_loss"].mean()),
                "acc": float(d["acc"].mean()),
                "margin_mae": float(d["margin_mae"].mean()),
                "brier_mkt": float(dm["brier"].mean()),
                "log_loss_mkt": float(dm["log_loss"].mean()),
                "acc_mkt": float(dm["acc"].mean()),
                "margin_mae_mkt": float(dm["margin_mae"].mean()),
                "ece": reliability([r[pk] for r in rows], [r["home_win"] for r in rows])["ece"],
            }
        )
    out["table"] = tbl
    tot = [r for r in preds if r["over_under"] is not None]
    out["totals"] = {
        lab: float(np.mean([abs(r[k] - r["total"]) for r in tot]))
        for lab, k in (
            ("v1.0", "t_v10"),
            ("v1.1", "t_v11"),
            ("Trees", "t_tree"),
            ("Ensemble v2", "t_ens"),
            ("Closing line", "over_under"),
        )
    } | {"n": len(tot)}
    out["calibration"] = {
        lab: reliability([r[pk] for r in mkt], [r["home_win"] for r in mkt])
        for lab, pk, _ in MODELS + [("Closing line", "market_p_home", None)]
    }
    # Paired day-clustered bootstrap CIs on the differences (negative = ensemble better).
    ens_all = per_game_losses(preds, "p_ens", "m_ens")
    cis: dict[str, dict[str, Any]] = {}
    for lab, pk, mk in (
        ("v1.1", "p_v11", "m_v11"),
        ("Elo", "p_elo", "m_elo"),
        ("Trees", "p_tree", "m_tree"),
    ):
        o = per_game_losses(preds, pk, mk)
        cis[f"Ensemble - {lab}"] = {
            k: cluster_bootstrap(preds, ens_all[k] - o[k])
            for k in ("brier", "log_loss", "margin_mae", "acc")
        }
    e, c = per_game_losses(mkt, "p_ens", "m_ens"), per_game_losses(mkt, "market_p_home", "m_close")
    cis["Ensemble - closing line"] = {
        k: cluster_bootstrap(mkt, e[k] - c[k]) for k in ("brier", "log_loss", "margin_mae", "acc")
    }
    out["cis"] = cis
    # Per-month stability of the key comparison.
    months: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in preds:
        months[r["day"][:7]].append(r)
    out["by_month"] = []
    for mo in sorted(months):
        rs = months[mo]
        a, b = per_game_losses(rs, "p_ens", "m_ens"), per_game_losses(rs, "p_v11", "m_v11")
        out["by_month"].append(
            {
                "month": mo,
                "n": len(rs),
                "ll_ens": float(a["log_loss"].mean()),
                "ll_v11": float(b["log_loss"].mean()),
                "mae_ens": float(a["margin_mae"].mean()),
                "mae_v11": float(b["margin_mae"].mean()),
            }
        )
    return out


def _f(x: float | None, d: int = 4) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def render_markdown(rep: dict[str, Any], cfg: dict[str, Any]) -> str:
    L = []
    L.append(
        f"Holdout season {cfg['holdout_season']}: {rep['n']} games; {rep['n_market']} with a "
        f"closing moneyline and spread (the market subset)."
    )
    L.append("\n### All holdout games (closing line: market subset)")
    L.append("| model | n | Brier | log loss | accuracy | margin MAE | ECE |")
    L.append("|---|---|---|---|---|---|---|")
    for t in rep["table"]:
        L.append(
            f"| {t['model']} | {t['n']} | {_f(t['brier'])} | {_f(t['log_loss'])} | "
            f"{t['acc']:.1%} | {_f(t['margin_mae'], 2)} | {_f(t['ece'], 3)} |"
        )
    L.append(f"\n### Market subset only ({rep['n_market']} games, every row on the same games)")
    L.append("| model | Brier | log loss | accuracy | margin MAE |")
    L.append("|---|---|---|---|---|")
    for t in rep["table"]:
        L.append(
            f"| {t['model']} | {_f(t['brier_mkt'])} | {_f(t['log_loss_mkt'])} | "
            f"{t['acc_mkt']:.1%} | {_f(t['margin_mae_mkt'], 2)} |"
        )
    tt = rep["totals"]
    L.append(f"\n### Total points MAE ({tt['n']} games with a closing total)")
    L.append("| " + " | ".join(k for k in tt if k != "n") + " |")
    L.append("|" + "---|" * (len(tt) - 1))
    L.append("| " + " | ".join(_f(v, 2) for k, v in tt.items() if k != "n") + " |")
    L.append(
        "\n### Paired differences, 95% day-clustered bootstrap CI (2,000 resamples; "
        "negative = ensemble better, except accuracy where positive = better)"
    )
    L.append("| comparison | Brier | log loss | margin MAE | accuracy |")
    L.append("|---|---|---|---|---|")
    for name, d in rep["cis"].items():
        cells = []
        for k, dig in (("brier", 4), ("log_loss", 4), ("margin_mae", 3), ("acc", 3)):
            c = d[k]
            cells.append(f"{c['mean']:+.{dig}f} ({c['lo']:+.{dig}f} to {c['hi']:+.{dig}f})")
        L.append(
            f"| {name} (n={d['brier']['n']}, {d['brier']['days']} days) | "
            + " | ".join(cells)
            + " |"
        )
    L.append(
        "\n### Calibration on the market subset (reliability bins of P(home win): "
        "n / mean predicted / observed)"
    )
    labs = list(rep["calibration"])
    L.append("| bin | " + " | ".join(labs) + " |")
    L.append("|---|" + "---|" * len(labs))
    for i in range(10):
        b0 = rep["calibration"][labs[0]]["bins"][i]
        cells = []
        for lab in labs:
            b = rep["calibration"][lab]["bins"][i]
            cells.append("-" if not b["n"] else f"{b['n']} / {b['pred']:.2f} / {b['obs']:.2f}")
        L.append(f"| {b0['lo']:.1f}-{b0['hi']:.1f} | " + " | ".join(cells) + " |")
    L.append("| ECE | " + " | ".join(f"{rep['calibration'][x]['ece']:.3f}" for x in labs) + " |")
    L.append("\n### By month: ensemble vs v1.1")
    L.append("| month | n | LL ens | LL v1.1 | margin MAE ens | margin MAE v1.1 |")
    L.append("|---|---|---|---|---|---|")
    for m in rep["by_month"]:
        L.append(
            f"| {m['month']} | {m['n']} | {_f(m['ll_ens'])} | {_f(m['ll_v11'])} | "
            f"{_f(m['mae_ens'], 2)} | {_f(m['mae_v11'], 2)} |"
        )
    return "\n".join(L) + "\n"


def render_validation(cfg: dict[str, Any]) -> str:
    L = [
        "### Tree grid (walk-forward on 2024 + 2025)",
        "| setting | log loss | margin MAE | total MAE |",
        "|---|---|---|---|",
    ]
    for g in cfg["trees"]["grid"]:
        L.append(
            f"| {TreeParams(**g['params']).label()} | {_f(g['log_loss'])} | "
            f"{_f(g['margin_mae'], 3)} | {_f(g['total_mae'], 3)} |"
        )
    L.append("\n### Blend candidates (fit on 2024 OOF, scored on 2025 OOF)")
    L.append("| target | method | inputs | loss on 2025 | weights (intercept) |")
    L.append("|---|---|---|---|---|")
    for kind, cands in cfg["blends"]["candidates"].items():
        for c in cands:
            w = ", ".join(f"{x:.3f}" for x in c["weights"])
            L.append(
                f"| {kind} | {c['method']} | {', '.join(c['inputs'])} | {_f(c['loss'])} | "
                f"{w} ({c['intercept']:.3f}) |"
            )
        for col, v in cfg["blends"]["single"][kind].items():
            L.append(f"| {kind} | single | {col} | {_f(v)} | |")
    L.append("\n### Frozen blends (refit on 2024 + 2025 OOF)")
    for kind, c in cfg["blends"]["chosen"].items():
        w = ", ".join(f"{i}={x:.3f}" for i, x in zip(c["inputs"], c["weights"], strict=True))
        L.append(f"- {kind}: {c['method']}: {w}, intercept {c['intercept']:.3f}")
    return "\n".join(L) + "\n"


# ---------- CLI ----------


def _load_rows(db: Path, cache: Path | None) -> list[dict[str, Any]]:
    import pickle

    if cache and cache.exists():
        return pickle.loads(cache.read_bytes())
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = build_features(con, include_players=True)
    finally:
        con.close()
    rows = [r for r in rows if r["state"] == "post"]
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(pickle.dumps(rows))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["validate", "holdout", "report"])
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--cache", type=Path, help="pickle of feature rows (large; external drive)")
    ap.add_argument("--config", type=Path, required=True, help="frozen config JSON")
    ap.add_argument("--out", type=Path, help="Markdown output")
    ap.add_argument("--preds", type=Path, help="holdout per-game predictions JSON")
    args = ap.parse_args(argv)
    if args.step == "report":  # re-render saved holdout predictions; no refitting
        cfg = json.loads(args.config.read_text())
        preds = json.loads(args.preds.read_text())
        md = render_markdown(holdout_report(preds, cfg), cfg)
        print(md)
        if args.out:
            args.out.write_text(md)
        return 0
    rows = _load_rows(args.db, args.cache)
    if args.step == "validate":
        cfg = validate(rows)
        args.config.parent.mkdir(parents=True, exist_ok=True)
        args.config.write_text(json.dumps(cfg, indent=1))
        print(render_validation(cfg))
        if args.out:
            args.out.write_text(render_validation(cfg))
        return 0
    marker = args.config.with_suffix(".holdout-scored")
    if marker.exists():
        print(f"holdout already scored ({marker}); refusing to score it again", file=sys.stderr)
        return 2
    if not args.preds:
        print("--preds is required for the holdout step", file=sys.stderr)
        return 2
    cfg = json.loads(args.config.read_text())
    preds = holdout_predictions(rows, cfg)
    args.preds.parent.mkdir(parents=True, exist_ok=True)
    args.preds.write_text(json.dumps(preds, default=str))
    marker.write_text(datetime.now(UTC).isoformat(timespec="seconds") + "\n")
    md = render_markdown(holdout_report(preds, cfg), cfg)
    print(md)
    if args.out:
        args.out.write_text(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
