"""College (NCAAB) v1 with a cross-season prior: tuning, a locked holdout, and the report.

    W=/Volumes/ExFATStorag/DeepSports/work
    # 1. tune on early 2024-25 (prior from 2023-24); freeze the config
    uv run python -m deepsports.analysis.ncaab_prior tune --db $W/COPY.duckdb --config CFG.json
    # 2. score the locked holdout ONCE: early 2025-26 (prior from 2024-25)
    uv run python -m deepsports.analysis.ncaab_prior holdout --db $W/COPY.duckdb --config CFG.json \
        --preds $W/ncaab_prior_holdout_preds.json
    # re-render saved holdout predictions (no refitting)
    uv run python -m deepsports.analysis.ncaab_prior report --config CFG.json --preds P.json

Protocol: docs/DECISIONS.md, 2026-11-06 ("College cross-season prior"). Two pieces of prior:
- **Elo carry-over** (`elo_ratings(carry_over=c)`): a team's rating is regressed toward its start
  value by (1 - c) at its first game of a new season.
- **Ridge prior** (`PriorRidgeRatings`): each team's offense/defense is shrunk toward rho x last
  season's final rating with weight `lam_prior` games (instead of toward 0 with weight lam). The
  prior's share of a rating is lam_prior / (lam_prior + games), so it fades as games come in.
The college v1 linear models (frozen `models/ncaab_v1/config.json`) are fit on the prior features
and compared with today's no-prior behavior, Elo and the closing line, by games-played bucket.

Leakage: last season's ratings come from games that finished before this season started; within
the season every feature uses only games finished (start + FINISH_LAG) before tip-off. Rows at
or after a phase's cutoff are dropped before anything is fit. Closing lines are benchmark only.
"""

import argparse
import copy
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from deepsports import config
from deepsports.analysis.elo import EloResult, elo_ratings
from deepsports.analysis.ensemble import _eastern_date, _ll, cluster_bootstrap, reliability
from deepsports.analysis.features import build_features
from deepsports.analysis.ncaab import (
    LEAGUE,
    POOL_RATING,
    SEASON_TYPES,
    RidgeRatings,
    _elo_margin_fit,
    _metrics,
    _per_game,
    _season_games,
    betting,
    listed_teams,
    make_model,
    market_subset,
    ridge_features,
    weekly_folds,
)

V1_CONFIG = config.ROOT / "models" / "ncaab_v1" / "config.json"
CONFIG_PATH = config.ROOT / "models" / "ncaab_prior" / "config.json"

TUNE_START = datetime(2024, 11, 1, 5, tzinfo=UTC)  # 00:00 US/Eastern
TUNE_END = datetime(2025, 2, 1, 5, tzinfo=UTC)
HOLDOUT_START = datetime(2025, 11, 1, 5, tzinfo=UTC)
HOLDOUT_END = datetime(2026, 2, 1, 5, tzinfo=UTC)

CARRY_GRID = (0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9)
# Round 1 was K 30-60; its best (K 60) sat on the edge, so round 2 widened K (tuning data only).
K_GRID = (30.0, 40.0, 60.0, 80.0, 100.0)
RHO_GRID = (0.4, 0.55, 0.7, 0.85, 1.0)
LAM_PRIOR_GRID = (2.0, 4.0, 8.0, 16.0, 32.0)
TRAIN_MODES = ("v1", "prior_rows")  # v1: rt_n >= min_games; prior_rows: + every row with a prior

BUCKETS = ("0", "1-2", "3-4", "5-9", "10+")
BUCKET_FLOOR = {"0": 0, "1-2": 1, "3-4": 3, "5-9": 5, "10+": 10}
ECE_MAX = 0.05
TARGETS = ("win", "margin", "total")
PRE = {"win": "p", "margin": "m", "total": "t"}
KEY = {"win": "p_home_win", "margin": "pred_home_margin", "total": "pred_total"}
METRIC = {"win": "log_loss", "margin": "margin_mae", "total": "total_mae"}


def bucket(n: float) -> str:
    """Games-played bucket of rt_n (the lower of the two teams' completed games this season)."""
    if n < 1:
        return "0"
    if n < 3:
        return "1-2"
    if n < 5:
        return "3-4"
    if n < 10:
        return "5-9"
    return "10+"


# ---------- ridge ratings with last season as the prior ----------


@dataclass
class SeasonRatings:
    """A season's final ridge ratings: league mean, home edge, offense and defense per key."""

    mu: float
    h: float
    off: dict[str, float] = field(default_factory=dict)
    dfn: dict[str, float] = field(default_factory=dict)


def final_ratings(games: list[tuple], d1: set[str], lam: float) -> SeasonRatings:
    """Ridge ratings fit on every completed game in `games` (a finished season)."""

    def key(t: str) -> str:
        return t if t in d1 else "unlisted"

    done = [g for g in games if g[4] is not None and g[5] is not None]
    rr = RidgeRatings([key(t) for g in done for t in (g[2], g[3])], lam)
    for _, _, home, away, hs, as_, neutral in done:
        rr.add(key(home), key(away), hs, as_, bool(neutral))
    th = rr.theta()
    off = {t: float(th[2 + i]) for t, i in rr.idx.items()}
    dfn = {t: float(th[2 + rr.nt + i]) for t, i in rr.idx.items()}
    return SeasonRatings(mu=float(th[0]), h=float(th[1]), off=off, dfn=dfn)


class PriorRidgeRatings(RidgeRatings):
    """RidgeRatings shrunk toward last season instead of toward 0.

    A team rated last season: off/def penalty `lam_prior` toward rho x last season's value.
    A team that wasn't: v1's `lam` toward 0. Mean and home edge are centered on last season's
    values with the base class's negligible weight, so they only matter before the first game.
    With no prior this is exactly RidgeRatings(teams, lam)."""

    def __init__(
        self,
        teams: list[str],
        lam: float,
        prior: SeasonRatings | None = None,
        rho: float = 1.0,
        lam_prior: float = 1.0,
    ):
        super().__init__(teams, lam)
        self.center = np.zeros_like(self.pen)
        self.has_prior = prior is not None
        if prior is None:
            return
        self.center[0], self.center[1] = prior.mu, prior.h
        for t, i in self.idx.items():
            if t in prior.off:
                for j, v in ((2 + i, prior.off[t]), (2 + self.nt + i, prior.dfn[t])):
                    self.pen[j] = float(lam_prior)
                    self.center[j] = rho * v

    def empty(self) -> bool:
        return self.n_total == 0 and not self.has_prior

    def theta(self) -> np.ndarray:
        if self._theta is None:
            self._theta = np.linalg.solve(
                self.ata + np.diag(self.pen), self.atb + self.pen * self.center
            )
        return self._theta


# ---------- rows ----------


def _v1_config(path: Path = V1_CONFIG) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def base_rows(con: duckdb.DuckDBPyConnection, v1: dict[str, Any], cutoff: datetime) -> list:
    """Completed college feature rows of every season tipping off before `cutoff`, built as
    today's live path does (Elo with v1's K / home edge and carry_over 0, players included).
    Ratings are attached per arm (with_ridge). Adds d1, day, has_prior (an earlier season
    exists in the warehouse)."""
    d1 = listed_teams(con)
    rows = build_features(
        con,
        league=LEAGUE,
        season_types=SEASON_TYPES,
        include_players=True,
        carry_over=0.0,
        elo_params={
            "pool_unlisted": True,
            "pool_rating": float(v1.get("pool_rating", POOL_RATING)),
            **v1["elo"],
        },
    )
    rows = [r for r in rows if r["state"] == "post" and r["start_time_utc"] < cutoff]
    first = min(r["season"] for r in rows)
    for r in rows:
        r["d1"] = r["home_team_id"] in d1 and r["away_team_id"] in d1
        r["day"] = _eastern_date(r["start_time_utc"])
        r["conference"] = None
        r["has_prior"] = r["season"] > first
    return rows


def run_elo(con: duckdb.DuckDBPyConnection, k: float, home_adv: float, carry: float) -> EloResult:
    return elo_ratings(
        con,
        k=k,
        home_adv=home_adv,
        carry_over=carry,
        league=LEAGUE,
        season_types=SEASON_TYPES,
        pool_unlisted=True,
        pool_rating=POOL_RATING,
    )


def with_elo(rows: list[dict[str, Any]], elo: EloResult) -> list[dict[str, Any]]:
    """Copies of `rows` with elo_diff / elo_p_home from another Elo run (same games)."""
    pre = {g["game_id"]: g for g in elo.games}
    out = []
    for r in rows:
        e = pre[r["game_id"]]
        x = {**r, "features": dict(r["features"])}
        x["features"]["elo_diff"] = e["home_elo_pre"] - e["away_elo_pre"]
        x["elo_p_home"] = e["p_home"]
        out.append(x)
    return out


def season_ridge(
    con: duckdb.DuckDBPyConnection,
    season: int,
    d1: set[str],
    lam: float,
    prior: dict[str, float] | None,
    cutoff: datetime | None,
    include_scheduled: bool = False,
) -> dict[str, dict[str, float]]:
    """Ridge features for one season's completed games before `cutoff` (None: no cutoff).
    With `prior` ({rho, lam_prior}) and a previous season in the warehouse, ratings start from
    last season's final ratings; otherwise v1's per-season ratings. `include_scheduled` adds
    the season's scheduled games (live predictions; they never enter a fit)."""
    games = [
        g
        for g in _season_games(con, season, include_scheduled=include_scheduled)
        if cutoff is None or g[1] < cutoff
    ]
    if prior is None:
        return ridge_features(games, d1, lam)
    prev = _season_games(con, season - 1)
    last = final_ratings(prev, d1, lam) if prev else None
    rho, lp = float(prior["rho"]), float(prior["lam_prior"])
    return ridge_features(
        games, d1, lam, make=lambda teams: PriorRidgeRatings(teams, lam, last, rho, lp)
    )


def with_ridge(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict[str, Any]],
    lam: float,
    prior: dict[str, float] | None,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """Attach rt_margin / rt_total / rt_n (in place) for every season in `rows`."""
    d1 = listed_teams(con)
    rt: dict[str, dict[str, float]] = {}
    for season in sorted({r["season"] for r in rows}):
        rt.update(season_ridge(con, season, d1, lam, prior, cutoff))
    for r in rows:
        x = rt[r["game_id"]]
        r["features"]["rt_margin"] = x["rt_margin"]
        r["features"]["rt_total"] = x["rt_total"]
        r["rt_n"] = x["rt_n"]
    return rows


# ---------- tuning grids (raw Elo / raw ratings) ----------


def _d1_window(games, d1, start, end):
    return [
        g
        for g in games
        if start <= g["start_time_utc"] < end
        and g["home_team_id"] in d1
        and g["away_team_id"] in d1
    ]


def elo_grid(
    con: duckdb.DuckDBPyConnection, home_adv: float, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """Raw Elo log loss on D1-vs-D1 games in [start, end) for each (K, carry-over)."""
    d1 = listed_teams(con)
    out = []
    for k in K_GRID:
        for c in CARRY_GRID:
            g = _d1_window(run_elo(con, k, home_adv, c).games, d1, start, end)
            p = np.array([x["p_home"] for x in g])
            y = np.array([x["home_win"] for x in g], dtype=float)
            out.append({"k": k, "carry": c, "n": len(g), "log_loss": float(np.mean(_ll(p, y)))})
    return out


def ridge_grid(
    con: duckdb.DuckDBPyConnection, season: int, lam: float, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """Raw prior-rating margin / total MAE on D1-vs-D1 games of `season` in [start, end)."""
    d1 = listed_teams(con)
    games = [g for g in _season_games(con, season) if g[1] < end]
    test = [g for g in games if start <= g[1] < end and g[2] in d1 and g[3] in d1]
    ym = np.array([g[4] - g[5] for g in test], dtype=float)
    yt = np.array([g[4] + g[5] for g in test], dtype=float)
    out = []
    for rho in RHO_GRID:
        for lp in LAM_PRIOR_GRID:
            rt = season_ridge(con, season, d1, lam, {"rho": rho, "lam_prior": lp}, end)
            m = np.array([rt[g[0]]["rt_margin"] for g in test])
            t = np.array([rt[g[0]]["rt_total"] for g in test])
            out.append(
                {
                    "rho": rho,
                    "lam_prior": lp,
                    "n": len(test),
                    "margin_mae": float(np.mean(np.abs(m - ym))),
                    "total_mae": float(np.mean(np.abs(t - yt))),
                }
            )
    return out


# ---------- walk-forward over arms ----------


def train_ok(r: dict[str, Any], min_games: int, mode: str) -> bool:
    """Training-row filter: v1's rt_n >= min_games; 'prior_rows' also keeps every row of a
    season that has a prior (its early rows carry last season's information)."""
    if mode not in TRAIN_MODES:
        raise ValueError(mode)
    return r["rt_n"] >= min_games or (mode == "prior_rows" and bool(r["has_prior"]))


def walk_forward_arms(
    arms: dict[str, list[dict[str, Any]]],
    variants: dict[str, tuple[str, dict[str, dict[str, Any]]]],
    home_adv: float,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Weekly walk-forward over the same games seen through each arm's features.

    `arms`: arm name -> rows (same game_ids). `variants`: name -> (arm, {target:
    {feature_set, min_games, mode}}); writes p_/m_/t_<name>. Per arm also: p_elo_/m_elo_<arm>
    (Elo and its least-squares margin line on the fold's training rows), m_rt_/t_rt_<arm> (raw
    ratings; NaN filled with 0 margin / the training mean total)."""
    names = list(arms)
    by_id = {a: {r["game_id"]: r for r in arms[a]} for a in names}
    base = arms[names[0]]
    out = []
    for _, train0, test0 in weekly_folds(base, start, end):
        assert max(r["start_time_utc"] for r in train0) < min(r["start_time_utc"] for r in test0)
        tr_ids = [r["game_id"] for r in train0]
        te_ids = [r["game_id"] for r in test0]
        train = {a: [by_id[a][g] for g in tr_ids] for a in names}
        test = {a: [by_id[a][g] for g in te_ids] for a in names}
        fitted: dict[tuple, list[dict[str, float]]] = {}
        for arm, choice in variants.values():
            for c in choice.values():
                fk = (arm, c["feature_set"], int(c["min_games"]), c["mode"])
                if fk not in fitted:
                    tr = [r for r in train[arm] if train_ok(r, int(c["min_games"]), c["mode"])]
                    fitted[fk] = make_model(c["feature_set"]).fit(tr).predict(test[arm])
        elo_m = {a: _elo_margin_fit(train[a], home_adv) for a in names}
        mean_total = float(np.mean([r["total"] for r in train0]))
        for i, r in enumerate(test0):
            mk = r["market"]
            row = {
                "game_id": r["game_id"],
                "start_time_utc": r["start_time_utc"].isoformat(),
                "day": r["day"],
                "season": r["season"],
                "season_type": r["season_type"],
                "neutral_site": r["neutral_site"],
                "rt_n": r["rt_n"],
                "bucket": bucket(r["rt_n"]),
                "home_win": r["home_win"],
                "home_margin": r["home_margin"],
                "total": r["total"],
                "market_p_home": mk.get("p_home"),
                "spread_home": mk.get("spread_home"),
                "over_under": mk.get("over_under"),
            }
            for a in names:
                x = test[a][i]
                row[f"p_elo_{a}"] = x["elo_p_home"]
                row[f"m_elo_{a}"] = elo_m[a](x)
                m, t = x["features"]["rt_margin"], x["features"]["rt_total"]
                row[f"m_rt_{a}"] = 0.0 if math.isnan(m) else m
                row[f"t_rt_{a}"] = mean_total if math.isnan(t) else t
            for name, (arm, choice) in variants.items():
                for tgt, c in choice.items():
                    fk = (arm, c["feature_set"], int(c["min_games"]), c["mode"])
                    row[f"{PRE[tgt]}_{name}"] = fitted[fk][i][KEY[tgt]]
            out.append(row)
    return out


def _choice(v1: dict[str, Any], mode: str | dict[str, str]) -> dict[str, dict[str, Any]]:
    modes = mode if isinstance(mode, dict) else {t: mode for t in TARGETS}
    return {
        t: {
            "feature_set": v1["choice"][t]["feature_set"],
            "min_games": int(v1["choice"][t]["min_games"]),
            "mode": modes[t],
        }
        for t in TARGETS
    }


def build_arms(
    con: duckdb.DuckDBPyConnection,
    v1: dict[str, Any],
    prior: dict[str, Any],
    cutoff: datetime,
) -> dict[str, list[dict[str, Any]]]:
    """'noprior' (today's live features) and 'prior' (carry-over Elo + ridge prior) rows."""
    rows = base_rows(con, v1, cutoff)
    home = float(v1["elo"]["home_adv"])
    lam = float(v1["ridge_lambda"])
    noprior = with_ridge(con, copy.deepcopy(rows), lam, None, cutoff)
    elo_p = run_elo(con, float(prior["elo"]["k"]), home, float(prior["elo"]["carry"]))
    pri = with_ridge(con, with_elo(rows, elo_p), lam, prior["ridge"], cutoff)
    return {"noprior": noprior, "prior": pri}


# ---------- tuning ----------


def tune(con: duckdb.DuckDBPyConnection, v1: dict[str, Any], log=print) -> dict[str, Any]:
    """Tune the prior on 2024-25 Nov-Jan (rows at or after TUNE_END dropped first)."""
    home = float(v1["elo"]["home_adv"])
    lam = float(v1["ridge_lambda"])
    etab = elo_grid(con, home, TUNE_START, TUNE_END)
    be = min(etab, key=lambda r: r["log_loss"])
    log(f"elo best K={be['k']} carry={be['carry']} LL={be['log_loss']:.4f}")
    season = 2025
    rtab = ridge_grid(con, season, lam, TUNE_START, TUNE_END)
    br = min(rtab, key=lambda r: r["margin_mae"])
    log(f"ridge prior best rho={br['rho']} lam_prior={br['lam_prior']} MAE={br['margin_mae']:.3f}")
    prior = {
        "elo": {"k": be["k"], "carry": be["carry"], "home_adv": home},
        "ridge": {"rho": br["rho"], "lam_prior": br["lam_prior"]},
    }
    arms = build_arms(con, v1, prior, TUNE_END)
    variants = {"noprior": ("noprior", _choice(v1, "v1"))}
    for mode in TRAIN_MODES:
        variants[f"prior_{mode}"] = ("prior", _choice(v1, mode))
    preds = walk_forward_arms(arms, variants, home, TUNE_START, TUNE_END)
    preds = [x for x in preds if x["season"] == season]
    mk = market_subset(preds)
    mode_tab = []
    for mode in TRAIN_MODES:
        s = _metrics(mk, f"p_prior_{mode}", f"m_prior_{mode}", f"t_prior_{mode}")
        mode_tab.append({"mode": mode, "n": len(mk), **s})
        log(f"train mode {mode}: {s}")
    chosen = {t: min(mode_tab, key=lambda r: r[METRIC[t]])["mode"] for t in TARGETS}  # per target
    log(f"chosen train modes {chosen}")
    for x in preds:
        for t in TARGETS:
            x[f"{PRE[t]}_prior"] = x[f"{PRE[t]}_prior_{chosen[t]}"]
    rep = report(preds)
    return {
        "league": LEAGUE,
        "v1_config": str(V1_CONFIG.relative_to(config.ROOT)),
        "tune_start": TUNE_START.isoformat(),
        "tune_end": TUNE_END.isoformat(),
        "holdout_start": HOLDOUT_START.isoformat(),
        "holdout_end": HOLDOUT_END.isoformat(),
        "prior": prior,
        "choice": _choice(v1, chosen),
        "tuning": {
            "elo": etab,
            "ridge": rtab,
            "train_modes": mode_tab,
            "n_games": len(preds),
            "n_market": len(mk),
            "report": rep,
        },
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def holdout_predictions(
    con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], v1: dict[str, Any]
) -> list[dict[str, Any]]:
    start = datetime.fromisoformat(cfg["holdout_start"])
    end = datetime.fromisoformat(cfg["holdout_end"])
    arms = build_arms(con, v1, cfg["prior"], end)
    variants = {
        "noprior": ("noprior", _choice(v1, "v1")),
        "prior": ("prior", cfg["choice"]),
    }
    preds = walk_forward_arms(arms, variants, float(v1["elo"]["home_adv"]), start, end)
    return [x for x in preds if start <= datetime.fromisoformat(x["start_time_utc"]) < end]


# ---------- daily use (shipped 2026-11-06: ncaab-v1p, and behind ncaab-v1-early) ----------


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """The frozen prior config (never edited; the holdout marker sits next to it)."""
    return json.loads(Path(path).read_text())


def live_rows(
    con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], v1: dict[str, Any]
) -> list[dict[str, Any]]:
    """Feature rows for every completed and scheduled college game (all seasons), seen through
    the frozen prior exactly as the study's 'prior' arm: Elo with carry-over (`cfg.prior.elo`),
    ridge ratings that start from last season's final ratings (`cfg.prior.ridge`, v1's lambda
    for teams without a prior). Adds `rt_n`, `d1` and `has_prior` (an earlier completed season
    exists; drives the `prior_rows` training filter). Scheduled rows are rated only from
    games finished before their tip-off and never enter a fit. Read-only."""
    d1 = listed_teams(con)
    pe = cfg["prior"]["elo"]
    rows = build_features(
        con,
        league=LEAGUE,
        season_types=SEASON_TYPES,
        include_players=True,
        carry_over=float(pe["carry"]),
        elo_params={
            "pool_unlisted": True,
            "pool_rating": float(v1.get("pool_rating", POOL_RATING)),
            "k": float(pe["k"]),
            "home_adv": float(pe["home_adv"]),
        },
    )
    lam = float(v1["ridge_lambda"])
    done = [r["season"] for r in rows if r["state"] == "post"]
    first = min(done) if done else None
    rt: dict[str, dict[str, float]] = {}
    for season in sorted({r["season"] for r in rows}):
        rt.update(
            season_ridge(con, season, d1, lam, cfg["prior"]["ridge"], None, include_scheduled=True)
        )
    out = []
    for r in rows:
        x = rt.get(r["game_id"])
        if x is None:  # not in ridge input (e.g. 'pre' with a stale state): skip
            continue
        r["features"]["rt_margin"] = x["rt_margin"]
        r["features"]["rt_total"] = x["rt_total"]
        r["rt_n"] = x["rt_n"]
        r["d1"] = r["home_team_id"] in d1 and r["away_team_id"] in d1
        r["has_prior"] = first is not None and r["season"] > first
        out.append(r)
    return out


# ---------- report ----------

MODELS = [  # label, prob key, margin key, total key
    ("Prior model", "p_prior", "m_prior", "t_prior"),
    ("No prior (today)", "p_noprior", "m_noprior", "t_noprior"),
    ("Elo, carry-over", "p_elo_prior", "m_elo_prior", None),
    ("Elo, no prior", "p_elo_noprior", "m_elo_noprior", None),
    ("Ratings, prior", None, "m_rt_prior", "t_rt_prior"),
    ("Ratings, no prior", None, "m_rt_noprior", "t_rt_noprior"),
    ("Closing line", "market_p_home", "m_close", "over_under"),
]
PAIRS = [  # label, model A keys, model B keys
    (
        "Prior - No prior",
        ("p_prior", "m_prior", "t_prior"),
        ("p_noprior", "m_noprior", "t_noprior"),
    ),
    ("Prior - Elo carry-over", ("p_prior", "m_prior", None), ("p_elo_prior", "m_elo_prior", None)),
    (
        "Prior - Closing line",
        ("p_prior", "m_prior", "t_prior"),
        ("market_p_home", "m_close", "over_under"),
    ),
]


def _diffs(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for lab, (pa, ma, ta), (pb, mb, tb) in PAIRS:
        d = {}
        for kind in ("brier", "log_loss"):
            d[kind] = cluster_bootstrap(rows, _per_game(rows, kind, pa) - _per_game(rows, kind, pb))
        d["margin_mae"] = cluster_bootstrap(
            rows, _per_game(rows, "margin_mae", ma) - _per_game(rows, "margin_mae", mb)
        )
        if ta:
            d["total_mae"] = cluster_bootstrap(
                rows, _per_game(rows, "total_mae", ta) - _per_game(rows, "total_mae", tb)
            )
        out[lab] = d
    return out


def _bets(rows: list[dict[str, Any]], m: str, t: str) -> list[dict[str, Any]]:
    return betting([{**x, "m_model": x[m], "t_model": x[t]} for x in rows])


def report(preds: list[dict[str, Any]]) -> dict[str, Any]:
    """Overall and per-bucket metrics on the market subset, paired CIs, flat bets."""
    mk = market_subset(preds)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in mk:
        groups[x["bucket"]].append(x)
    out: dict[str, Any] = {
        "n_all": len(preds),
        "n_market": len(mk),
        "days": len({x["day"] for x in mk}),
        "n_all_by_bucket": {b: sum(1 for x in preds if x["bucket"] == b) for b in BUCKETS},
        "overall": {lab: _metrics(mk, p, m, t) for lab, p, m, t in MODELS},
        "diffs": _diffs(mk),
        "buckets": {},
        "calibration": {
            lab: reliability([x[p] for x in mk], [x["home_win"] for x in mk])
            for lab, p, _, _ in MODELS
            if p
        },
        "betting": {
            "Prior model": _bets(mk, "m_prior", "t_prior"),
            "No prior (today)": _bets(mk, "m_noprior", "t_noprior"),
        },
    }
    for b in BUCKETS:
        rows = groups.get(b, [])
        if not rows:
            continue
        out["buckets"][b] = {
            "n": len(rows),
            "days": len({x["day"] for x in rows}),
            "metrics": {lab: _metrics(rows, p, m, t) for lab, p, m, t in MODELS},
            "diffs": _diffs(rows),
        }
    return out


def ship_decision(rep: dict[str, Any]) -> dict[str, Any]:
    """The declared ship rule and gate proposal, evaluated mechanically."""
    d = rep["diffs"]["Prior - No prior"]
    beats = bool(d["log_loss"]["hi"] < 0 and d["margin_mae"]["hi"] < 0)
    top = rep["buckets"].get("10+")
    worse_10 = bool(
        top
        and (
            top["diffs"]["Prior - No prior"]["log_loss"]["lo"] > 0
            or top["diffs"]["Prior - No prior"]["margin_mae"]["lo"] > 0
        )
    )
    qual = {}
    for b in BUCKETS:
        e = rep["buckets"].get(b)
        if e is None:
            qual[b] = False
            continue
        m = e["metrics"]
        qual[b] = bool(
            m["Prior model"]["ece"] <= ECE_MAX
            and m["Prior model"]["log_loss"] < m["Elo, carry-over"]["log_loss"]
            and m["Prior model"]["margin_mae"] < m["Elo, carry-over"]["margin_mae"]
        )
    gate = None
    for i, b in enumerate(BUCKETS):
        if all(qual[x] for x in BUCKETS[i:]):
            gate = BUCKET_FLOOR[b]
            break
    ship = beats and not worse_10
    return {
        "ship": ship,
        "beats_no_prior": beats,
        "worse_at_10_plus": worse_10,
        "bucket_qualifies": qual,
        "proposed_gate": gate if ship else None,
        "gate_if_shipped": gate,
    }


# ---------- markdown ----------


def _f(x, d=4):
    return "-" if x is None else f"{x:.{d}f}"


def _ci(c: dict[str, float] | None, d=4) -> str:
    if not c:
        return "-"
    return f"{c['mean']:+.{d}f} ({c['lo']:+.{d}f} to {c['hi']:+.{d}f})"


def _model_table(metrics: dict[str, dict[str, float]]) -> list[str]:
    lines = [
        "| model | Brier | log loss | ECE | margin MAE | total MAE |",
        "|---|---|---|---|---|---|",
    ]
    for lab, *_ in MODELS:
        s = metrics[lab]
        lines.append(
            f"| {lab} | {_f(s.get('brier'))} | {_f(s.get('log_loss'))} | {_f(s.get('ece'), 3)} "
            f"| {_f(s.get('margin_mae'), 2)} | {_f(s.get('total_mae'), 2)} |"
        )
    return lines


def _diff_table(diffs: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        "| comparison | Brier | log loss | margin MAE | total MAE |",
        "|---|---|---|---|---|",
    ]
    for lab, d in diffs.items():
        lines.append(
            f"| {lab} | {_ci(d['brier'])} | {_ci(d['log_loss'])} | {_ci(d['margin_mae'], 3)} "
            f"| {_ci(d.get('total_mae'), 3)} |"
        )
    return lines


def render_markdown(rep: dict[str, Any], title: str) -> str:
    lines = [
        f"## {title}",
        "",
        f"D1-vs-D1 games: {rep['n_all']}; with a closing moneyline, spread and total: "
        f"{rep['n_market']} over {rep['days']} game days.",
        "",
        *_model_table(rep["overall"]),
        "",
        "Paired differences (95% day-clustered bootstrap CI; negative = prior model better):",
        "",
        *_diff_table(rep["diffs"]),
        "",
        "### By games played (the lower of the two teams' completed games this season)",
        "",
        "| bucket | n | prior LL | no-prior LL | Elo-c LL | close LL | prior ECE | prior margin "
        "| no-prior margin | Elo-c margin | close margin | prior total | no-prior total "
        "| close total |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b, e in rep["buckets"].items():
        m = e["metrics"]
        p, n, ec, c = (
            m["Prior model"],
            m["No prior (today)"],
            m["Elo, carry-over"],
            m["Closing line"],
        )
        lines.append(
            f"| {b} | {e['n']} | {_f(p['log_loss'])} | {_f(n['log_loss'])} | {_f(ec['log_loss'])} "
            f"| {_f(c['log_loss'])} | {_f(p['ece'], 3)} | {_f(p['margin_mae'], 2)} "
            f"| {_f(n['margin_mae'], 2)} | {_f(ec['margin_mae'], 2)} | {_f(c['margin_mae'], 2)} "
            f"| {_f(p['total_mae'], 2)} | {_f(n['total_mae'], 2)} | {_f(c['total_mae'], 2)} |"
        )
    lines += [
        "",
        "Per-bucket paired differences (95% day-clustered CI):",
        "",
        "| bucket | comparison | log loss | Brier | margin MAE | total MAE |",
        "|---|---|---|---|---|---|",
    ]
    for b, e in rep["buckets"].items():
        for lab, d in e["diffs"].items():
            lines.append(
                f"| {b} | {lab} | {_ci(d['log_loss'])} | {_ci(d['brier'])} "
                f"| {_ci(d['margin_mae'], 3)} | {_ci(d.get('total_mae'), 3)} |"
            )
    lines += [
        "",
        "### Flat bets at -110 vs the close (backtest, not a betting record)",
        "",
        "| model | market | edge >= t | bets | hit rate | day-clustered 95% | ROI |",
        "|---|---|---|---|---|---|---|",
    ]
    for lab, bets in rep["betting"].items():
        for x in bets:
            ci = x["day_ci"]
            cis = "-" if ci is None else f"{100 * ci[0]:.1f}-{100 * ci[1]:.1f}%"
            lines.append(
                f"| {lab} | {'spread' if x['market'] == 'ats' else 'total'} | {x['threshold']:g} "
                f"| {x['bets']} | {100 * x['hit_rate']:.1f}% | {cis} | {100 * x['roi']:+.1f}% |"
            )
    return "\n".join(lines) + "\n"


# ---------- CLI ----------


def _marker(cfg_path: Path) -> Path:
    return cfg_path.with_suffix(".holdout-scored")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m deepsports.analysis.ncaab_prior")
    ap.add_argument("step", choices=["tune", "holdout", "report"])
    ap.add_argument("--db", type=Path)
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--v1-config", type=Path, default=V1_CONFIG)
    ap.add_argument("--preds", type=Path)
    a = ap.parse_args(argv)
    v1 = _v1_config(a.v1_config)
    if a.step == "tune":
        con = duckdb.connect(str(a.db), read_only=True)
        cfg = tune(con, v1)
        a.config.parent.mkdir(parents=True, exist_ok=True)
        a.config.write_text(json.dumps(cfg, indent=1) + "\n")
        print(render_markdown(cfg["tuning"]["report"], "Tuning: 2024-25 Nov 1 - Jan 31"))
        return 0
    cfg = json.loads(a.config.read_text())
    if a.step == "holdout":
        marker = _marker(a.config)
        if marker.exists():
            print(f"refusing: holdout already scored ({marker})", file=sys.stderr)
            return 2
        con = duckdb.connect(str(a.db), read_only=True)
        preds = holdout_predictions(con, cfg, v1)  # nothing is scored until report() below
        a.preds.write_text(json.dumps(preds))
        marker.write_text(datetime.now(UTC).isoformat(timespec="seconds") + "\n")
    else:
        preds = json.loads(a.preds.read_text())
    rep = report(preds)
    print(render_markdown(rep, "Locked holdout: 2025-26 Nov 1 - Jan 31"))
    print(json.dumps(ship_decision(rep), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
