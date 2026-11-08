"""Print a compact analysis report; optionally write it as Markdown.

    uv run python -m deepsports.analysis.report --out /path/to/report.md

Opens the warehouse read-only ($DEEPSPORTS_DB or config.DB_PATH).
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.analysis.elo import elo_ratings
from deepsports.analysis.evaluate import evaluate_elo
from deepsports.analysis.market import home_court, market_accuracy


def _f(v: Any, digits: int = 3) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.1f}%"


def _table(headers: list[str], rows: list[list[str]], md: bool) -> list[str]:
    if md:
        lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        return lines + ["| " + " | ".join(r) + " |" for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:>{w}}}" for w in widths)
    return [fmt.format(*headers)] + [fmt.format(*r) for r in rows]


def _score_cells(d: dict[str, Any] | None) -> list[str]:
    if not d:
        return ["-", "-"]
    return [_f(d["brier"], 4), _f(d["log_loss"], 4)]


def build_report(con: duckdb.DuckDBPyConnection, md: bool = False) -> str:
    h = (lambda t: f"## {t}") if md else (lambda t: f"\n== {t} ==")
    out = ["# DeepSports analysis report" if md else "DeepSports analysis report"]
    out.append(f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Season 2026 = 2025-26.")

    hc = home_court(con)
    out.append(h("Home court (regular season, non-neutral)"))
    rows = [
        [str(r["season"]), str(r["n"]), _pct(r["home_win_pct"]), _f(r["avg_home_margin"], 2)]
        for r in hc
    ]
    out += _table(["season", "n", "home win", "avg margin"], rows, md) if rows else ["no games"]

    ma = market_accuracy(con)
    out.append(h("Closing line accuracy"))
    rows = [
        [
            str(r["season"]),
            str(r["n_spread"]),
            _pct(r["favorite_win_pct"]),
            _pct(r["home_cover_pct"]),
            str(r["pushes"]),
            _f(r["spread_mae"], 2),
            str(r["n_total"]),
            _f(r["total_mae"], 2),
            _pct(r["over_pct"]),
        ]
        for r in ma["closing"]
    ]
    out += (
        _table(
            [
                "season",
                "n",
                "fav won",
                "home cover",
                "push",
                "spread MAE",
                "n tot",
                "total MAE",
                "over",
            ],
            rows,
            md,
        )
        if rows
        else ["no closing lines"]
    )
    rejected = sum(r["n_spread_rejected"] + r["n_total_rejected"] for r in ma["closing"])
    if rejected:
        out.append(f"({rejected} implausible spread/total values excluded)")

    out.append(h("Opening -> closing movement"))
    rows = [
        [
            str(r["season"]),
            str(r["n_spread"]),
            _f(r["spread_mean_abs_move"], 2),
            _f(r["open_spread_mae"], 2),
            _f(r["close_spread_mae"], 2),
            _pct(r["close_spread_better_pct"]),
            str(r["n_total"]),
            _f(r["total_mean_abs_move"], 2),
            _f(r["open_total_mae"], 2),
            _f(r["close_total_mae"], 2),
        ]
        for r in ma["movement"]
    ]
    out += (
        _table(
            [
                "season",
                "n",
                "spread move",
                "open MAE",
                "close MAE",
                "close closer",
                "n tot",
                "total move",
                "open MAE",
                "close MAE",
            ],
            rows,
            md,
        )
        if rows
        else ["no opening lines"]
    )

    elo = elo_ratings(con)
    ev = evaluate_elo(con, elo=elo)
    out.append(h("Elo win probability (Brier / log loss; lower is better)"))
    rows = []
    for r in ev["per_season"]:
        a, m = r["all"], r["market"]
        rows.append(
            [
                str(r["season"]),
                str(a["n"]),
                *_score_cells(a.get("elo")),
                *_score_cells(a.get("coin_flip")),
                *_score_cells(a.get("home_always")),
                str(m["n"]),
                *_score_cells(m.get("elo") if m["n"] else None),
                *_score_cells(m.get("market") if m["n"] else None),
            ]
        )
    o = ev["overall"]
    oa, om = o["all"], o["market"]
    rows.append(
        [
            "overall",
            str(oa["n"]),
            *_score_cells(oa["elo"] if oa["n"] else None),
            *_score_cells(oa["coin_flip"] if oa["n"] else None),
            *_score_cells(oa["home_always"] if oa["n"] else None),
            str(om["n"]),
            *_score_cells(om["elo"] if om["n"] else None),
            *_score_cells(om["market"] if om["n"] else None),
        ]
    )
    out += _table(
        [
            "season",
            "n",
            "elo B",
            "elo LL",
            "50/50 B",
            "50/50 LL",
            "home B",
            "home LL",
            "n mkt",
            "elo B",
            "elo LL",
            "mkt B",
            "mkt LL",
        ],
        rows,
        md,
    )
    out.append(
        f"overall pools seasons {o['seasons'][0] if o['seasons'] else '-'}+ "
        "(first season is Elo burn-in). Home baseline uses earlier seasons only."
    )

    names = dict(con.execute("SELECT team_id, abbreviation FROM teams").fetchall())
    top = sorted(elo.ratings.items(), key=lambda kv: -kv[1])
    out.append(h("Current Elo"))
    rows = [[str(i + 1), names.get(t, t), f"{r:.0f}"] for i, (t, r) in enumerate(top)]
    out += _table(["#", "team", "elo"], rows, md) if rows else ["no teams"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="also write a Markdown report to this path")
    ap.add_argument("--db", type=Path, default=config.DB_PATH, help="warehouse path")
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"warehouse not found: {args.db}", file=sys.stderr)
        return 1
    con = duckdb.connect(str(args.db), read_only=True)
    try:
        print(build_report(con, md=False))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(build_report(con, md=True))
            print(f"wrote {args.out}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
