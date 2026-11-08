"""Betting simulation on the model's out-of-sample (walk-forward) predictions.

    uv run python -m deepsports.analysis.simulate --model-version v1.0 --bankroll 100 \
        --out /Volumes/ExFATStorag/DeepSports/reports/sim-v1-100usd.md

Answers "how would $100 have done if we had bet the model's disagreements with the market?"
This is a measurement, not a recommendation: DeepSports does not place bets (docs/PRODUCT.md).

Rules (see tests/test_simulate.py):
- Predictions come from `backtest.walk_forward`: each game is predicted by a model trained only
  on games that tipped off before that game's month began.
- A bet is decided from the prediction and the line only; its result is applied afterwards.
- Bets are processed by game day (US Eastern date of tip-off) in tip-off order. Every stake on a
  day is sized from the bankroll at the start of that day, and the stakes of one day can never
  add up to more than that bankroll. The bankroll only changes once the day's games are final.
- Stakes are rounded down to whole cents; a stake under `min_bet` is not placed. Once the
  bankroll is below `min_bet` the run is over (busted).
- Pricing (`--pricing`): 'real' (default) prices each spread/total bet at the stored American
  price of its side on the same odds row (`spread_home_price` / `spread_away_price`,
  `over_price` / `under_price`), falling back to -110 only where that price is NULL or invalid
  (counted and reported); '-110' prices every spread/total bet at -110 (the 2026-11-04 report).
  Moneyline bets always use the stored American odds. Pushes return the stake.

Opens the warehouse read-only ($DEEPSPORTS_DB or config.DB_PATH), retrying while a writer holds it.
"""

import argparse
import csv
import math
import shutil
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import numpy as np

from deepsports import config
from deepsports.analysis.metrics import american_to_decimal, devig_probability

EASTERN = ZoneInfo("America/New_York")
PRICE_110 = 1 + 100 / 110  # decimal odds of a -110 bet
BREAK_EVEN_110 = 110 / 210  # 52.38%
SPREAD_THRESHOLDS = (0.0, 1.0, 2.0, 3.0, 5.0)  # points of disagreement with the spread
TOTAL_THRESHOLDS = (0.0, 2.0, 4.0, 6.0, 10.0)  # points of disagreement with the total
ML_EDGES = (0.0, 0.02, 0.05, 0.08, 0.12)  # model prob - vig-free market prob
# Headline thresholds, fixed before any simulation was run (not chosen from the results).
HEADLINE = {"spread": 3.0, "total": 4.0, "moneyline": 0.05}
TIMINGS = ("closing", "opening")
PRICINGS = ("real", "-110")
# odds row key holding the American price of each spread/total side
PRICE_KEYS = {
    "home": "spread_home_price",
    "away": "spread_away_price",
    "over": "over_price",
    "under": "under_price",
}
DEFAULT_CSV_DIR = Path("/Volumes/ExFATStorag/DeepSports/reports/sim")
SANE_SPREAD, SANE_TOTAL = 40.0, (150.0, 320.0)


# ---------- bets ----------


@dataclass(frozen=True)
class Bet:
    """One wager, decided before tip-off. `result`: +1 win, 0 push, -1 loss for the chosen
    side; `alt_*` are the same for the opposite side (used by the coin-flip baseline)."""

    game_id: str
    start: datetime
    day: date
    season: int
    market: str  # spread | total | moneyline
    side: str  # home | away | over | under
    decimal: float  # payout per 1 staked, stake included
    result: int
    alt_side: str
    alt_decimal: float
    alt_result: int
    p_win: float | None = None  # model probability the side wins (moneyline only, for Kelly)
    real_price: bool = True  # False: spread/total priced at -110 because the side's price was NULL


def side_price(ln: dict[str, Any], side: str, pricing: str = "real") -> tuple[float, bool]:
    """(decimal odds, real?) for a spread/total `side` on odds row `ln`. 'real' uses the row's
    stored American price for that side; a NULL or invalid price falls back to -110 (real =
    False). '-110' always returns -110 (real = False)."""
    if pricing not in PRICINGS:
        raise ValueError(f"unknown pricing {pricing!r} (use {', '.join(PRICINGS)})")
    if pricing == "real":
        d = american_to_decimal(ln.get(PRICE_KEYS[side]))
        if d is not None:
            return d, True
    return PRICE_110, False


def game_day(t: datetime) -> date:
    """NBA game day: the US Eastern calendar date of tip-off (a 10:30 pm ET tip is that day)."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(EASTERN).date()


def _sign(x: float) -> int:
    return 0 if x == 0 else (1 if x > 0 else -1)


def select_bets(
    games: Sequence[dict[str, Any]],
    market: str,
    timing: str = "closing",
    rule: str = "model",
    threshold: float = 0.0,
    pricing: str = "real",
) -> list[Bet]:
    """Pick at most one bet per game. Uses only the prediction and the line to choose a side;
    the outcome fields are read afterwards only to label the bet's result.

    rule: 'model' (bet the model's side when it disagrees by >= threshold; an exact tie is no
    bet), 'home' (always the home team: spread / moneyline), 'over' (always the over),
    'favorite' (moneyline: the side with the shorter price; equal prices are skipped).
    Each game needs a line at `timing` ('closing' or 'opening'); games without one are skipped.
    `pricing` ('real' or '-110') prices spread/total sides (see side_price); the price never
    affects which side is chosen.
    """
    out = []
    for g in sorted(games, key=lambda x: (x["start"], x["game_id"])):
        ln = (g.get("lines") or {}).get(timing)
        if not ln:
            continue
        common = {
            "game_id": g["game_id"],
            "start": g["start"],
            "day": game_day(g["start"]),
            "season": g["season"],
            "market": market,
        }
        if market == "spread":
            if ln.get("spread_home") is None:
                continue
            edge = g["pred_home_margin"] + ln["spread_home"]  # model margin - market margin
            if rule == "model":
                if edge == 0 or abs(edge) < threshold:
                    continue
                home = edge > 0
            elif rule == "home":
                home = True
            else:
                raise ValueError(f"rule {rule!r} not valid for spread")
            r_home = _sign(g["home_margin"] + ln["spread_home"])
            sides = (("home", r_home), ("away", -r_home))
            (s, r), (a, ar) = sides if home else sides[::-1]
            (d, real), (ad, _) = side_price(ln, s, pricing), side_price(ln, a, pricing)
            out.append(Bet(**common, side=s, decimal=d, result=r, alt_side=a,
                           alt_decimal=ad, alt_result=ar, real_price=real))  # fmt: skip
        elif market == "total":
            if ln.get("over_under") is None:
                continue
            edge = g["pred_total"] - ln["over_under"]
            if rule == "model":
                if edge == 0 or abs(edge) < threshold:
                    continue
                over = edge > 0
            elif rule == "over":
                over = True
            else:
                raise ValueError(f"rule {rule!r} not valid for total")
            r_over = _sign(g["total"] - ln["over_under"])
            sides = (("over", r_over), ("under", -r_over))
            (s, r), (a, ar) = sides if over else sides[::-1]
            (d, real), (ad, _) = side_price(ln, s, pricing), side_price(ln, a, pricing)
            out.append(Bet(**common, side=s, decimal=d, result=r, alt_side=a,
                           alt_decimal=ad, alt_result=ar, real_price=real))  # fmt: skip
        elif market == "moneyline":
            dh = american_to_decimal(ln.get("home_ml"))
            da = american_to_decimal(ln.get("away_ml"))
            p_mkt = devig_probability(ln.get("home_ml"), ln.get("away_ml"))
            if dh is None or da is None or p_mkt is None:
                continue
            edge = g["p_home_win"] - p_mkt
            if rule == "model":
                if edge == 0 or abs(edge) < threshold:
                    continue
                home = edge > 0
            elif rule == "home":
                home = True
            elif rule == "favorite":
                if dh == da:
                    continue
                home = dh < da
            else:
                raise ValueError(f"rule {rule!r} not valid for moneyline")
            r_home = 1 if g["home_margin"] > 0 else -1
            p_home = g["p_home_win"]
            h = ("home", dh, r_home, p_home)
            w = ("away", da, -r_home, 1 - p_home)
            (s, d, r, p), (a, ad, ar, _) = (h, w) if home else (w, h)
            out.append(Bet(**common, side=s, decimal=d, result=r, alt_side=a,
                           alt_decimal=ad, alt_result=ar, p_win=p))  # fmt: skip
        else:
            raise ValueError(f"unknown market {market!r}")
    return out


# ---------- sizing ----------


@dataclass(frozen=True)
class Sizing:
    """stake = flat + frac * (bankroll at the start of the day), with per-bet `frac` for Kelly."""

    name: str
    flat: float = 0.0
    frac: float = 0.0
    kelly: float = 0.0  # fraction of full Kelly (0 = not Kelly)
    cap: float = 1.0  # max fraction of the bankroll per bet (Kelly)

    def fractions(self, bets: Sequence[Bet]) -> np.ndarray:
        if not self.kelly:
            return np.full(len(bets), self.frac)
        return np.array([kelly_fraction(b.p_win, b.decimal, self.kelly, self.cap) for b in bets])


def kelly_fraction(p: float | None, decimal: float, mult: float = 0.25, cap: float = 0.05) -> float:
    """mult * full Kelly (p*d - 1) / (d - 1), capped; 0 when the model sees no positive value."""
    if p is None or decimal <= 1:
        return 0.0
    full = (p * decimal - 1) / (decimal - 1)
    return max(0.0, min(cap, mult * full))


def flat_dollars(amount: float) -> Sizing:
    return Sizing(f"flat ${amount:g}", flat=amount)


def flat_pct(frac: float) -> Sizing:
    return Sizing(f"{frac:.0%} of bankroll", frac=frac)


def quarter_kelly(cap: float = 0.05) -> Sizing:
    return Sizing(f"1/4 Kelly (cap {cap:.0%})", kelly=0.25, cap=cap)


# ---------- engine ----------


def run_engine(
    day_index: Sequence[int],
    result: np.ndarray,
    decimal: np.ndarray,
    flat: float,
    frac: np.ndarray,
    start: float = 100.0,
    min_bet: float = 0.01,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized bankroll simulation over `runs` parallel histories.

    day_index: per bet, its day number (non-decreasing). result/decimal: (runs, n) arrays.
    Returns (stakes (runs, n), bankroll after each distinct day (runs, n_days)).
    """
    result = np.atleast_2d(result)
    decimal = np.atleast_2d(decimal)
    runs, n = result.shape
    bank = np.full(runs, float(start))
    stakes = np.zeros((runs, n))
    day_end = []
    i = 0
    while i < n:
        j = i
        while j < n and day_index[j] == day_index[i]:
            j += 1
        sod = bank.copy()  # sizes come from the start-of-day bankroll
        avail = sod.copy()  # cash not yet staked today
        back = np.zeros(runs)  # money returned when today's games are final
        for k in range(i, j):
            want = flat + frac[k] * sod
            st = np.floor(np.minimum(want, avail) * 100 + 1e-9) / 100
            st = np.where(st < min_bet - 1e-12, 0.0, st)
            avail = avail - st
            stakes[:, k] = st
            r = result[:, k]
            back += np.where(r > 0, st * decimal[:, k], np.where(r == 0, st, 0.0))
        bank = avail + back
        day_end.append(bank.copy())
        i = j
    days = np.array(day_end).T if day_end else np.zeros((runs, 0))
    return stakes, days


def _day_index(bets: Sequence[Bet]) -> tuple[list[int], list[date]]:
    idx, days = [], []
    for b in bets:
        if not days or b.day != days[-1]:
            if days and b.day < days[-1]:
                raise ValueError("bets must be in tip-off order")
            days.append(b.day)
        idx.append(len(days) - 1)
    return idx, days


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = wins / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def simulate(
    bets: Sequence[Bet], sizing: Sizing, start: float = 100.0, min_bet: float = 0.01
) -> dict[str, Any]:
    """One bankroll history for `bets` (in tip-off order). Returns the per-bet ledger,
    the end-of-day bankroll series, and summary statistics."""
    bets = list(bets)
    idx, days = _day_index(bets)
    res = np.array([[b.result for b in bets]], dtype=float)
    dec = np.array([[b.decimal for b in bets]], dtype=float)
    stakes, day_bank = run_engine(
        idx, res, dec, sizing.flat, sizing.fractions(bets), start, min_bet
    )
    stakes, day_bank = stakes[0], day_bank[0]
    ledger = []
    for b, st in zip(bets, stakes, strict=True):
        if st <= 0:
            continue
        profit = st * (b.decimal - 1) if b.result > 0 else (0.0 if b.result == 0 else -st)
        ledger.append({"bet": b, "stake": float(st), "profit": float(profit)})
    daily = [{"date": d, "bankroll": float(x)} for d, x in zip(days, day_bank, strict=True)]
    return {"ledger": ledger, "daily": daily, "summary": summarize(ledger, daily, start, min_bet)}


def summarize(
    ledger: list[dict[str, Any]], daily: list[dict[str, Any]], start: float, min_bet: float = 0.01
) -> dict[str, Any]:
    w = sum(1 for x in ledger if x["bet"].result > 0)
    lo = sum(1 for x in ledger if x["bet"].result < 0)
    pu = sum(1 for x in ledger if x["bet"].result == 0)
    staked = sum(x["stake"] for x in ledger)
    final = daily[-1]["bankroll"] if daily else start
    peak, max_dd, max_dd_usd = start, 0.0, 0.0
    for d in daily:
        peak = max(peak, d["bankroll"])
        max_dd = max(max_dd, (peak - d["bankroll"]) / peak if peak > 0 else 0.0)
        max_dd_usd = max(max_dd_usd, peak - d["bankroll"])
    streak = longest = 0
    for x in ledger:  # pushes neither extend nor break a losing streak
        if x["bet"].result < 0:
            streak += 1
            longest = max(longest, streak)
        elif x["bet"].result > 0:
            streak = 0
    by_season: dict[int, float] = {}
    season_of_day = {}
    for x in ledger:
        season_of_day[x["bet"].day] = x["bet"].season
    for d in daily:
        s = season_of_day.get(d["date"])
        if s is not None:
            by_season[s] = d["bankroll"]
    bust_day = next((d["date"] for d in daily if d["bankroll"] < min_bet), None)
    ci = wilson(w, w + lo)
    return {
        "bets": len(ledger),
        "wins": w,
        "losses": lo,
        "pushes": pu,
        "hit_rate": w / (w + lo) if w + lo else None,
        "ci_lo": ci[0],
        "ci_hi": ci[1],
        "staked": staked,
        "final": final,
        "profit": final - start,
        "roi": (final - start) / staked if staked else None,
        "max_dd": max_dd,
        "max_dd_usd": max_dd_usd,
        "longest_losing": longest,
        "by_season": by_season,
        "busted": bust_day,
    }


# ---------- resampling ----------


def bootstrap(
    bets: Sequence[Bet],
    sizing: Sizing,
    start: float = 100.0,
    n_boot: int = 2000,
    seed: int = 0,
    min_bet: float = 0.01,
) -> dict[str, Any] | None:
    """Resample the bets with replacement (same count), play each resample one bet at a time,
    and summarize the final bankrolls. Measures luck around the realized hit rate; it assumes
    bets are independent and cannot tell whether that hit rate reflects skill."""
    bets = list(bets)
    if not bets:
        return None
    rng = np.random.default_rng(seed)
    res = np.array([b.result for b in bets], dtype=float)
    dec = np.array([b.decimal for b in bets], dtype=float)
    frac = sizing.fractions(bets)
    pick = rng.integers(0, len(bets), size=(n_boot, len(bets)))
    # each resampled bet is its own "day"; per-bet Kelly fractions travel with the bet
    out = np.full(n_boot, float(start))
    for k in range(len(bets)):
        col = pick[:, k]
        want = sizing.flat + frac[col] * out
        st = np.floor(np.minimum(want, out) * 100 + 1e-9) / 100
        st = np.where(st < min_bet - 1e-12, 0.0, st)
        r = res[col]
        out = out - st + np.where(r > 0, st * dec[col], np.where(r == 0, st, 0.0))
    return {
        "n": n_boot,
        "median": float(np.median(out)),
        "p5": float(np.percentile(out, 5)),
        "p95": float(np.percentile(out, 95)),
        "p_above_start": float(np.mean(out > start)),
        "p_bust": float(np.mean(out < min_bet)),
    }


def coin_flip(
    bets: Sequence[Bet],
    sizing: Sizing,
    start: float = 100.0,
    runs: int = 500,
    seed: int = 0,
    min_bet: float = 0.01,
) -> dict[str, Any] | None:
    """Same games and timing as `bets`, but each side picked by a fair coin, `runs` times.
    (Kelly sizing is not meaningful for a coin, so only flat sizes are used.)"""
    bets = list(bets)
    if not bets:
        return None
    rng = np.random.default_rng(seed)
    idx, _ = _day_index(bets)
    flip = rng.integers(0, 2, size=(runs, len(bets))).astype(bool)
    res = np.where(flip, [b.alt_result for b in bets], [b.result for b in bets]).astype(float)
    dec = np.where(flip, [b.alt_decimal for b in bets], [b.decimal for b in bets])
    stakes, day_bank = run_engine(
        idx, res, dec, sizing.flat, np.full(len(bets), sizing.frac), start, min_bet
    )
    final = day_bank[:, -1]
    staked = stakes.sum(axis=1)
    roi = np.where(staked > 0, (final - start) / np.where(staked > 0, staked, 1), np.nan)
    return {
        "runs": runs,
        "mean_final": float(final.mean()),
        "p5": float(np.percentile(final, 5)),
        "p95": float(np.percentile(final, 95)),
        "mean_roi": float(np.nanmean(roi)),
        "p_bust": float(np.mean(final < min_bet)),
    }


# ---------- calibration ----------


def calibration(games: Sequence[dict[str, Any]], bins: int = 10) -> list[dict[str, Any]]:
    """Model home-win probability by bin vs how often the home team actually won, with the
    vig-free closing probability on the same games (where it exists) for comparison."""
    buckets: dict[int, list] = defaultdict(list)
    for g in games:
        buckets[min(int(g["p_home_win"] * bins), bins - 1)].append(g)
    out = []
    for b in sorted(buckets):
        gs = buckets[b]
        wins = sum(1 for g in gs if g["home_margin"] > 0)
        mk = [g["market_p_close"] for g in gs if g.get("market_p_close") is not None]
        ci = wilson(wins, len(gs))
        out.append(
            {
                "lo": b / bins,
                "hi": (b + 1) / bins,
                "n": len(gs),
                "pred": sum(g["p_home_win"] for g in gs) / len(gs),
                "actual": wins / len(gs),
                "ci_lo": ci[0],
                "ci_hi": ci[1],
                "market": sum(mk) / len(mk) if mk else None,
            }
        )
    return out


def edge_calibration(bets: Sequence[Bet], games_by_id: dict[str, dict[str, Any]], timing: str):
    """On moneyline bets: the model's average win probability for the side it bet, the
    market's (vig-free), and the side's actual win rate. Kelly is justified only if the actual
    rate tracks the model, not the market."""
    if not bets:
        return None
    pm, pk = [], []
    for b in bets:
        ln = games_by_id[b.game_id]["lines"][timing]
        p_home = devig_probability(ln["home_ml"], ln["away_ml"])
        pk.append(p_home if b.side == "home" else 1 - p_home)
        pm.append(b.p_win)
    wins = sum(1 for b in bets if b.result > 0)
    return {
        "n": len(bets),
        "model": sum(pm) / len(pm),
        "market": sum(pk) / len(pk),
        "actual": wins / len(bets),
        "ci": wilson(wins, len(bets)),
    }


def line_value(bets: Sequence[Bet], games_by_id: dict[str, dict[str, Any]]) -> dict | None:
    """Closing-line value of opening-line bets: how far the line moved between the opening and
    the close in the bet's favor (points for spread/total, vig-free probability for moneyline).
    Positive = the market later moved toward the model's side, a sign of real information."""
    moves = []
    for b in bets:
        ln = games_by_id[b.game_id]["lines"]
        o, c = ln.get("opening"), ln.get("closing")
        if not o or not c:
            continue
        if b.market == "spread":
            if o["spread_home"] is None or c["spread_home"] is None:
                continue
            d = o["spread_home"] - c["spread_home"]  # > 0: home became a bigger favorite
            moves.append(d if b.side == "home" else -d)
        elif b.market == "total":
            if o["over_under"] is None or c["over_under"] is None:
                continue
            d = c["over_under"] - o["over_under"]
            moves.append(d if b.side == "over" else -d)
        else:
            po = devig_probability(o["home_ml"], o["away_ml"])
            pc = devig_probability(c["home_ml"], c["away_ml"])
            if po is None or pc is None:
                continue
            moves.append((pc - po) if b.side == "home" else (po - pc))
    if not moves:
        return None
    return {
        "n": len(moves),
        "mean": sum(moves) / len(moves),
        "toward": sum(1 for m in moves if m > 0) / len(moves),
        "against": sum(1 for m in moves if m < 0) / len(moves),
    }


# ---------- data ----------


def connect_read_only(path: Path, tries: int = 20, wait: float = 15.0):
    """Open the warehouse read-only, retrying while the scheduled sync holds the write lock."""
    for i in range(tries):
        try:
            return duckdb.connect(str(path), read_only=True)
        except duckdb.IOException as e:  # lock held by a writer
            if i == tries - 1:
                raise
            print(f"warehouse locked ({e}); retrying in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def load_lines(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, dict[str, Any]]]:
    """game_id -> {'closing': {...}, 'opening': {...}}: the latest closing row and the earliest
    opening row, with implausible spreads/totals set to None (same filters as market.py)."""
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    have = {r[0] for r in con.execute("DESCRIBE odds_snapshots").fetchall()}
    keys = list(PRICE_KEYS.values())
    price_cols = ", ".join(k if k in have else f"NULL AS {k}" for k in keys)  # older warehouses
    for source, order in (("closing", "DESC"), ("opening", "ASC")):
        rows = con.execute(
            f"""
            SELECT game_id, provider, spread_home, over_under, home_moneyline, away_moneyline,
                   {price_cols}
            FROM odds_snapshots WHERE source = ?
            QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at {order}) = 1
            """,
            [source],
        ).fetchall()
        for gid, prov, sp, ou, hml, aml, *prices in rows:
            out[gid][source] = {
                **dict(zip(keys, prices, strict=True)),
                "provider": prov,
                "spread_home": sp if sp is not None and abs(sp) <= SANE_SPREAD else None,
                "over_under": ou
                if ou is not None and SANE_TOTAL[0] <= ou <= SANE_TOTAL[1]
                else None,
                "home_ml": hml,
                "away_ml": aml,
            }
    return dict(out)


def out_of_sample_predictions(
    con: duckdb.DuckDBPyConnection, model_version: str = "v1.0", refit: str = "monthly"
) -> dict[str, Any]:
    """Walk-forward predictions exactly as the backtest report makes them.

    backtest.py / model.py are being extended in parallel, so this calls their public
    functions defensively: older signatures without versions fall back to plain ModelV1."""
    from deepsports.analysis import backtest, features, model

    version = model_version
    try:
        version = model.resolve_version(model_version)
        players = model.uses_players(model_version)
        factory = lambda: model.make_model(version)  # noqa: E731
    except AttributeError:
        if model_version.split("-")[0] not in ("v1", "v1.0"):
            raise
        players, factory = False, model.ModelV1
    try:
        rows = features.build_features(con, include_players=players)
    except TypeError:
        if players:
            raise
        rows = features.build_features(con)
    try:
        wf = backtest.walk_forward(rows, refit=refit, model_factory=factory)
    except TypeError:
        wf = backtest.walk_forward(rows, refit=refit)
    # either team played the day before (the main way a feature can postdate an opening line)
    b2b = {
        r["game_id"]: bool(
            (r["features"].get("b2b_home") or 0) > 0 or (r["features"].get("b2b_away") or 0) > 0
        )
        for r in rows
    }
    return {"version": version, "b2b": b2b, **wf}


def prepare_games(
    preds: list[dict[str, Any]], lines: dict[str, dict], b2b: dict[str, bool] | None = None
) -> list[dict[str, Any]]:
    games = []
    for p in preds:
        ln = lines.get(p["game_id"], {})
        close = ln.get("closing", {})
        games.append(
            {
                "game_id": p["game_id"],
                "season": p["season"],
                "start": p["start_time_utc"],
                "p_home_win": p["p_home_win"],
                "pred_home_margin": p["pred_home_margin"],
                "pred_total": p["pred_total"],
                "home_margin": p["home_margin"],
                "total": p["total"],
                "lines": ln,
                "b2b": (b2b or {}).get(p["game_id"], False),
                "market_p_close": devig_probability(close.get("home_ml"), close.get("away_ml")),
            }
        )
    games.sort(key=lambda g: (g["start"], g["game_id"]))
    return games


# ---------- strategies ----------

MARKETS = {
    "spread": SPREAD_THRESHOLDS,
    "total": TOTAL_THRESHOLDS,
    "moneyline": ML_EDGES,
}
BASELINES = {"spread": "home", "total": "over", "moneyline": "favorite"}


def sizings(market: str, flat: float, pct: float) -> list[Sizing]:
    out = [flat_dollars(flat), flat_pct(pct)]
    return out + [quarter_kelly()] if market == "moneyline" else out


def _slug(*parts: Any) -> str:
    s = "-".join(str(p) for p in parts).lower()
    for a, b in ((" ", ""), ("$", "usd"), ("%", "pct"), ("/", ""), ("(", ""), (")", "")):
        s = s.replace(a, b)
    return s


def price_stats(bets: Sequence[Bet], unit: float = 2.0) -> dict[str, Any] | None:
    """Spread/total bets only: how many used a real price vs the -110 fallback, the average
    decimal price and break-even hit rate, and the price's effect vs -110 per `unit` bet:
    `win_diff` = extra payout if the bet wins, `realized` = extra profit actually collected
    (wins only; losses and pushes cost the same at any price). Bankroll-independent."""
    bets = [b for b in bets if b.market in ("spread", "total")]
    if not bets:
        return None
    dec = np.array([b.decimal for b in bets])
    won = np.array([b.result > 0 for b in bets])
    return {
        "n": len(bets),
        "fallback": sum(1 for b in bets if not b.real_price),
        "mean_decimal": float(dec.mean()),
        "break_even": float(np.mean(1 / dec)),
        "win_diff": float(unit * (dec.mean() - PRICE_110)),
        "realized": float(unit * np.mean(np.where(won, dec - PRICE_110, 0.0))),
    }


def run_all(
    games: list[dict[str, Any]],
    start: float = 100.0,
    flat: float | None = None,
    pct: float = 0.02,
    n_boot: int = 2000,
    coin_runs: int = 500,
    seed: int = 7,
    pricing: str = "real",
) -> list[dict[str, Any]]:
    """Every (timing, market, rule, threshold, sizing) combination, plus baselines."""
    flat = start * 0.02 if flat is None else flat
    by_id = {g["game_id"]: g for g in games}
    out = []
    for timing in TIMINGS:
        for market, thresholds in MARKETS.items():
            candidates = [("model", t) for t in thresholds] + [(BASELINES[market], None)]
            if market == "moneyline":
                candidates.append(("home", None))
            for rule, t in candidates:
                bets = select_bets(games, market, timing, rule, t or 0.0, pricing)
                prices = price_stats(bets, flat)
                for sz in sizings(market, flat, pct):
                    if sz.kelly and rule != "model":
                        continue  # Kelly needs a model probability
                    sim = simulate(bets, sz, start)
                    row = {
                        "timing": timing,
                        "market": market,
                        "rule": rule,
                        "threshold": t,
                        "sizing": sz.name,
                        "kelly": bool(sz.kelly),
                        "slug": _slug(
                            timing, market, rule, "" if t is None else f"t{t:g}", sz.name
                        ),
                        "summary": sim["summary"],
                        "daily": sim["daily"],
                        "n_candidates": len(bets),
                        "prices": prices,
                    }
                    if not sz.kelly:
                        row["coin"] = coin_flip(bets, sz, start, coin_runs, seed)
                        if rule == "model":
                            row["boot"] = bootstrap(bets, sz, start, n_boot, seed)
                    if rule == "model" and market == "moneyline":
                        row["edge_cal"] = edge_calibration(bets, by_id, timing)
                    if rule == "model" and timing == "opening" and not sz.kelly:
                        row["clv"] = line_value(bets, by_id)
                    out.append(row)
    return out


def robustness(
    games: list[dict[str, Any]], start: float = 100.0, flat: float = 2.0, pricing: str = "real"
) -> list[dict[str, Any]]:
    """Headline strategies at both timings on games where neither team played the day before
    (removes the main path by which the model could know a result the opening line did not)."""
    rested = [g for g in games if not g["b2b"]]
    out = []
    for timing in TIMINGS:
        for market, t in HEADLINE.items():
            for label, gs in (("all games", games), ("no back-to-backs", rested)):
                bets = select_bets(gs, market, timing, "model", t, pricing)
                final = simulate(bets, flat_dollars(flat), start)["summary"]["final"]
                u = sum((b.decimal - 1) if b.result > 0 else (0 if b.result == 0 else -1)
                        for b in bets)  # fmt: skip
                w = sum(1 for b in bets if b.result > 0)
                lo = sum(1 for b in bets if b.result < 0)
                ci = wilson(w, w + lo)
                s = {"hit_rate": w / (w + lo) if w + lo else None, "ci_lo": ci[0],
                     "ci_hi": ci[1], "final": final}  # fmt: skip
                out.append({"timing": timing, "market": market, "threshold": t, "games": label,
                            "summary": s, "n": len(bets),
                            "unit_roi": u / len(bets) if bets else None})  # fmt: skip
    return out


def write_csvs(results: list[dict[str, Any]], out_dir: Path, start: float) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for r in results:
        p = out_dir / f"{r['slug']}.csv"
        with p.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "bankroll"])
            w.writerow(["start", f"{start:.2f}"])
            for d in r["daily"]:
                w.writerow([d["date"].isoformat(), f"{d['bankroll']:.2f}"])
        paths.append(p)
    return paths


# ---------- report ----------


def _money(x: float | None) -> str:
    return "-" if x is None else f"${math.floor(max(0.0, x) * 100 + 1e-6) / 100:,.2f}"


def _pct(x: float | None, nd: int = 1) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.{nd}f}%"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
        *("| " + " | ".join(r) + " |" for r in rows),
    ]


def _rule_label(r: dict[str, Any]) -> str:
    if r["rule"] == "model":
        t = r["threshold"]
        return f"model, edge >= {t:.0%}" if r["market"] == "moneyline" else f"model, t >= {t:g}"
    return {
        "home": "always home",
        "over": "always over",
        "favorite": "always favorite",
    }[r["rule"]]


def _row_cells(r: dict[str, Any], seasons: list[int]) -> list[str]:
    s = r["summary"]
    placed = str(s["bets"])
    if s["bets"] < r.get("n_candidates", s["bets"]):
        placed += f" of {r['n_candidates']}"
    return [
        placed,
        f"{s['wins']}-{s['losses']}-{s['pushes']}",
        _pct(s["hit_rate"]),
        f"{_pct(s['ci_lo'])}-{_pct(s['ci_hi'])}" if s["ci_lo"] is not None else "-",
        _money(s["staked"]),
        _money(s["final"]) + (" (bust)" if s["busted"] else ""),
        _pct(s["roi"]),
        _pct(s["max_dd"], 0),
        str(s["longest_losing"]),
        *(_money(s["by_season"].get(y)) for y in seasons),
    ]


def render_report(
    results: list[dict[str, Any]],
    games: list[dict[str, Any]],
    meta: dict[str, Any],
    start: float,
    robust: list[dict[str, Any]] | None = None,
) -> str:
    seasons = sorted({g["season"] for g in games})
    v = meta["version"]
    get = {(r["timing"], r["market"], r["rule"], r["threshold"], r["sizing"]): r for r in results}
    flat_name, pct_name = flat_dollars(meta["flat"]).name, flat_pct(meta["pct"]).name

    def head(timing, market, sizing):
        return get.get((timing, market, "model", HEADLINE[market], sizing))

    sp_c = head("closing", "spread", flat_name)
    sp_o = head("opening", "spread", flat_name)
    n_open = sum(1 for g in games if "opening" in g["lines"])
    n_close = sum(1 for g in games if "closing" in g["lines"])
    out = [f"# What would $100 have done? Betting simulation of model {v}"]
    out.append(
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. {len(games)} out-of-sample NBA games "
        f"from {games[0]['start']:%Y-%m-%d} to {games[-1]['start']:%Y-%m-%d} "
        f"(seasons {seasons[0] - 1}-{str(seasons[0])[2:]} to {seasons[-1] - 1}-"
        f"{str(seasons[-1])[2:]}; ESPN season {seasons[0]} = "
        f"{seasons[0] - 1}-{str(seasons[0])[2:]})"
        f", {meta['folds']} walk-forward folds (monthly refit). Fold check: {meta['fold_check']}."
    )
    out.append("")
    out.append("**Not financial advice.** DeepSports is for following games and measuring a "
               "model honestly; placing bets is an explicit non-goal (docs/PRODUCT.md). This "
               "replays history on paper.")  # fmt: skip
    out.append("## Summary in plain language")

    def line(r):
        s = r["summary"]
        return (
            f"${start:,.0f} -> {_money(s['final'])} ({s['bets']} bets, hit {_pct(s['hit_rate'])})"
        )

    model_flat = [r for r in results if r["rule"] == "model" and r["sizing"] == flat_name]
    up = [r for r in model_flat if r["summary"]["final"] > start]
    sig = [
        r
        for r in model_flat
        if r["market"] != "moneyline"
        and r["summary"]["ci_lo"] is not None
        and r["summary"]["ci_lo"] > ((r.get("prices") or {}).get("break_even") or BREAK_EVEN_110)
    ]
    ml_c = head("closing", "moneyline", flat_name)
    clvs = [(m, (head("opening", m, flat_name) or {}).get("clv")) for m in ("spread", "total")]
    if all(c and c["toward"] > c["against"] for _, c in clvs):
        clv_note = (
            "Between the opening and the close, the line moved toward the model's side more "
            "often than away ("
            + ", ".join(f"{m} {_pct(c['toward'], 0)} vs {_pct(c['against'], 0)}" for m, c in clvs)
            + "), so the model may hold a little "
            "real information against early lines. That edge is gone by the closing line, and "
            "opening lines are rarely available for meaningful stakes."
        )
    else:
        clv_note = (
            "The line did not consistently move toward the model's side after the opening, so "
            "there is no sign of real information against early lines."
        )
    out += [
        f"- **Spreads at the closing line, flat ${meta['flat']:g} per bet** (bet when the model "
        f"and the line differ by {HEADLINE['spread']:g}+ points): {line(sp_c)}.",
        f"- The same at the **opening line**: {line(sp_o)}.",
        f"- Moneyline at the closing line, edge {HEADLINE['moneyline']:.0%}+, flat "
        f"${meta['flat']:g}: {line(ml_c)}.",
        f"- Totals at the **opening line**, {HEADLINE['total']:g}+ points, flat "
        f"${meta['flat']:g}: {line(head('opening', 'total', flat_name))}. " + clv_note,
        f"- Of {len(model_flat)} model strategies (flat ${meta['flat']:g}, every market, "
        f"threshold and line timing), {len(up)} ended above ${start:g}; {len(sig)} of the "
        "spread/total ones have a hit rate whose whole 95% range is above its break-even "
        "(52.4% at -110; with real prices, each strategy's average 1/price). "
        "Every one is in the tables below.",
        "",
        "How to read this, if you are new to betting:",
        "- **-110** is the usual price of a spread or over/under bet: you risk $110 to win $100 "
        "(or $2 to win about $1.82). If you win you get your stake back plus the win.",
        f"- So you must win **{BREAK_EVEN_110:.1%}** of those bets just to break even "
        '(110 / 210), not 50%. The gap is the bookmaker\'s cut (the "vig").',
        "- **Spread**: a handicap. Home -6.5 means the home team must win by 7+ for a home bet "
        "to win. **Total**: bet whether both teams together score over or under a number. "
        "**Moneyline**: bet a team just to win; favorites pay less than they risk (e.g. -200: "
        "risk $200 to win $100), underdogs more (+170: risk $100 to win $170).",
        "- **Push**: the result lands exactly on the line; the stake is refunded.",
        "- **Drawdown**: the biggest fall from a high point to a later low, as a share of the "
        "high point. A 40% drawdown means at some point you had lost 40% of your best balance.",
        "- **ROI**: profit divided by the total amount staked. -4.5% is what a coin flip loses "
        "at -110 on average.",
        *(
            [
                "- **Real prices**: books often charge a bit more or less than -110 (e.g. -115 "
                "to win $100 on one side, -105 on the other). Here each spread/total bet is paid "
                "at the price actually listed for its side; see the price table below."
            ]
            if meta.get("pricing") == "real"
            else []
        ),
        "- **Hit rate 95% range**: with a few hundred bets, luck alone moves the hit rate by "
        "several points; only a range entirely above 52.4% suggests real skill.",
        "- **Closing line** = the price right before tip-off, after all the news and the "
        "professionals' money: the hardest test. **Opening line** = the first price posted; "
        "easier to beat in principle, but see the caveats.",
    ]

    # ---- main table ----
    out.append("## Main strategies vs baselines (headline thresholds fixed in advance)")
    out.append(
        f"Headline thresholds were set before running: spread {HEADLINE['spread']:g} pts, total "
        f"{HEADLINE['total']:g} pts, moneyline edge {HEADLINE['moneyline']:.0%}. Coin flip = same "
        f"games, random side, mean of {meta['coin_runs']} seeded runs (5th-95th pct)."
    )
    hdr = ["strategy", "sizing", "bets", "W-L-P", "hit", "95% CI", "staked", "final", "ROI",
           "max DD", "worst streak"] + [f"end {y}" for y in seasons]  # fmt: skip
    for timing in TIMINGS:
        out.append(f"### {timing.capitalize()} line")
        rows = []
        for market in MARKETS:
            keys = [("model", HEADLINE[market])]
            keys.append((BASELINES[market], None))
            if market == "moneyline":
                keys.append(("home", None))
            for rule, t in keys:
                for sz in sizings(market, meta["flat"], meta["pct"]):
                    r = get.get((timing, market, rule, t, sz.name))
                    if r is None:
                        continue
                    label = f"{market}: {_rule_label(r)}"
                    rows.append([label, sz.name, *_row_cells(r, seasons)])
                    c = r.get("coin")
                    if c and rule == "model":
                        rows.append(
                            [f"{market}: coin flip, same games", sz.name, str(r["n_candidates"]),
                             "-", "-", "-", "-",
                             f"{_money(c['mean_final'])} ({_money(c['p5'])}-{_money(c['p95'])})",
                             _pct(c["mean_roi"]), "-", "-"] + ["-"] * len(seasons)
                        )  # fmt: skip
        out += _table(hdr, rows)

    # ---- prices ----
    out.append(f"## Prices of spread/total bets ({meta.get('pricing', '-110')} pricing)")
    out.append(
        f"Per strategy, all candidate bets (before any bankroll limit). 'fallback' = bets with no "
        f"stored price for their side, paid at -110. 'If win' = extra payout of a winning "
        f"${meta['flat']:g} bet vs -110; 'realized' = extra profit actually collected per "
        f"${meta['flat']:g} bet vs -110 (negative = the real prices cost money)."
    )
    rows = []
    for timing in TIMINGS:
        for market in ("spread", "total"):
            for rule, t in [("model", x) for x in MARKETS[market]] + [(BASELINES[market], None)]:
                r = get.get((timing, market, rule, t, flat_name))
                p = (r or {}).get("prices")
                if not p:
                    continue
                rows.append(
                    [timing, f"{market}: {_rule_label(r)}", str(p["n"]), str(p["fallback"]),
                     f"{p['mean_decimal']:.4f}", _pct(p["break_even"]),
                     f"{p['win_diff']:+.4f}", f"{p['realized']:+.4f}"]
                )  # fmt: skip
    out += _table(
        ["line", "strategy", "bets", "fallback", "avg decimal", "break-even", "if win $",
         "realized $ per bet"],
        rows,
    )  # fmt: skip

    # ---- bootstrap ----
    out.append("## Bootstrap: how much of the result is luck? (flat sizing)")
    out.append(
        f"Each strategy's bets resampled with replacement {meta['n_boot']} times and replayed. "
        "The range shows how differently the same hit rate could have played out; it is centered "
        "on what happened, so it does not prove or disprove skill."
    )
    rows = []
    for r in results:
        b = r.get("boot")
        if not b or r["sizing"] not in (flat_name, pct_name):
            continue
        rows.append(
            [r["timing"], r["market"], _rule_label(r), r["sizing"], str(r["summary"]["bets"]),
             _money(r["summary"]["final"]), _money(b["median"]),
             f"{_money(b['p5'])} - {_money(b['p95'])}", _pct(b["p_above_start"], 0),
             _pct(b["p_bust"], 0)]
        )  # fmt: skip
    out += _table(
        ["line", "market", "strategy", "sizing", "bets", "actual final", "boot median",
         "5th-95th pct", f"P(> ${start:g})", "P(bust)"],
        rows,
    )  # fmt: skip

    # ---- calibration ----
    out.append(f"## Is Kelly justified? Calibration of {v} win probabilities")
    out.append(
        "Kelly sizing bets more when the model is more confident, so it only helps if the "
        "model's probabilities are right. Bins of the model's home-win probability vs how often "
        "the home team actually won (all out-of-sample games):"
    )
    rows = []
    for c in calibration(games):
        rows.append(
            [f"{c['lo']:.1f}-{c['hi']:.1f}", str(c["n"]), _pct(c["pred"]), _pct(c["actual"]),
             f"{_pct(c['ci_lo'])}-{_pct(c['ci_hi'])}", _pct(c["market"])]
        )  # fmt: skip
    out += _table(["model p bin", "games", "model avg", "home won", "95% CI", "market avg"], rows)
    out.append(
        "The test that matters for Kelly: on the moneyline bets, the model's probability for "
        "the side it bet vs the market's vig-free probability vs what happened. If 'actual' "
        "tracks the market rather than the model, the model's edge is mostly imaginary and "
        "Kelly over-bets."
    )
    rows = []
    for r in results:
        e = r.get("edge_cal")
        if not e or r["sizing"] != flat_name:
            continue
        rows.append(
            [r["timing"], _rule_label(r), str(e["n"]), _pct(e["model"]), _pct(e["market"]),
             _pct(e["actual"]), f"{_pct(e['ci'][0])}-{_pct(e['ci'][1])}"]
        )  # fmt: skip
    out += _table(["line", "strategy", "bets", "model p", "market p", "actual", "95% CI"], rows)

    # ---- opening line: real information or stale lines? ----
    out.append("## Opening line: did the market later agree with the model?")
    out.append(
        "If the model really knows something at the opening line, the line should tend to move "
        "toward the model's side by tip-off (\"closing-line value\"). Mean move in the bet's "
        "favor: points for spread/total, vig-free win probability for the moneyline."
    )
    rows = []
    for r in results:
        c = r.get("clv")
        if not c or r["sizing"] != flat_name:
            continue
        unit = "pp" if r["market"] == "moneyline" else "pts"
        mean = c["mean"] * 100 if r["market"] == "moneyline" else c["mean"]
        rows.append(
            [r["market"], _rule_label(r), str(c["n"]), f"{mean:+.2f} {unit}",
             _pct(c["toward"], 0), _pct(c["against"], 0), _pct(r["summary"]["hit_rate"])]
        )  # fmt: skip
    out += _table(
        ["market", "strategy", "bets", "mean move our way", "moved toward us", "moved against",
         "hit"],
        rows,
    )  # fmt: skip
    if robust:
        out.append("### Leak check: drop games after a back-to-back")
        out.append(
            "The model knows last night's results; an opening line posted before last night's "
            "games did not. Dropping every game where either team played the day before removes "
            "that path. If the opening-line edge were only this leak, it would vanish here. "
            f"Headline thresholds, flat ${meta['flat']:g}; 'ROI per unit' = profit per 1 staked "
            "on every bet, ignoring bankroll limits; hit rate is over every bet the rule picks "
            "(the bankroll run may have gone bust earlier)."
        )
        rows = [
            [x["timing"], x["market"], x["games"], str(x["n"]),
             _pct(x["summary"]["hit_rate"]),
             f"{_pct(x['summary']['ci_lo'])}-{_pct(x['summary']['ci_hi'])}",
             _pct(x["unit_roi"]), _money(x["summary"]["final"])]
            for x in robust
        ]  # fmt: skip
        out += _table(
            ["line", "market", "games", "bets", "hit", "95% CI", "ROI per unit", "final"], rows
        )

    # ---- every threshold ----
    out.append("## Every threshold (no cherry-picking)")
    out.append(
        "All thresholds and sizings. The row marked **best (in-sample)** is the highest final "
        "bankroll in each block: picking it after seeing these results is cherry-picking (it is "
        "the luckiest of several tries), so it is not an estimate of future results."
    )
    for timing in TIMINGS:
        for market in MARKETS:
            rs = [r for r in results if r["timing"] == timing and r["market"] == market]
            if not rs:
                continue
            model_rs = [r for r in rs if r["rule"] == "model"]
            best = max(model_rs, key=lambda r: r["summary"]["final"]) if model_rs else None
            out.append(f"### {timing.capitalize()} line: {market}")
            rows = []
            for r in rs:
                tag = " **best (in-sample)**" if r is best else ""
                rows.append([_rule_label(r) + tag, r["sizing"], *_row_cells(r, seasons)])
            out += _table(hdr, rows)

    # ---- method ----
    out.append("## Method and assumptions")
    out += [
        f"- Predictions: `backtest.walk_forward` with model {v}, monthly refit, the same folds as "
        "the backtest report. Each month is predicted by a model trained only on games that "
        "tipped off before that month started. Features use only games finished 4+ hours "
        "before tip-off.",
        f"- Lines: latest `closing` row per game ({n_close} of {len(games)} games have one), "
        f"earliest `opening` row ({n_open} games). Spreads with |x| > {SANE_SPREAD:g} and totals "
        f"outside {SANE_TOTAL[0]:g}-{SANE_TOTAL[1]:g} are dropped. Providers: ESPN BET / "
        "DraftKings (as stored).",
        (
            "- Prices: each spread/total bet is paid at the stored American price of its side on "
            "the same odds row (`spread_home_price`/`spread_away_price`, `over_price`/"
            "`under_price`, filled offline by `deepsports prices-backfill`); -110 only where that "
            "price is NULL (counted in the price table). Moneylines use the stored American odds."
            if meta.get("pricing") == "real"
            else "- Prices: every spread/total bet is at -110 (decimal 1.909). Moneylines use the "
            "stored American odds of the same row."
        ),
        "- Edges: spread edge = model home margin - (-spread_home); total edge = model total - "
        "line; moneyline edge = model home-win probability - `metrics.devig_probability`. An "
        "exact zero edge is no bet.",
        "- Bankroll: game days are US Eastern dates. Every stake on a day comes from the "
        "start-of-day bankroll; a day's stakes never exceed it; results are applied when the "
        "day ends. Stakes are rounded down to cents; below $0.01 the run is over (bust).",
        f"- Sizing: flat ${meta['flat']:g} (2% of the start); {pct_name} at the start of the day; "
        "1/4 Kelly on the model's moneyline probability, capped at 5% of the bankroll, no bet if "
        "Kelly is <= 0.",
        "- Baselines use the same sizing: always the home team (spread, moneyline), always the "
        "favorite (moneyline), always the over (total), and a coin flip on the same games as "
        "each strategy.",
        "- Losing streak: consecutive losses; pushes neither break nor extend it. Max drawdown "
        "uses end-of-day balances.",
        f"- Bootstrap: {meta['n_boot']} resamples of the strategy's bets (with replacement), "
        "played one at a time. Seeded, reproducible.",
    ]
    out.append("## Caveats (read before believing any number)")
    out += [
        "- **Selection bias.** Many strategies were tried (3 markets x 5 thresholds x 2-3 "
        "sizings x 2 line timings). Even with zero skill, some will look good. Only the "
        "pre-set headline thresholds are honest single estimates.",
        "- **Real books limit stakes and move lines.** Winners get their limits cut; a line we "
        "'bet' may not have been available in size"
        + (
            ", and the stored price is one book's quote at that moment. "
            if meta.get("pricing") == "real"
            else ", and prices other than -110 (e.g. -115) are common. "
        )
        + "Results here are an upper bound on what was achievable.",
        "- **Opening lines are optimistic for the model.** The stored opening rows carry the "
        "tip-off time as their timestamp, not when they were posted. An opening line is "
        "usually posted the day before or the morning of the game, while the model's features "
        "include games that finished up to 4 hours before tip-off (e.g. the previous night's "
        "game of a team on a back-to-back). Some opening-line bets therefore used information "
        "the line did not yet have. Treat opening-line results as a best case.",
        "- **Closing moneylines and providers.** Closing rows come from ESPN's game summary "
        "after the game; they are the book's last pre-game price, not a price we could always "
        "get. Opening and closing usually come from the same provider (a few dozen games differ).",
        "- **Correlated bets.** Same-day bets are sized together; streaks matter, and the "
        "bootstrap's independence assumption understates bad-luck runs a little.",
        "- **Past results do not predict future ones.** The market adapts; this model uses only "
        "public box-score data the market already prices in.",
    ]
    out.append("## Reproduce")
    out.append(
        "```\nuv run python -m deepsports.analysis.simulate --model-version "
        f"{meta['model_version']} --pricing={meta.get('pricing', '-110')} --bankroll {start:g} "
        "--out <report.md>\n```\n"
        "Bankroll-over-time CSVs (date, end-of-day bankroll), one per strategy: "
        f"`{meta['csv_dir']}`"
    )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-version", default="v1.0")
    ap.add_argument("--bankroll", type=float, default=100.0)
    ap.add_argument("--out", type=Path, help="write the Markdown report here")
    ap.add_argument("--copy", type=Path, action="append", default=[], help="extra report copy")
    ap.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--refit", choices=["monthly", "season"], default="monthly")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--coin-runs", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument(
        "--pricing",
        choices=PRICINGS,
        default="real",
        help="spread/total prices: stored per-side prices (-110 where NULL) or flat -110",
    )
    ap.add_argument(
        "--until",
        type=date.fromisoformat,
        help="only games tipping off before this UTC date (e.g. reproduce an older report)",
    )
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"warehouse not found: {args.db}", file=sys.stderr)
        return 1
    con = connect_read_only(args.db)
    try:
        wf = out_of_sample_predictions(con, args.model_version, args.refit)
        lines = load_lines(con)
    finally:
        con.close()
    if not wf["predictions"]:
        print("no out-of-sample predictions (not enough seasons)", file=sys.stderr)
        return 1
    preds = wf["predictions"]
    if args.until:
        cut = datetime(args.until.year, args.until.month, args.until.day, tzinfo=UTC)
        preds = [p for p in preds if p["start_time_utc"] < cut]
    games = prepare_games(preds, lines, wf.get("b2b"))
    leak = [f for f in wf["folds"] if f["train_max_start"] >= f["test_min_start"]]
    flat = args.bankroll * 0.02
    results = run_all(
        games, args.bankroll, flat, 0.02, args.boot, args.coin_runs, args.seed, args.pricing
    )
    # -110 keeps the 2026-11-04 directory names; real prices get their own
    suffix = "" if args.pricing == "-110" else "-real"
    csv_dir = args.csv_dir / (_slug(args.model_version) + suffix)
    write_csvs(results, csv_dir, args.bankroll)
    meta = {
        "version": "v1" if wf["version"] == "v1.0" else wf["version"],
        "model_version": args.model_version,
        "folds": len(wf["folds"]),
        "fold_check": "OK" if not leak else f"FAILED in {len(leak)} folds",
        "flat": flat,
        "pct": 0.02,
        "n_boot": args.boot,
        "coin_runs": args.coin_runs,
        "csv_dir": str(csv_dir),
        "pricing": args.pricing,
    }
    robust = robustness(games, args.bankroll, flat, args.pricing)
    text = render_report(results, games, meta, args.bankroll, robust)
    print(text)
    for p in [args.out, *args.copy]:
        if p is None:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if p == args.out:
            p.write_text(text)
        else:
            shutil.copyfile(args.out, p) if args.out else p.write_text(text)
        print(f"wrote {p}", file=sys.stderr)
    print(f"wrote {len(results)} CSVs to {csv_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
