"""Bet grading: spread / total / moneyline results, ROI, a day-clustered bootstrap CI, CLV,
price sensitivity and drawdown. Pure: no DB, no network; numpy + stdlib only.

Ported from the DeepSeek edge study's shared harness (collab/deepseek/lab/harness.py), which
graded every bet of that study. Bets and games are plain data: a list of dicts, a dict of
columns, or anything with a pandas-style `.to_dict("records")` (pandas is never imported).
Inputs are never mutated.

Bet rows::

    {"game_id": "401591869", "market": "spread" | "total" | "moneyline",
     "side": "home" | "away" (spread, moneyline) or "over" | "under" (total),
     "line": -4.5,      # spread/total; spread_home convention (negative = home favored)
     "price": -110,     # American odds; spread/total default -110, required for moneyline
     "stake": 1.0,      # default 1 unit
     "timing": "close", # "open" bets (taken before the close) also get closing-line value
     "variant": ..., "notes": ..., "league": ...}   # optional pass-through

Semantics (exact):
  - margin = home - away, total = home + away.
  - spread: home at line L wins iff margin + L > 0, pushes iff == 0; away wins iff < 0.
  - total: over wins iff total > L, under iff total < L, push iff equal.
  - moneyline: the winner wins; no push.
  - profit on a win = stake * (decimal - 1) (price 0 = even money); push 0; loss -stake.
  - win% = wins / (wins + losses); pushes stay in the ROI denominator (committed capital).
  - ROI = profit / staked; drawdown on the daily US/Eastern P&L from a bankroll = total staked.
  - bootstrap CI on ROI: resample whole tip dates with replacement (2,000 resamples, seed 42,
    2.5-97.5 percentile). Needs `tip_date` on the game rows.
  - CLV (timing "open" only, positive = beat the close): spread home open - close, away
    close - open; over close - open, under open - close; moneyline the change in the
    de-vigged probability of the bet side, in percentage points.
  - price sensitivity (spread/total): ROI at -105/-110/-115, and at -110 with the line moved
    0.5 point against the bettor.
"""

from __future__ import annotations

import csv
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from deepsports.analysis.metrics import american_to_decimal, devig_probability

MARKETS = ("spread", "total", "moneyline")
SIDES_BY_MARKET = {
    "spread": ("home", "away"),
    "total": ("over", "under"),
    "moneyline": ("home", "away"),
}
TIMINGS = ("open", "close")
DEFAULT_PRICE = -110  # spread/total: the warehouse stores no prices for these
DEFAULT_STAKE = 1.0
DEFAULT_SEED = 42
DEFAULT_N_BOOTSTRAP = 2000
SENSITIVITY_PRICES = (-105, -110, -115)
SLIPPAGE = 0.5  # points against the bettor


# ---------- input normalization ----------


def _records(obj: Any, what: str) -> list[dict[str, Any]]:
    """A list of dicts, a dict of columns, or a DataFrame-like -> list of row dicts."""
    if isinstance(obj, Mapping):
        cols = {k: list(v) for k, v in obj.items()}
        if not cols:
            return []
        n = len(next(iter(cols.values())))
        if any(len(v) != n for v in cols.values()):
            raise ValueError(f"{what}: ragged column lengths")
        return [dict(zip(cols, vals, strict=True)) for vals in zip(*cols.values(), strict=True)]
    if isinstance(obj, list | tuple):
        out = []
        for row in obj:
            if not isinstance(row, Mapping):
                raise TypeError(f"{what}: rows must be dicts, got {type(row).__name__}")
            out.append(dict(row))
        return out
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return [dict(r) for r in to_dict("records")]
    raise TypeError(
        f"{what}: expected list of dicts, dict of columns, or DataFrame; got {type(obj).__name__}"
    )


def _finite(value: Any, what: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what}: expected a number, got {value!r}") from exc
    if not math.isfinite(f):
        raise ValueError(f"{what}: expected a finite number, got {value!r}")
    return f


def normalize_bet(bet: Mapping[str, Any], where: str = "bet") -> dict[str, Any]:
    """Validate one bet row and fill the defaults (price -110 for spread/total, stake 1,
    timing close). Raises ValueError on a bad row."""
    row = dict(bet)
    if row.get("game_id") is None or str(row["game_id"]) == "":
        raise ValueError(f"{where}: missing game_id")
    row["game_id"] = str(row["game_id"])
    market = row.get("market")
    if market not in MARKETS:
        raise ValueError(f"{where}: market must be one of {MARKETS}, got {market!r}")
    side = row.get("side")
    if side not in SIDES_BY_MARKET[market]:
        valid = SIDES_BY_MARKET[market]
        raise ValueError(f"{where}: side for market={market} must be one of {valid}, got {side!r}")
    row["timing"] = row.get("timing") or "close"
    if row["timing"] not in TIMINGS:
        raise ValueError(f"{where}: timing must be one of {TIMINGS}, got {row['timing']!r}")
    row["variant"] = str(row.get("variant") or "")
    row["notes"] = str(row.get("notes") or "")
    row["league"] = row.get("league")
    if market == "moneyline":
        row["line"] = None
        if row.get("price") is None:
            raise ValueError(f"{where}: moneyline bets require a price (American odds)")
    else:
        if row.get("line") is None:
            raise ValueError(f"{where}: {market} bets require a line")
        row["line"] = _finite(row["line"], f"{where} line")
        if row.get("price") is None:
            row["price"] = DEFAULT_PRICE
    price = float(row["price"])
    if price != int(price):
        raise ValueError(f"{where}: price must be an integer, got {row['price']!r}")
    if price != 0 and american_to_decimal(price) is None:
        raise ValueError(f"{where}: invalid American price {price!r} (<= -100, 0, or >= +100)")
    row["price"] = price
    row["stake"] = _finite(row.get("stake", DEFAULT_STAKE), f"{where} stake")
    if row["stake"] < 0:
        raise ValueError(f"{where}: stake must be >= 0, got {row['stake']!r}")
    return row


def _normalize_games(games: Any) -> dict[str, dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for i, game in enumerate(_records(games, "games")):
        where = f"games[{i}]"
        row = dict(game)
        if row.get("game_id") is None:
            raise ValueError(f"{where}: missing game_id")
        gid = str(row["game_id"])
        if gid in seen:
            raise ValueError(f"{where}: duplicate game_id {gid!r} in games")
        for key in ("home_score", "away_score"):
            if row.get(key) is None:
                raise ValueError(f"{where}: missing {key} for game {gid!r}")
            row[key] = _finite(row[key], f"{where} {key}")
        row["game_id"] = gid
        row["margin"] = row["home_score"] - row["away_score"]
        row["total"] = row["home_score"] + row["away_score"]
        seen[gid] = row
    return seen


def _normalize_lines(lines: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if lines is None:
        return out
    for i, row in enumerate(_records(lines, "lines")):
        if row.get("game_id") is None:
            raise ValueError(f"lines[{i}]: missing game_id")
        gid = str(row["game_id"])
        if gid in out:
            raise ValueError(f"lines[{i}]: duplicate game_id {gid!r} in lines")
        out[gid] = dict(row)
    return out


# ---------- per-bet grading ----------


def profit_on_win(price: float, stake: float) -> float:
    """Profit (stake excluded) of a winning bet at American `price`; 0 = even money."""
    if price == 0:
        return stake
    dec = american_to_decimal(price)
    if dec is None:
        raise ValueError(f"invalid American price {price!r} (<= -100, 0, or >= +100)")
    return stake * (dec - 1)


def outcome(market: str, side: str, line: float | None, margin: float, total: float) -> str:
    """'win', 'push' or 'loss' for one bet given the final margin and total."""
    if market == "spread":
        v = margin + line  # > 0 home covers, < 0 away covers
        if v == 0:
            return "push"
        return "win" if (v > 0) == (side == "home") else "loss"
    if market == "total":
        if total == line:
            return "push"
        return "win" if (total > line) == (side == "over") else "loss"
    if market == "moneyline":
        return "win" if (margin > 0) == (side == "home") else "loss"
    raise ValueError(f"unknown market {market!r}")


def clv(bet: Mapping[str, Any], lines_row: Mapping[str, Any] | None) -> float | None:
    """Closing-line value of an opening bet (positive = beat the close); None when not
    applicable or a line is missing. `lines_row` carries open_/close_ columns."""
    if bet.get("timing") != "open" or lines_row is None:
        return None
    market, side = bet["market"], bet["side"]
    if market == "spread":
        o, c = lines_row.get("open_spread_home"), lines_row.get("close_spread_home")
        if o is None or c is None:
            return None
        return float(o - c) if side == "home" else float(c - o)
    if market == "total":
        o, c = lines_row.get("open_total"), lines_row.get("close_total")
        if o is None or c is None:
            return None
        return float(c - o) if side == "over" else float(o - c)
    if market == "moneyline":
        p_open = devig_probability(lines_row.get("open_home_ml"), lines_row.get("open_away_ml"))
        p_close = devig_probability(lines_row.get("close_home_ml"), lines_row.get("close_away_ml"))
        if p_open is None or p_close is None:
            return None
        delta = (p_close - p_open) * 100.0
        return delta if side == "home" else -delta
    raise ValueError(f"unknown market {market!r}")


def grade_bet(
    bet: dict[str, Any], game: Mapping[str, Any], lines_row: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Grade one normalized bet against a normalized game (with margin/total). Returns the
    bet row plus scores, tip_date, grade, profit and clv. Use `grade()` for batches."""
    result = outcome(bet["market"], bet["side"], bet["line"], game["margin"], game["total"])
    stake = bet["stake"]
    if result == "win":
        profit = profit_on_win(bet["price"], stake)
    else:
        profit = 0.0 if result == "push" else -stake
    return {
        **bet,
        "home_score": game["home_score"],
        "away_score": game["away_score"],
        "margin": game["margin"],
        "total": game["total"],
        "tip_date": game.get("tip_date"),
        "grade": result,
        "profit": profit,
        "clv": clv(bet, lines_row),
    }


# ---------- aggregate statistics ----------


def drawdown(daily_profits: Sequence[float], bankroll: float) -> tuple[float | None, float | None]:
    """Max drawdown (units, fraction of the running peak) on end-of-day balances."""
    if not daily_profits or bankroll <= 0:
        return (None, None)
    peak = balance = bankroll
    max_units = max_pct = 0.0
    for p in daily_profits:
        balance += p
        peak = max(peak, balance)
        dd = peak - balance
        max_units = max(max_units, dd)
        max_pct = max(max_pct, dd / peak)
    return max_units, max_pct


def bootstrap_rois(
    day_profits: Sequence[float],
    day_stakes: Sequence[float],
    *,
    seed: int = DEFAULT_SEED,
    n: int = DEFAULT_N_BOOTSTRAP,
) -> np.ndarray:
    """Day-clustered bootstrap: resample whole days with replacement; ROI of each resample."""
    if len(day_profits) == 0:
        return np.array([], dtype=float)
    profits = np.asarray(day_profits, dtype=float)
    stakes = np.asarray(day_stakes, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(profits), size=(n, len(profits)))
    with np.errstate(divide="ignore", invalid="ignore"):
        rois = profits[idx].sum(axis=1) / stakes[idx].sum(axis=1)
    return rois[np.isfinite(rois)]


def bootstrap_ci(
    day_profits: Sequence[float],
    day_stakes: Sequence[float],
    *,
    seed: int = DEFAULT_SEED,
    n: int = DEFAULT_N_BOOTSTRAP,
) -> tuple[float | None, float | None]:
    """2.5-97.5 percentile CI on ROI from the day-clustered bootstrap."""
    rois = bootstrap_rois(day_profits, day_stakes, seed=seed, n=n)
    if len(rois) == 0:
        return (None, None)
    lo, hi = np.percentile(rois, [2.5, 97.5])
    return (float(lo), float(hi))


def price_sensitivity(graded: list[dict[str, Any]]) -> dict[str, float | None]:
    """ROI of the graded spread/total bets at -105/-110/-115 and at -110 with 0.5-point
    slippage against the bettor (re-graded from the final scores)."""
    rows = [b for b in graded if b["market"] in ("spread", "total")]
    keys = [f"roi_neg{abs(p)}" for p in SENSITIVITY_PRICES] + ["roi_neg110_slip05"]
    stakes = sum(r["stake"] for r in rows)
    if not rows or stakes <= 0:
        return dict.fromkeys(keys)

    def roi_at(price: float, slip: float = 0.0) -> float:
        profit = 0.0
        for r in rows:
            line = r["line"]
            if r["market"] == "spread":
                line = line - slip if r["side"] == "home" else line + slip
            else:
                line = line + slip if r["side"] == "over" else line - slip
            res = outcome(r["market"], r["side"], line, r["margin"], r["total"])
            if res == "win":
                profit += profit_on_win(price, r["stake"])
            elif res == "loss":
                profit -= r["stake"]
        return profit / stakes

    out = {f"roi_neg{abs(p)}": roi_at(p) for p in SENSITIVITY_PRICES}
    out["roi_neg110_slip05"] = roi_at(-110, SLIPPAGE)
    return out


@dataclass
class GradeResult:
    """Output of `grade()`: per-bet rows, aggregate summary, per-tip-date rows."""

    bets: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    daily: list[dict[str, Any]] = field(default_factory=list)

    def to_csv(self, out_dir: str | os.PathLike, prefix: str) -> list[str]:
        """Write {prefix}_bets.csv, {prefix}_daily.csv and {prefix}_summary.json. Large
        exports belong on the external drive (/Volumes/ExFATStorag/DeepSports/...)."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for name, rows in ((f"{prefix}_bets.csv", self.bets), (f"{prefix}_daily.csv", self.daily)):
            path = out / name
            cols = list(dict.fromkeys(k for row in rows for k in row))
            with path.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            written.append(str(path))
        path = out / f"{prefix}_summary.json"
        path.write_text(json.dumps(self.summary, indent=2, default=_json_default))
        written.append(str(path))
        return written


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.floating | np.integer):
        return obj.item()
    return str(obj)


def summarize(
    graded: list[dict[str, Any]],
    *,
    seed: int = DEFAULT_SEED,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(summary, daily rows) for already-graded bet rows (with grade, profit, stake, clv,
    timing, tip_date)."""
    by_day: dict[str, list[dict[str, Any]]] = {}
    no_date = 0
    for row in graded:
        d = row.get("tip_date")
        if d is None or str(d) == "":
            no_date += 1
            continue
        by_day.setdefault(str(d), []).append(row)
    daily, cum = [], 0.0
    for d in sorted(by_day):
        rows = by_day[d]
        profit = sum(r["profit"] for r in rows)
        cum += profit
        daily.append(
            {
                "date": d,
                "n": len(rows),
                "stake": sum(r["stake"] for r in rows),
                "profit": profit,
                "cum_profit": cum,
            }
        )

    wins = sum(r["grade"] == "win" for r in graded)
    losses = sum(r["grade"] == "loss" for r in graded)
    pushes = sum(r["grade"] == "push" for r in graded)
    total_profit = sum(r["profit"] for r in graded)
    total_staked = sum(r["stake"] for r in graded)
    bankroll = sum(d["stake"] for d in daily)
    dd_units, dd_pct = drawdown([d["profit"] for d in daily], bankroll)
    ci_low, ci_high = bootstrap_ci(
        [d["profit"] for d in daily], [d["stake"] for d in daily], seed=seed, n=n_bootstrap
    )
    clvs = [r["clv"] for r in graded if r.get("timing") == "open" and r.get("clv") is not None]
    summary: dict[str, Any] = {
        "n": len(graded),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "record": f"{wins}-{losses}-{pushes}",
        "win_pct": wins / (wins + losses) if wins + losses else None,
        "roi": total_profit / total_staked if total_staked > 0 else None,
        "units": sum(r["profit"] / r["stake"] for r in graded if r["stake"] > 0),
        "total_staked": total_staked,
        "max_drawdown_units": dd_units,
        "max_drawdown_pct": dd_pct,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "n_days": len(daily),
        "n_bets_no_tip_date": no_date,
        "clv_n": len(clvs),
        "clv_mean": float(np.mean(clvs)) if clvs else None,
        "clv_median": float(np.median(clvs)) if clvs else None,
        "clv_pct_positive": float(np.mean([c > 0 for c in clvs]) * 100.0) if clvs else None,
        "price_sensitivity": price_sensitivity(graded),
    }
    return summary, daily


def grade(
    bets: Any,
    games: Any,
    lines: Any = None,
    *,
    seed: int = DEFAULT_SEED,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
) -> GradeResult:
    """Grade bets against final scores (see the module docstring for the exact rules).

    bets: rows with game_id, market, side[, line, price, stake, timing, ...].
    games: rows with game_id, home_score, away_score[, tip_date 'YYYY-MM-DD' US/Eastern].
    lines: optional rows with game_id and open_/close_ spread_home, total, home_ml, away_ml
        (`loaders.load_lines`); needed for CLV on opening bets.
    """
    bet_rows = [normalize_bet(b, f"bets[{i}]") for i, b in enumerate(_records(bets, "bets"))]
    games_by_id = _normalize_games(games)
    lines_by_id = _normalize_lines(lines)
    missing = sorted({b["game_id"] for b in bet_rows} - set(games_by_id))
    if missing:
        raise ValueError(f"bets reference games missing from `games`: {missing}")
    graded = [
        grade_bet(b, games_by_id[b["game_id"]], lines_by_id.get(b["game_id"])) for b in bet_rows
    ]
    summary, daily = summarize(graded, seed=seed, n_bootstrap=n_bootstrap)
    return GradeResult(bets=graded, summary=summary, daily=daily)
