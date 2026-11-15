"""Night-before college totals (`et-v1`): a pre-registered, watch-only forward test (pure logic).

Rule and pass/fail: docs/results/2026-11-15-early-totals-preregistration.md. In short: at 21:00 the
evening before, for each college game tomorrow, take Caesars' (`williamhill`) total from the
night-before grab; bet the side where DeepSports' and ManualBets' model totals are both past that
side's line and their average edge is >= MIN_AVG_EDGE points; price = Caesars' price. One bet per
game, the first logged row wins (re-runs add nothing). Graded by CLV vs the warehouse closing total
and W/L/P at the logged line and price (1 notional unit; no stake is ever recorded).

I/O (warehouse reads, files, the CLI) lives in `early_totals_cli.py`.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from deepsports.analysis.betting.grading import outcome, profit_on_win
from deepsports.store import SANE_LIMITS

RULE_VERSION = "et-v1"
LEAGUE = "ncaab"
BOOK = "williamhill"  # Caesars' feed stands in for William Hill NV (DECISIONS 2026-11-14)
MIN_AVG_EDGE = 4.0
MIN_LEAD = timedelta(minutes=60)
MB_MAX_AGE = timedelta(hours=36)
VERDICT_N = 300
EXTENSION_N = 600
EARLY_DS_VERSION = "ncaab-v1-early"
BOOT_REPS = 4000
BOOT_SEED = 0


def book_totals(early: Mapping[str, Any] | None) -> dict[str, dict[str, dict]]:
    """game_id -> {"over": {line, price}, "under": {line, price}} from a lines payload (Circa
    contract). The first quote per game and side wins; quotes without a line or price are
    skipped."""
    out: dict[str, dict[str, dict]] = {}
    for q in (early or {}).get("lines") or []:
        if q.get("market") != "total" or q.get("side") not in ("over", "under"):
            continue
        if q.get("game_id") is None or q.get("line") is None or q.get("price") is None:
            continue
        slot = out.setdefault(str(q["game_id"]), {})
        slot.setdefault(q["side"], {"line": float(q["line"]), "price": int(q["price"])})
    return out


def side_edges(model_total: float, quotes: Mapping[str, Mapping]) -> dict[str, float]:
    """Edge in points per quoted side: over = model - line, under = line - model."""
    out = {}
    if "over" in quotes:
        out["over"] = model_total - quotes["over"]["line"]
    if "under" in quotes:
        out["under"] = quotes["under"]["line"] - model_total
    return out


def qualify(
    ds_total: float | None, mb_total: float | None, quotes: Mapping[str, Mapping]
) -> tuple[str, float, float] | None:
    """(side, ds_edge, mb_edge) if both models are past that side's line and the average edge is
    >= MIN_AVG_EDGE; else None. Only one side can qualify (both edges > 0 on a side)."""
    if ds_total is None or mb_total is None:
        return None
    ds, mb = side_edges(ds_total, quotes), side_edges(mb_total, quotes)
    for side in ("over", "under"):
        if side not in ds:
            continue
        d, m = ds[side], mb[side]
        if d > 0 and m > 0 and (d + m) / 2 >= MIN_AVG_EDGE:
            return side, d, m
    return None


def find_bets(
    games: Sequence[Mapping[str, Any]],
    ds_preds: Mapping[str, Mapping[str, Any]],
    mb_export: Mapping[str, Any] | None,
    early: Mapping[str, Any] | None,
    now: datetime,
    game_date: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """(qualifying bets, counts) for one game day. `games`: {game_id, away, home, start_time_utc,
    min_rest_days?}; `ds_preds`: game_id -> {model_version, pred_total, created_at};
    `mb_export`: the ManualBets export; `early`: the night-before lines payload. Pure."""
    quotes = book_totals(early)
    mb_ok = mb_export is not None and _mb_fresh(mb_export, now)
    mb = {}
    if mb_ok:
        mb = {str(g["game_id"]): g for g in (mb_export.get("ncaab") or {}).get("games") or []}
    counts = {"games": 0, "too_soon": 0, "ds": 0, "mb": 0, "book": 0, "all_inputs": 0, "bets": 0}
    bets = []
    for g in games:
        gid = str(g["game_id"])
        counts["games"] += 1
        start = g["start_time_utc"]
        if start - now < MIN_LEAD:
            counts["too_soon"] += 1
            continue
        ds = ds_preds.get(gid)
        mbg = mb.get(gid)
        q = quotes.get(gid)
        counts["ds"] += ds is not None and ds.get("pred_total") is not None
        mb_total = ((mbg or {}).get("model") or {}).get("total")
        counts["mb"] += mb_total is not None
        counts["book"] += bool(q)
        if ds is None or ds.get("pred_total") is None or mb_total is None or not q:
            continue
        counts["all_inputs"] += 1
        hit = qualify(float(ds["pred_total"]), float(mb_total), q)
        if hit is None:
            continue
        side, d, m = hit
        bets.append(
            {
                "rule_version": RULE_VERSION,
                "logged_at": now.isoformat(timespec="seconds"),
                "game_date": game_date,
                "game_id": gid,
                "league": LEAGUE,
                "away": g.get("away"),
                "home": g.get("home"),
                "tip_utc": start.isoformat(),
                "market": "total",
                "side": side,
                "line": q[side]["line"],
                "price": q[side]["price"],
                "book": BOOK,
                "book_grabbed_at": (early or {}).get("grabbed_at"),
                "ds_total": round(float(ds["pred_total"]), 1),
                "ds_version": ds.get("model_version"),
                "ds_created_at": _iso(ds.get("created_at")),
                "mb_total": round(float(mb_total), 1),
                "mb_gated": bool(mbg.get("gated")),
                "mb_created_at": mb_export.get("created_at"),
                "ds_edge": round(d, 2),
                "mb_edge": round(m, 2),
                "avg_edge": round((d + m) / 2, 2),
                "min_rest_days": g.get("min_rest_days"),
            }
        )
    counts["bets"] = len(bets)
    counts["mb_export_ok"] = int(mb_ok)
    return bets, counts


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.isoformat() if isinstance(v, datetime) else str(v)


def _mb_fresh(export: Mapping[str, Any], now: datetime) -> bool:
    try:
        made = datetime.fromisoformat(str(export.get("created_at")))
    except ValueError:
        return False
    if made.tzinfo is None:
        return False
    return timedelta(0) <= now - made <= MB_MAX_AGE


def new_rows(existing: Iterable[Mapping[str, Any]], bets: Sequence[dict]) -> list[dict]:
    """Bets not yet logged under the same (rule version, game). The first logged row is the bet."""
    seen = {(r.get("rule_version"), str(r.get("game_id"))) for r in existing}
    out = []
    for b in bets:
        key = (b["rule_version"], str(b["game_id"]))
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out


# ---------- grading ----------


def _sane_total(v: float | None, league: str = LEAGUE) -> float | None:
    lim = SANE_LIMITS.get(league)
    if v is None or lim is None:
        return v
    return v if lim[1] <= v <= lim[2] else None


def total_clv(side: str, line: float, close: float | None) -> float | None:
    """Points the logged total beat the other total by, from the bet side's view."""
    if close is None:
        return None
    return float(close - line) if side == "over" else float(line - close)


def break_even(price: int) -> float:
    return -price / (-price + 100) if price < 0 else 100 / (price + 100)


def grade_bet(
    bet: Mapping[str, Any],
    final: Mapping[str, Any] | None,
    close_total: float | None,
    dayof: Mapping[str, Mapping] | None = None,
) -> dict[str, Any]:
    """The bet plus `grade` (win|loss|push|pending), `profit` (1 unit), `clv` vs the closing total,
    `close_grade` (graded at the closing total, same side) and `clv_dayof` (vs Caesars' own day-of
    quote for the side, when given)."""
    out = dict(bet)
    close = _sane_total(close_total, bet.get("league", LEAGUE))
    out["close_total"] = close
    out["clv"] = total_clv(bet["side"], bet["line"], close)
    q = (dayof or {}).get(bet["side"])
    out["clv_dayof"] = None if not q else total_clv(bet["side"], bet["line"], q["line"])
    if final is None:
        out.update(grade="pending", profit=None, close_grade=None)
        return out
    total = final["home_score"] + final["away_score"]
    margin = final["home_score"] - final["away_score"]
    res = outcome("total", bet["side"], bet["line"], margin, total)
    out["grade"] = res
    out["profit"] = round(
        profit_on_win(bet["price"], 1.0) if res == "win" else (0.0 if res == "push" else -1.0), 4
    )
    out["close_grade"] = None if close is None else outcome("total", bet["side"], close, 0, total)
    return out


def day_ci(
    items: Sequence[tuple[str, float]],
    stat: Callable[[list[float]], float] = lambda xs: sum(xs) / len(xs),
    reps: int = BOOT_REPS,
    seed: int = BOOT_SEED,
) -> tuple[float, float] | None:
    """95% bootstrap CI of `stat` resampling whole game days ((day, value) items)."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for d, v in items:
        by_day[d].append(v)
    keys = sorted(by_day)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(reps):
        pool = [x for _ in keys for x in by_day[rng.choice(keys)]]
        out.append(stat(pool))
    out.sort()
    return round(out[int(0.025 * reps)], 3), round(out[int(0.975 * reps) - 1], 3)


def _record(graded: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    w = sum(g["grade"] == "win" for g in graded)
    lo = sum(g["grade"] == "loss" for g in graded)
    pu = sum(g["grade"] == "push" for g in graded)
    profit = sum(g["profit"] for g in graded)
    clvs = [g["clv"] for g in graded if g.get("clv") is not None]
    cw = sum(g.get("close_grade") == "win" for g in graded)
    cl = sum(g.get("close_grade") == "loss" for g in graded)
    return {
        "bets": len(graded),
        "record": f"{w}-{lo}-{pu}",
        "win_pct": None if w + lo == 0 else round(w / (w + lo), 3),
        "units_profit": round(profit, 2),
        "roi": None if not graded else round(profit / len(graded), 3),
        "clv_n": len(clvs),
        "clv_mean": None if not clvs else round(sum(clvs) / len(clvs), 2),
        "clv_pct_positive": None if not clvs else round(sum(c > 0 for c in clvs) / len(clvs), 3),
        "win_pct_at_close": None if cw + cl == 0 else round(cw / (cw + cl), 3),
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Running record vs the pre-registered thresholds (`grade_bet` rows; pending ones counted)."""
    graded = [r for r in rows if r["grade"] != "pending"]
    out: dict[str, Any] = {
        "rule_version": RULE_VERSION,
        "logged": len(rows),
        "pending": len(rows) - len(graded),
        **_record(graded),
    }
    prices = [r["price"] for r in graded]
    out["break_even"] = None if not prices else round(sum(map(break_even, prices)) / len(prices), 3)
    clv_items = [(r["game_date"], r["clv"]) for r in graded if r.get("clv") is not None]
    out["clv_ci"] = day_ci(clv_items) if clv_items else None
    out["roi_ci"] = day_ci([(r["game_date"], r["profit"]) for r in graded]) if graded else None
    dayof = [r["clv_dayof"] for r in rows if r.get("clv_dayof") is not None]
    out["clv_dayof_n"] = len(dayof)
    out["clv_dayof_mean"] = None if not dayof else round(sum(dayof) / len(dayof), 2)
    splits = {
        "side": lambda r: r["side"],
        "edge": lambda r: "6+" if r["avg_edge"] >= 6 else "4-6",
        "ds_version": lambda r: r.get("ds_version") or "?",
        "rest": lambda r: (
            "?"
            if r.get("min_rest_days") is None
            else (">=2d" if r["min_rest_days"] >= 2 else "<2d")
        ),
    }
    out["splits"] = {}
    for name, key in splits.items():
        groups: dict[str, list] = defaultdict(list)
        for r in graded:
            groups[key(r)].append(r)
        out["splits"][name] = {k: _record(v) for k, v in sorted(groups.items())}
    out["verdict"] = verdict(out)
    return out


def verdict(s: Mapping[str, Any]) -> str:
    """Pre-registered decision (docs/results/2026-11-15-early-totals-preregistration.md)."""
    n = s["bets"]
    if n < VERDICT_N:
        return f"collecting ({n}/{VERDICT_N}; no decision before {VERDICT_N})"
    ci, clv, win, be = s.get("clv_ci"), s.get("clv_mean"), s.get("win_pct"), s.get("break_even")
    if ci and win is not None and be is not None and ci[0] > 0 and win >= be:
        return "PASS"
    if clv is None or clv <= 0 or (win is not None and win < 0.5):
        return "FAIL"
    if n < EXTENSION_N:
        return f"inconclusive: extend to {EXTENSION_N} ({n}/{EXTENSION_N})"
    return "FAIL (not a pass at the extension)"


def render(s: Mapping[str, Any]) -> str:
    """A few phone-readable lines."""

    def pct(v: float | None) -> str:
        return "-" if v is None else f"{v:.1%}"

    ci = s.get("clv_ci")
    rci = s.get("roi_ci")
    clv = "-" if s.get("clv_mean") is None else f"{s['clv_mean']:+.2f}"
    lines = [
        f"Early totals {s['rule_version']} (watch-only): {s['verdict']}",
        f"{s['bets']} graded ({s['record']}), {s['pending']} pending; win {pct(s['win_pct'])}"
        f" vs break-even {pct(s['break_even'])}; ROI {pct(s['roi'])}"
        + (f" [{rci[0]:+.1%}, {rci[1]:+.1%}]" if rci else ""),
        f"CLV vs close {clv} pts"
        + (f" [{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "")
        + f", {pct(s['clv_pct_positive'])} positive (n {s['clv_n']});"
        f" win at the close {pct(s['win_pct_at_close'])}",
    ]
    if s.get("clv_dayof_n"):
        lines.append(f"CLV vs Caesars day-of {s['clv_dayof_mean']:+.2f} (n {s['clv_dayof_n']})")
    return "\n".join(lines)
