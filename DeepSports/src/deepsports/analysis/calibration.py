"""Calibration study for the displayed win probabilities (NBA v1.1, college ncaab-v1).

    R=/Volumes/ExFATStorag/DeepSports/reports/calibration
    DB=/Volumes/ExFATStorag/DeepSports/copies/analyst-2026-11-06.duckdb
    # 1. walk-forward out-of-sample predictions for every L2 setting (no scoring)
    uv run python -m deepsports.analysis.calibration oos --league nba --db $DB --out $R/nba_oos.json
    # 2. tuning: diagnose + choose the candidate on pre-holdout games only; freeze it
    uv run python -m deepsports.analysis.calibration tune --league nba --preds $R/nba_oos.json \
        --config models/calibration/nba.json
    # 3. score the locked holdout ONCE (marker next to the config blocks a second run)
    uv run python -m deepsports.analysis.calibration holdout --league nba \
        --preds $R/nba_oos.json --config models/calibration/nba.json --out $R/nba_holdout.json

Protocol: docs/results/2026-11-06-calibration.md (written before the holdout was scored).

Candidates (declared): Platt scaling of the logit (sigmoid(a + b * logit p)), temperature
scaling (a = 0), and a stronger L2 penalty on the logistic win model (C grid below). Platt and
temperature are refit at the start of every monthly block on all out-of-sample predictions of
games that tipped off before the block (expanding window, as production would).

The pure helpers (logistic fits, calibration slope, ECE, buckets, selection table) are
importable and tested; the CLI only loads data and renders the tables.
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from deepsports.analysis.ensemble import _eastern_date, cluster_bootstrap, reliability

C_GRID = (1.0, 0.3, 0.1, 0.03, 0.01)  # inverse L2 strength; 1.0 = the current model
MODES = ("platt", "temperature")
MIN_CAL_GAMES = 300  # fewer earlier OOS games than this: leave the block uncalibrated
EPS = 1e-6
NBA_HOLDOUT_SEASON = 2026  # all of 2025-26
NBA_TUNE_SEASONS = (2025,)  # 2024-25 (2023-24 OOS only feeds the first calibrator fit)
NCAAB_OOS_START = datetime(2023, 12, 1, 5, tzinfo=UTC)
NCAAB_TUNE_START = datetime(2024, 11, 1, 5, tzinfo=UTC)
NCAAB_HOLDOUT_START = datetime(2026, 2, 1, 5, tzinfo=UTC)  # ncaab-v1's holdout
NCAAB_HOLDOUT_END = datetime(2026, 5, 1, 5, tzinfo=UTC)
NCAAB_GATE = 5  # displayed ncaab-v1 games: both D1 with >= 5 games


# ---------- pure math ----------


def logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z) -> np.ndarray:
    return 1 / (1 + np.exp(-np.asarray(z, dtype=float)))


def logistic_fit(x: np.ndarray, y: np.ndarray, iters: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Unpenalized logistic regression by Newton's method. `x` is the full design matrix
    (add a ones column for an intercept). Returns (coefficients, standard errors)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    beta = np.zeros(x.shape[1])
    for _ in range(iters):
        p = sigmoid(x @ beta)
        w = p * (1 - p)
        h = x.T @ (x * w[:, None]) + 1e-9 * np.eye(x.shape[1])
        step = np.linalg.solve(h, x.T @ (y - p))
        beta += step
        if np.max(np.abs(step)) < 1e-10:
            break
    p = sigmoid(x @ beta)
    h = x.T @ (x * (p * (1 - p))[:, None])
    se = np.sqrt(np.diag(np.linalg.inv(h)))
    return beta, se


def calibration_slope(p, y) -> dict[str, float]:
    """Logistic recalibration y ~ a + b * logit(p). Perfect calibration: a = 0, b = 1.
    b < 1 means the probabilities are too extreme (overconfident), b > 1 too timid."""
    z = logit(p)
    beta, se = logistic_fit(np.column_stack([np.ones_like(z), z]), y)
    return {
        "intercept": float(beta[0]),
        "slope": float(beta[1]),
        "se_a": float(se[0]),
        "se_b": float(se[1]),
    }


def ece(p, y, bins: int = 10) -> float:
    return reliability([float(v) for v in p], [int(v) for v in y], bins)["ece"]


def log_loss_vec(p, y) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-15, 1 - 1e-15)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def summary(p, y) -> dict[str, Any]:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return {
        "n": len(p),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(np.mean(log_loss_vec(p, y))),
        "ece": ece(p, y),
        **calibration_slope(p, y),
    }


@dataclass
class Calibrator:
    """sigmoid(a + b * logit p). mode 'platt' fits a and b; 'temperature' fits b (a = 0);
    'identity' leaves p unchanged."""

    mode: str = "identity"
    a: float = 0.0
    b: float = 1.0
    n: int = 0

    def fit(self, p, y) -> "Calibrator":
        z = logit(p)
        self.n = len(z)
        if self.mode == "platt":
            beta, _ = logistic_fit(np.column_stack([np.ones_like(z), z]), y)
            self.a, self.b = float(beta[0]), float(beta[1])
        elif self.mode == "temperature":
            beta, _ = logistic_fit(z[:, None], y)
            self.a, self.b = 0.0, float(beta[0])
        elif self.mode != "identity":
            raise ValueError(f"unknown calibration mode {self.mode!r}")
        return self

    def apply(self, p) -> np.ndarray:
        if self.mode == "identity":
            return np.asarray(p, dtype=float)
        return sigmoid(self.a + self.b * logit(p))

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "a": self.a, "b": self.b, "n": self.n}


def walk_forward_calibrate(
    preds: list[dict[str, Any]], p_key: str, mode: str, out_key: str, min_n: int = MIN_CAL_GAMES
) -> list[dict[str, Any]]:
    """For each block (`block` key, in tip-off order), fit a `mode` calibrator on `p_key` of
    every prediction that tipped off before the block's first game and write the calibrated
    probability to `out_key`. Blocks with fewer than `min_n` earlier games stay uncalibrated.
    Returns the per-block fits (block, n, a, b)."""
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in preds:
        blocks[x["block"]].append(x)
    order = sorted(blocks, key=lambda b: min(x["start_time_utc"] for x in blocks[b]))
    fits = []
    for b in order:
        start = min(x["start_time_utc"] for x in blocks[b])
        prior = [x for x in preds if x["start_time_utc"] < start]
        cal = Calibrator("identity")
        if len(prior) >= min_n:
            cal = Calibrator(mode).fit([x[p_key] for x in prior], [x["home_win"] for x in prior])
        for x in blocks[b]:
            x[out_key] = float(cal.apply([x[p_key]])[0])
        fits.append({"block": b, **cal.to_dict()})
    return fits


BUCKETS = ((0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5))  # |p - 0.5|


def by_confidence(p, y, ref=None) -> list[dict[str, Any]]:
    """Folded to the favorite of `ref` (default `p`; the side `ref` gives >= 50%): per
    |ref - 0.5| bucket, the mean probability `p` gives that side vs how often it won, plus
    log loss and Brier of `p`. Passing the current model as `ref` puts every model on the
    same games in each bucket."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    ref = p if ref is None else np.asarray(ref, dtype=float)
    d = np.abs(ref - 0.5)
    home_fav = ref >= 0.5
    fav = np.where(home_fav, p, 1 - p)
    won = np.where(home_fav, y, 1 - y)
    out = []
    for lo, hi in BUCKETS:
        m = (d >= lo) & ((d < hi) | ((hi == 0.5) & (d <= hi)))
        n = int(m.sum())
        if not n:
            out.append({"lo": lo, "hi": hi, "n": 0})
            continue
        out.append(
            {
                "lo": lo,
                "hi": hi,
                "n": n,
                "pred": float(fav[m].mean()),
                "obs": float(won[m].mean()),
                "log_loss": float(log_loss_vec(p[m], y[m]).mean()),
                "brier": float(np.mean((p[m] - y[m]) ** 2)),
            }
        )
    return out


def picks(
    rows: list[dict[str, Any]], p_key: str, thresholds=(0.0, 0.05, 0.12)
) -> list[dict[str, Any]]:
    """The moneyline 'picks' view: for each game, the side where p_key's probability exceeds
    the closing line's vig-free probability by at least t. Mean model p, market p and the
    actual win rate of the picked side (games with a closing moneyline)."""
    out = []
    for t in thresholds:
        mp, kp, won = [], [], []
        for x in rows:
            q, k = x[p_key], x["market_p_home"]
            if q is None or k is None:
                continue
            for side_p, side_k, side_won in (
                (q, k, x["home_win"]),
                (1 - q, 1 - k, 1 - x["home_win"]),
            ):
                if side_p - side_k >= t and side_p > side_k:
                    mp.append(side_p)
                    kp.append(side_k)
                    won.append(side_won)
        n = len(won)
        out.append(
            {
                "threshold": t,
                "n": n,
                "model_p": float(np.mean(mp)) if n else None,
                "market_p": float(np.mean(kp)) if n else None,
                "actual": float(np.mean(won)) if n else None,
            }
        )
    return out


def encompassing(rows: list[dict[str, Any]], p_key: str) -> dict[str, float]:
    """y ~ a + b_model * logit(p_model) + b_market * logit(p_market). If b_model ~ 0 the model
    adds nothing the closing line doesn't already know, so disagreements with the line are
    noise and selecting them is the winner's curse (no recalibration of p alone can fix it)."""
    r = [x for x in rows if x["market_p_home"] is not None]
    zm = logit([x[p_key] for x in r])
    zk = logit([x["market_p_home"] for x in r])
    y = np.array([x["home_win"] for x in r], dtype=float)
    beta, se = logistic_fit(np.column_stack([np.ones_like(zm), zm, zk]), y)
    return {
        "n": len(r),
        "a": float(beta[0]),
        "b_model": float(beta[1]),
        "se_model": float(se[1]),
        "b_market": float(beta[2]),
        "se_market": float(se[2]),
    }


def winners_curse_sim(rows: list[dict[str, Any]], p_key: str, reps: int = 200, seed: int = 0):
    """What a *perfectly calibrated* model that knows nothing beyond the closing line would show
    on its picks. Truth = the vig-free closing probability; the simulated model's logit is the
    truth's plus noise with the same spread as logit(model) - logit(market) has here, then
    recalibrated on the simulated outcomes so it is calibrated by construction. Returns the
    picks table (t = 0) averaged over reps."""
    r = [x for x in rows if x["market_p_home"] is not None]
    zk = logit([x["market_p_home"] for x in r])
    sd = float(np.std(logit([x[p_key] for x in r]) - zk))
    rng = np.random.default_rng(seed)
    res = defaultdict(list)
    for _ in range(reps):
        y = (rng.random(len(r)) < sigmoid(zk)).astype(float)
        zs = zk + rng.normal(0, sd, len(r))
        cal = Calibrator("platt").fit(sigmoid(zs), y)
        ps = cal.apply(sigmoid(zs))
        sim = [
            {"p": float(a), "market_p_home": float(k), "home_win": int(b)}
            for a, k, b in zip(ps, sigmoid(zk), y, strict=True)
        ]
        row = picks(sim, "p", thresholds=(0.0,))[0]
        for k in ("model_p", "market_p", "actual"):
            res[k].append(row[k])
        res["ece"].append(ece(ps, y))
    return {"noise_sd": sd, **{k: float(np.mean(v)) for k, v in res.items()}}


# ---------- walk-forward OOS predictions (no scoring here) ----------


def _win_pipe(c: float):
    from sklearn.linear_model import LogisticRegression

    from deepsports.analysis.model import _pipe

    return _pipe(LogisticRegression(C=c, max_iter=1000))


def _fit_predict(train, test, feats: list[str], c_grid) -> dict[float, np.ndarray]:
    from deepsports.analysis.features import feature_matrix

    xtr = np.array(feature_matrix(train, feats))
    ytr = np.array([r["home_win"] for r in train])
    xte = np.array(feature_matrix(test, feats))
    out = {}
    for c in c_grid:
        out[c] = _win_pipe(c).fit(xtr, ytr).predict_proba(xte)[:, 1]
    return out


def _pred_row(r: dict[str, Any], block: str, season: int, ps: dict[float, np.ndarray], i: int):
    mk = r["market"]
    row = {
        "game_id": r["game_id"],
        "season": season,
        "block": block,
        "start_time_utc": r["start_time_utc"].astimezone(UTC).isoformat(),
        "day": _eastern_date(r["start_time_utc"]),
        "home_win": int(r["home_win"]),
        "market_p_home": mk.get("p_home"),
    }
    for c, p in ps.items():
        row[f"p_c{c:g}"] = float(p[i])
    return row


def nba_oos(con, c_grid=C_GRID, log=print) -> list[dict[str, Any]]:
    """v1.1's monthly walk-forward (backtest.iter_folds, the folds of the v1.1 backtest),
    with the logistic win model refit for every C. Same features, same training rows."""
    from deepsports.analysis.backtest import iter_folds
    from deepsports.analysis.features import build_features
    from deepsports.analysis.model import V11_WIN_FEATURES

    rows = build_features(con, include_players=True)
    out = []
    for key, train, test in iter_folds(rows, "monthly"):
        assert max(r["start_time_utc"] for r in train) < min(r["start_time_utc"] for r in test)
        ps = _fit_predict(train, test, V11_WIN_FEATURES, c_grid)
        block = f"{key[1]:04d}-{key[2]:02d}"
        out += [_pred_row(r, block, key[0], ps, i) for i, r in enumerate(test)]
        log(f"nba fold {block}: train {len(train)} test {len(test)}")
    return out


def ncaab_oos(con, c_grid=C_GRID, log=print) -> list[dict[str, Any]]:
    """ncaab-v1 as it runs live (`ncaab.live_rows`: Elo restarts each season, per-season
    ridge ratings, all seasons) predicted walk-forward in weekly blocks from NCAAB_OOS_START:
    each block's win model trains on every earlier completed D1 row with rt_n >= 5 (the
    frozen `min_games`). Kept: D1 games before NCAAB_HOLDOUT_END with rt_n >= the gate."""
    from deepsports.analysis import ncaab

    cfg = ncaab.load_config()
    feats, _ = ncaab.feature_lists(cfg["choice"]["win"]["feature_set"])
    mg = int(cfg["choice"]["win"]["min_games"])
    rows = [
        r
        for r in ncaab.live_rows(con, cfg)
        if r["state"] == "post" and r["d1"] and r["start_time_utc"] < NCAAB_HOLDOUT_END
    ]
    out = []
    for b, train, test in ncaab.weekly_folds(rows, NCAAB_OOS_START):
        train = [r for r in train if r["rt_n"] >= mg]
        test = [r for r in test if r["rt_n"] >= NCAAB_GATE]
        if not train or not test:
            continue
        assert max(r["start_time_utc"] for r in train) < min(r["start_time_utc"] for r in test)
        ps = _fit_predict(train, test, feats, c_grid)
        for i, r in enumerate(test):
            t = r["start_time_utc"].astimezone(UTC)
            row = _pred_row(r, f"{t.year:04d}-{t.month:02d}", r["season"], ps, i)
            row["week"] = b.isoformat()
            out.append(row)
        log(f"ncaab week {b:%Y-%m-%d}: train {len(train)} test {len(test)}")
    return out


# ---------- tuning and holdout ----------


def _load(path: Path) -> list[dict[str, Any]]:
    preds = json.loads(Path(path).read_text())
    for x in preds:
        x["start_time_utc"] = datetime.fromisoformat(x["start_time_utc"])
    return sorted(preds, key=lambda x: (x["start_time_utc"], x["game_id"]))


def split(league: str, preds: list[dict[str, Any]]):
    """(pre-holdout predictions, tuning-window predictions, holdout predictions)."""
    if league == "nba":
        pre = [x for x in preds if x["season"] < NBA_HOLDOUT_SEASON]
        tune = [x for x in pre if x["season"] in NBA_TUNE_SEASONS]
        hold = [x for x in preds if x["season"] == NBA_HOLDOUT_SEASON]
    else:
        pre = [x for x in preds if x["start_time_utc"] < NCAAB_HOLDOUT_START]
        tune = [x for x in pre if x["start_time_utc"] >= NCAAB_TUNE_START]
        hold = [x for x in preds if NCAAB_HOLDOUT_START <= x["start_time_utc"] < NCAAB_HOLDOUT_END]
    return pre, tune, hold


def _y(rows):
    return np.array([x["home_win"] for x in rows], dtype=float)


def diagnose(rows: list[dict[str, Any]], keys: dict[str, str]) -> dict[str, Any]:
    """Every diagnostic for each label -> probability key, on `rows`."""
    y = _y(rows)
    mk = [x for x in rows if x["market_p_home"] is not None]
    out: dict[str, Any] = {"n": len(rows), "n_market": len(mk), "models": {}}
    ref = np.array([x[keys["current"]] for x in rows])
    for lab, k in keys.items():
        p = np.array([x[k] for x in rows])
        out["models"][lab] = {
            **summary(p, y),
            "reliability": reliability(list(p), list(y.astype(int)))["bins"],
            "by_confidence": by_confidence(p, y, ref),
            "picks": picks(rows, k),
        }
    if mk:
        pm = np.array([x["market_p_home"] for x in mk])
        out["market"] = {
            **summary(pm, _y(mk)),
            "by_confidence": by_confidence(pm, _y(mk)),
        }
        out["market_subset"] = {lab: summary([x[k] for x in mk], _y(mk)) for lab, k in keys.items()}
        out["encompassing"] = {lab: encompassing(rows, k) for lab, k in keys.items()}
    return out


def calibrate_all(preds: list[dict[str, Any]], base: str = "p_c1") -> dict[str, list]:
    """Walk-forward Platt and temperature on `base` over all of `preds` (each block fit only on
    earlier predictions; pass only the rows the study may see)."""
    return {m: walk_forward_calibrate(preds, base, m, f"p_{m}") for m in MODES}


def tune(league: str, preds: list[dict[str, Any]], log=print) -> dict[str, Any]:
    pre, tune_rows, _ = split(league, preds)
    fits = calibrate_all(pre)  # fit on pre-holdout predictions only
    y = _y(tune_rows)
    ll = {}
    for c in C_GRID:
        ll[f"l2_c{c:g}"] = float(np.mean(log_loss_vec([x[f"p_c{c:g}"] for x in tune_rows], y)))
    for m in MODES:
        ll[m] = float(np.mean(log_loss_vec([x[f"p_{m}"] for x in tune_rows], y)))
    best_c = min(C_GRID, key=lambda c: ll[f"l2_c{c:g}"])
    cands = {
        "platt": ll["platt"],
        "temperature": ll["temperature"],
        f"l2_c{best_c:g}": ll[f"l2_c{best_c:g}"],
    }
    # ties go to the simpler candidate (temperature, then L2, then Platt)
    pref = {"temperature": 0, f"l2_c{best_c:g}": 1, "platt": 2}
    choice = min(cands, key=lambda k: (round(cands[k], 6), pref[k]))
    for k, v in sorted(ll.items(), key=lambda kv: kv[1]):
        log(f"tuning log loss {k}: {v:.5f}")
    keys = {"current": "p_c1", "platt": "p_platt", "temperature": "p_temperature"}
    if best_c != 1.0:
        keys[f"l2_c{best_c:g}"] = f"p_c{best_c:g}"
    return {
        "league": league,
        "n_pre": len(pre),
        "n_tune": len(tune_rows),
        "tune_log_loss": ll,
        "best_c": best_c,
        "choice": choice,
        "fits": {m: fits[m][-3:] for m in MODES},
        "diagnostics": diagnose(tune_rows, keys),
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _key(choice: str) -> str:
    return f"p_{choice[3:]}" if choice.startswith("l2_") else f"p_{choice}"


def holdout(league: str, preds: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """Score the frozen choice on the holdout. Calibrators refit monthly on every earlier OOS
    prediction (pre-holdout plus earlier holdout months), as production would."""
    pre, _, hold = split(league, preds)
    seen = pre + hold
    calibrate_all(seen)
    choice = cfg["choice"]
    ck = _key(choice)
    keys = {"current": "p_c1", "platt": "p_platt", "temperature": "p_temperature"}
    keys[f"l2_c{cfg['best_c']:g}"] = f"p_c{cfg['best_c']:g}"
    rep = diagnose(hold, keys)
    y = _y(hold)
    cur = log_loss_vec([x["p_c1"] for x in hold], y)
    diffs = {}
    for lab, k in keys.items():
        if lab == "current":
            continue
        p = np.array([x[k] for x in hold])
        diffs[lab] = {
            "log_loss": cluster_bootstrap(hold, log_loss_vec(p, y) - cur),
            "brier": cluster_bootstrap(
                hold, (p - y) ** 2 - (np.array([x["p_c1"] for x in hold]) - y) ** 2
            ),
            "ece_diff": ece_bootstrap(hold, k, "p_c1"),
        }
    rep["diffs"] = diffs
    rep["choice"] = choice
    rep["choice_key"] = ck
    rep["decision"] = ship_decision(rep, choice)
    mk = [x for x in hold if x["market_p_home"] is not None]
    rep["winners_curse_sim"] = winners_curse_sim(mk, "p_c1") if mk else None
    rep["days"] = len({x["day"] for x in hold})
    return rep


def ece_bootstrap(rows, key: str, base: str, reps: int = 1000, seed: int = 1) -> dict[str, float]:
    """ECE(key) - ECE(base) with a day-clustered 95% percentile CI (information only)."""
    by_day: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_day[r["day"]].append(i)
    days = list(by_day.values())
    p, q, y = (np.array([r[k] for r in rows], dtype=float) for k in (key, base, "home_win"))
    rng = np.random.default_rng(seed)
    st = np.empty(reps)
    for b in range(reps):
        ix = np.concatenate([days[j] for j in rng.integers(0, len(days), len(days))])
        st[b] = ece(p[ix], y[ix]) - ece(q[ix], y[ix])
    return {
        "mean": ece(p, y) - ece(q, y),
        "lo": float(np.percentile(st, 2.5)),
        "hi": float(np.percentile(st, 97.5)),
    }


def ship_decision(rep: dict[str, Any], choice: str) -> dict[str, Any]:
    """Declared rule: ship if the holdout log loss difference (choice - current) has a 95%
    day-clustered CI entirely below 0, OR ECE is lower and the log loss CI's upper end is
    <= +0.001. Otherwise: calibrated enough, no change."""
    d = rep["diffs"][choice]["log_loss"]
    e_new = rep["models"][choice]["ece"]
    e_cur = rep["models"]["current"]["ece"]
    by_ll = d["hi"] < 0
    by_ece = e_new < e_cur and d["hi"] <= 0.001
    return {"ship": bool(by_ll or by_ece), "by_log_loss": bool(by_ll), "by_ece": bool(by_ece)}


# ---------- rendering ----------


def _f(x, d=4):
    return "-" if x is None else f"{x:.{d}f}"


def _pc(x):
    return "-" if x is None else f"{100 * x:.1f}%"


def render(rep: dict[str, Any], title: str) -> str:
    """Markdown tables for a diagnose() result (plus holdout diffs when present)."""
    o = [f"### {title}", f"{rep['n']} games ({rep['n_market']} with a closing moneyline)."]
    o += [
        "",
        "| model | Brier | log loss | ECE | slope b (SE) | intercept a (SE) |",
        "|---|---|---|---|---|---|",
    ]
    for lab, m in rep["models"].items():
        o.append(
            f"| {lab} | {_f(m['brier'])} | {_f(m['log_loss'])} | {_f(m['ece'], 3)} | "
            f"{m['slope']:.3f} ({m['se_b']:.3f}) | {m['intercept']:+.3f} ({m['se_a']:.3f}) |"
        )
    if "market" in rep:
        m = rep["market"]
        o.append(
            f"| closing line (n {rep['n_market']}) | {_f(m['brier'])} | {_f(m['log_loss'])} | "
            f"{_f(m['ece'], 3)} | {m['slope']:.3f} ({m['se_b']:.3f}) | "
            f"{m['intercept']:+.3f} ({m['se_a']:.3f}) |"
        )
        o += [
            "",
            "Same games as the closing line:",
            "",
            "| model | Brier | log loss | ECE |",
            "|---|---|---|---|",
        ]
        for lab, m in rep["market_subset"].items():
            o.append(f"| {lab} | {_f(m['brier'])} | {_f(m['log_loss'])} | {_f(m['ece'], 3)} |")
        k = rep["market"]
        o.append(f"| closing line | {_f(k['brier'])} | {_f(k['log_loss'])} | {_f(k['ece'], 3)} |")
    if "diffs" in rep:
        o += [
            "",
            f"Paired differences vs current (95% day-clustered bootstrap, {rep['days']} days; "
            "negative = better):",
            "",
            "| candidate | log loss | Brier | ECE (info) |",
            "|---|---|---|---|",
        ]
        for lab, d in rep["diffs"].items():
            ll, br, ec = d["log_loss"], d["brier"], d["ece_diff"]
            o.append(
                f"| {lab}{' (declared choice)' if lab == rep['choice'] else ''} | "
                f"{ll['mean']:+.4f} ({ll['lo']:+.4f} to {ll['hi']:+.4f}) | "
                f"{br['mean']:+.4f} ({br['lo']:+.4f} to {br['hi']:+.4f}) | "
                f"{ec['mean']:+.3f} ({ec['lo']:+.3f} to {ec['hi']:+.3f}) |"
            )
    cur = rep["models"]["current"]
    o += ["", "Reliability (current model; equal-width bins of P(home win)):", ""]
    o += ["| bin | games | model avg | home won |", "|---|---|---|---|"]
    for b in cur["reliability"]:
        if b["n"]:
            o.append(
                f"| {b['lo']:.1f}-{b['hi']:.1f} | {b['n']} | {_pc(b['pred'])} | {_pc(b['obs'])} |"
            )
    o += [
        "",
        "By confidence: games bucketed by the current model's |p - 0.5|, folded to its favorite; "
        "each model's mean probability for that side vs how often it won:",
        "",
    ]
    labs = list(rep["models"])
    o.append(
        "| |p - 0.5| | games | "
        + " | ".join(f"{lab} pred" for lab in labs)
        + " | won | "
        + " | ".join(f"{lab} LL" for lab in labs)
        + " |"
    )
    o.append("|" + "---|" * (3 + 2 * len(labs)))
    for i, b in enumerate(cur["by_confidence"]):
        if not b["n"]:
            continue
        preds = " | ".join(_pc(rep["models"][lab]["by_confidence"][i]["pred"]) for lab in labs)
        lls = " | ".join(_f(rep["models"][lab]["by_confidence"][i]["log_loss"]) for lab in labs)
        o.append(f"| {b['lo']:.1f}-{b['hi']:.1f} | {b['n']} | {preds} | {_pc(b['obs'])} | {lls} |")
    if "encompassing" in rep:
        o += [
            "",
            "Moneyline picks (side where the model's p beats the vig-free close by >= t):",
            "",
        ]
        o += ["| model | t | picks | model p | market p | actual |", "|---|---|---|---|---|---|"]
        for lab in labs:
            for r in rep["models"][lab]["picks"]:
                o.append(
                    f"| {lab} | {r['threshold']:.2f} | {r['n']} | {_pc(r['model_p'])} | "
                    f"{_pc(r['market_p'])} | {_pc(r['actual'])} |"
                )
        o += [
            "",
            "Encompassing regression y ~ a + b_model logit(p_model) + b_market logit(p_close):",
            "",
        ]
        o += ["| model | n | b_model (SE) | b_market (SE) |", "|---|---|---|---|"]
        for lab, e in rep["encompassing"].items():
            o.append(
                f"| {lab} | {e['n']} | {e['b_model']:.3f} ({e['se_model']:.3f}) | "
                f"{e['b_market']:.3f} ({e['se_market']:.3f}) |"
            )
    if rep.get("winners_curse_sim"):
        s = rep["winners_curse_sim"]
        o += [
            "",
            "Winner's-curse simulation (perfectly calibrated model with no information beyond "
            f"the close, noise sd {s['noise_sd']:.3f} in logit units, 200 draws): picks at t = 0 "
            f"show model p {_pc(s['model_p'])}, market p {_pc(s['market_p'])}, actual "
            f"{_pc(s['actual'])}; its ECE {s['ece']:.3f}.",
        ]
    return "\n".join(o) + "\n"


def _marker(cfg_path: Path) -> Path:
    return cfg_path.with_suffix(".holdout-scored")


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["oos", "tune", "holdout", "report"])
    ap.add_argument("--league", choices=["nba", "ncaab"], required=True)
    ap.add_argument("--db", type=Path)
    ap.add_argument("--preds", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--config", type=Path)
    a = ap.parse_args(argv)
    if a.step == "oos":
        import duckdb

        con = duckdb.connect(str(a.db), read_only=True)
        preds = (nba_oos if a.league == "nba" else ncaab_oos)(con)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(preds))
        print(f"wrote {len(preds)} predictions to {a.out}")
        return 0
    preds = _load(a.preds)
    if a.step == "tune":
        cfg = tune(a.league, preds)
        cfg["preds_sha256"] = _sha(a.preds)
        a.config.parent.mkdir(parents=True, exist_ok=True)
        a.config.write_text(json.dumps(cfg, indent=1))
        print(render(cfg["diagnostics"], f"{a.league} tuning window"))
        print(f"choice: {cfg['choice']} (best C {cfg['best_c']}); frozen to {a.config}")
        return 0
    cfg = json.loads(a.config.read_text())
    if a.step == "holdout":
        mk = _marker(a.config)
        if mk.exists():
            print(f"holdout already scored ({mk}); use the report step", file=sys.stderr)
            return 1
        if _sha(a.preds) != cfg["preds_sha256"]:
            print("predictions file changed since tuning", file=sys.stderr)
            return 1
        mk.write_text(f"{_sha(a.config)} {datetime.now(UTC).isoformat(timespec='seconds')}\n")
        rep = holdout(a.league, preds, cfg)
        a.out.write_text(json.dumps(rep, indent=1, default=str))
    else:
        rep = json.loads(a.out.read_text())
    print(render(rep, f"{a.league} holdout"))
    print("decision:", rep["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
