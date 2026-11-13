"""Daily models-only picks (watch-only): DeepSports' model and ManualBets' model vs today's lines.

Replaces the daily ensemble-agent vote (DECISIONS 2026-11-13). No agents, no prompt: a fixed rule
over the same slate the vote used (`ensemble_bets.load_slate` + `manualbets_context`).

For each game and market (spread, total) each model's edge is how far its number sits past the
line, in points, on the side it favours:
- spread: model home margin + home line (> 0 = home covers, < 0 = away covers)
- total:  model total - line (> 0 = over)

Tiers (both models must be on the same side):
- strong: both edges >= STRONG_PTS
- lean:   both edges >= LEAN_PTS (and not strong)
Top picks: up to TOP_N of the strong + lean bets, one per game, ranked by the smaller of the two
edges. College spreads with a line beyond BIG_DOG_LINE are left out of the top picks: early-season
models pull lopsided games toward the middle, so those edges are mostly a model quirk.

Neither model has beaten the closing line; this is a recommendation list, never a placed bet.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.analysis.ensemble_bets import (
    _short_tip,
    grade_pick,
    label,
    load_finals,
    new_run_dir,
    summarize_graded,
)

RUNS_DIR = config.REPORTS_DIR / "model-picks"
RULE_VERSION = "mp-v1"
STRONG_PTS = 4.0
LEAN_PTS = 3.0
TOP_N = 5
BIG_DOG_LINE = 15.0
MARKETS = ("spread", "total")


def _edge(market: str, margin_or_total: float | None, game: Mapping[str, Any]) -> float | None:
    """Signed edge in points: spread > 0 = home side, total > 0 = over. None if not computable."""
    m = game["markets"].get(market)
    if m is None or margin_or_total is None:
        return None
    if market == "spread":
        return margin_or_total + m["home_line"]
    return margin_or_total - m["line"]


def _model_number(model: Mapping[str, Any] | None, market: str) -> float | None:
    if not model:
        return None
    return model.get("home_margin" if market == "spread" else "total")


def _side(market: str, edge: float) -> str:
    if market == "spread":
        return "home" if edge > 0 else "away"
    return "over" if edge > 0 else "under"


def _best_price(game: Mapping[str, Any], market: str, side: str, line: float) -> dict | None:
    """ManualBets' best price across books for this side, when it is at the same line or better."""
    best = (((game.get("manualbets") or {}).get("best_prices") or {}).get(market) or {}).get(side)
    if not best or best.get("point") is None or best["point"] < line:
        return None
    return {"price": best["price"], "point": best["point"], "book": best["book"]}


def find_picks(slate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every strong or lean bet on the slate, best first (pure)."""
    picks = []
    for g in slate["games"]:
        mb_model = (g.get("manualbets") or {}).get("model")
        for market in MARKETS:
            ds = _edge(market, _model_number(g.get("model"), market), g)
            mb = _edge(market, _model_number(mb_model, market), g)
            if ds is None or mb is None or ds == 0 or (ds > 0) != (mb > 0):
                continue
            low, high = sorted((abs(ds), abs(mb)))
            if low < LEAN_PTS:
                continue
            side = _side(market, ds)
            m = g["markets"][market]
            line = m[f"{side}_line"] if market == "spread" else m["line"]
            pick = {
                "game_id": g["game_id"],
                "league": g["league"],
                "market": market,
                "side": side,
                "line": line,
                "price": m[f"{side}_price"],
                "stake": 1,
                "tier": "strong" if low >= STRONG_PTS else "lean",
                "ds_edge": round(abs(ds), 1),
                "mb_edge": round(abs(mb), 1),
                "min_edge": round(low, 1),
                "early": bool((g.get("manualbets") or {}).get("gated")),
                "label": label(g, market, side, line),
            }
            best = _best_price(g, market, side, line) if market == "spread" else None
            if best:
                pick["best"] = best
            picks.append(pick)
    picks.sort(key=lambda p: (p["tier"] != "strong", -p["min_edge"]))
    return picks


def top_picks(picks: Sequence[Mapping[str, Any]], n: int = TOP_N) -> list[dict[str, Any]]:
    """Up to n picks, one per game, skipping big college spreads (see module doc)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in sorted(picks, key=lambda p: -p["min_edge"]):
        if p["game_id"] in seen:
            continue
        if p["league"] == "ncaab" and p["market"] == "spread" and abs(p["line"]) > BIG_DOG_LINE:
            continue
        out.append(dict(p))
        seen.add(p["game_id"])
        if len(out) == n:
            break
    return out


def _table(rows: Sequence[Sequence[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    fmt = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()  # noqa: E731
    return ["```", *(fmt(r) for r in rows), "```"]


def _row(p: Mapping[str, Any], games: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    g = games[p["game_id"]]
    game = f"{g['away']['abbr']} @ {g['home']['abbr']}"
    return (
        p["label"] + ("*" if p["early"] else ""),
        f"{p['price']:+d}",
        game,
        _short_tip(g["tip_local"]),
        f"+{p['ds_edge']:g}",
        f"+{p['mb_edge']:g}",
    )


def render(slate: Mapping[str, Any], picks: Sequence[Mapping[str, Any]], top: Sequence) -> str:
    """Discord message: top picks, then the strong and lean tables, then caveats (pure)."""
    games = {g["game_id"]: g for g in slate["games"]}
    head = ("Bet", "Odds", "Game", "Tip", "DS", "MB")
    when = datetime.fromisoformat(slate["created_at"]).astimezone(config.LOCAL_TZ)
    out = [
        f"Model picks, {when:%a %b %d} (DeepSports + ManualBets vs {when:%-I:%M %p} lines,"
        " watch-only)",
    ]
    mb = slate.get("manualbets") or {}
    if not mb.get("available"):
        out.append("ManualBets export missing today: no picks (the rule needs both models).")
        return "\n".join(out)
    for league, err in (mb.get("errors") or {}).items():
        out.append(f"ManualBets {league.upper()} missing today ({str(err)[:60]}).")
    if not picks:
        out.append("No bet today: the two models don't agree 3+ points past any line.")
        return "\n".join(out)
    out.append(f"Top {len(top)} (1 unit each, one per game):")
    for p in top:
        g = games[p["game_id"]]
        best = p.get("best")
        shop = ""
        if best and (best["price"] > p["price"] or best["point"] > p["line"]):
            shop = f", best {best['point']:+g} {best['price']:+d} {best['book']}"
        out.append(
            f"- {p['label']} ({p['price']:+d}) {g['away']['abbr']} @ {g['home']['abbr']}"
            f" {_short_tip(g['tip_local'])}: DS +{p['ds_edge']:g}, MB +{p['mb_edge']:g}{shop}"
        )
    for tier, title in (
        ("strong", f"Strong: both models {STRONG_PTS:g}+ pts past the line"),
        ("lean", f"Lean: both {LEAN_PTS:g}+ pts, one under {STRONG_PTS:g}"),
    ):
        rows = [_row(p, games) for p in picks if p["tier"] == tier]
        if rows:
            out.append(title)
            out += _table([head, *rows])
    notes = []
    if any(p["early"] for p in picks):
        notes.append("* early-season college game (ManualBets withholds its own bets)")
    if not any(p["league"] == "nba" for p in picks):
        notes.append("NBA: the models don't agree on any line today")
    notes.append("Neither model has beaten the closing line. Check the line before betting.")
    out += notes
    return "\n".join(out)


# ---------- run directory I/O and grading ----------


def write_run(slate: Mapping[str, Any], now: datetime, root: Path = RUNS_DIR) -> tuple[Path, str]:
    picks = find_picks(slate)
    top = top_picks(picks)
    run = new_run_dir(now, root)
    (run / "slate.json").write_text(json.dumps(slate, indent=1, default=str))
    payload = {
        "rule_version": RULE_VERSION,
        "created_at": slate["created_at"],
        "picks": picks,
        "top": top,
    }
    (run / "picks.json").write_text(json.dumps(payload, indent=1))
    text = render(slate, picks, top)
    (run / "message.txt").write_text(text + "\n")
    return run, text


def grade_runs(con: duckdb.DuckDBPyConnection, root: Path = RUNS_DIR) -> dict[str, Any]:
    """Graded record of every run at the run's line and price, 1 unit per pick: top picks,
    strong, lean. Unfinished games count as pending."""
    groups: dict[str, list[dict]] = {"top": [], "strong": [], "lean": []}
    pending = 0
    runs = sorted(root.glob("*/picks.json"))
    for f in runs:
        r = json.loads(f.read_text())
        finals = load_finals(con, sorted({p["game_id"] for p in r["picks"]}))
        for name, ps in (("top", r["top"]), ("all", r["picks"])):
            for p in ps:
                if p["game_id"] not in finals:
                    pending += name == "all"
                    continue
                groups[name if name == "top" else p["tier"]].append(
                    grade_pick(p, finals[p["game_id"]])
                )
    return {
        "runs": len(runs),
        "pending_picks": pending,
        **{k: summarize_graded(v) for k, v in groups.items()},
    }
