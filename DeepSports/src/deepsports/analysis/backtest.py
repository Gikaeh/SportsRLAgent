"""Walk-forward backtest of model v1 against Elo, simple baselines, and the closing line.

    uv run python -m deepsports.analysis.backtest --out /path/to/backtest.md [--refit season]

Folds: for each test season (after the Elo burn-in season and at least one training season),
the season is split into blocks (calendar months by default, or the whole season). Each block
is predicted by a model trained only on games that tipped off before the block starts. The
fold log records the latest training game and the earliest test game so this can be checked.

Opens the warehouse read-only ($DEEPSPORTS_DB or config.DB_PATH).
"""

import argparse
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.analysis.features import build_features
from deepsports.analysis.metrics import brier, log_loss
from deepsports.analysis.model import (
    ModelV1,
    make_model,
    resolve_version,
    training_rows,
    uses_players,
)
from deepsports.analysis.report import _f, _pct, _table

BREAK_EVEN = 110 / 210  # 52.38%: win rate needed to break even at -110 on both sides
WIN_PAYOUT = 100 / 110  # profit per unit staked on a winning -110 bet
ATS_THRESHOLDS = (0.0, 1.0, 2.0, 3.0, 5.0)
OU_THRESHOLDS = (0.0, 2.0, 4.0, 6.0, 10.0)


def _block_key(r: dict[str, Any], refit: str) -> tuple:
    if refit == "season":
        return (r["season"],)
    t = r["start_time_utc"]
    return (r["season"], t.year, t.month)


def iter_folds(
    rows: list[dict[str, Any]],
    refit: str = "monthly",
    burn_in_seasons: int = 1,
    min_train_seasons: int = 1,
):
    """Yield (block key, train rows, test rows) for each walk-forward fold, in time order.
    Train rows all tipped off before the block's first game."""
    if refit not in ("monthly", "season"):
        raise ValueError("refit must be 'monthly' or 'season'")
    train_pool = training_rows(rows, burn_in_seasons)  # completed, post burn-in
    seasons = sorted({r["season"] for r in train_pool})
    test_seasons = seasons[min_train_seasons:]
    blocks: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in train_pool:
        if r["season"] in test_seasons:
            blocks[_block_key(r, refit)].append(r)
    for key in sorted(blocks):
        test = blocks[key]
        block_start = min(r["start_time_utc"] for r in test)
        season = test[0]["season"]
        train = [r for r in train_pool if r["start_time_utc"] < block_start]
        if refit == "season":
            train = [r for r in train if r["season"] < season]
        if train:
            yield key, train, test


def walk_forward(
    rows: list[dict[str, Any]],
    refit: str = "monthly",
    burn_in_seasons: int = 1,
    min_train_seasons: int = 1,
    model_factory=ModelV1,
) -> dict[str, Any]:
    """Out-of-sample predictions for completed games, one prediction per game.

    Returns {"predictions": [...], "folds": [...]}. Each prediction carries the model's
    numbers, the Elo / home-always / league-average baselines, the closing line, and the truth.
    """
    preds, folds = [], []
    for key, train, test in iter_folds(rows, refit, burn_in_seasons, min_train_seasons):
        block_start = min(r["start_time_utc"] for r in test)
        season = test[0]["season"]
        model = model_factory().fit(train)
        reg_home = [r for r in train if r["season_type"] == 2 and not r["neutral_site"]]
        home_rate = sum(r["home_win"] for r in reg_home) / len(reg_home) if reg_home else 0.5
        folds.append(
            {
                "block": key,
                "n_train": len(train),
                "n_test": len(test),
                "train_seasons": sorted({r["season"] for r in train}),
                "train_max_start": max(r["start_time_utc"] for r in train),
                "test_min_start": block_start,
            }
        )
        for r, p in zip(test, model.predict(test), strict=True):
            mk = r["market"]
            preds.append(
                {
                    "game_id": r["game_id"],
                    "season": season,
                    "start_time_utc": r["start_time_utc"],
                    **p,
                    "elo_p_home": r["elo_p_home"],
                    "elo_margin": r["elo_margin"],
                    "home_always": 0.5 if r["neutral_site"] else home_rate,
                    "league_total": r["features"]["lg_total"],
                    "market_p_home": mk.get("p_home"),
                    "spread_home": mk.get("spread_home"),
                    "over_under": mk.get("over_under"),
                    "home_win": r["home_win"],
                    "home_margin": r["home_margin"],
                    "total": r["total"],
                }
            )
    return {"predictions": preds, "folds": folds}


# ---------- scoring ----------


def _mae(xs: list[float], ys: list[float]) -> float | None:
    return sum(abs(x - y) for x, y in zip(xs, ys, strict=True)) / len(xs) if xs else None


def _probs(ps: list[dict[str, Any]], key: str) -> dict[str, float | None]:
    p = [x[key] for x in ps]
    y = [x["home_win"] for x in ps]
    return {"brier": brier(p, y), "log_loss": log_loss(p, y)}


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """95% Wilson interval for a hit rate."""
    if n == 0:
        return None, None
    p = wins / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def _bets(results: list[int]) -> dict[str, Any]:
    """results: +1 win, -1 loss, 0 push. Hit rate excludes pushes; ROI assumes -110."""
    w, lo, pu = results.count(1), results.count(-1), results.count(0)
    n = w + lo
    ci = wilson(w, n)
    return {
        "bets": n,
        "wins": w,
        "losses": lo,
        "pushes": pu,
        "hit_rate": w / n if n else None,
        "ci_lo": ci[0],
        "ci_hi": ci[1],
        "roi": (w * WIN_PAYOUT - lo) / n if n else None,
    }


def ats(ps: list[dict[str, Any]], thresholds=ATS_THRESHOLDS) -> list[dict[str, Any]]:
    """Bet our side against the closing spread when |pred margin - market margin| >= t.
    The market's predicted home margin is -spread_home. Home covers if margin + spread > 0.
    At t=0 we bet every game where we disagree at all (exact ties are skipped)."""
    out = []
    for t in thresholds:
        res = []
        for x in ps:
            edge = x["pred_home_margin"] - (-x["spread_home"])
            if abs(edge) < t or edge == 0:
                continue
            cover = x["home_margin"] + x["spread_home"]
            side = 1 if edge > 0 else -1
            res.append(0 if cover == 0 else (1 if side * cover > 0 else -1))
        out.append({"threshold": t, **_bets(res)})
    return out


def over_under(ps: list[dict[str, Any]], thresholds=OU_THRESHOLDS) -> list[dict[str, Any]]:
    """Bet over when pred total - closing total >= t, under when <= -t."""
    out = []
    for t in thresholds:
        res = []
        for x in ps:
            edge = x["pred_total"] - x["over_under"]
            if abs(edge) < t or edge == 0:
                continue
            diff = x["total"] - x["over_under"]
            side = 1 if edge > 0 else -1
            res.append(0 if diff == 0 else (1 if side * diff > 0 else -1))
        out.append({"threshold": t, **_bets(res)})
    return out


def score(ps: list[dict[str, Any]]) -> dict[str, Any]:
    """All metrics on one set of predictions. Market comparisons use only the games that
    have that market number, and every model is scored on that same subset."""
    win_m = [x for x in ps if x["market_p_home"] is not None]
    sp = [x for x in ps if x["spread_home"] is not None]
    tot = [x for x in ps if x["over_under"] is not None]
    mg = [x["home_margin"] for x in ps]
    return {
        "n": len(ps),
        "win": {
            "n": len(ps),
            "model": _probs(ps, "p_home_win"),
            "elo": _probs(ps, "elo_p_home"),
            "home_always": _probs(ps, "home_always"),
        },
        "win_market": {
            "n": len(win_m),
            "model": _probs(win_m, "p_home_win"),
            "elo": _probs(win_m, "elo_p_home"),
            "market": _probs(win_m, "market_p_home"),
        },
        "margin": {
            "n": len(ps),
            "model": _mae([x["pred_home_margin"] for x in ps], mg),
            "elo": _mae([x["elo_margin"] for x in ps], mg),
        },
        "margin_market": {
            "n": len(sp),
            "model": _mae([x["pred_home_margin"] for x in sp], [x["home_margin"] for x in sp]),
            "elo": _mae([x["elo_margin"] for x in sp], [x["home_margin"] for x in sp]),
            "market": _mae([-x["spread_home"] for x in sp], [x["home_margin"] for x in sp]),
        },
        "total": {
            "n": len(ps),
            "model": _mae([x["pred_total"] for x in ps], [x["total"] for x in ps]),
            "league_avg": _mae([x["league_total"] for x in ps], [x["total"] for x in ps]),
        },
        "total_market": {
            "n": len(tot),
            "model": _mae([x["pred_total"] for x in tot], [x["total"] for x in tot]),
            "market": _mae([x["over_under"] for x in tot], [x["total"] for x in tot]),
        },
        "ats": ats(sp),
        "ou": over_under(tot),
    }


def evaluate_backtest(preds: list[dict[str, Any]]) -> dict[str, Any]:
    by_season: dict[int, list] = defaultdict(list)
    for p in preds:
        by_season[p["season"]].append(p)
    return {
        "per_season": [{"season": s, **score(by_season[s])} for s in sorted(by_season)],
        "overall": {"seasons": sorted(by_season), **score(preds)},
    }


# ---------- report ----------


def _pb(d: dict[str, Any]) -> list[str]:
    return [_f(d["brier"], 4), _f(d["log_loss"], 4)]


def run_backtest(
    con: duckdb.DuckDBPyConnection | None = None,
    refit: str = "monthly",
    model_version: str = "v1.0",
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Features -> walk-forward -> scores, plus the coefficients of a model fit on everything.
    Pass `rows` (from build_features, with player features for v1.1) to reuse them."""
    if rows is None:
        rows = build_features(con, include_players=uses_players(model_version))
    version = resolve_version(model_version)
    wf = walk_forward(rows, refit=refit, model_factory=lambda: make_model(version))
    train = training_rows(rows)
    coefs = make_model(version).fit(train).coefficients() if wf["predictions"] else {}
    return {
        "refit": refit,
        "model_version": version,
        **wf,
        "eval": evaluate_backtest(wf["predictions"]),
        "coefs": coefs,
    }


def _label(version: str) -> str:
    return "v1" if version == "v1.0" else version


def backtest_report(
    con: duckdb.DuckDBPyConnection | None = None,
    md: bool = False,
    refit: str = "monthly",
    result: dict[str, Any] | None = None,
) -> str:
    """Render a backtest as text or Markdown (pass `result` from run_backtest to reuse it)."""
    result = result or run_backtest(con, refit=refit)
    refit = result["refit"]
    v = _label(result.get("model_version", "v1.0"))
    h = (lambda t: f"## {t}") if md else (lambda t: f"\n== {t} ==")
    wf, ev = result, result["eval"]
    title = f"DeepSports model {v} backtest"
    out = [f"# {title}" if md else title]
    out.append(
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Refit: {refit}. "
        f"{len(wf['folds'])} folds, {len(wf['predictions'])} out-of-sample games. "
        "Season 2026 = 2025-26."
    )
    if not wf["predictions"]:
        out.append("Not enough seasons to backtest (need a burn-in season plus a training one).")
        return "\n".join(out) + "\n"
    leak = [f for f in wf["folds"] if f["train_max_start"] >= f["test_min_start"]]
    out.append(
        "Fold check: every training game tipped off before its test block "
        + ("(OK)." if not leak else f"(FAILED in {len(leak)} folds!)")
    )
    labeled = [(str(r["season"]), r) for r in ev["per_season"]] + [("all", ev["overall"])]

    out.append(h("Win probability (Brier / log loss, lower is better)"))
    t = []
    for name, r in labeled:
        w, wm = r["win"], r["win_market"]
        t.append(
            [
                name,
                str(w["n"]),
                *_pb(w["model"]),
                *_pb(w["elo"]),
                *_pb(w["home_always"]),
                str(wm["n"]),
                *(_pb(wm["model"]) + _pb(wm["market"]) if wm["n"] else ["-"] * 4),
            ]
        )
    out += _table(
        ["season", "n", f"{v} B", f"{v} LL", "elo B", "elo LL", "home B", "home LL"]
        + ["n mkt", f"{v} B", f"{v} LL", "mkt B", "mkt LL"],
        t,
        md,
    )

    out.append(h("Home margin (MAE in points, lower is better)"))
    t = []
    for name, r in labeled:
        m, mm = r["margin"], r["margin_market"]
        t.append(
            [
                name,
                str(m["n"]),
                _f(m["model"], 2),
                _f(m["elo"], 2),
                str(mm["n"]),
                _f(mm["model"], 2),
                _f(mm["elo"], 2),
                _f(mm["market"], 2),
            ]
        )
    out += _table(["season", "n", v, "elo", "n spread", v, "elo", "closing spread"], t, md)

    out.append(h("Total points (MAE, lower is better)"))
    t = []
    for name, r in labeled:
        x, xm = r["total"], r["total_market"]
        t.append(
            [
                name,
                str(x["n"]),
                _f(x["model"], 2),
                _f(x["league_avg"], 2),
                str(xm["n"]),
                _f(xm["model"], 2),
                _f(xm["market"], 2),
            ]
        )
    out += _table(["season", "n", v, "league avg", "n O/U", v, "closing total"], t, md)

    o = ev["overall"]
    for title, key in (
        (f"Against the spread, all test seasons (bet our side when |{v} - market| >= t)", "ats"),
        (f"Over/under, all test seasons (bet when |{v} - closing total| >= t)", "ou"),
    ):
        out.append(h(title))
        t = [
            [
                _f(b["threshold"], 1),
                str(b["bets"]),
                str(b["pushes"]),
                _pct(b["hit_rate"]),
                f"{_pct(b['ci_lo'])} - {_pct(b['ci_hi'])}",
                _pct(b["roi"]),
            ]
            for b in o[key]
        ]
        out += _table(["t", "bets", "pushes", "hit rate", "95% CI", "ROI at -110"], t, md)
    out.append(
        f"Break-even at -110 is {BREAK_EVEN:.1%}. A hit rate is only meaningful if its whole "
        "95% interval sits above that; with a few hundred bets the interval is about +-5 points."
    )

    beats = []
    if (
        o["win_market"]["n"]
        and o["win_market"]["model"]["brier"] < o["win_market"]["market"]["brier"]
    ):
        beats.append("win probability")
    if o["margin_market"]["n"] and o["margin_market"]["model"] < o["margin_market"]["market"]:
        beats.append("margin")
    if o["total_market"]["n"] and o["total_market"]["model"] < o["total_market"]["market"]:
        beats.append("total")
    out.append(h("Sanity"))
    out.append(
        f"{v} beats the closing line on: " + ", ".join(beats) + ". TREAT AS A PROBABLE BUG: "
        "check for leakage (features using the game's own result, odds data, or future games) "
        "before believing it."
        if beats
        else f"{v} does not beat the closing line on any target (expected for a public-data model)."
    )

    out.append(h("Coefficients of the model trained on all completed games (raw units)"))
    coefs = result["coefs"]
    names = sorted({n for c in coefs.values() for n in c})
    t = [[n] + [_f(coefs[k].get(n), 4) for k in ("win", "margin", "total")] for n in names]
    out += _table(["feature", "win (log-odds)", "margin (pts)", "total (pts)"], t, md)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="also write a Markdown report to this path")
    ap.add_argument("--db", type=Path, default=config.DB_PATH, help="warehouse path")
    ap.add_argument("--refit", choices=["monthly", "season"], default="monthly")
    ap.add_argument("--model-version", default="v1.0", help="v1.0 (default) or v1.1")
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"warehouse not found: {args.db}", file=sys.stderr)
        return 1
    con = duckdb.connect(str(args.db), read_only=True)
    try:
        result = run_backtest(con, refit=args.refit, model_version=args.model_version)
        print(backtest_report(md=False, result=result))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(backtest_report(md=True, result=result))
            print(f"wrote {args.out}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
