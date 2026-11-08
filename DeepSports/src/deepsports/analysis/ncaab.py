"""College basketball (NCAAB, men's D1) model v1, with a locked holdout.

    W=/Volumes/ExFATStorag/DeepSports/work
    # 1. validation only (games before HOLDOUT_START): tune Elo, ratings, model choice; freeze
    uv run python -m deepsports.analysis.ncaab validate --db $W/COPY.duckdb --config CFG.json
    # 2. score the locked holdout ONCE with the frozen config
    uv run python -m deepsports.analysis.ncaab holdout --db $W/COPY.duckdb --config CFG.json \
        --preds $W/ncaab_v1_holdout_preds.json
    # re-render saved holdout predictions (no refitting)
    uv run python -m deepsports.analysis.ncaab report --config CFG.json --preds P.json

Protocol (docs/DECISIONS.md, 2026-11-04): the holdout is every completed 2025-26 game from
2026-02-01 00:00 US/Eastern on with both teams D1. `validate` removes every row at or after
HOLDOUT_START before anything is scored, so no setting can see it. `holdout` reads the frozen
config, refuses to run twice (marker file next to the config), and predicts the holdout
walk-forward (weekly refits on all earlier games, frozen settings).

What's college-specific, compared with NBA v1:
- **No prior season** in the warehouse, so everyone starts level (Elo 1500, ratings 0) and the
  early season leans on shrinkage. Only season 2026 (2025-26) is used.
- **Non-D1 opponents** (`teams.listed = false`) are pooled into one "unlisted" team for Elo and
  the ratings; their games feed history but are never trained on or scored.
- **Opponent-adjusted ratings** (`RidgeRatings`): a Massey-style ridge regression of each
  team's points on (offense of the team, defense of the opponent, home edge), refit before
  every tip-off on the games that had finished by then. With ~360 teams and lopsided
  schedules, raw recent form mostly measures schedule strength; this adjusts for it.
- Travel is dropped (unknown for most college cities).

Leakage: every feature comes from games that finished (start + FINISH_LAG) before tip-off.
Closing lines are carried only to score the market as a benchmark.
"""

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from deepsports import config
from deepsports.analysis.backtest import BREAK_EVEN, ats, over_under
from deepsports.analysis.elo import elo_ratings
from deepsports.analysis.ensemble import (
    _eastern_date,
    _ll,
    cluster_bootstrap,
    reliability,
)
from deepsports.analysis.features import FINISH_LAG, build_features
from deepsports.analysis.market import _in, final_sql
from deepsports.analysis.model import MODEL_NAME, ModelV1, _json_features
from deepsports.analysis.players import PLAYER_DIFF_FEATURES, PLAYER_SUM_FEATURES

LEAGUE = "ncaab"
SEASON = 2026  # 2025-26, the only complete college season in the warehouse
SEASON_TYPES = (2, 3)  # regular season (incl. conference tournaments), postseason
VAL_START = datetime(2025, 12, 1, 5, tzinfo=UTC)  # 00:00 US/Eastern
HOLDOUT_START = datetime(2026, 2, 1, 5, tzinfo=UTC)
FOLD_DAYS = 7
POOL_RATING = 1200.0  # starting Elo of the pooled non-D1 team (fixed, not tuned)

# Validation grids (declared in DECISIONS: Elo K / home edge, rating shrinkage, early-row
# filter, team vs team + players).
# Round 1 was K 20-60 x home 60-120 and lambda 1-8; its best values sat on the grid edges
# (K 60, home 60, lambda 1), so round 2 widened both (still validation only).
ELO_GRID = [
    (k, h) for k in (20.0, 30.0, 40.0, 60.0, 80.0, 100.0, 140.0) for h in (30.0, 60.0, 90.0, 120.0)
]
LAMBDA_GRID = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)  # ridge prior, in games of an average opponent
MIN_GAMES_GRID = (0, 5)  # 10 is infeasible: no team has 10 games before mid-December
FEATURE_SETS = ("team", "players")

WIN_FEATURES = [
    "elo_diff",
    "home_court",
    "rt_margin",  # ridge-rating predicted home margin (includes the home edge)
    "rest_diff",
    "b2b_home",
    "b2b_away",
    "g7_home",
    "g7_away",
    "form_net_diff",
    "eff_net_diff",
]
TOTAL_FEATURES = [
    "rt_total",  # ridge-rating predicted total
    "lg_total",
    "form_total",
    "pace_sum",
    "eff_sum",
    "home_court",
    "rest_diff",
]
TARGETS = ("win", "margin", "total")


def feature_lists(feature_set: str) -> tuple[list[str], list[str]]:
    """(win/margin features, total features) for 'team' or 'players'."""
    if feature_set == "team":
        return list(WIN_FEATURES), list(TOTAL_FEATURES)
    if feature_set == "players":
        return WIN_FEATURES + PLAYER_DIFF_FEATURES, TOTAL_FEATURES + PLAYER_SUM_FEATURES
    raise ValueError(feature_set)


def make_model(feature_set: str) -> ModelV1:
    win, total = feature_lists(feature_set)
    return ModelV1(win_features=win, margin_features=list(win), total_features=total)


# ---------- conference flags (raw ESPN summaries; not in the warehouse) ----------


def conference_flag(summary: dict[str, Any]) -> bool | None:
    """ESPN's `conferenceCompetition` flag from a game summary (None if absent)."""
    comps = (summary.get("header") or {}).get("competitions") or [{}]
    v = comps[0].get("conferenceCompetition")
    return None if v is None else bool(v)


def conference_flags(raw_dir: Path, game_ids: list[str]) -> dict[str, bool]:
    """game_id -> conference game?, read from raw summaries (`<raw_dir>/<id>.json.gz`)."""
    out = {}
    for gid in game_ids:
        p = raw_dir / f"{gid}.json.gz"
        if not p.exists():
            continue
        try:
            v = conference_flag(json.loads(gzip.decompress(p.read_bytes())))
        except (OSError, ValueError):
            continue
        if v is not None:
            out[gid] = v
    return out


# ---------- opponent-adjusted ridge ratings ----------


class RidgeRatings:
    """Massey-style ratings on points, solved by ridge regression on the games added so far.

    Per team-game: points = mu + h * loc + off[team] + def[opponent] (loc +1 home, -1 away, 0
    neutral). Ridge penalty `lam` on off/def (a prior of `lam` games against an average team);
    mu and h are almost unpenalized. Normal equations are accumulated incrementally, so each
    refit is one dense solve.
    """

    def __init__(self, teams: list[str], lam: float):
        self.idx = {t: i for i, t in enumerate(sorted(set(teams)))}
        self.nt = len(self.idx)
        p = 2 + 2 * self.nt
        self.ata = np.zeros((p, p))
        self.atb = np.zeros(p)
        self.pen = np.full(p, float(lam))
        self.pen[:2] = 1e-6
        self.n_games: dict[str, int] = defaultdict(int)
        self.n_total = 0
        self._theta: np.ndarray | None = None

    def _obs(self, team: str, opp: str, loc: float, pts: float) -> None:
        cols = [0, 1, 2 + self.idx[team], 2 + self.nt + self.idx[opp]]
        vals = [1.0, loc, 1.0, 1.0]
        for i, a in zip(cols, vals, strict=True):
            self.atb[i] += a * pts
            for j, b in zip(cols, vals, strict=True):
                self.ata[i, j] += a * b

    def add(self, home: str, away: str, hs: float, as_: float, neutral: bool) -> None:
        loc = 0.0 if neutral else 1.0
        self._obs(home, away, loc, hs)
        self._obs(away, home, -loc, as_)
        self.n_games[home] += 1
        self.n_games[away] += 1
        self.n_total += 1
        self._theta = None

    def theta(self) -> np.ndarray:
        if self._theta is None:
            self._theta = np.linalg.solve(self.ata + np.diag(self.pen), self.atb)
        return self._theta

    def empty(self) -> bool:
        """True when nothing is known yet (no games added; a prior subclass overrides)."""
        return self.n_total == 0

    def predict(self, home: str, away: str, neutral: bool) -> tuple[float, float]:
        """(home margin, total) predicted from the games added so far (NaN before any)."""
        if self.empty():
            return math.nan, math.nan
        th = self.theta()
        mu, h = th[0], th[1]
        ih, ia = self.idx[home], self.idx[away]
        off, dfn = th[2 : 2 + self.nt], th[2 + self.nt :]
        loc = 0.0 if neutral else 1.0
        ph = mu + h * loc + off[ih] + dfn[ia]
        pa = mu - h * loc + off[ia] + dfn[ih]
        return float(ph - pa), float(ph + pa)


def _season_games(
    con: duckdb.DuckDBPyConnection, season: int, include_scheduled: bool = False
) -> list[tuple]:
    """Completed games of `season` in tip-off order as ridge_features input. With
    `include_scheduled`, also the season's scheduled (state 'pre') games between two known
    teams (the same rows build_features returns), with NULL scores."""
    final = final_sql(LEAGUE)
    scheduled = (
        f"""OR (g.state = 'pre'
                AND g.home_team_id IN (SELECT team_id FROM teams WHERE league = '{LEAGUE}')
                AND g.away_team_id IN (SELECT team_id FROM teams WHERE league = '{LEAGUE}'))"""
        if include_scheduled
        else ""
    )
    return con.execute(
        f"""
        SELECT g.game_id, g.start_time_utc, g.home_team_id, g.away_team_id,
               CASE WHEN {final} THEN g.home_score END,
               CASE WHEN {final} THEN g.away_score END, coalesce(g.neutral_site, false)
        FROM games g
        WHERE g.league = '{LEAGUE}' AND g.season_year = ?
          AND g.season_type IN ({_in(SEASON_TYPES)}) AND (({final}) {scheduled})
        ORDER BY g.start_time_utc, g.game_id
        """,
        [season],
    ).fetchall()


def listed_teams(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        r[0]
        for r in con.execute(
            "SELECT team_id FROM teams WHERE league = ? AND coalesce(listed, true)", [LEAGUE]
        ).fetchall()
    }


def ridge_features(
    games: list[tuple],
    d1: set[str],
    lam: float,
    make: Callable[[list[str]], RidgeRatings] | None = None,
) -> dict[str, dict[str, float]]:
    """game_id -> pre-game rt_margin, rt_total and rt_n (min games rated of the two teams),
    walking games in tip-off order. A game enters the fit only once start + FINISH_LAG <= the
    current tip-off, the same visibility rule as build_features. Non-D1 teams are pooled.

    Scheduled games (scores None) get features too, rated from the finished games visible
    before their tip-off; they never enter the fit themselves. `make(teams)` builds the
    ratings object instead of RidgeRatings(teams, lam) (e.g. a cross-season prior)."""

    def key(t: str) -> str:
        return t if t in d1 else "unlisted"

    teams = [key(t) for g in games for t in (g[2], g[3])]
    rr = make(teams) if make else RidgeRatings(teams, lam)
    pending: list[tuple] = []
    pi = 0
    out = {}
    for gid, start, home, away, hs, as_, neutral in games:
        while pi < len(pending) and pending[pi][0] + FINISH_LAG <= start:
            _, h, a, phs, pas, pn = pending[pi]
            rr.add(h, a, phs, pas, pn)
            pi += 1
        hk, ak = key(home), key(away)
        m, t = rr.predict(hk, ak, bool(neutral))
        out[gid] = {
            "rt_margin": m,
            "rt_total": t,
            "rt_n": float(min(rr.n_games[hk], rr.n_games[ak])),
        }
        if hs is not None and as_ is not None:
            pending.append((start, hk, ak, hs, as_, bool(neutral)))
    return out


# ---------- rows ----------


def college_rows(
    con: duckdb.DuckDBPyConnection,
    elo_params: dict[str, Any],
    lam: float,
    include_players: bool = True,
    conf: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Completed season-2026 feature rows (build_features with league='ncaab') with the ridge
    ratings, D1 flags, conference flag and game day attached. Includes non-D1 games (flagged
    `d1 = False`); callers train and score only `d1` rows."""
    d1 = listed_teams(con)
    rows = build_features(
        con,
        league=LEAGUE,
        season_types=SEASON_TYPES,
        include_players=include_players,
        elo_params={"pool_unlisted": True, "pool_rating": POOL_RATING, **elo_params},
    )
    rt = ridge_features(_season_games(con, SEASON), d1, lam)
    conf = conf or {}
    out = []
    for r in rows:
        if r["state"] != "post" or r["season"] != SEASON:
            continue
        x = rt[r["game_id"]]
        r["features"]["rt_margin"] = x["rt_margin"]
        r["features"]["rt_total"] = x["rt_total"]
        r["rt_n"] = x["rt_n"]
        r["d1"] = r["home_team_id"] in d1 and r["away_team_id"] in d1
        r["conference"] = conf.get(r["game_id"])
        r["day"] = _eastern_date(r["start_time_utc"])
        out.append(r)
    return out


# ---------- daily use: pre-tip predictions for scheduled games ----------

MODEL_VERSION = "ncaab-v1"  # stored with model = model.MODEL_NAME ("v1")
CONFIG_PATH = config.ROOT / "models" / "ncaab_v1" / "config.json"
# Gate (DECISIONS 2026-11-04): predict only when both teams are D1 and each has at least this
# many completed games this season. Ratings restart every season (cross-season carry-over is
# not validated yet), so early-season rows carry little signal; this matches the training
# filter (config `min_games`).
MIN_GAMES_TO_PREDICT = 5
# Early-season predictions (owner opt-in, 2026-11-04): for games where a team has fewer than
# MIN_GAMES_TO_PREDICT games (at least EARLY_MIN_GAMES each; the gate has no upper bound, so it
# also covers gated games). Stored under their own version so they never mix with ncaab-v1's
# record; clients hide them unless toggled. Since 2026-11-06 the model behind them is the
# cross-season prior model (analysis/ncaab_prior.py), not v1 (DECISIONS 2026-11-06).
EARLY_VERSION = "ncaab-v1-early"
EARLY_MIN_GAMES = 1
# The prior model on v1's gate (both teams D1 with >= 5 games), written beside ncaab-v1 with
# its own graded record. Not shown on cards, glasses or the calendar (config.HIDDEN_MODEL_VERSIONS).
PRIOR_VERSION = "ncaab-v1p"
VERSIONS = (MODEL_VERSION, PRIOR_VERSION, EARLY_VERSION)
# ncaab-v1 with a stronger L2 penalty on the logistic win model (C = 0.1 instead of 1): the
# declared calibration fix that passed its locked-holdout rule (docs/results/
# 2026-11-06-calibration.md). Same gate, margin and total as ncaab-v1. Deliberately NOT in
# VERSIONS, so `deepsports predict --league ncaab --model-version all` and the scheduled sync
# are unchanged; produce it with predict_upcoming_calibrated.
CALIBRATED_VERSION = "ncaab-v1c"
CALIBRATED_WIN_C = 0.1
VERSION_MIN_GAMES = {
    MODEL_VERSION: MIN_GAMES_TO_PREDICT,
    PRIOR_VERSION: MIN_GAMES_TO_PREDICT,
    EARLY_VERSION: EARLY_MIN_GAMES,
    CALIBRATED_VERSION: MIN_GAMES_TO_PREDICT,
}
PRIOR_MODEL_VERSIONS = (PRIOR_VERSION, EARLY_VERSION)  # one fit per run serves both gates
SKIP_NON_D1 = "non_d1"
SKIP_FEW_GAMES = "few_games"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def live_rows(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Feature rows for every completed and scheduled college game (all seasons), with the
    frozen config's Elo settings and per-season ridge ratings attached (`rt_margin`,
    `rt_total` features; `rt_n`, `d1` keys). Elo restarts level every season (carry_over 0),
    the setting the model was validated with. Scheduled rows use only finished games."""
    d1 = listed_teams(con)
    rows = build_features(
        con,
        league=LEAGUE,
        season_types=SEASON_TYPES,
        include_players=True,
        carry_over=0.0,
        elo_params={
            "pool_unlisted": True,
            "pool_rating": float(cfg.get("pool_rating", POOL_RATING)),
            **cfg["elo"],
        },
    )
    rt: dict[str, dict[str, float]] = {}
    for season in sorted({r["season"] for r in rows}):
        rt.update(
            ridge_features(
                _season_games(con, season, include_scheduled=True), d1, cfg["ridge_lambda"]
            )
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
        out.append(r)
    return out


def skip_reason(row: dict[str, Any], min_games: int = MIN_GAMES_TO_PREDICT) -> str | None:
    """Why a scheduled row gets no prediction (None = predict it)."""
    if not row["d1"]:
        return SKIP_NON_D1
    if row["rt_n"] < min_games:
        return SKIP_FEW_GAMES
    return None


def _version_predictions(
    rows: list[dict[str, Any]],
    choice: dict[str, dict[str, Any]],
    train_ok: Callable[[dict[str, Any], dict[str, Any]], bool],
    versions: list[str],
    win_c: float = 1.0,
) -> dict[str, list[dict[str, Any]]]:
    """Fit one model (per target: `choice[target]` feature set, training rows where
    `train_ok(row, choice[target])`) on every completed D1-vs-D1 row, once, and predict every
    scheduled row that at least one of `versions` predicts. Each version gets one row per
    scheduled game with its own gate (VERSION_MIN_GAMES) as `skip_reason`. `win_c` is the
    logistic win model's inverse L2 strength (1.0 = ModelV1's default)."""
    done = [r for r in rows if r["state"] == "post" and r["d1"]]
    upcoming = [r for r in rows if r["state"] == "pre"]
    reasons = {v: [skip_reason(r, VERSION_MIN_GAMES[v]) for r in upcoming] for v in versions}
    todo_idx = [i for i in range(len(upcoming)) if any(reasons[v][i] is None for v in versions)]
    todo = [upcoming[i] for i in todo_idx]
    key = {"win": "p_home_win", "margin": "pred_home_margin", "total": "pred_total"}
    preds: dict[str, list[float]] = {}
    if todo:
        fitted: dict[tuple, list[dict[str, float]]] = {}
        for tgt, c in choice.items():
            fk = (c["feature_set"], int(c["min_games"]), c.get("mode"))
            if fk not in fitted:
                train = [r for r in done if train_ok(r, c)]
                m = make_model(c["feature_set"])
                m.win_c = win_c
                fitted[fk] = m.fit(train).predict(todo)
            preds[key[tgt]] = [p[key[tgt]] for p in fitted[fk]]
    pos = {i: j for j, i in enumerate(todo_idx)}
    now = datetime.now(UTC)
    out: dict[str, list[dict[str, Any]]] = {}
    for v in versions:
        vrows = []
        for i, (r, why) in enumerate(zip(upcoming, reasons[v], strict=True)):
            row = {
                "game_id": r["game_id"],
                "model": MODEL_NAME,
                "model_version": v,
                "created_at": now,
                "p_home_win": None,
                "pred_home_margin": None,
                "pred_total": None,
                "features_json": None,
                "skip_reason": why,
            }
            if why is None:
                for k, vals in preds.items():
                    row[k] = float(vals[pos[i]])
                row["features_json"] = _json_features({**r["features"], "rt_n": r["rt_n"]})
            vrows.append(row)
        out[v] = vrows
    return out


def predict_upcoming_versions(
    con: duckdb.DuckDBPyConnection,
    versions: list[str],
    cfg: dict[str, Any] | None = None,
    prior_cfg: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Predict every scheduled college game for each of `versions` (see VERSIONS). Read-only.

    - `ncaab-v1`: college v1 (frozen `models/ncaab_v1/config.json`): Elo restarts every
      season, per-season ridge ratings, each target trained on rows with rt_n >= min_games.
    - `ncaab-v1p` / `ncaab-v1-early`: the cross-season prior model (frozen
      `models/ncaab_prior/config.json`: Elo carry-over, ridge prior from last season,
      `prior_rows` training filter), fit once and shared by both versions.

    Every model trains on all completed D1-vs-D1 games of all seasons. Market blend weights are
    not applied (no closing line exists before tip). Returns version -> rows with
    PREDICTION_KEYS plus `skip_reason` (prediction fields None when set)."""
    unknown = [v for v in versions if v not in VERSIONS]
    if unknown:
        raise ValueError(f"unknown college model version(s) {unknown} (use {', '.join(VERSIONS)})")
    out: dict[str, list[dict[str, Any]]] = {}
    v1 = cfg or load_config()
    if MODEL_VERSION in versions:
        out |= _version_predictions(
            live_rows(con, v1),
            v1["choice"],
            lambda r, c: r["rt_n"] >= int(c["min_games"]),
            [MODEL_VERSION],
        )
    pv = [v for v in versions if v in PRIOR_MODEL_VERSIONS]
    if pv:
        from deepsports.analysis import ncaab_prior

        pcfg = prior_cfg or ncaab_prior.load_config()
        out |= _version_predictions(
            ncaab_prior.live_rows(con, pcfg, v1),
            pcfg["choice"],
            lambda r, c: ncaab_prior.train_ok(r, int(c["min_games"]), c["mode"]),
            pv,
        )
    return {v: out[v] for v in versions}


def predict_upcoming_calibrated(
    con: duckdb.DuckDBPyConnection, cfg: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """`ncaab-v1c` rows: exactly ncaab-v1 (same rows, gate and margin/total models) with the
    win model refit at C = CALIBRATED_WIN_C. Read-only; same row shape as predict_upcoming."""
    v1 = cfg or load_config()
    return _version_predictions(
        live_rows(con, v1),
        v1["choice"],
        lambda r, c: r["rt_n"] >= int(c["min_games"]),
        [CALIBRATED_VERSION],
        win_c=CALIBRATED_WIN_C,
    )[CALIBRATED_VERSION]


def predict_upcoming(
    con: duckdb.DuckDBPyConnection,
    model_version: str = MODEL_VERSION,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One version's rows from predict_upcoming_versions (see there)."""
    return predict_upcoming_versions(con, [model_version], cfg)[model_version]


# ---------- Elo tuning (Elo alone, on validation games) ----------


def elo_validation(
    con: duckdb.DuckDBPyConnection, grid=ELO_GRID, start=VAL_START, end=HOLDOUT_START
) -> list[dict[str, Any]]:
    """Log loss of raw Elo on D1-vs-D1 games in [start, end) for each (K, home edge)."""
    d1 = listed_teams(con)
    out = []
    for k, h in grid:
        res = elo_ratings(
            con,
            k=k,
            home_adv=h,
            league=LEAGUE,
            season_types=SEASON_TYPES,
            pool_unlisted=True,
            pool_rating=POOL_RATING,
        )
        g = [
            x
            for x in res.games
            if x["season"] == SEASON
            and start <= x["start_time_utc"] < end
            and x["home_team_id"] in d1
            and x["away_team_id"] in d1
        ]
        p = np.array([x["p_home"] for x in g])
        y = np.array([x["home_win"] for x in g], dtype=float)
        out.append({"k": k, "home_adv": h, "n": len(g), "log_loss": float(np.mean(_ll(p, y)))})
    return out


def ridge_validation(
    con: duckdb.DuckDBPyConnection, lams=LAMBDA_GRID, start=VAL_START, end=HOLDOUT_START
) -> list[dict[str, Any]]:
    """Margin / total MAE of the raw ridge ratings on D1-vs-D1 games in [start, end)."""
    d1 = listed_teams(con)
    games = _season_games(con, SEASON)
    test = [g for g in games if start <= g[1] < end and g[2] in d1 and g[3] in d1]
    out = []
    for lam in lams:
        rt = ridge_features(games, d1, lam)
        m = np.array([rt[g[0]]["rt_margin"] for g in test])
        t = np.array([rt[g[0]]["rt_total"] for g in test])
        ym = np.array([g[4] - g[5] for g in test], dtype=float)
        yt = np.array([g[4] + g[5] for g in test], dtype=float)
        out.append(
            {
                "lam": lam,
                "n": len(test),
                "margin_mae": float(np.mean(np.abs(m - ym))),
                "total_mae": float(np.mean(np.abs(t - yt))),
            }
        )
    return out


# ---------- weekly walk-forward ----------


def weekly_folds(rows: list[dict[str, Any]], start: datetime, end: datetime | None = None):
    """Yield (block start, train rows, test rows): D1 rows only. Test blocks are FOLD_DAYS-long
    windows from `start`; each trains on every D1 row that tipped off before the block."""
    d1 = sorted((r for r in rows if r["d1"]), key=lambda r: r["start_time_utc"])
    last = max(r["start_time_utc"] for r in d1)
    end = end or last + timedelta(seconds=1)
    b = start
    while b < end:
        e = min(b + timedelta(days=FOLD_DAYS), end)
        test = [r for r in d1 if b <= r["start_time_utc"] < e]
        train = [r for r in d1 if r["start_time_utc"] < b]
        if test and train:
            yield b, train, test
        b = e


def _elo_margin_fit(train: list[dict[str, Any]], home_adv: float):
    """Elo margin baseline: least squares margin ~ a + b * (elo_diff + home edge)."""
    x = np.array(
        [r["features"]["elo_diff"] + home_adv * r["features"]["home_court"] for r in train]
    )
    y = np.array([r["home_margin"] for r in train], dtype=float)
    b, a = np.polyfit(x, y, 1)
    return lambda r: float(
        a + b * (r["features"]["elo_diff"] + home_adv * r["features"]["home_court"])
    )


def walk_forward(
    rows: list[dict[str, Any]],
    choice: dict[str, dict[str, Any]],
    home_adv: float,
    start: datetime,
    end: datetime | None = None,
    extra: tuple[tuple[str, int], ...] = (),
) -> list[dict[str, Any]]:
    """Per-game out-of-sample predictions. `choice` maps target -> {feature_set, min_games}
    (the college model); `extra` adds (feature_set, min_games) variants as p_/m_/t_<fs>_<mg>
    (validation grid). Also: Elo, ridge ratings, the closing line, truth and breakdown keys."""
    variants = {(c["feature_set"], c["min_games"]) for c in choice.values()} | set(extra)
    out = []
    for _, train, test in weekly_folds(rows, start, end):
        assert max(r["start_time_utc"] for r in train) < min(r["start_time_utc"] for r in test)
        fitted = {}
        for fs, mg in variants:
            tr = [r for r in train if r["rt_n"] >= mg]
            fitted[(fs, mg)] = make_model(fs).fit(tr).predict(test)
        elo_m = _elo_margin_fit(train, home_adv)
        for i, r in enumerate(test):
            mk = r["market"]
            row = {
                "game_id": r["game_id"],
                "start_time_utc": r["start_time_utc"].isoformat(),
                "day": r["day"],
                "season_type": r["season_type"],
                "neutral_site": r["neutral_site"],
                "conference": r["conference"],
                "rt_n": r["rt_n"],
                "home_win": r["home_win"],
                "home_margin": r["home_margin"],
                "total": r["total"],
                "market_p_home": mk.get("p_home"),
                "spread_home": mk.get("spread_home"),
                "over_under": mk.get("over_under"),
                "p_elo": r["elo_p_home"],
                "m_elo": elo_m(r),
                "m_rt": r["features"]["rt_margin"],
                "t_rt": r["features"]["rt_total"],
            }
            key = {"win": "p_home_win", "margin": "pred_home_margin", "total": "pred_total"}
            pre = {"win": "p", "margin": "m", "total": "t"}
            for tgt, c in choice.items():
                row[f"{pre[tgt]}_model"] = fitted[(c["feature_set"], c["min_games"])][i][key[tgt]]
            for fs, mg in extra:
                for tgt in TARGETS:
                    row[f"{pre[tgt]}_{fs}_{mg}"] = fitted[(fs, mg)][i][key[tgt]]
            out.append(row)
    return out


# ---------- model + market blend (fit on validation, frozen) ----------


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_market_blend(preds: list[dict[str, Any]]) -> dict[str, float]:
    """One weight per target w in [0, 1] (0 = the close alone) minimizing validation log loss
    (logit average) or MAE (point average). Grid search, step 0.01."""
    ws = np.round(np.linspace(0, 1, 101), 2)
    out = {}
    pw = [x for x in preds if x["market_p_home"] is not None]
    y = np.array([x["home_win"] for x in pw], dtype=float)
    lm, lc = _logit([x["p_model"] for x in pw]), _logit([x["market_p_home"] for x in pw])
    out["win"] = float(
        min(ws, key=lambda w: np.mean(_ll(1 / (1 + np.exp(-(w * lm + (1 - w) * lc))), y)))
    )
    for tgt, k, mk, f in (
        ("margin", "m_model", "spread_home", lambda v: -v),
        ("total", "t_model", "over_under", lambda v: v),
    ):
        tk = "home_margin" if tgt == "margin" else "total"
        pp = [x for x in preds if x[mk] is not None]
        a = np.array([x[k] for x in pp])
        c = np.array([f(x[mk]) for x in pp])
        yy = np.array([x[tk] for x in pp], dtype=float)
        out[tgt] = float(min(ws, key=lambda w: np.mean(np.abs(w * a + (1 - w) * c - yy))))
    return out


def apply_market_blend(preds: list[dict[str, Any]], w: dict[str, float]) -> None:
    for x in preds:
        if x["market_p_home"] is not None:
            z = w["win"] * _logit(x["p_model"]) + (1 - w["win"]) * _logit(x["market_p_home"])
            x["p_blend"] = float(1 / (1 + np.exp(-z)))
        if x["spread_home"] is not None:
            x["m_blend"] = w["margin"] * x["m_model"] + (1 - w["margin"]) * -x["spread_home"]
        if x["over_under"] is not None:
            x["t_blend"] = w["total"] * x["t_model"] + (1 - w["total"]) * x["over_under"]


# ---------- validation ----------


def _scores(preds: list[dict[str, Any]], p: str, m: str, t: str) -> dict[str, float]:
    y = np.array([x["home_win"] for x in preds], dtype=float)
    return {
        "log_loss": float(np.mean(_ll(np.array([x[p] for x in preds]), y))),
        "margin_mae": float(np.mean([abs(x[m] - x["home_margin"]) for x in preds])),
        "total_mae": float(np.mean([abs(x[t] - x["total"]) for x in preds])),
    }


def validate(
    con: duckdb.DuckDBPyConnection, conf: dict[str, bool] | None = None, log=print
) -> dict[str, Any]:
    """Tune everything on games before HOLDOUT_START; return the frozen config."""
    elo_tab = elo_validation(con)
    best_elo = min(elo_tab, key=lambda r: r["log_loss"])
    log(f"elo best K={best_elo['k']} home={best_elo['home_adv']} LL={best_elo['log_loss']:.4f}")
    rt_tab = ridge_validation(con)
    best_rt = min(rt_tab, key=lambda r: r["margin_mae"])
    log(f"ridge best lam={best_rt['lam']} margin MAE={best_rt['margin_mae']:.3f}")
    elo_params = {"k": best_elo["k"], "home_adv": best_elo["home_adv"]}
    rows = college_rows(con, elo_params, best_rt["lam"], include_players=True, conf=conf)
    rows = [r for r in rows if r["start_time_utc"] < HOLDOUT_START]  # holdout never seen
    grid = tuple((fs, mg) for fs in FEATURE_SETS for mg in MIN_GAMES_GRID)
    base = {t: {"feature_set": "team", "min_games": 0} for t in TARGETS}
    preds = walk_forward(rows, base, best_elo["home_adv"], VAL_START, HOLDOUT_START, extra=grid)
    model_tab = []
    for fs, mg in grid:
        s = _scores(preds, f"p_{fs}_{mg}", f"m_{fs}_{mg}", f"t_{fs}_{mg}")
        model_tab.append({"feature_set": fs, "min_games": mg, "n": len(preds), **s})
        log(f"{fs} min_games={mg}: {s}")
    metric = {"win": "log_loss", "margin": "margin_mae", "total": "total_mae"}
    choice = {}
    for tgt in TARGETS:
        b = min(model_tab, key=lambda r: r[metric[tgt]])
        choice[tgt] = {"feature_set": b["feature_set"], "min_games": b["min_games"]}
    for x in preds:  # the chosen college model's validation predictions, for the blend weights
        x["p_model"] = x[f"p_{choice['win']['feature_set']}_{choice['win']['min_games']}"]
        x["m_model"] = x[f"m_{choice['margin']['feature_set']}_{choice['margin']['min_games']}"]
        x["t_model"] = x[f"t_{choice['total']['feature_set']}_{choice['total']['min_games']}"]
    blend = fit_market_blend(preds)
    val_rep = holdout_report(preds, {"market_blend": blend}, with_blend=False)
    log(f"choice {choice}; market blend weights {blend}")
    return {
        "league": LEAGUE,
        "season": SEASON,
        "val_start": VAL_START.isoformat(),
        "holdout_start": HOLDOUT_START.isoformat(),
        "fold_days": FOLD_DAYS,
        "pool_rating": POOL_RATING,
        "elo": elo_params,
        "ridge_lambda": best_rt["lam"],
        "choice": choice,
        "market_blend": blend,
        "validation": {
            "elo": elo_tab,
            "ridge": rt_tab,
            "models": model_tab,
            "n_val_games": len(preds),
            "summary": val_rep["overall"],
        },
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def holdout_predictions(
    con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], conf: dict[str, bool] | None = None
) -> list[dict[str, Any]]:
    rows = college_rows(con, cfg["elo"], cfg["ridge_lambda"], include_players=True, conf=conf)
    start = datetime.fromisoformat(cfg["holdout_start"])
    preds = walk_forward(rows, cfg["choice"], cfg["elo"]["home_adv"], start)
    apply_market_blend(preds, cfg["market_blend"])
    return preds


# ---------- holdout report ----------

MODELS = [  # label, prob key, margin key, total key (None = not available)
    ("Elo", "p_elo", "m_elo", None),
    ("Ratings (ridge)", None, "m_rt", "t_rt"),
    ("College v1", "p_model", "m_model", "t_model"),
    ("Closing line", "market_p_home", "m_close", "over_under"),
]


def _arr(rows, k):
    return np.array([x[k] for x in rows], dtype=float)


def _metrics(rows: list[dict[str, Any]], p: str | None, m: str | None, t: str | None):
    out: dict[str, float | None] = {}
    if p:
        pp, y = _arr(rows, p), _arr(rows, "home_win")
        out["brier"] = float(np.mean((pp - y) ** 2))
        out["log_loss"] = float(np.mean(_ll(pp, y)))
        out["acc"] = float(np.mean((pp >= 0.5) == (y == 1)))
        out["ece"] = reliability(list(pp), list(y.astype(int)))["ece"]
    if m:
        out["margin_mae"] = float(np.mean(np.abs(_arr(rows, m) - _arr(rows, "home_margin"))))
    if t:
        out["total_mae"] = float(np.mean(np.abs(_arr(rows, t) - _arr(rows, "total"))))
    return out


def _per_game(rows, kind: str, key: str) -> np.ndarray:
    if kind == "brier":
        return (_arr(rows, key) - _arr(rows, "home_win")) ** 2
    if kind == "log_loss":
        return _ll(_arr(rows, key), _arr(rows, "home_win"))
    if kind == "acc":
        return ((_arr(rows, key) >= 0.5) == (_arr(rows, "home_win") == 1)) * 1.0
    tgt = "home_margin" if kind == "margin_mae" else "total"
    return np.abs(_arr(rows, key) - _arr(rows, tgt))


def market_subset(preds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Games with a closing moneyline, spread and total (every model on the same games)."""
    out = []
    for x in preds:
        if None in (x["market_p_home"], x["spread_home"], x["over_under"]):
            continue
        out.append({**x, "m_close": -x["spread_home"]})
    return out


def breakdown_keys(x: dict[str, Any]) -> dict[str, str]:
    """The declared breakdowns (DECISIONS 2026-11-04): spread size, game type, venue."""
    s = abs(x["spread_home"])
    size = "|spread| <= 5" if s <= 5 else ("5 < |spread| <= 12" if s <= 12 else "|spread| > 12")
    if x["season_type"] == 3:
        gtype = "postseason"
    elif x["conference"] is True:
        gtype = "conference"
    elif x["conference"] is False:
        gtype = "non-conference"
    else:
        gtype = "unknown"
    return {
        "spread": size,
        "game type": gtype,
        "venue": "neutral" if x["neutral_site"] else "home court",
    }


def _bet_bootstrap(rows, results: list[int], reps=2000, seed=0):
    """Hit rate with a day-clustered 95% CI (pushes excluded)."""
    by_day: dict[str, list[int]] = defaultdict(list)
    for r, v in zip(rows, results, strict=True):
        if v != 0:
            by_day[r["day"]].append(v)
    days = list(by_day.values())
    if not days:
        return None
    w = np.array([sum(1 for v in d if v > 0) for d in days], dtype=float)
    n = np.array([len(d) for d in days], dtype=float)
    rng = np.random.default_rng(seed)
    st = np.empty(reps)
    for b in range(reps):
        pick = rng.integers(0, len(days), len(days))
        st[b] = w[pick].sum() / n[pick].sum()
    return float(np.percentile(st, 2.5)), float(np.percentile(st, 97.5))


def _bet_results(rows, kind: str, t: float) -> tuple[list, list[int]]:
    used, res = [], []
    for x in rows:
        if kind == "ats":
            edge = x["m_model"] - (-x["spread_home"])
            diff = x["home_margin"] + x["spread_home"]
        else:
            edge = x["t_model"] - x["over_under"]
            diff = x["total"] - x["over_under"]
        if abs(edge) < t or edge == 0:
            continue
        side = 1 if edge > 0 else -1
        used.append(x)
        res.append(0 if diff == 0 else (1 if side * diff > 0 else -1))
    return used, res


def betting(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Declared flat-bet checks at -110 (backtest only): ATS t = 0, 3; totals t = 0, 4."""
    out = []
    sp = [x for x in rows if x["spread_home"] is not None]
    tot = [x for x in rows if x["over_under"] is not None]
    for kind, ts, src in (("ats", (0.0, 3.0), sp), ("ou", (0.0, 4.0), tot)):
        fn = ats if kind == "ats" else over_under
        renamed = [{**x, "pred_home_margin": x["m_model"], "pred_total": x["t_model"]} for x in src]
        for b in fn(renamed, thresholds=ts):
            used, res = _bet_results(src, kind, b["threshold"])
            ci = _bet_bootstrap(used, res)
            out.append({"market": kind, **b, "day_ci": ci})
    return out


def holdout_report(
    preds: list[dict[str, Any]], cfg: dict[str, Any], with_blend: bool = True
) -> dict[str, Any]:
    mk = market_subset(preds)
    models = MODELS + (
        [("Model + close blend", "p_blend", "m_blend", "t_blend")] if with_blend else []
    )
    overall = {lab: _metrics(mk, p, m, t) for lab, p, m, t in models}
    all_games = {
        lab: _metrics(preds, p, m, t) for lab, p, m, t in models[:3]
    }  # every D1 game (no market needed)
    pairs = [
        (
            "College v1 - Closing line",
            "p_model",
            "market_p_home",
            "m_model",
            "m_close",
            "t_model",
            "over_under",
        ),
        ("College v1 - Elo", "p_model", "p_elo", "m_model", "m_elo", None, None),
        ("College v1 - Ratings", None, None, "m_model", "m_rt", "t_model", "t_rt"),
    ]
    if with_blend:
        pairs.append(
            (
                "Blend - Closing line",
                "p_blend",
                "market_p_home",
                "m_blend",
                "m_close",
                "t_blend",
                "over_under",
            )
        )
    diffs = {}
    for lab, pa, pb, ma, mb, ta, tb in pairs:
        d = {}
        if pa:
            for kind in ("brier", "log_loss", "acc"):
                d[kind] = cluster_bootstrap(mk, _per_game(mk, kind, pa) - _per_game(mk, kind, pb))
        d["margin_mae"] = cluster_bootstrap(
            mk, _per_game(mk, "margin_mae", ma) - _per_game(mk, "margin_mae", mb)
        )
        if ta:
            d["total_mae"] = cluster_bootstrap(
                mk, _per_game(mk, "total_mae", ta) - _per_game(mk, "total_mae", tb)
            )
        diffs[lab] = d
    calib = {
        lab: reliability([x[p] for x in mk], [x["home_win"] for x in mk])
        for lab, p, _, _ in models
        if p
    }
    groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for x in mk:
        for dim, val in breakdown_keys(x).items():
            groups[dim][val].append(x)
    breakdown = {}
    for dim, vals in groups.items():
        breakdown[dim] = {}
        for val, rows in sorted(vals.items()):
            e = {
                "n": len(rows),
                "model": _metrics(rows, "p_model", "m_model", "t_model"),
                "close": _metrics(rows, "market_p_home", "m_close", "over_under"),
            }
            if len(rows) >= 30:
                e["ll_diff"] = cluster_bootstrap(
                    rows,
                    _per_game(rows, "log_loss", "p_model")
                    - _per_game(rows, "log_loss", "market_p_home"),
                )
                e["margin_diff"] = cluster_bootstrap(
                    rows,
                    _per_game(rows, "margin_mae", "m_model")
                    - _per_game(rows, "margin_mae", "m_close"),
                )
            breakdown[dim][val] = e
    return {
        "n_all": len(preds),
        "n_market": len(mk),
        "days": len({x["day"] for x in mk}),
        "overall": overall,
        "all_games": all_games,
        "diffs": diffs,
        "calibration": calib,
        "breakdown": breakdown,
        "betting": betting(preds),
        "market_blend": cfg.get("market_blend"),
    }


def ship_decision(rep: dict[str, Any]) -> dict[str, Any]:
    """The declared ship rule, evaluated mechanically."""
    vs_elo = rep["diffs"]["College v1 - Elo"]
    vs_close = rep["diffs"]["College v1 - Closing line"]
    ece = rep["overall"]["College v1"]["ece"]
    ship = vs_elo["log_loss"]["hi"] < 0 and vs_elo["margin_mae"]["hi"] < 0 and ece <= 0.05
    beats_close = any(vs_close[k]["hi"] < 0 for k in ("log_loss", "margin_mae", "total_mae"))
    bet_ok = any(b["ci_lo"] is not None and b["ci_lo"] > BREAK_EVEN for b in rep["betting"])
    return {"ship_as_context": ship, "betting_edge": beats_close and bet_ok, "ece": ece}


def _f(x, d=4):
    return "-" if x is None else f"{x:.{d}f}"


def _ci(c: dict[str, float], d=4, scale=1.0) -> str:
    return f"{c['mean'] * scale:+.{d}f} ({c['lo'] * scale:+.{d}f} to {c['hi'] * scale:+.{d}f})"


def render_markdown(rep: dict[str, Any], cfg: dict[str, Any]) -> str:
    o = rep["overall"]
    out = [
        "## Holdout results (scored once)",
        f"{rep['n_all']} D1-vs-D1 games; {rep['n_market']} with a closing moneyline, spread and "
        f"total ({rep['days']} game days). Every row below uses those same "
        f"{rep['n_market']} games.",
        "",
        "| model | Brier | log loss | accuracy | ECE | margin MAE | total MAE |",
        "|---|---|---|---|---|---|---|",
    ]
    for lab, r in o.items():
        acc = r.get("acc")
        out.append(
            f"| {lab} | {_f(r.get('brier'))} | {_f(r.get('log_loss'))} | "
            f"{'-' if acc is None else f'{acc:.1%}'} | {_f(r.get('ece'), 3)} | "
            f"{_f(r.get('margin_mae'), 2)} | {_f(r.get('total_mae'), 2)} |"
        )
    out += [
        "",
        f"All {rep['n_all']} games (no market needed):",
        "",
        "| model | Brier | log loss | margin MAE | total MAE |",
        "|---|---|---|---|---|",
    ]
    for lab, r in rep["all_games"].items():
        out.append(
            f"| {lab} | {_f(r.get('brier'))} | {_f(r.get('log_loss'))} | "
            f"{_f(r.get('margin_mae'), 2)} | {_f(r.get('total_mae'), 2)} |"
        )
    out += [
        "",
        "### Paired differences (95% day-clustered bootstrap CI; negative = first is better; "
        "accuracy in points, positive = first is better)",
        "",
        "| comparison | Brier | log loss | accuracy | margin MAE | total MAE |",
        "|---|---|---|---|---|---|",
    ]
    for lab, d in rep["diffs"].items():
        out.append(
            f"| {lab} | {_ci(d['brier']) if 'brier' in d else '-'} | "
            f"{_ci(d['log_loss']) if 'log_loss' in d else '-'} | "
            f"{_ci(d['acc'], 1, 100) if 'acc' in d else '-'} | {_ci(d['margin_mae'], 3)} | "
            f"{_ci(d['total_mae'], 3) if 'total_mae' in d else '-'} |"
        )
    cal = rep["calibration"]
    labs = list(cal)
    out += [
        "",
        "### Calibration (n / mean predicted / observed home win rate)",
        "",
        "| bin | " + " | ".join(labs) + " |",
        "|---" * (len(labs) + 1) + "|",
    ]
    for i in range(10):
        cells = []
        for lab in labs:
            b = cal[lab]["bins"][i]
            cells.append("-" if not b["n"] else f"{b['n']} / {b['pred']:.2f} / {b['obs']:.2f}")
        lo = cal[labs[0]]["bins"][i]
        out.append(f"| {lo['lo']:.1f}-{lo['hi']:.1f} | " + " | ".join(cells) + " |")
    out.append("| ECE | " + " | ".join(f"{cal[lab]['ece']:.3f}" for lab in labs) + " |")
    out += [
        "",
        "### Declared breakdowns (college v1 vs the closing line)",
        "",
        "| slice | n | v1 LL | close LL | LL diff (CI) | v1 margin | close margin | "
        "margin diff (CI) | v1 total | close total |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for dim, vals in rep["breakdown"].items():
        for val, e in vals.items():
            mo, cl = e["model"], e["close"]
            out.append(
                f"| {dim}: {val} | {e['n']} | {_f(mo['log_loss'])} | {_f(cl['log_loss'])} | "
                f"{_ci(e['ll_diff']) if 'll_diff' in e else '-'} | {_f(mo['margin_mae'], 2)} | "
                f"{_f(cl['margin_mae'], 2)} | "
                f"{_ci(e['margin_diff'], 2) if 'margin_diff' in e else '-'} | "
                f"{_f(mo['total_mae'], 2)} | {_f(cl['total_mae'], 2)} |"
            )
    out += [
        "",
        "### Flat-bet check at -110 (BACKTEST, not a betting record)",
        "",
        "| market | edge >= t | bets | pushes | hit rate | Wilson 95% | day-clustered 95% | ROI |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in rep["betting"]:
        dc = b["day_ci"]
        out.append(
            f"| {'spread' if b['market'] == 'ats' else 'total'} | {b['threshold']:g} | "
            f"{b['bets']} | "
            f"{b['pushes']} | {_pct(b['hit_rate'])} | {_pct(b['ci_lo'])} - {_pct(b['ci_hi'])} | "
            f"{'-' if dc is None else f'{_pct(dc[0])} - {_pct(dc[1])}'} | {_pct(b['roi'])} |"
        )
    out.append(f"\nBreak-even at -110 is {BREAK_EVEN:.1%}.")
    sd = ship_decision(rep)
    out += [
        "",
        "### Ship rule (declared before fitting)",
        f"- Ship as context (beats Elo on log loss and margin MAE, CIs exclude 0, ECE <= 0.05): "
        f"**{'yes' if sd['ship_as_context'] else 'no'}** (ECE {sd['ece']:.3f})",
        f"- Betting edge (beats the close with CI and a flat-bet lower bound > 52.4%): "
        f"**{'yes' if sd['betting_edge'] else 'no'}**",
        f"- Frozen config: market blend weights {cfg.get('market_blend')}, "
        f"choice {cfg.get('choice')}",
    ]
    return "\n".join(out) + "\n"


def _pct(x):
    return "-" if x is None else f"{x:.1%}"


def render_validation(cfg: dict[str, Any]) -> str:
    v = cfg["validation"]
    out = [
        "## Validation (2025-12-01 to 2026-01-31, weekly walk-forward)",
        "",
        "Elo (raw, D1-vs-D1 games):",
        "",
        "| K | home edge | n | log loss |",
        "|---|---|---|---|",
    ]
    out += [
        f"| {r['k']:g} | {r['home_adv']:g} | {r['n']} | {r['log_loss']:.4f} |" for r in v["elo"]
    ]
    out += [
        "",
        "Ridge ratings (raw):",
        "",
        "| lambda | n | margin MAE | total MAE |",
        "|---|---|---|---|",
    ]
    out += [
        f"| {r['lam']:g} | {r['n']} | {r['margin_mae']:.3f} | {r['total_mae']:.3f} |"
        for r in v["ridge"]
    ]
    out += [
        "",
        "College model variants:",
        "",
        "| features | train min games | n | log loss | margin MAE | total MAE |",
        "|---|---|---|---|---|---|",
    ]
    out += [
        f"| {r['feature_set']} | {r['min_games']} | {r['n']} | {r['log_loss']:.4f} | "
        f"{r['margin_mae']:.3f} | {r['total_mae']:.3f} |"
        for r in v["models"]
    ]
    out += [
        "",
        "Validation summary (chosen model, market subset):",
        "",
        "| model | Brier | log loss | margin MAE | total MAE |",
        "|---|---|---|---|---|",
    ]
    for lab, r in v["summary"].items():
        out.append(
            f"| {lab} | {_f(r.get('brier'))} | {_f(r.get('log_loss'))} | "
            f"{_f(r.get('margin_mae'), 2)} | {_f(r.get('total_mae'), 2)} |"
        )
    out += [
        "",
        f"Chosen: Elo {cfg['elo']}, ridge lambda {cfg['ridge_lambda']}, "
        f"model {cfg['choice']}, market blend weights {cfg['market_blend']}.",
    ]
    return "\n".join(out) + "\n"


# ---------- CLI ----------


def _conf_cache(con, raw_dir: Path, cache: Path | None) -> dict[str, bool]:
    if cache and cache.exists():
        return json.loads(cache.read_text())
    gids = [g[0] for g in _season_games(con, SEASON)]
    conf = conference_flags(raw_dir, gids)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(conf))
    return conf


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["validate", "holdout", "report"])
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--raw", type=Path, default=config.DATA_DIR / "raw/espn/ncaab/summary")
    ap.add_argument("--conf-cache", type=Path, help="JSON cache of conference flags")
    ap.add_argument("--config", type=Path, required=True, help="frozen config JSON")
    ap.add_argument("--out", type=Path, help="Markdown output")
    ap.add_argument("--preds", type=Path, help="holdout per-game predictions JSON")
    args = ap.parse_args(argv)
    if args.step == "report":
        cfg = json.loads(args.config.read_text())
        md = render_markdown(holdout_report(json.loads(args.preds.read_text()), cfg), cfg)
        print(md)
        if args.out:
            args.out.write_text(md)
        return 0
    if args.step == "holdout":
        marker = args.config.with_suffix(".holdout-scored")
        if marker.exists():
            print(f"holdout already scored ({marker}); refusing to score it again", file=sys.stderr)
            return 2
        if not args.preds:
            print("--preds is required for the holdout step", file=sys.stderr)
            return 2
    con = duckdb.connect(str(args.db), read_only=True)
    try:
        conf = _conf_cache(con, args.raw, args.conf_cache)
        if args.step == "validate":
            cfg = validate(con, conf)
            args.config.parent.mkdir(parents=True, exist_ok=True)
            args.config.write_text(json.dumps(cfg, indent=1))
            md = render_validation(cfg)
            print(md)
            if args.out:
                args.out.write_text(md)
            return 0
        cfg = json.loads(args.config.read_text())
        preds = holdout_predictions(con, cfg, conf)
    finally:
        con.close()
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
