"""To The Moon (betting) simulator: Monte Carlo of a tier over `months` months of deposits.

The horizon defaults to 12 months; `months=1` is the one-month view.

Assumptions (also in docs/TO_THE_MOON.md):
- Every leg has the same expected value per $1 staked, `ev_leg`. Default: minus the vig of a
  standard -110/-110 market, 0.5 x 1.909 - 1 = -4.55%. No model has beaten the closing line
  (docs/results/2026-11-06-sim-v1.1-prices.md), so there is no edge by default. A positive
  `ev_leg` is a hypothetical, never a measured edge.
- A leg at decimal odds d wins with probability p = (1 + ev_leg) / d, independent of other legs.
  A parlay of n legs pays d^n and hits with p^n: the vig compounds per leg, EV = (1+ev_leg)^n - 1.
- No pushes (half-point lines), no taxes, $1 minimum stake, stakes are not rounded.
- A deposit lands at the start of each month, before that month's bets.
- The `mix` tier plays `tiers.DAYS_PER_MONTH` slate days a month: each day it stakes what
  `tiers.pace_allowance` allows out of the month's deposit minus the month's stakes, as flat
  single units plus one 2-leg parlay (`tiers.mix_card`). Legs are independent.

Reported per tier (all over `paths` seeded runs):
- p_reach: balance >= target at the end of the last month
- p_up: ending balance above all deposits (ahead of keeping the cash)
- p_touch: balance >= target at any point (what a perfect cash-out would lock in)
- p_lose_half: ending balance < half of all deposits
- median / p10 / p90 ending balance, mean ending balance
- months_mostly_lost: share of months where more than half of that month's deposit was lost
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from deepsports.analysis.metrics import american_to_decimal
from deepsports.moon import tiers as tiers_mod
from deepsports.moon.tiers import MONTHS, STANDARD_PRICE, Tier

MIN_STAKE = 1.0
DEFAULT_PATHS = 20_000
DEFAULT_SEED = 7
MAX_BETS_PER_MONTH = 500  # cap for the bold rule, which bets until target or $0


def decimal(price: float) -> float:
    d = american_to_decimal(price)
    if d is None:
        raise ValueError(f"invalid American price {price!r}")
    return d


def american(dec: float) -> int:
    """Decimal odds -> American price, rounded: 2.0 -> +100, 6.958 -> +596, 1.909 -> -110."""
    if dec <= 1:
        raise ValueError(f"decimal odds must be > 1, got {dec}")
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def vig_ev(price: float = STANDARD_PRICE) -> float:
    """EV per $1 of one side of a two-way market priced `price` on both sides (fair p = 0.5)."""
    return 0.5 * decimal(price) - 1


DEFAULT_EV = vig_ev()  # -0.04545...


def parlay_decimal(prices: list[float] | tuple[float, ...]) -> float:
    """Decimal payout of an ordinary parlay of independent legs (product of leg decimals)."""
    return math.prod(decimal(p) for p in prices)


@dataclass(frozen=True)
class BetOdds:
    legs: int
    decimal: float
    american: int
    p_hit: float
    ev: float  # per $1 staked


def bet_odds(legs: int = 1, leg_price: float = STANDARD_PRICE, ev_leg: float = DEFAULT_EV):
    """Price, hit probability and EV of an n-leg bet at `leg_price` per leg."""
    d_leg = decimal(leg_price)
    p_leg = (1 + ev_leg) / d_leg
    if not 0 < p_leg <= 1:
        raise ValueError(f"ev_leg {ev_leg} gives an impossible win probability at {leg_price}")
    d = d_leg**legs
    p = p_leg**legs
    return BetOdds(legs, d, american(d), p, p * d - 1)


@dataclass(frozen=True)
class SimResult:
    tier_id: int
    tier: str
    budget: float
    target: float
    months: int
    paths: int
    seed: int
    ev_leg: float
    cash_out: bool
    deposits: float
    p_reach: float
    p_up: float
    p_touch: float
    p_lose_half: float
    p_zero: float  # ending balance under $1
    median: float
    p10: float
    p90: float
    mean_end: float
    months_mostly_lost: float
    bets_per_path: float
    staked_per_path: float

    @property
    def se_reach(self) -> float:
        return math.sqrt(max(self.p_reach * (1 - self.p_reach), 1e-12) / self.paths)

    def as_dict(self) -> dict:
        return asdict(self)


def _stake(
    tier: Tier, bal: np.ndarray, k: int, budget: float, target: float, dec: float
) -> np.ndarray:
    if tier.stake == "fraction":
        s = tier.fraction * bal
    elif tier.stake == "deposit":
        s = np.full_like(bal, budget if k == 0 else 0.0)
    elif tier.stake == "all":
        s = bal.copy()
    elif tier.stake == "bold":
        s = np.where(bal < target, np.maximum(target - bal, 0.0) / (dec - 1), 0.0)
    else:
        return np.zeros_like(bal)
    s = np.where(s > 0, np.maximum(s, MIN_STAKE), 0.0)
    return np.minimum(s, bal)


def simulate(
    tier: Tier | int | str,
    budget: float = tiers_mod.DEFAULT_BUDGET,
    target: float = tiers_mod.DEFAULT_TARGET,
    *,
    months: int = MONTHS,
    paths: int = DEFAULT_PATHS,
    seed: int = DEFAULT_SEED,
    ev_leg: float = DEFAULT_EV,
    cash_out: bool | None = None,
) -> SimResult:
    """Monte Carlo of one tier: `paths` runs of `months` months with `budget` deposited monthly.
    Seeded and vectorized over paths. `cash_out` overrides the tier's own rule."""
    t = tier if isinstance(tier, Tier) else tiers_mod.get(tier)
    co = t.cash_out if cash_out is None else cash_out
    odds = bet_odds(t.legs, t.leg_price, ev_leg)
    rng = np.random.default_rng(seed)
    bal = np.zeros(paths)
    touched = np.zeros(paths, dtype=bool)
    done = np.zeros(paths, dtype=bool)
    mostly_lost = 0
    bets = np.zeros(paths)
    staked = np.zeros(paths)
    for m in range(1, months + 1):
        start = bal.copy()
        bal += budget
        touched |= bal >= target
        if co:
            done |= touched
        if t.stake == "mix":
            _mix_month(t, budget, target, ev_leg, rng, bal, touched, done, bets, staked, co)
        elif t.stake != "none" and m >= t.start_month:
            n = t.bets_per_month or MAX_BETS_PER_MONTH
            for k in range(n):
                s = np.where(
                    done | (bal < MIN_STAKE), 0.0, _stake(t, bal, k, budget, target, odds.decimal)
                )
                live = s > 0
                if not live.any():
                    break
                win = rng.random(paths) < odds.p_hit
                bal += np.where(live, np.where(win, s * (odds.decimal - 1), -s), 0.0)
                bets += live
                staked += s
                touched |= bal >= target
                if co:
                    done |= touched
        mostly_lost += int((bal < start + 0.5 * budget).sum())
    deposits = budget * months
    q10, q50, q90 = np.quantile(bal, [0.1, 0.5, 0.9])
    return SimResult(
        tier_id=t.id,
        tier=t.name,
        budget=budget,
        target=target,
        months=months,
        paths=paths,
        seed=seed,
        ev_leg=ev_leg,
        cash_out=co,
        deposits=deposits,
        p_reach=float((bal >= target).mean()),
        p_up=float((bal > deposits + 1e-9).mean()),
        p_touch=float(touched.mean()),
        p_lose_half=float((bal < 0.5 * deposits).mean()),
        p_zero=float((bal < MIN_STAKE).mean()),
        median=float(q50),
        p10=float(q10),
        p90=float(q90),
        mean_end=float(bal.mean()),
        months_mostly_lost=mostly_lost / (paths * months),
        bets_per_path=float(bets.mean()),
        staked_per_path=float(staked.mean()),
    )


def _mix_month(t: Tier, budget, target, ev_leg, rng, bal, touched, done, bets, staked, co):
    """One month of the `mix` tier, in place on the per-path arrays. Stakes come only out of
    this month's deposit (`budget`), never out of winnings."""
    single = tiers_mod.unit_usd(t.unit, budget)
    parlay = tiers_mod.unit_usd(t.parlay_unit, budget)
    o1 = bet_odds(1, t.leg_price, ev_leg)
    o2 = bet_odds(2, t.leg_price, ev_leg)
    days = tiers_mod.DAYS_PER_MONTH
    spent = np.zeros_like(bal)
    last = np.zeros_like(bal)  # day of the month's last bet (0 = none yet)
    for d in range(1, days + 1):
        left = budget - spent
        allow = tiers_mod.pace_allowance(left, days - d + 1, d - last)
        n, par = tiers_mod.mix_card(allow, left, single, parlay, t.per_day)
        n = np.where(done, 0, n)
        par = par & ~done
        day = np.zeros_like(bal)
        for j in range(t.per_day):
            live = n > j
            win = rng.random(bal.size) < o1.p_hit
            day += np.where(live, np.where(win, single * (o1.decimal - 1), -single), 0.0)
            bets += live
            staked += live * single
            spent += live * single
        win = rng.random(bal.size) < o2.p_hit
        day += np.where(par, np.where(win, parlay * (o2.decimal - 1), -parlay), 0.0)
        bets += par
        staked += par * parlay
        spent += par * parlay
        last = np.where((n > 0) | par, d, last)
        bal += day
        touched |= bal >= target
        if co:
            done |= touched


def ladder(
    budget: float = tiers_mod.DEFAULT_BUDGET,
    target: float = tiers_mod.DEFAULT_TARGET,
    *,
    months: int = MONTHS,
    paths: int = DEFAULT_PATHS,
    seed: int = DEFAULT_SEED,
    ev_leg: float = DEFAULT_EV,
) -> list[SimResult]:
    """Every tier at one budget, target and horizon (same seed for each tier)."""
    return [
        simulate(t, budget, target, months=months, paths=paths, seed=seed, ev_leg=ev_leg)
        for t in tiers_mod.TIERS
    ]


def best_tier(results: list[SimResult]) -> SimResult:
    """Highest P(reach); ties go to the lower P(lose > half), then the timider tier."""
    return max(results, key=lambda r: (round(r.p_reach, 3), -r.p_lose_half, -r.tier_id))


# ---------- terminal rendering ----------


def _pct(x: float) -> str:
    if x == 0:
        return "0%"
    if x < 0.001:
        return "<0.1%"
    return f"{x:.1%}" if x < 0.1 else f"{x:.0%}"


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def table(rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows
    )


def render_ladder(results: list[SimResult], *, markdown: bool = False) -> str:
    head = ["#", "Tier", "P(reach)", "P(up)", "P(touch)", "P(lose>1/2)", "p10", "Median", "p90",
            "Mean", "Months mostly lost"]  # fmt: skip
    rows = [
        [str(r.tier_id), r.tier, _pct(r.p_reach), _pct(r.p_up), _pct(r.p_touch),
         _pct(r.p_lose_half), _usd(r.p10), _usd(r.median), _usd(r.p90), _usd(r.mean_end),
         _pct(r.months_mostly_lost)]
        for r in results
    ]  # fmt: skip
    if markdown:
        lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])
    return table([head, *rows])


def months_label(n: int) -> str:
    return "1 month" if n == 1 else f"{n} months"


def headline(results: list[SimResult]) -> str:
    r0 = results[0]
    ev = r0.ev_leg
    label = "at -vig" if abs(ev - DEFAULT_EV) < 1e-9 else f"HYPOTHETICAL edge {ev:+.1%}/leg"
    return (
        f"${r0.budget:,.0f}/month for {months_label(r0.months)} (${r0.deposits:,.0f} deposited), "
        f"target ${r0.target:,.0f}, {label}, {r0.paths:,} runs, seed {r0.seed}"
    )
