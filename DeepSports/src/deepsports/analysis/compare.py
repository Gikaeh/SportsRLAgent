"""Compare model versions on the same walk-forward folds, plus permutation importance.

    uv run python -m deepsports.analysis.compare --out /path/report.md [--copy docs/x.md]

Features are built once (with player features), so every version sees the same games and the
same folds; v1.0 just doesn't read the player columns. Paired per-game differences (v1.1 - v1.0)
get a normal-approximation 95% interval, which is fair because each game is one independent-ish
observation scored by both models.

Permutation importance is measured out of sample: in each fold the model is fit on the training
rows, then one feature at a time is shuffled across the test block's games and the increase in
log loss / margin MAE / total MAE is recorded (averaged over `repeats` shuffles and all folds).
Correlated features share credit, so a low score does not prove a feature is useless.

Opens the warehouse read-only ($DEEPSPORTS_DB or config.DB_PATH).
"""

import argparse
import math
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from deepsports import config
from deepsports.analysis.backtest import (
    BREAK_EVEN,
    _label,
    evaluate_backtest,
    iter_folds,
    run_backtest,
    walk_forward,
)
from deepsports.analysis.features import build_features
from deepsports.analysis.metrics import log_loss
from deepsports.analysis.model import ModelV1, make_model, resolve_version
from deepsports.analysis.players import PLAYER_FEATURES
from deepsports.analysis.report import _f, _pct, _table

EPS = 1e-15


def _ll1(p: float, y: int) -> float:
    p = min(max(p, EPS), 1 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _mean_ci(d: list[float]) -> dict[str, float | None]:
    n = len(d)
    if n == 0:
        return {"n": 0, "mean": None, "lo": None, "hi": None}
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    h = 1.96 * sd / math.sqrt(n)
    return {"n": n, "mean": m, "lo": m - h, "hi": m + h}


def paired_deltas(base: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-game (new - base) for Brier, log loss, |margin error| and |total error|, with 95%
    intervals. Negative = the new model is better. Matches games by game_id."""
    b = {p["game_id"]: p for p in base}
    pairs = [(b[p["game_id"]], p) for p in new if p["game_id"] in b]
    d = defaultdict(list)
    for x0, x1 in pairs:
        y = x0["home_win"]
        d["brier"].append((x1["p_home_win"] - y) ** 2 - (x0["p_home_win"] - y) ** 2)
        d["log_loss"].append(_ll1(x1["p_home_win"], y) - _ll1(x0["p_home_win"], y))
        m = x0["home_margin"]
        d["margin_mae"].append(abs(x1["pred_home_margin"] - m) - abs(x0["pred_home_margin"] - m))
        t = x0["total"]
        d["total_mae"].append(abs(x1["pred_total"] - t) - abs(x0["pred_total"] - t))
    return {k: _mean_ci(v) for k, v in d.items()} | {"n": len(pairs)}


def _scores(model, rows: list[dict[str, Any]]) -> tuple[float, float, float]:
    p = model.predict(rows)
    ll = log_loss([x["p_home_win"] for x in p], [r["home_win"] for r in rows])
    mm = np.mean(
        [abs(x["pred_home_margin"] - r["home_margin"]) for x, r in zip(p, rows, strict=True)]
    )
    tm = np.mean([abs(x["pred_total"] - r["total"]) for x, r in zip(p, rows, strict=True)])
    return ll, float(mm), float(tm)


# Correlated features shuffled together (grouped importance). The two player plus-minus sums
# correlate ~0.99 with each other and ~0.96 with team form, so one-at-a-time scores split or
# inflate credit (the model can put offsetting weights on them).
GROUPS = {
    "elo": ["elo_diff"],
    "team form": ["form_net_diff", "eff_net_diff"],
    "schedule": [
        "home_court",
        "rest_diff",
        "b2b_home",
        "b2b_away",
        "g7_home",
        "g7_away",
        "travel_away",
        "road_trip_away",
    ],
    "totals inputs": ["lg_total", "form_total", "pace_sum", "eff_sum"],
    "player quality": ["top6_pm_diff", "avail_top6_pm_diff", "top3_pts_diff", "top6_pts_std_diff"],
    "availability": [
        "top6_out_last_diff",
        "top3_out_last_diff",
        "top6_out_2of3_diff",
        "miss_share_diff",
        "top3_since_diff",
    ],
    "player totals": ["miss_share_sum", "top3_pts_sum"],
}
# Feature-group ablations (diagnostic only; v1.1 itself is fixed in advance).
AVAILABILITY = GROUPS["availability"]
QUALITY = GROUPS["player quality"]


def permutation_importance(
    rows: list[dict[str, Any]],
    model_version: str = "v1.1",
    refit: str = "monthly",
    repeats: int = 3,
    seed: int = 0,
    groups: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Out-of-sample permutation importance, averaged over folds (weighted by test games).

    With `groups=None` each feature the model reads is its own group; otherwise every listed
    group (restricted to the model's columns) is shuffled jointly, with one permutation of the
    test games applied to all its features. Rows: feature (group name), d_log_loss,
    d_margin_mae, d_total_mae = increase when shuffled (bigger = more important)."""
    rng = random.Random(seed)
    cols = make_model(model_version).columns()
    if groups is None:
        groups = {f: [f] for f in cols}
    groups = {g: [f for f in fs if f in cols] for g, fs in groups.items()}
    groups = {g: fs for g, fs in groups.items() if fs}
    acc = {g: np.zeros(3) for g in groups}
    n_total = 0
    for _, train, test in iter_folds(rows, refit):
        model = make_model(model_version).fit(train)
        base = np.array(_scores(model, test))
        n = len(test)
        n_total += n
        idx = list(range(n))
        for g, fs in groups.items():
            inc = np.zeros(3)
            for _ in range(repeats):
                rng.shuffle(idx)
                shuffled = [
                    {**r, "features": {**r["features"], **{f: test[j]["features"][f] for f in fs}}}
                    for r, j in zip(test, idx, strict=True)
                ]
                inc += np.array(_scores(model, shuffled)) - base
            acc[g] += n * inc / repeats
    out = []
    for g, fs in groups.items():
        a = acc[g] / n_total if n_total else acc[g]
        out.append(
            {
                "feature": g,
                "new": all(f in PLAYER_FEATURES for f in fs),
                "d_log_loss": float(a[0]),
                "d_margin_mae": float(a[1]),
                "d_total_mae": float(a[2]),
            }
        )
    return sorted(out, key=lambda x: (-x["d_log_loss"], -x["d_margin_mae"], -x["d_total_mae"]))


def ablations(rows: list[dict[str, Any]], refit: str = "monthly") -> list[dict[str, Any]]:
    """v1 plus one player-feature group at a time (diagnostic, same folds and settings)."""
    win0, tot0 = make_model("v1.0").win_features, make_model("v1.0").total_features
    win1, tot1 = make_model("v1.1").win_features, make_model("v1.1").total_features
    variants = [
        ("v1", win0, tot0),
        ("v1 + availability", win0 + AVAILABILITY, tot0),
        ("v1 + player quality", win0 + QUALITY, tot0),
        ("v1.1 (all)", win1, tot1),
    ]
    out = []
    for name, win, tot in variants:
        wf = walk_forward(
            rows,
            refit=refit,
            model_factory=lambda w=win, t=tot: ModelV1(
                win_features=list(w), margin_features=list(w), total_features=list(t)
            ),
        )
        o = evaluate_backtest(wf["predictions"])["overall"]
        out.append(
            {
                "name": name,
                "brier": o["win"]["model"]["brier"],
                "log_loss": o["win"]["model"]["log_loss"],
                "margin_mae": o["margin"]["model"],
                "total_mae": o["total"]["model"],
            }
        )
    return out


def compare(
    con: duckdb.DuckDBPyConnection,
    versions: tuple[str, str] = ("v1.0", "v1.1"),
    refit: str = "monthly",
    importance: bool = True,
    repeats: int = 3,
) -> dict[str, Any]:
    rows = build_features(con, include_players=True)
    results = {v: run_backtest(refit=refit, model_version=v, rows=rows) for v in versions}
    base, new = (results[v]["predictions"] for v in versions)
    by_season = sorted({p["season"] for p in base})
    deltas = {
        "all": paired_deltas(base, new),
        **{
            s: paired_deltas(
                [p for p in base if p["season"] == s], [p for p in new if p["season"] == s]
            )
            for s in by_season
        },
    }
    imp = permutation_importance(rows, versions[1], refit, repeats) if importance else []
    gimp = (
        permutation_importance(rows, versions[1], refit, repeats, groups=GROUPS)
        if importance
        else []
    )
    abl = ablations(rows, refit) if importance else []
    same_folds = [f["block"] for f in results[versions[0]]["folds"]] == [
        f["block"] for f in results[versions[1]]["folds"]
    ]
    return {
        "versions": [resolve_version(v) for v in versions],
        "refit": refit,
        "results": results,
        "deltas": deltas,
        "importance": imp,
        "group_importance": gimp,
        "ablations": abl,
        "same_folds": same_folds,
    }


# ---------- report ----------


def _ci(d: dict[str, Any], nd: int) -> str:
    if d["mean"] is None:
        return "-"
    return f"{d['mean']:+.{nd}f} ({d['lo']:+.{nd}f} to {d['hi']:+.{nd}f})"


def compare_report(res: dict[str, Any], md: bool = True) -> str:
    v0, v1 = res["versions"]
    l0, l1 = _label(v0), _label(v1)
    r0, r1 = (res["results"][v] for v in (v0, v1))
    h = (lambda t: f"## {t}") if md else (lambda t: f"\n== {t} ==")
    out = [f"# DeepSports backtest: {l1} vs {l0}" if md else f"{l1} vs {l0}"]
    leak = [f for r in (r0, r1) for f in r["folds"] if f["train_max_start"] >= f["test_min_start"]]
    out.append(
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Refit: {res['refit']}. "
        f"{len(r1['folds'])} folds, {len(r1['predictions'])} out-of-sample games. "
        "Season 2026 = 2025-26. Same folds for both: "
        + ("yes." if res["same_folds"] else "NO!")
        + " Fold check: "
        + ("every training game tipped off before its test block (OK)." if not leak else "FAILED")
    )
    seasons = [s["season"] for s in r0["eval"]["per_season"]]
    lab = [(str(s), i) for i, s in enumerate(seasons)] + [("all", None)]

    def ev(r, i):
        return r["eval"]["overall"] if i is None else r["eval"]["per_season"][i]

    out.append(h("Win probability (lower is better; market columns use games with a moneyline)"))
    t = []
    for name, i in lab:
        a, b = ev(r0, i), ev(r1, i)
        t.append(
            [
                name,
                str(a["win"]["n"]),
                _f(a["win"]["model"]["brier"], 4),
                _f(b["win"]["model"]["brier"], 4),
                _f(a["win"]["model"]["log_loss"], 4),
                _f(b["win"]["model"]["log_loss"], 4),
                _f(b["win_market"]["model"]["brier"], 4),
                _f(b["win_market"]["market"]["brier"], 4),
            ]
        )
    out += _table(
        [
            "season",
            "n",
            f"{l0} B",
            f"{l1} B",
            f"{l0} LL",
            f"{l1} LL",
            f"{l1} B (mkt games)",
            "mkt B",
        ],
        t,
        md,
    )
    out.append(h("Margin and total MAE (points)"))
    t = []
    for name, i in lab:
        a, b = ev(r0, i), ev(r1, i)
        t.append(
            [
                name,
                _f(a["margin"]["model"], 2),
                _f(b["margin"]["model"], 2),
                _f(b["margin_market"]["market"], 2),
                _f(a["total"]["model"], 2),
                _f(b["total"]["model"], 2),
                _f(b["total_market"]["market"], 2),
            ]
        )
    out += _table(
        ["season", f"{l0} margin", f"{l1} margin", "closing spread"]
        + [f"{l0} total", f"{l1} total", "closing total"],
        t,
        md,
    )
    out.append(h(f"Paired per-game change, {l1} - {l0} (negative = {l1} better; 95% CI)"))
    t = []
    for key in [*seasons, "all"]:
        d = res["deltas"][key]
        t.append(
            [
                str(key),
                str(d["n"]),
                _ci(d["brier"], 4),
                _ci(d["log_loss"], 4),
                _ci(d["margin_mae"], 3),
                _ci(d["total_mae"], 3),
            ]
        )
    out += _table(["season", "n", "Brier", "log loss", "margin MAE", "total MAE"], t, md)

    o0, o1 = r0["eval"]["overall"], r1["eval"]["overall"]
    for title, key in (("Against the spread (all test seasons)", "ats"), ("Over/under", "ou")):
        out.append(h(title))
        t = []
        for b0, b1 in zip(o0[key], o1[key], strict=True):
            t.append(
                [
                    _f(b0["threshold"], 1),
                    f"{b0['bets']} / {b1['bets']}",
                    f"{_pct(b0['hit_rate'])} ({_pct(b0['ci_lo'])}-{_pct(b0['ci_hi'])})",
                    f"{_pct(b1['hit_rate'])} ({_pct(b1['ci_lo'])}-{_pct(b1['ci_hi'])})",
                    f"{_pct(b0['roi'])} / {_pct(b1['roi'])}",
                ]
            )
        out += _table(
            ["t", f"bets {l0} / {l1}", f"{l0} hit (95% CI)", f"{l1} hit (95% CI)", "ROI at -110"],
            t,
            md,
        )
    out.append(f"Break-even at -110 is {BREAK_EVEN:.1%}.")

    beats = []
    if o1["win_market"]["model"]["brier"] < o1["win_market"]["market"]["brier"]:
        beats.append("win probability")
    if o1["margin_market"]["model"] < o1["margin_market"]["market"]:
        beats.append("margin")
    if o1["total_market"]["model"] < o1["total_market"]["market"]:
        beats.append("total")
    out.append(h("Sanity"))
    out.append(
        f"{l1} beats the closing line on: {', '.join(beats)}. TREAT AS A PROBABLE BUG."
        if beats
        else f"{l1} does not beat the closing line on any target."
    )

    if res["importance"]:
        out.append(
            h(f"Permutation importance, {l1}, out of sample (increase when shuffled; * = new)")
        )
        t = [
            [
                ("* " if x["new"] else "") + x["feature"],
                _f(x["d_log_loss"], 5),
                _f(x["d_margin_mae"], 4),
                _f(x["d_total_mae"], 4),
            ]
            for x in res["importance"]
        ]
        out += _table(["feature", "log loss", "margin MAE", "total MAE"], t, md)
    if res.get("group_importance"):
        out.append(
            h(f"Grouped permutation importance, {l1} (correlated features shuffled together)")
        )
        t = [
            [
                ("* " if x["new"] else "") + x["feature"],
                _f(x["d_log_loss"], 5),
                _f(x["d_margin_mae"], 4),
                _f(x["d_total_mae"], 4),
            ]
            for x in res["group_importance"]
        ]
        out += _table(["group", "log loss", "margin MAE", "total MAE"], t, md)
    if res.get("ablations"):
        out.append(
            h("Ablation: v1 plus one player group (same folds; diagnostic, not a model pick)")
        )
        t = [
            [
                x["name"],
                _f(x["brier"], 4),
                _f(x["log_loss"], 4),
                _f(x["margin_mae"], 3),
                _f(x["total_mae"], 3),
            ]
            for x in res["ablations"]
        ]
        out += _table(["variant", "Brier", "log loss", "margin MAE", "total MAE"], t, md)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="write a Markdown report here")
    ap.add_argument("--copy", type=Path, help="also write the same report here")
    ap.add_argument("--db", type=Path, default=config.DB_PATH, help="warehouse path")
    ap.add_argument("--refit", choices=["monthly", "season"], default="monthly")
    ap.add_argument("--repeats", type=int, default=3, help="shuffles per feature per fold")
    ap.add_argument("--no-importance", action="store_true")
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"warehouse not found: {args.db}", file=sys.stderr)
        return 1
    con = duckdb.connect(str(args.db), read_only=True)
    try:
        res = compare(
            con, refit=args.refit, importance=not args.no_importance, repeats=args.repeats
        )
    finally:
        con.close()
    print(compare_report(res, md=False))
    for p in (args.out, args.copy):
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(compare_report(res, md=True))
            print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
