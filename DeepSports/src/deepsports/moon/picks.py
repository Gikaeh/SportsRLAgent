"""To The Moon (betting) proposals: today's bets for a tier, built from the models-only picks.

Source: the latest run of `deepsports model-picks run` (`model_picks.RUNS_DIR/<run>/picks.json`
+ `slate.json`). Only the public output of `deepsports.analysis.model_picks` is used.

The proposal is a recommendation, never a placed bet. The owner bets at Circa, which is not in
The Odds API feed: each proposal shows the slate's reference price (ManualBets' best price when
it is better) and says to skip when Circa is worse. The ledger records the price actually taken.

Hit probabilities are "at -vig": each leg's no-vig market probability (both sides of the
slate's market, vig removed). Neither model has beaten the closing line, so the picks are a way
to choose sides, not an edge.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepsports.analysis import model_picks
from deepsports.analysis.metrics import devig_probability
from deepsports.moon import sim
from deepsports.moon.tiers import Tier

DOG_MIN, DOG_MAX = 200, 400  # the underdog tier's moneyline window
OTHER = {"home": "away", "away": "home", "over": "under", "under": "over"}


@dataclass
class Leg:
    game_id: str
    league: str
    market: str
    side: str
    line: float | None
    price: int  # reference price (slate, or ManualBets' best when better)
    label: str
    game: str
    tip: str
    fair_p: float


@dataclass
class Proposal:
    tier: Tier
    stake: float
    legs: list[Leg]
    price: int
    p_hit: float
    ev: float  # per $1 at the reference price, -vig assumption
    p_reach: float | None = None  # the tier's simulated P(reach target)
    target: float = 0.0

    @property
    def kind(self) -> str:
        if len(self.legs) > 1:
            return f"{len(self.legs)}-leg parlay"
        return "moneyline" if self.legs[0].market == "moneyline" else self.legs[0].market

    def odds_line(self) -> str:
        """One line: e.g. '3-leg parlay +596: ~13% to hit at -vig; Let it ride ... ~14% (sim)'."""
        s = f"{self.kind} {self.price:+d}: ~{self.p_hit:.0%} to hit at -vig (EV {self.ev:+.1%})"
        if self.p_reach is not None:
            s += (
                f"; {self.tier.name} reaches ${self.target:,.0f} in 12 months"
                f" ~{_pct(self.p_reach)} (sim)"
            )
        return s

    def circa_line(self) -> str:
        return f"Check Circa; skip if Circa is worse than {self.price:+d}" + (
            " or any leg's line is worse" if len(self.legs) > 1 else " or the line is worse"
        )


@dataclass
class Plan:
    """What `propose` says today: proposals, or a reason there are none."""

    tier: Tier
    balance: float
    month: int
    proposals: list[Proposal] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _pct(x: float) -> str:
    return "<1%" if 0 < x < 0.01 else f"{x:.0%}"


# ---------- loading the models-only run ----------


def latest_run(root: Path | None = None) -> Path | None:
    root = Path(root or model_picks.RUNS_DIR)
    runs = sorted(p.parent for p in root.glob("*/picks.json") if (p.parent / "slate.json").exists())
    return runs[-1] if runs else None


def load_run(run: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """(picks payload, slate) of a model-picks run directory."""
    return json.loads((run / "picks.json").read_text()), json.loads(
        (run / "slate.json").read_text()
    )


# ---------- legs ----------


def _fair(game: Mapping[str, Any], market: str, side: str) -> float | None:
    m = (game.get("markets") or {}).get(market)
    if not m:
        return None
    return devig_probability(m.get(f"{side}_price"), m.get(f"{OTHER[side]}_price"))


def _leg(pick: Mapping[str, Any], game: Mapping[str, Any]) -> Leg:
    price, line = pick["price"], pick["line"]
    best = pick.get("best")
    if best and best["point"] == line and best["price"] > price:
        price = best["price"]
    fair = _fair(game, pick["market"], pick["side"])
    if fair is None:
        fair = (1 + sim.DEFAULT_EV) / sim.decimal(pick["price"])
    return Leg(
        game_id=pick["game_id"],
        league=pick["league"],
        market=pick["market"],
        side=pick["side"],
        line=line,
        price=int(price),
        label=pick["label"],
        game=f"{game['away']['abbr']} @ {game['home']['abbr']}",
        tip=game.get("tip_local", ""),
        fair_p=fair,
    )


def single_legs(payload: Mapping[str, Any], slate: Mapping[str, Any]) -> list[Leg]:
    """The run's top picks (one per game, best first) as legs."""
    games = {g["game_id"]: g for g in slate["games"]}
    return [_leg(p, games[p["game_id"]]) for p in payload.get("top", []) if p["game_id"] in games]


def dog_legs(payload: Mapping[str, Any], slate: Mapping[str, Any]) -> list[Leg]:
    """Moneyline underdogs at +200..+400 on the side a spread pick backs (one per game)."""
    games = {g["game_id"]: g for g in slate["games"]}
    out, seen = [], set()
    for p in payload.get("picks", []):
        g = games.get(p["game_id"])
        if g is None or p["market"] != "spread" or p["game_id"] in seen or p["line"] <= 0:
            continue
        ml = (g.get("markets") or {}).get("moneyline") or {}
        price = ml.get(f"{p['side']}_price")
        if price is None or not DOG_MIN <= price <= DOG_MAX:
            continue
        team = g[p["side"]]["abbr"]
        leg = _leg(p | {"market": "moneyline", "line": None, "price": price,
                        "label": f"{team} ML", "best": None}, g)  # fmt: skip
        out.append(leg)
        seen.add(p["game_id"])
    return out


def parlay(legs: Sequence[Leg]) -> tuple[int, float, float]:
    """(reference American price, P(hit) at -vig, EV per $1) of independent legs."""
    dec = sim.parlay_decimal([lg.price for lg in legs])
    p = math.prod(lg.fair_p for lg in legs)
    return sim.american(dec), p, p * dec - 1


# ---------- the proposal ----------


def stake_for(tier: Tier, balance: float, budget: float, target: float, dec: float) -> float:
    if tier.stake == "fraction":
        s = tier.fraction * balance
    elif tier.stake == "deposit":
        s = min(budget, balance)
    elif tier.stake == "all":
        s = balance
    elif tier.stake == "bold":
        s = min(balance, max(target - balance, 0.0) / (dec - 1))
    else:
        return 0.0
    return round(min(max(s, sim.MIN_STAKE), balance), 2)


def propose(
    tier: Tier,
    payload: Mapping[str, Any] | None,
    slate: Mapping[str, Any] | None,
    *,
    balance: float,
    month: int,
    budget: float,
    target: float,
    bets_this_month: int = 0,
    p_reach: float | None = None,
) -> Plan:
    """Today's proposals for `tier` (pure). `bets_this_month` counts bets already logged."""
    plan = Plan(tier, balance, month)
    say = plan.messages.append
    if tier.stake == "none":
        say(f"{tier.name}: no bet. Keep the ${budget:,.0f}.")
        return plan
    if month < tier.start_month:
        say(f"No bet in month {month}: bank the deposit. Bold play starts in month "
            f"{tier.start_month} with the whole balance.")  # fmt: skip
        return plan
    if tier.cash_out and balance >= target:
        say(f"Target ${target:,.0f} reached (balance ${balance:,.2f}): cash out, no more bets.")
        return plan
    if tier.bets_per_month and bets_this_month >= tier.bets_per_month:
        say(f"This month's {tier.bets_per_month} bet(s) are logged; next bets next month.")
        return plan
    if balance < sim.MIN_STAKE:
        say("Balance is $0: wait for next month's deposit.")
        return plan
    if payload is None or slate is None:
        say("No model-picks run found (run `deepsports model-picks run` first).")
        return plan
    legs = dog_legs(payload, slate) if tier.leg_price > 0 else single_legs(payload, slate)
    if tier.legs > 1:
        if len(legs) < tier.legs:
            say(f"Only {len(legs)} pick(s) today: not enough for a {tier.legs}-leg parlay.")
            return plan
        groups = [legs[: tier.legs]]
    else:
        n = tier.per_day
        if tier.bets_per_month:
            n = min(n, tier.bets_per_month - bets_this_month)
        groups = [[lg] for lg in legs[:n]]
    if not groups:
        what = "moneyline underdog at +200 to +400" if tier.leg_price > 0 else "pick"
        say(f"No qualifying {what} today: no bet.")
        return plan
    left = balance
    for grp in groups:
        price, p, ev = parlay(grp)
        stake = stake_for(tier, left if tier.stake != "fraction" else balance, budget, target,
                          sim.decimal(price))  # fmt: skip
        if stake < sim.MIN_STAKE or stake > left:
            break
        left -= stake
        plan.proposals.append(Proposal(tier, stake, list(grp), price, p, ev, p_reach, target))
    return plan


def log_command(prop: Proposal) -> str:
    """The `log` command to copy after placing the bet (price/stake to be edited to the fill)."""
    base = "uv run python -m deepsports.moon log"
    tier = f"--tier {prop.tier.key}"
    if len(prop.legs) == 1:
        lg = prop.legs[0]
        line = "" if lg.line is None else f" --line {lg.line:g}"
        return (
            f"{base} bet {tier} --game-id {lg.game_id} --league {lg.league} --market {lg.market}"
            f' --side {lg.side}{line} --bet "{lg.label}" --price <PRICE> --stake {prop.stake:g}'
        )
    legs = " ".join(
        f"--leg {lg.game_id}:{lg.league}:{lg.market}:{lg.side}:"
        f"{'' if lg.line is None else f'{lg.line:g}'}:{lg.price}"
        for lg in prop.legs
    )
    desc = " + ".join(lg.label for lg in prop.legs)
    return f'{base} parlay {tier} {legs} --bet "{desc}" --price <PRICE> --stake {prop.stake:g}'


def render(plan: Plan, budget: float, target: float) -> str:
    t = plan.tier
    out = [
        f"To The Moon proposal (watch-only): tier {t.id} {t.name}, month {plan.month} of 12, "
        f"balance ${plan.balance:,.2f}, target ${target:,.0f}, ${budget:,.0f}/month",
        f"Rule: {t.description}",
    ]
    out += plan.messages
    for i, pr in enumerate(plan.proposals, 1):
        out.append(f"{i}. Stake ${pr.stake:,.2f} on " + " + ".join(lg.label for lg in pr.legs))
        for lg in pr.legs:
            out.append(f"   - {lg.label} ({lg.price:+d}) {lg.game} {lg.tip} [{lg.league}]")
        out.append(f"   {pr.odds_line()}")
        out.append(f"   {pr.circa_line()}")
        out.append(f"   Log it after placing: {log_command(pr)}")
    out.append(
        "Neither model has beaten the closing line: every bet loses the vig on average. "
        "You place every bet yourself; nothing here places a wager."
    )
    return "\n".join(out)
