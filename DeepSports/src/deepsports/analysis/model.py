"""Prediction model v1: three small linear models on pre-game features.

- win probability: logistic regression
- home margin: ridge regression
- total points: ridge regression

Each is a scikit-learn pipeline (mean imputation -> standardization -> linear model). Simple
on purpose: few features, strong regularization, coefficients you can read.

Versions (same model classes and fixed settings; only the feature lists differ):
- `v1.0`: team features (Elo, schedule context, rolling team form). Any version label that is
  not registered (e.g. `v1.0-test`) uses v1.0, so existing callers are unchanged.
- `v1.1`: v1.0 plus player-availability and top-N player features (players.py).
- `v1.1c`: v1.1 with a stronger L2 penalty on the logistic win model (C = 0.03 instead of 1),
  the declared calibration fix that passed its locked-holdout rule
  (docs/results/2026-11-06-calibration.md). Margin and total models are identical to v1.1.
  Not the display or default version.
"""

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import duckdb
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from deepsports.analysis.features import FEATURES, INJURY_FEATURES, build_features, feature_matrix
from deepsports.analysis.players import PLAYER_DIFF_FEATURES, PLAYER_FEATURES, PLAYER_SUM_FEATURES

MODEL_NAME = "v1"
DEFAULT_VERSION = "v1.0"

WIN_FEATURES = [
    "elo_diff",
    "home_court",
    "rest_diff",
    "b2b_home",
    "b2b_away",
    "g7_home",
    "g7_away",
    "travel_away",
    "road_trip_away",
    "form_net_diff",
    "eff_net_diff",
]
MARGIN_FEATURES = WIN_FEATURES
TOTAL_FEATURES = [
    "lg_total",
    "form_total",
    "pace_sum",
    "eff_sum",
    "b2b_home",
    "b2b_away",
    "rest_diff",
    "home_court",
]
assert set(WIN_FEATURES + TOTAL_FEATURES) <= set(FEATURES)

# Model v1.1: the v1 lists plus the player features. Fixed in advance, not tuned.
V11_WIN_FEATURES = WIN_FEATURES + PLAYER_DIFF_FEATURES
V11_TOTAL_FEATURES = TOTAL_FEATURES + PLAYER_SUM_FEATURES
assert set(V11_WIN_FEATURES + V11_TOTAL_FEATURES) <= set(FEATURES + PLAYER_FEATURES)

# version -> (needs player features in build_features, win/margin features, total features)
MODEL_VERSIONS: dict[str, tuple[bool, list[str], list[str]]] = {
    "v1.0": (False, WIN_FEATURES, TOTAL_FEATURES),
    "v1.1": (True, V11_WIN_FEATURES, V11_TOTAL_FEATURES),
    "v1.1c": (True, V11_WIN_FEATURES, V11_TOTAL_FEATURES),
}
# Inverse L2 strength of the logistic win model per version (default ModelV1.win_c = 1.0).
# v1.1c: C = 0.03, chosen on 2024-25 out-of-sample log loss (calibration study 2026-11-06).
VERSION_WIN_C: dict[str, float] = {"v1.1c": 0.03}


def resolve_version(model_version: str) -> str:
    """The registered spec for a version label: a registered name, optionally with a
    '-suffix' ('v1.1', 'v1.1-test' -> 'v1.1'; 'v1.1c' -> 'v1.1c'); everything else -> 'v1.0'
    (labels like 'v1', 'v1.0' or 'v1.0-test')."""
    head = model_version.split("-")[0]
    return head if head in MODEL_VERSIONS else "v1.0"


def uses_players(model_version: str) -> bool:
    return MODEL_VERSIONS[resolve_version(model_version)][0]


def make_model(model_version: str = "v1.0") -> "ModelV1":
    """An unfitted model with the feature lists of `model_version`."""
    version = resolve_version(model_version)
    _, win, total = MODEL_VERSIONS[version]
    return ModelV1(
        win_c=VERSION_WIN_C.get(version, 1.0),
        win_features=list(win),
        margin_features=list(win),
        total_features=list(total),
    )


PREDICTION_KEYS = (
    "game_id",
    "model",
    "model_version",
    "created_at",
    "p_home_win",
    "pred_home_margin",
    "pred_total",
    "features_json",
)


def _pipe(est) -> Pipeline:
    # keep_empty_features: a column that is all-NaN in training (e.g. no context view) is
    # imputed to 0 instead of dropped, so the column layout stays fixed.
    return make_pipeline(
        SimpleImputer(strategy="mean", keep_empty_features=True), StandardScaler(), est
    )


def _raw_coefs(pipe: Pipeline, names: list[str]) -> dict[str, float]:
    """Coefficients in original feature units (undoing the standardization)."""
    scaler: StandardScaler = pipe.named_steps["standardscaler"]
    est = pipe.steps[-1][1]
    coef = np.ravel(est.coef_)
    scale = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    raw = coef / scale
    out = dict(zip(names, raw.tolist(), strict=True))
    out["intercept"] = float(np.ravel(est.intercept_)[0] - np.sum(raw * scaler.mean_))
    return out


@dataclass
class ModelV1:
    """Fit on completed feature rows (from build_features); predict any rows."""

    win_c: float = 1.0  # inverse L2 strength for the logistic model (on standardized inputs)
    ridge_alpha: float = 10.0
    win_features: list[str] = field(default_factory=lambda: list(WIN_FEATURES))
    margin_features: list[str] = field(default_factory=lambda: list(MARGIN_FEATURES))
    total_features: list[str] = field(default_factory=lambda: list(TOTAL_FEATURES))
    n_train: int = 0

    def with_injuries(self) -> "ModelV1":
        """Optional injury hook: add out_home/out_away to the win and margin models."""
        self.win_features += INJURY_FEATURES
        self.margin_features = self.win_features
        return self

    def columns(self) -> list[str]:
        """Every feature column any of the three models reads (sorted)."""
        return sorted(set(self.win_features + self.margin_features + self.total_features))

    def _check_columns(self, rows: list[dict[str, Any]]) -> None:
        """Train/predict parity guard: a row missing a column the model reads is an error,
        not a silent NaN (which the imputer would quietly fill with the training mean)."""
        need = self.columns()
        for r in rows:
            missing = [c for c in need if c not in r["features"]]
            if missing:
                raise KeyError(f"game {r.get('game_id')} lacks model features {missing}")

    def fit(self, rows: list[dict[str, Any]]) -> "ModelV1":
        rows = [r for r in rows if r["home_margin"] is not None]
        if not rows:
            raise ValueError("no completed games to train on")
        self._check_columns(rows)
        y_win = np.array([r["home_win"] for r in rows])
        y_margin = np.array([r["home_margin"] for r in rows], dtype=float)
        y_total = np.array([r["total"] for r in rows], dtype=float)
        self.win = _pipe(LogisticRegression(C=self.win_c, max_iter=1000))
        if len(set(y_win)) < 2:
            raise ValueError("need both home wins and home losses to train")
        self.win.fit(np.array(feature_matrix(rows, self.win_features)), y_win)
        self.margin = _pipe(Ridge(alpha=self.ridge_alpha))
        self.margin.fit(np.array(feature_matrix(rows, self.margin_features)), y_margin)
        self.total_model = _pipe(Ridge(alpha=self.ridge_alpha))
        self.total_model.fit(np.array(feature_matrix(rows, self.total_features)), y_total)
        self.n_train = len(rows)
        return self

    def predict(self, rows: list[dict[str, Any]]) -> list[dict[str, float]]:
        if not rows:
            return []
        self._check_columns(rows)
        p = self.win.predict_proba(np.array(feature_matrix(rows, self.win_features)))[:, 1]
        m = self.margin.predict(np.array(feature_matrix(rows, self.margin_features)))
        t = self.total_model.predict(np.array(feature_matrix(rows, self.total_features)))
        return [
            {"p_home_win": float(a), "pred_home_margin": float(b), "pred_total": float(c)}
            for a, b, c in zip(p, m, t, strict=True)
        ]

    def coefficients(self) -> dict[str, dict[str, float]]:
        return {
            "win": _raw_coefs(self.win, self.win_features),
            "margin": _raw_coefs(self.margin, self.margin_features),
            "total": _raw_coefs(self.total_model, self.total_features),
        }


def training_rows(rows: list[dict[str, Any]], burn_in_seasons: int = 1) -> list[dict[str, Any]]:
    """Completed rows minus the first `burn_in_seasons` seasons (Elo starts everyone at 1500,
    so the first season's Elo differences are not yet meaningful)."""
    seasons = sorted({r["season"] for r in rows if r["home_margin"] is not None})
    skip = set(seasons[:burn_in_seasons])
    return [r for r in rows if r["home_margin"] is not None and r["season"] not in skip]


def _json_features(feats: dict[str, float]) -> str:
    return json.dumps({k: (None if math.isnan(v) else round(v, 4)) for k, v in feats.items()})


def predict_upcoming(
    con: duckdb.DuckDBPyConnection,
    model_version: str = DEFAULT_VERSION,
    include_injuries: bool = False,
    burn_in_seasons: int = 1,
    injury_override: bool = False,
) -> list[dict[str, Any]]:
    """Train on all completed games, predict every scheduled (state='pre') game.

    `model_version` picks the feature set (see resolve_version) and is stored as the label.
    `injury_override` (v1.1 only, off by default): scheduled games with a pre-tip injury
    snapshot use it instead of "played the previous game" (players.py).

    Returns rows shaped like the `predictions` table (keys in PREDICTION_KEYS). Does not write
    to the database; the caller passes the rows to Store.add_predictions.
    """
    rows = build_features(
        con,
        include_injuries=include_injuries,
        include_players=uses_players(model_version),
        injury_override=injury_override,
    )
    model = make_model(model_version)
    if include_injuries:
        model.with_injuries()
    model.fit(training_rows(rows, burn_in_seasons))
    upcoming = [r for r in rows if r["state"] == "pre"]
    now = datetime.now(UTC)
    out = []
    for r, p in zip(upcoming, model.predict(upcoming), strict=True):
        out.append(
            {
                "game_id": r["game_id"],
                "model": MODEL_NAME,
                "model_version": model_version,
                "created_at": now,
                "p_home_win": p["p_home_win"],
                "pred_home_margin": p["pred_home_margin"],
                "pred_total": p["pred_total"],
                "features_json": _json_features(r["features"]),
            }
        )
    return out
