"""Scoring rules for the et-v2 backtest (`docs/results/2026-11-23-et-v2-preregistration.md` and its
Amendment 1). Pure functions only: the base cell, the nine candidate rules (C0-C6, K1, K2), grading
at a price, the C5 shrink fit, the day-clustered bootstrap, Holm and the PASS test.

A *game* here is a mapping with these keys (all known at T = 21:00 PT on D-1 except the last three):
  season, day, ds, ds_alt, mb, gp, played_d1 (either team played on D-1),
  lines: {book: (point, over_price, under_price)} at T  (grading book included),
  open15: {book: point} at the earliest pulled D-1 snapshot (15:00),
  wh0900: point of the grading book at 0@09:00 (or None),
  final (final total), close (ESPN closing total) - outcomes, used only to grade.
Lines dicts hold only sane, pre-game quotes.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import numpy as np

THRESHOLD = 4.0  # base cell: avg edge >= 4.0
C2_AVG, C2_GP = 8.0, 10
C5_MIN = 1.5
C6_GAP = 1.0
DEFAULT_PRICE = -110
CANDIDATES = ("C0", "C1", "C2", "C3", "C4", "C5", "C6", "K1", "K2")
N_CONDITIONS = {"C0": 0, "C1": 1, "C2": 1, "C3": 1, "C4": 1, "C5": 1, "C6": 1, "K1": 2, "K2": 2}


# ---------------------------------------------------------------- basics


def payout(price: float) -> float:
    """Profit per unit staked at an American price when the bet wins."""
    return 100.0 / -price if price < 0 else price / 100.0


def implied(price: float) -> float:
    return -price / (-price + 100.0) if price < 0 else 100.0 / (price + 100.0)


def toward(side: str, a: float, b: float) -> float:
    """Move toward the pick from line a to line b (+ = the market moved our way)."""
    return b - a if side == "over" else a - b


def base_side(
    ds: float | None, mb: float | None, line: float | None, thr: float = THRESHOLD
) -> str | None:
    """The base cell: the side where both edges > 0 and the average edge >= thr, else None."""
    if ds is None or mb is None or line is None or _nan(ds) or _nan(mb):
        return None
    de, me = ds - line, mb - line
    if de > 0 and me > 0 and (de + me) / 2 >= thr:
        return "over"
    if de < 0 and me < 0 and -(de + me) / 2 >= thr:
        return "under"
    return None


def avg_edge(side: str, ds: float, mb: float, line: float) -> float:
    s = 1.0 if side == "over" else -1.0
    return s * ((ds - line) + (mb - line)) / 2


def _nan(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


# ---------------------------------------------------------------- rules


def c3_ok(side: str, line: float, pin: float | None) -> bool:
    """Pinnacle quotes and is on our side of or equal to the grading line."""
    if pin is None:
        return False
    return pin >= line if side == "over" else pin <= line


def c4_ok(side: str, g: Mapping[str, Any], book: str) -> bool:
    """Move toward the pick from the opener reference O to L >= 0. O = the grading book at the
    earliest D-1 snapshot; if it has no quote there, O and L both from DraftKings."""
    o = (g.get("open15") or {}).get(book)
    lt = g["lines"].get(book)
    if o is not None and lt is not None:
        return toward(side, o, lt[0]) >= 0
    o_dk = (g.get("open15") or {}).get("draftkings")
    l_dk = g["lines"].get("draftkings")
    if o_dk is not None and l_dk is not None:
        return toward(side, o_dk, l_dk[0]) >= 0
    return False


def c6_ok(side: str, line: float, others: Sequence[float]) -> bool:
    """False (skip) when the grading book is off-market in our favor by >= 1 point against the
    median of every other book quoting at T; fewer than 2 others -> not skipped."""
    if len(others) < 2:
        return True
    med = statistics.median(others)
    if side == "over":
        return not (med - line >= C6_GAP)
    return not (line - med >= C6_GAP)


def shrunk_edge(side: str, b: tuple[float, float], ds: float, mb: float, line: float) -> float:
    s = 1.0 if side == "over" else -1.0
    return b[0] * s * (ds - line) + b[1] * s * (mb - line)


def fit_shrink(rows: Iterable[tuple[float, float, float, float]]) -> tuple[float, float] | None:
    """OLS without intercept of (final - L) on (DS - L, MB - L); each b clipped to [0, 1].
    rows: (ds, mb, line, final)."""
    x, y = [], []
    for ds, mb, line, final in rows:
        x.append((ds - line, mb - line))
        y.append(final - line)
    if len(y) < 2:
        return None
    b = np.linalg.lstsq(np.array(x, float), np.array(y, float), rcond=None)[0]
    return float(np.clip(b[0], 0, 1)), float(np.clip(b[1], 0, 1))


def pick(
    rule: str, g: Mapping[str, Any], book: str, shrink: tuple[float, float] | None = None
) -> str | None:
    """The side the rule bets on game g graded at `book`, or None (no bet)."""
    lt = g["lines"].get(book)
    if lt is None:
        return None
    line = lt[0]
    if rule in ("C1", "K1"):
        side = base_side(g.get("ds_alt"), g["mb"], line)
    else:
        side = base_side(g["ds"], g["mb"], line)
    if side is None:
        return None
    others = [v[0] for k, v in g["lines"].items() if k != book]
    pin = g["lines"].get("pinnacle")
    pin_line = pin[0] if pin is not None and book != "pinnacle" else None
    if rule in ("C0", "C1"):
        return side
    if rule == "C2":
        ok = (
            avg_edge(side, g["ds"], g["mb"], line) >= C2_AVG
            and g["gp"] is not None
            and g["gp"] < C2_GP
        )
    elif rule == "C3":
        ok = c3_ok(side, line, pin_line)
    elif rule == "C4":
        ok = c4_ok(side, g, book)
    elif rule == "C5":
        ok = shrink is not None and shrunk_edge(side, shrink, g["ds"], g["mb"], line) >= C5_MIN
    elif rule in ("C6", "K1"):
        ok = c6_ok(side, line, others)
    elif rule == "K2":
        ok = c3_ok(side, line, pin_line) and c4_ok(side, g, book)
    else:
        raise ValueError(rule)
    return side if ok else None


# ---------------------------------------------------------------- grading


def grade(
    side: str, line: float, price: float | None, final: float
) -> tuple[float, int | None, float]:
    """(pnl at price, win 1/0 or None for a push, implied probability of the price)."""
    p = DEFAULT_PRICE if price is None else price
    d = toward(side, line, final)  # final above the line is good for an over
    if d == 0:
        return 0.0, None, implied(p)
    return (payout(p), 1, implied(p)) if d > 0 else (-1.0, 0, implied(p))


# ---------------------------------------------------------------- bootstrap


def day_weights(
    days: Sequence[Any], reps: int = 10_000, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Multinomial day-resample counts (reps x n_days) and each row's day index."""
    u, idx = np.unique(np.asarray(days, dtype=str), return_inverse=True)
    rng = np.random.default_rng(seed)
    w = rng.multinomial(len(u), np.full(len(u), 1.0 / len(u)), size=reps).astype(float)
    return w, idx


def boot_stats(
    days: Sequence[Any],
    pnl: Sequence[float],
    win: Sequence[float],
    be: Sequence[float],
    reps: int = 10_000,
    seed: int = 0,
) -> dict[str, float]:
    """Day-clustered bootstrap: ROI 95% CI and the one-sided p = share of resamples with
    win % <= break-even (both over decided bets; win is nan for pushes)."""
    pnl, win, be = (np.asarray(x, float) for x in (pnl, win, be))
    n = len(pnl)
    if n == 0:
        return {"roi_lo": math.nan, "roi_hi": math.nan, "p": math.nan}
    w, idx = day_weights(days, reps, seed)
    k = w.shape[1]
    dec = ~np.isnan(win)

    def agg(x: np.ndarray) -> np.ndarray:
        return w @ np.bincount(idx, weights=x, minlength=k)

    cnt = agg(np.ones(n))
    roi = agg(pnl) / np.maximum(cnt, 1)
    nd = agg(dec.astype(float))
    wr = agg(np.where(dec, win, 0.0)) / np.maximum(nd, 1)
    br = agg(np.where(dec, be, 0.0)) / np.maximum(nd, 1)
    lo, hi = np.percentile(roi, [2.5, 97.5])
    return {"roi_lo": float(lo), "roi_hi": float(hi), "p": float(np.mean(wr <= br))}


def boot_mean_ci(
    days: Sequence[Any], x: Sequence[float], reps: int = 10_000, seed: int = 0
) -> tuple[float, float]:
    x = np.asarray(x, float)
    if len(x) == 0:
        return math.nan, math.nan
    w, idx = day_weights(days, reps, seed)
    k = w.shape[1]
    est = (w @ np.bincount(idx, weights=x, minlength=k)) / np.maximum(
        w @ np.bincount(idx, minlength=k), 1
    )
    lo, hi = np.percentile(est, [2.5, 97.5])
    return float(lo), float(hi)


# ---------------------------------------------------------------- family + pass


def holm(pvals: Mapping[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Holm step-down: True = rejected (passes) at family-wise alpha."""
    order = sorted(pvals, key=lambda k: pvals[k])
    m = len(order)
    out = {k: False for k in pvals}
    for i, k in enumerate(order):
        if pvals[k] <= alpha / (m - i):
            out[k] = True
        else:
            break
    return out


def season_rule_ok(
    per_season: Mapping[Any, Mapping[str, float]], min_n: int = 100, min_seasons: int = 3
) -> bool:
    """PASS part 1: ROI > 0 in every season with >= min_n bets; >= min_n bets in >= min_seasons."""
    big = [s for s, v in per_season.items() if v["n"] >= min_n]
    return len(big) >= min_seasons and all(per_season[s]["roi"] > 0 for s in big)


def practical(per_season: Mapping[Any, Mapping[str, float]], floor: int = 150) -> bool:
    return all(v["n"] >= floor for v in per_season.values())


def tie_break(passers: Mapping[str, float], tol: float = 0.005) -> str | None:
    """passers: rule -> pooled ROI lower 95% bound. Highest bound; within tol of it, the rule with
    fewer conditions (C0 < single filters < combos)."""
    if not passers:
        return None
    best = max(passers.values())
    near = [r for r, v in passers.items() if best - v <= tol]
    return min(near, key=lambda r: (N_CONDITIONS[r], -passers[r]))


def summarize(
    rows: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], Any] | None = None
) -> dict:
    """n, W-L-P, win %, ROI, break-even over bet rows (pnl, win, be)."""
    n = len(rows)
    w = sum(1 for r in rows if r["win"] == 1)
    lo = sum(1 for r in rows if r["win"] == 0)
    dec = [r for r in rows if r["win"] is not None]
    return {
        "n": n,
        "w": w,
        "l": lo,
        "push": n - w - lo,
        "win": w / (w + lo) if w + lo else math.nan,
        "roi": sum(r["pnl"] for r in rows) / n if n else math.nan,
        "be": statistics.fmean(r["be"] for r in dec) if dec else math.nan,
    }
