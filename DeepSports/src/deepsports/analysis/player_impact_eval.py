"""Backtest and market tests for player impact features (model v1.2 candidate), NBA.

    # 1) method choice on the train period only (test seasons 2024-2025), prints no later season
    DEEPSPORTS_DB=/path/copy.duckdb uv run python -m deepsports.analysis.player_impact select
    # 2) everything, including the locked 2025-26 holdout, with the chosen method
    DEEPSPORTS_DB=/path/copy.duckdb uv run python -m deepsports.analysis.player_impact report \\
        --out /Volumes/ExFATStorag/DeepSports/reports/player-impact/report.md [--scramble]

Results and the decision: `docs/results/2026-11-11-player-impact.md` (negative result: research
tooling only; the pre-registered plan is inlined there). In short: same rows/folds as
compare.py (monthly walk-forward); v1.2 = v1.1 + IMPACT_FEATURES (fixed C = 1, alpha = 10);
rating method picked by the lowest 2024-25 v1.2 margin MAE; holdout = 2026; season 2027
reported separately ("live"). Paired per-game deltas get normal and day-clustered 95% CIs (one
cluster per slate date); the day-clustered intervals govern decisions, including a
slate-cluster bootstrap for line-move correlations. Oracle rows use who actually played:
LEAKED, ceiling only.

Opens the warehouse read-only ($DEEPSPORTS_DB or config.DB_PATH).
"""

import argparse
import math
import random
import sys
import warnings
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from deepsports import config
from deepsports.analysis.backtest import BREAK_EVEN, WIN_PAYOUT, walk_forward, wilson
from deepsports.analysis.compare import _ll1, paired_deltas
from deepsports.analysis.features import build_features, closing_lines
from deepsports.analysis.market import sane_spread
from deepsports.analysis.metrics import devig_probability
from deepsports.analysis.model import (
    TOTAL_FEATURES,
    V11_TOTAL_FEATURES,
    V11_WIN_FEATURES,
    WIN_FEATURES,
    ModelV1,
    make_model,
)
from deepsports.analysis.player_impact import (
    CHOSEN_METHOD,
    FULL_FEATURE,
    IMPACT_FEATURES,
    METHODS,
    ORACLE_FEATURES,
    Data,
    ImpactEngine,
    impact_features,
    load_data,
    slate_date,
    snapshot_out,
    with_impact,
)
from deepsports.analysis.report import _f, _pct, _table

TRAIN_SEASONS = (2024, 2025)
HOLDOUT_SEASONS = (2026,)
LIVE_SEASONS = (2027,)
PERIODS = {
    "train 2024-25": TRAIN_SEASONS,
    "holdout 2026": HOLDOUT_SEASONS,
    "live 2027": LIVE_SEASONS,
}
OPEN_RULE_T = 2.0  # pre-registered single threshold, points vs the opening spread
SELECT_TIE = 0.005  # margin-MAE tie band for the selection rule


def _factory(win: list[str], total: list[str]) -> Callable[[], ModelV1]:
    return lambda: ModelV1(
        win_features=list(win), margin_features=list(win), total_features=list(total)
    )


MODELS: dict[str, Callable[[], ModelV1]] = {
    "v1.0": lambda: make_model("v1.0"),
    "v1.1": lambda: make_model("v1.1"),
    "v1.2": _factory(V11_WIN_FEATURES + IMPACT_FEATURES, V11_TOTAL_FEATURES),
    "oracle (LEAKED)": _factory(V11_WIN_FEATURES + ORACLE_FEATURES, V11_TOTAL_FEATURES),
    "v1.0+impact": _factory(WIN_FEATURES + IMPACT_FEATURES, TOTAL_FEATURES),
    # Post-hoc diagnostics (added after the first holdout run, not part of the decision):
    # is the gain team strength (full-strength diff, no availability) or injury information?
    "v1.1+full only": _factory(V11_WIN_FEATURES + [FULL_FEATURE], V11_TOTAL_FEATURES),
    "v1.1+missing only": _factory(V11_WIN_FEATURES + ["imp_missing_diff"], V11_TOTAL_FEATURES),
}
EARLY_MONTHS = (10, 11)  # diagnostic split: October-November vs the rest of the season


# ---------- statistics ----------


def clustered_ci(values: Sequence[float], clusters: Sequence[Any]) -> dict[str, float | None]:
    """Mean with a cluster-robust (CR1) 95% normal interval: games on the same slate share
    noise (same-night news, refs, market moves), so they are not independent."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "lo": None, "hi": None}
    m = sum(values) / n
    sums: dict[Any, float] = defaultdict(float)
    for v, c in zip(values, clusters, strict=True):
        sums[c] += v - m
    g = len(sums)
    var = sum(s * s for s in sums.values()) / (n * n) * (g / (g - 1) if g > 1 else 1.0)
    h = 1.96 * math.sqrt(var)
    return {"n": n, "mean": m, "lo": m - h, "hi": m + h}


def pearson_ci(x: Sequence[float], y: Sequence[float]) -> dict[str, float | None]:
    """Pearson r with a Fisher-z 95% interval and the OLS slope of y on x."""
    pairs = [(a, b) for a, b in zip(x, y, strict=True) if not (math.isnan(a) or math.isnan(b))]
    n = len(pairs)
    if n < 4:
        return {"n": n, "r": None, "lo": None, "hi": None, "slope": None}
    xa = np.array([p[0] for p in pairs])
    ya = np.array([p[1] for p in pairs])
    if xa.std() == 0 or ya.std() == 0:
        return {"n": n, "r": None, "lo": None, "hi": None, "slope": None}
    r = float(np.corrcoef(xa, ya)[0, 1])
    z, se = math.atanh(max(min(r, 0.999999), -0.999999)), 1 / math.sqrt(n - 3)
    slope = float(np.polyfit(xa, ya, 1)[0])
    return {"n": n, "r": r, "lo": math.tanh(z - 1.96 * se), "hi": math.tanh(z + 1.96 * se),
            "slope": slope}  # fmt: skip


def cluster_boot_r(
    x: Sequence[float],
    y: Sequence[float],
    clusters: Sequence[Any],
    reps: int = 2000,
    seed: int = 0,
) -> tuple[float | None, float | None]:
    """Percentile 95% interval for Pearson r, resampling whole clusters (slates) with
    replacement. Games on one slate share news and market moves; this is the interval that
    governs decisions (the Fisher interval assumes independent games and is too narrow)."""
    by: dict[Any, list[tuple[float, float]]] = defaultdict(list)
    for a, b, c in zip(x, y, clusters, strict=True):
        if not (math.isnan(a) or math.isnan(b)):
            by[c].append((a, b))
    keys = sorted(by)
    if len(keys) < 4:
        return None, None
    rng = random.Random(seed)
    rs = []
    for _ in range(reps):
        pts = [pt for k in rng.choices(keys, k=len(keys)) for pt in by[k]]
        xa = np.array([p[0] for p in pts])
        ya = np.array([p[1] for p in pts])
        if xa.std() > 0 and ya.std() > 0:
            rs.append(float(np.corrcoef(xa, ya)[0, 1]))
    if not rs:
        return None, None
    lo, hi = np.percentile(rs, [2.5, 97.5])
    return float(lo), float(hi)


# ---------- data ----------


def opening_lines(con: duckdb.DuckDBPyConnection, league: str = "nba") -> dict[str, dict]:
    """game_id -> earliest `opening` spread_home (sane only, else None) and vig-free home
    probability. No fallback to a later row: the warehouse holds exactly one `opening` row per
    game (checked 2026-11-11), so an insane earliest spread has nothing to fall back to."""
    ok = sane_spread(league).format(col="o.spread_home")
    rows = con.execute(
        f"""SELECT o.game_id, CASE WHEN {ok} THEN o.spread_home END,
                   o.home_moneyline, o.away_moneyline
            FROM odds_snapshots o JOIN games g USING (game_id)
            WHERE o.source = 'opening' AND g.league = ?
            QUALIFY row_number() OVER (PARTITION BY o.game_id ORDER BY o.captured_at) = 1""",
        [league],
    ).fetchall()
    return {g: {"spread_home": s, "p_home": devig_probability(h, a)} for g, s, h, a in rows}


def prepare(con: duckdb.DuckDBPyConnection, methods: Sequence[str]) -> dict[str, Any]:
    """Feature rows (with v1.1 player columns), box data and impact features per method."""
    rows = build_features(con, include_players=True)
    data = load_data(con)
    feats = {m: impact_features(data, m, oracle=True) for m in methods}
    return {"rows": rows, "data": data, "feats": feats, "open": opening_lines(con)}


def predictions(
    rows: list[dict[str, Any]], names: Sequence[str], max_season: int | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Walk-forward predictions per model on the same rows and folds. With `max_season`, rows
    of later seasons are dropped before anything is fitted or predicted."""
    if max_season is not None:
        rows = [r for r in rows if r["season"] <= max_season]
    by_id = {r["game_id"]: r for r in rows}
    out = {}
    for name in names:
        preds = walk_forward(rows, model_factory=MODELS[name])["predictions"]
        for p in preds:
            f = by_id[p["game_id"]]["features"]
            p["slate"] = slate_date(p["start_time_utc"])
            extra = [FULL_FEATURE, "miss_share_diff", "form_net_diff"]
            for k in IMPACT_FEATURES + ORACLE_FEATURES + extra:
                p[k] = f.get(k, math.nan)
        out[name] = preds
    return out


# ---------- scoring ----------


def _period(preds: list[dict[str, Any]], seasons: Sequence[int]) -> list[dict[str, Any]]:
    return [p for p in preds if p["season"] in seasons]


def overall(preds: list[dict[str, Any]]) -> dict[str, float | None]:
    if not preds:
        return {"n": 0, "brier": None, "log_loss": None, "margin_mae": None, "total_mae": None}
    n = len(preds)
    return {
        "n": n,
        "brier": sum((p["p_home_win"] - p["home_win"]) ** 2 for p in preds) / n,
        "log_loss": sum(_ll1(p["p_home_win"], p["home_win"]) for p in preds) / n,
        "margin_mae": sum(abs(p["pred_home_margin"] - p["home_margin"]) for p in preds) / n,
        "total_mae": sum(abs(p["pred_total"] - p["total"]) for p in preds) / n,
    }


def paired(base: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-game (new - base) with day-clustered CIs (plus compare.paired_deltas' normal CIs)."""
    b = {p["game_id"]: p for p in base}
    pairs = [(b[p["game_id"]], p) for p in new if p["game_id"] in b]
    cl = [x0["slate"] for x0, _ in pairs]
    d = defaultdict(list)
    for x0, x1 in pairs:
        y, m, t = x0["home_win"], x0["home_margin"], x0["total"]
        d["brier"].append((x1["p_home_win"] - y) ** 2 - (x0["p_home_win"] - y) ** 2)
        d["log_loss"].append(_ll1(x1["p_home_win"], y) - _ll1(x0["p_home_win"], y))
        d["margin_mae"].append(abs(x1["pred_home_margin"] - m) - abs(x0["pred_home_margin"] - m))
        d["total_mae"].append(abs(x1["pred_total"] - t) - abs(x0["pred_total"] - t))
    return {
        "n": len(pairs),
        "clustered": {k: clustered_ci(v, cl) for k, v in d.items()},
        "normal": paired_deltas([x0 for x0, _ in pairs], [x1 for _, x1 in pairs]),
    }


def vs_market(preds: list[dict[str, Any]], lines: dict[str, dict], label: str) -> dict[str, Any]:
    """Model vs a market line on the games that have it: Brier vs the vig-free moneyline and
    margin MAE vs -spread_home, with day-clustered CIs of the per-game (model - market) gap."""
    pw = [p for p in preds if (lines.get(p["game_id"]) or {}).get("p_home") is not None]
    ps = [p for p in preds if (lines.get(p["game_id"]) or {}).get("spread_home") is not None]
    db = [
        (p["p_home_win"] - p["home_win"]) ** 2
        - (lines[p["game_id"]]["p_home"] - p["home_win"]) ** 2
        for p in pw
    ]
    dm = [
        abs(p["pred_home_margin"] - p["home_margin"])
        - abs(-lines[p["game_id"]]["spread_home"] - p["home_margin"])
        for p in ps
    ]
    return {
        "line": label,
        "n_ml": len(pw),
        "model_brier": sum((p["p_home_win"] - p["home_win"]) ** 2 for p in pw) / len(pw)
        if pw
        else None,
        "mkt_brier": sum((lines[p["game_id"]]["p_home"] - p["home_win"]) ** 2 for p in pw) / len(pw)
        if pw
        else None,
        "d_brier": clustered_ci(db, [p["slate"] for p in pw]),
        "n_spread": len(ps),
        "model_mae": sum(abs(p["pred_home_margin"] - p["home_margin"]) for p in ps) / len(ps)
        if ps
        else None,
        "mkt_mae": sum(abs(-lines[p["game_id"]]["spread_home"] - p["home_margin"]) for p in ps)
        / len(ps)
        if ps
        else None,
        "d_mae": clustered_ci(dm, [p["slate"] for p in ps]),
    }


def open_rule(
    preds: list[dict[str, Any]],
    opening: dict[str, dict],
    closing: dict[str, dict],
    t: float = OPEN_RULE_T,
) -> dict[str, Any]:
    """The pre-registered bet: the model's side vs the OPENING spread when |pred margin -
    (-open spread)| >= t, graded against the opening spread (push refunded, -110). CLV = share
    of bets whose closing spread moved toward our side (ties excluded)."""
    res, clv, clv_n = [], 0, 0
    for p in preds:
        o = (opening.get(p["game_id"]) or {}).get("spread_home")
        if o is None:
            continue
        edge = p["pred_home_margin"] + o
        if abs(edge) < t or edge == 0:
            continue
        side = 1 if edge > 0 else -1
        cover = p["home_margin"] + o
        res.append(0 if cover == 0 else (1 if side * cover > 0 else -1))
        c = (closing.get(p["game_id"]) or {}).get("spread_home")
        if c is not None and c != o:
            clv_n += 1
            clv += int((side > 0 and c < o) or (side < 0 and c > o))
    w, lo, pu = res.count(1), res.count(-1), res.count(0)
    n = w + lo
    ci = wilson(w, n)
    return {
        "bets": n,
        "wins": w,
        "pushes": pu,
        "hit": w / n if n else None,
        "lo": ci[0],
        "hi": ci[1],
        "roi": (w * WIN_PAYOUT - lo) / n if n else None,
        "clv": clv / clv_n if clv_n else None,
        "clv_n": clv_n,
    }


def movement(
    preds: list[dict[str, Any]], opening: dict[str, dict], closing: dict[str, dict], key: str
) -> dict[str, Any]:
    """Correlation of a feature with the open->close spread move (close - open, home side):
    Fisher CI (`lo`/`hi`) and the slate-cluster bootstrap CI (`clo`/`chi`, governs)."""
    xs, ys, cl = [], [], []
    for p in preds:
        o = (opening.get(p["game_id"]) or {}).get("spread_home")
        c = (closing.get(p["game_id"]) or {}).get("spread_home")
        if o is None or c is None:
            continue
        xs.append(p[key])
        ys.append(c - o)
        cl.append(p["slate"])
    clo, chi = cluster_boot_r(xs, ys, cl)
    return pearson_ci(xs, ys) | {"clo": clo, "chi": chi}


# ---------- selection (train period only) ----------


def select(prep: dict[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered rule on test seasons <= 2025 only (later rows are dropped
    before fitting): lowest v1.2 margin MAE, ties within SELECT_TIE broken by log loss."""
    last = max(TRAIN_SEASONS)
    base = predictions(prep["rows"], ["v1.1"], max_season=last)["v1.1"]
    table = [{"method": "(v1.1 baseline)", **overall(base)}]
    for m, feats in prep["feats"].items():
        rows = with_impact(prep["rows"], feats)
        p = predictions(rows, ["v1.2"], max_season=last)["v1.2"]
        d = paired(base, p)["clustered"]
        table.append(
            {"method": m, **overall(p), "d_margin": d.get("margin_mae"), "d_brier": d.get("brier")}
        )
    cands = [r for r in table if r["method"] in METHODS and r["margin_mae"] is not None]
    if not cands:
        return {"table": table, "chosen": None, "seasons": TRAIN_SEASONS}
    best = min(r["margin_mae"] for r in cands)
    tied = [r for r in cands if r["margin_mae"] <= best + SELECT_TIE]
    chosen = min(tied, key=lambda r: r["log_loss"])["method"]
    assert all(p["season"] <= last for p in base)
    return {"table": table, "chosen": chosen, "seasons": TRAIN_SEASONS}


def select_report(sel: dict[str, Any], md: bool = True) -> str:
    rows = []
    for r in sel["table"]:
        dm = r.get("d_margin")
        db = r.get("d_brier")
        rows.append(
            [
                r["method"],
                str(r["n"]),
                _f(r["brier"], 4),
                _f(r["log_loss"], 4),
                _f(r["margin_mae"], 3),
                _ci(dm, 3) if dm else "-",
                _ci(db, 4) if db else "-",
            ]
        )
    head = ["method", "n", "Brier", "log loss", "margin MAE", "d margin vs v1.1", "d Brier"]
    return "\n".join(
        [
            f"Selection on test seasons {sel['seasons']} only (v1.2 = v1.1 + impact features).",
            *_table(head, rows, md),
            f"Chosen by the pre-registered rule: **{sel['chosen']}**",
        ]
    )


# ---------- pre-tip snapshot games ----------


def pretip_table(con: duckdb.DuckDBPyConnection, data: Data, method: str) -> list[dict]:
    """Games with a pre-tip injury snapshot for both teams: missing impact with the real OUT
    list vs the proxy, and (completed games) the oracle, the result and the closing spread."""
    outs = snapshot_out(con)
    eng = ImpactEngine(data, method)
    abbr = dict(
        con.execute("SELECT team_id, abbreviation FROM teams WHERE league='nba'").fetchall()
    )
    close = closing_lines(con)
    out = []
    for gid in sorted((g for g in outs if g in data.by_id), key=lambda g: (data.by_id[g].start, g)):
        g = data.by_id[gid]
        snap = eng.game(gid, out_players=outs[gid])
        prox = eng.game(gid)
        orc = eng.game(gid, oracle=True) if g.state == "post" else None
        listed = sum(p["out"] for s in ("home", "away") for p in snap[s]["players"])
        out.append(
            {
                "game_id": gid,
                "date": slate_date(g.start).isoformat(),
                "matchup": f"{abbr.get(g.away, g.away)} @ {abbr.get(g.home, g.home)}",
                "state": g.state,
                "out_listed": len(outs[gid]),
                "out_in_rotation": listed,
                "snap_home": snap["home"]["missing"],
                "snap_away": snap["away"]["missing"],
                "snap_diff": snap["home"]["missing"] - snap["away"]["missing"],
                "proxy_diff": prox["home"]["missing"] - prox["away"]["missing"],
                "oracle_diff": None
                if orc is None
                else orc["home"]["missing"] - orc["away"]["missing"],
                "margin": g.margin,
                "close_spread": (close.get(gid) or {}).get("spread_home"),
            }
        )
    return out


# ---------- scrambled box scores (real-data leakage check) ----------


def _scramble_box(data: Data, game_ids: Sequence[str]) -> Data:
    """A copy whose listed games have rewritten box scores: DNP flipped, minutes 48 - m (30
    for former DNPs), plus-minus negated."""
    box = dict(data.box)
    for gid in game_ids:
        g = data.by_id[gid]
        for t in (g.home, g.away):
            box[(gid, t)] = {
                a: (not ln[0], 48.0 - ln[1] if ln[0] else 30.0, ln[2], -ln[3])
                for a, ln in data.box[(gid, t)].items()
            }
    return Data([*data.games], box)


def scramble_check(data: Data, method: str, n_slates: int = 40, seed: int = 0) -> dict:
    """Pick `n_slates` random slates (seasons 2024-2026) and, one slate at a time, rewrite the
    box scores of EVERY game on it. Games of one slate can't see each other (shared as-of), so
    each rewritten game's own proxy features must be identical; its oracle features (LEAKED by
    design) and the teams' next games should change, so the check has teeth.

    One slate at a time because ratings pool all teams over two seasons: a rewritten game
    legitimately changes every later game's ratings, so rewriting games on many dates at once
    cannot isolate a game's effect on itself (the v1.1 check's one-per-team-season design
    works only for same-team-season features)."""
    rng = random.Random(seed)
    slates: dict[Any, list[str]] = defaultdict(list)
    for g in data.games:
        if (
            g.state == "post"
            and g.season in (2024, 2025, 2026)
            and data.box.get((g.game_id, g.home))
            and data.box.get((g.game_id, g.away))
        ):
            slates[slate_date(g.start)].append(g.game_id)
    picked = rng.sample(sorted(slates), min(n_slates, len(slates)))
    tot = own = orc = nxt_n = nxt = 0
    for d in picked:
        gids = slates[d]
        nexts = []
        for gid in gids:
            g = data.by_id[gid]
            for t in (g.home, g.away):
                ids = [data.games[i].game_id for i in data.team_idx[(t, g.season)]]
                k = ids.index(gid)
                if k + 1 < len(ids):
                    nexts.append(ids[k + 1])
        want = sorted(set(gids + nexts))
        base = impact_features(data, method, oracle=True, game_ids=want)
        scr = impact_features(_scramble_box(data, gids), method, oracle=True, game_ids=want)

        def same(a: dict, b: dict, names: list[str]) -> bool:
            return all((math.isnan(a[n]) and math.isnan(b[n])) or a[n] == b[n] for n in names)

        names = [*IMPACT_FEATURES, FULL_FEATURE]
        tot += len(gids)
        own += sum(not same(base[g], scr[g], names) for g in gids)
        orc += sum(not same(base[g], scr[g], ORACLE_FEATURES) for g in gids)
        nxt_n += len(nexts)
        nxt += sum(not same(base[g], scr[g], names) for g in nexts)
    return {
        "slates": len(picked),
        "games": tot,
        "own_changed": own,
        "oracle_changed": orc,
        "next_games": nxt_n,
        "next_changed": nxt,
    }


# ---------- full evaluation ----------


def evaluate(
    con: duckdb.DuckDBPyConnection, method: str = CHOSEN_METHOD, scramble: bool = False
) -> dict[str, Any]:
    prep = prepare(con, list(METHODS))
    sel = select(prep)
    note = None
    if method != sel["chosen"]:
        note = (
            f"WARNING: scoring method {method!r}, but the pre-registered rule chose "
            f"{sel['chosen']!r} on this data. These numbers are not the pre-registered result."
        )
        warnings.warn(note, stacklevel=2)
    rows = with_impact(prep["rows"], prep["feats"][method], oracle=True)
    preds = predictions(rows, list(MODELS))
    closing = closing_lines(con)
    opening = prep["open"]
    res: dict[str, Any] = {"method": method, "selection": sel, "periods": {}, "note": note}

    # Multiplicity check: v1.2 - v1.1 per candidate method in every period (only the chosen
    # one counts; the others show how much the choice itself could be luck).
    base = preds["v1.1"]
    res["per_method"] = {}
    for m, feats in prep["feats"].items():
        pm = preds["v1.2"] if m == method else predictions(
            with_impact(prep["rows"], feats), ["v1.2"]
        )["v1.2"]  # fmt: skip
        res["per_method"][m] = {
            label: paired(_period(base, ss), _period(pm, ss))["clustered"]
            for label, ss in PERIODS.items()
        }

    def early(p: dict[str, Any]) -> bool:
        return p["slate"].month in EARLY_MONTHS

    for label, seasons in PERIODS.items():
        pp = {k: _period(v, seasons) for k, v in preds.items()}
        res["periods"][label] = {
            "overall": {k: overall(v) for k, v in pp.items()},
            "v12_vs_v11": paired(pp["v1.1"], pp["v1.2"]),
            "oracle_vs_v11": paired(pp["v1.1"], pp["oracle (LEAKED)"]),
            "v10imp_vs_v10": paired(pp["v1.0"], pp["v1.0+impact"]),
            "diag": {
                k: paired(pp["v1.1"], pp[k])
                for k in ("v1.1+full only", "v1.1+missing only", "v1.2")
            }
            | {
                f"v1.2 {part}": paired(
                    [p for p in pp["v1.1"] if early(p) == is_early],
                    [p for p in pp["v1.2"] if early(p) == is_early],
                )
                for part, is_early in (("Oct-Nov", True), ("Dec-Jun", False))
            },
            "market": {
                k: [vs_market(pp[k], closing, "closing"), vs_market(pp[k], opening, "opening")]
                for k in ("v1.1", "v1.2", "oracle (LEAKED)")
            },
            "movement": {
                k: movement(pp["v1.2"], opening, closing, k)
                for k in (
                    "imp_missing_diff",
                    "imp_avail_diff",
                    "miss_share_diff",
                    "orc_missing_diff",
                )  # fmt: skip
            },
            "open_rule": {
                k: open_rule(pp[k], opening, closing) for k in ("v1.1", "v1.2", "oracle (LEAKED)")
            },
            "corr": {
                k: pearson_ci([p[k] for p in pp["v1.2"]], [p["home_margin"] for p in pp["v1.2"]])
                for k in (
                    "imp_avail_diff",
                    "imp_missing_diff",
                    "orc_missing_diff",
                    "form_net_diff",
                )  # fmt: skip
            },
        }
    feats_all = [r["features"] for r in rows if r["state"] == "post" and r["season"] >= 2024]
    res["feature_corr"] = {
        (a, b): pearson_ci([f[a] for f in feats_all], [f[b] for f in feats_all])["r"]
        for a, b in (
            ("imp_avail_diff", "form_net_diff"),
            ("imp_avail_diff", "elo_diff"),
            ("imp_missing_diff", "miss_share_diff"),
            ("imp_missing_diff", "orc_missing_diff"),
        )
    }
    res["coverage"] = {
        k: sum(not math.isnan(f[k]) for f in feats_all) / len(feats_all) if feats_all else None
        for k in IMPACT_FEATURES
    }
    res["pretip"] = pretip_table(con, prep["data"], method)
    res["scramble"] = scramble_check(prep["data"], method) if scramble else None
    res["generated"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return res


# ---------- report ----------


def _ci(d: dict[str, Any] | None, nd: int) -> str:
    if not d or d.get("mean") is None:
        return "-"
    return f"{d['mean']:+.{nd}f} ({d['lo']:+.{nd}f} to {d['hi']:+.{nd}f})"


def _r(d: dict[str, Any]) -> str:
    if d.get("r") is None:
        return "-"
    return f"{d['r']:+.3f} ({d['lo']:+.3f} to {d['hi']:+.3f}), slope {d['slope']:+.3f}, n={d['n']}"


def report(res: dict[str, Any], md: bool = True) -> str:
    out = [
        f"Generated {res['generated']}. Rating method: {res['method']}. Periods: "
        + ", ".join(f"{k} = seasons {v}" for k, v in PERIODS.items()),
        "",
        *([f"**{res['note']}**", ""] if res.get("note") else []),
        "## Method selection (train period only)",
        select_report(res["selection"], md),
        "",
        "## Multiplicity check: v1.2 - v1.1 per candidate method (day-clustered 95% CI)",
    ]
    rows = []
    for m, per in res.get("per_method", {}).items():
        for label, c in per.items():
            rows.append(
                [
                    m + (" (chosen)" if m == res["method"] else ""),
                    label,
                    _ci(c.get("brier"), 4),
                    _ci(c.get("margin_mae"), 3),
                ]  # fmt: skip
            )
    out += _table(["method", "period", "Brier", "margin MAE"], rows, md)
    out += [
        "",
        "## Model scores per period",
    ]
    rows = []
    for label, per in res["periods"].items():
        for name, o in per["overall"].items():
            rows.append(
                [
                    label,
                    name,
                    str(o["n"]),
                    _f(o["brier"], 4),
                    _f(o["log_loss"], 4),
                    _f(o["margin_mae"], 3),
                    _f(o["total_mae"], 3),
                ]  # fmt: skip
            )
    out += _table(
        ["period", "model", "n", "Brier", "log loss", "margin MAE", "total MAE"], rows, md
    )
    for key, title in (
        ("v12_vs_v11", "Paired per-game change, v1.2 - v1.1 (negative = v1.2 better)"),
        ("oracle_vs_v11", "Oracle ceiling, oracle - v1.1 (LEAKED: who actually played)"),
        ("v10imp_vs_v10", "Diagnostic: (v1.0 + impact) - v1.0"),
    ):
        out += ["", f"## {title}", "Day-clustered 95% CI; normal CI in brackets for margin MAE."]
        rows = []
        for label, per in res["periods"].items():
            d = per[key]
            c, n = d["clustered"], d["normal"]
            rows.append(
                [
                    label,
                    str(d["n"]),
                    _ci(c.get("brier"), 4),
                    _ci(c.get("log_loss"), 4),
                    _ci(c.get("margin_mae"), 3) + f" [{_ci(n.get('margin_mae'), 3)}]",
                    _ci(c.get("total_mae"), 3),
                ]  # fmt: skip
            )
        out += _table(["period", "n", "Brier", "log loss", "margin MAE", "total MAE"], rows, md)
    out += [
        "",
        "## Post-hoc diagnostics (not part of the decision): where does the gain come from?",
        "Paired vs v1.1, day-clustered 95% CI. `full only` = full-strength diff (ratings, no "
        "availability); `missing only` = missing impact alone; v1.2 split by month.",
    ]
    rows = []
    for label, per in res["periods"].items():
        for name, d in per["diag"].items():
            c = d["clustered"]
            rows.append(
                [
                    label,
                    name,
                    str(d["n"]),
                    _ci(c.get("brier"), 4),
                    _ci(c.get("log_loss"), 4),
                    _ci(c.get("margin_mae"), 3),
                ]  # fmt: skip
            )
    out += _table(["period", "variant", "n", "Brier", "log loss", "margin MAE"], rows, md)
    out += ["", "## Against the market (model - market per game, day-clustered 95% CI)"]
    rows = []
    for label, per in res["periods"].items():
        for name, pair in per["market"].items():
            for m in pair:
                rows.append(
                    [
                        label,
                        name,
                        m["line"],
                        str(m["n_ml"]),
                        _f(m["model_brier"], 4),
                        _f(m["mkt_brier"], 4),
                        _ci(m["d_brier"], 4),
                        str(m["n_spread"]),
                        _f(m["model_mae"], 3),
                        _f(m["mkt_mae"], 3),
                        _ci(m["d_mae"], 3),
                    ]  # fmt: skip
                )
    out += _table(
        [
            "period",
            "model",
            "line",
            "n ML",
            "model B",
            "mkt B",
            "d Brier",
            "n spr",
            "model MAE",
            "mkt MAE",
            "d MAE",
        ],  # fmt: skip
        rows,
        md,
    )
    out += [
        "",
        "## Does the feature predict the open -> close line move? (close - open spread_home)",
        "Expected sign: positive (home missing more -> line moves toward the away team).",
    ]
    rows = []
    for label, per in res["periods"].items():
        for k, d in per["movement"].items():
            boot = "-" if d.get("clo") is None else f"{d['clo']:+.3f} to {d['chi']:+.3f}"
            rows.append([label, k + (" (LEAKED)" if k.startswith("orc") else ""), _r(d), boot])
    out += _table(
        ["period", "feature", "r (Fisher 95% CI), slope pts/pt", "slate-bootstrap 95% CI"],
        rows,
        md,
    )
    out += [
        "",
        f"## Pre-registered rule: model side vs the OPENING spread when |edge| >= {OPEN_RULE_T}",
        f"Graded against the opening spread at -110; break-even {_pct(BREAK_EVEN)}. CLV = "
        "share of bets where the closing spread moved toward our side.",
    ]
    rows = []
    for label, per in res["periods"].items():
        for name, b in per["open_rule"].items():
            rows.append(
                [
                    label,
                    name,
                    str(b["bets"]),
                    _pct(b["hit"]),
                    f"{_pct(b['lo'])}-{_pct(b['hi'])}",
                    _pct(b["roi"]),
                    f"{_pct(b['clv'])} (n={b['clv_n']})",
                ]  # fmt: skip
            )
    out += _table(["period", "model", "bets", "hit", "95% CI", "ROI", "CLV"], rows, md)
    out += ["", "## Feature sanity (correlation with the home margin, per period)"]
    rows = []
    for label, per in res["periods"].items():
        for k, d in per["corr"].items():
            rows.append([label, k, _r(d)])
    out += _table(["period", "feature", "r with margin"], rows, md)
    out += ["", "Feature-feature correlations (seasons >= 2024): " + "; ".join(
        f"{a} ~ {b}: {_f(v, 3)}" for (a, b), v in res["feature_corr"].items()
    ), "Coverage (non-NaN share, seasons >= 2024): " + ", ".join(
        f"{k} {_pct(v)}" for k, v in res["coverage"].items()
    )]  # fmt: skip
    out += [
        "",
        "## Pre-tip snapshot games (real OUT lists; descriptive, tiny n)",
        "Missing impact in points (home - away unless noted). `oracle` = who actually sat "
        "(LEAKED, completed games only). close = closing spread_home.",
    ]
    rows = [
        [
            r["date"],
            r["matchup"],
            r["state"],
            f"{r['out_listed']}/{r['out_in_rotation']}",
            _f(r["snap_home"], 2),
            _f(r["snap_away"], 2),
            _f(r["snap_diff"], 2),
            _f(r["proxy_diff"], 2),
            _f(r["oracle_diff"], 2),
            _f(r["margin"], 0),
            _f(r["close_spread"], 1),
        ]  # fmt: skip
        for r in res["pretip"]
    ]
    out += _table(
        [
            "date",
            "game",
            "state",
            "Out listed/in rot.",
            "home miss",
            "away miss",
            "snap diff",
            "proxy diff",
            "oracle diff",
            "margin",
            "close",
        ],  # fmt: skip
        rows,
        md,
    )
    post = [r for r in res["pretip"] if r["state"] == "post"]
    if post:
        pc = pearson_ci([r["snap_diff"] for r in post], [r["oracle_diff"] for r in post])
        px = pearson_ci([r["proxy_diff"] for r in post], [r["oracle_diff"] for r in post])
        out += [
            "",
            f"Completed snapshot games: {len(post)}. Agreement with the oracle missing diff: "
            f"snapshot r = {_r(pc)}; proxy r = {_r(px)}.",
        ]
    if res.get("scramble"):
        s = res["scramble"]
        out += [
            "",
            "## Scrambled box scores (real data)",
            f"{s['slates']} random slates, every game on a slate rewritten together, one slate "
            f"at a time ({s['games']} games). Own proxy features changed: "
            f"{s['own_changed']}/{s['games']} (must be 0). Own oracle features changed: "
            f"{s['oracle_changed']}/{s['games']} (leaked by design). Teams' next games changed: "
            f"{s['next_changed']}/{s['next_games']}.",
        ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stage", choices=["select", "report"])
    ap.add_argument("--out", type=Path, help="write a Markdown report here")
    ap.add_argument("--db", type=Path, default=config.DB_PATH, help="warehouse path")
    ap.add_argument("--method", default=CHOSEN_METHOD, choices=list(METHODS))
    ap.add_argument("--scramble", action="store_true", help="also run the scramble check")
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"warehouse not found: {args.db}", file=sys.stderr)
        return 1
    con = duckdb.connect(str(args.db), read_only=True)
    try:
        if args.stage == "select":
            text = select_report(select(prepare(con, list(METHODS))), md=True) + "\n"
        else:
            text = report(evaluate(con, args.method, args.scramble), md=True)
    finally:
        con.close()
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
