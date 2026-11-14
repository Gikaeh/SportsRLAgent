"""To The Moon (betting) proposals: today's bets for a tier, built from the models-only picks.

Source: the latest run of `deepsports model-picks run` (`model_picks.RUNS_DIR/<run>/picks.json`
+ `slate.json`). Only the public output of `deepsports.analysis.model_picks` is used.

The proposal is a recommendation, never a placed bet. The owner bets at Circa, which is not in
The Odds API feed: each proposal shows the slate's reference price (ManualBets' best price when
it is better), repriced at Circa's lines when a Circa lines file exists (`circa.reprice`), and
says to skip when Circa is worse. The ledger records the price actually taken.

The `mix` tier (straights + a parlay) is paced on THIS month's deposit: `month_budget` reads the
ledger (every tier's stakes, manual included, count against it) and `tiers.pace_allowance` says
what today may stake.

Hit probabilities are "at -vig": each leg's no-vig market probability (both sides of the
slate's market, vig removed). Neither model has beaten the closing line, so the picks are a way
to choose sides, not an edge.
"""

from __future__ import annotations

import calendar
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.analysis import model_picks
from deepsports.analysis.metrics import devig_probability
from deepsports.moon import circa as circa_mod
from deepsports.moon import ledger, sim
from deepsports.moon import tiers as tiers_mod
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
    ref_price: int = 0  # the slate's own price (what Circa is compared with)
    source: str = "ref"  # ref (no Circa file) | circa (Circa's price) | unchecked (not on Circa)
    away_names: tuple[str, ...] = ()
    home_names: tuple[str, ...] = ()


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
    months: int = 12  # the sim horizon p_reach is over
    p_up: float | None = None  # mix: the tier's simulated P(end the month ahead)

    @property
    def kind(self) -> str:
        if len(self.legs) > 1:
            return f"{len(self.legs)}-leg parlay"
        return "moneyline" if self.legs[0].market == "moneyline" else self.legs[0].market

    def odds_line(self) -> str:
        """One line: e.g. '3-leg parlay +596: ~13% to hit at -vig; Let it ride ... ~14% (sim)'."""
        s = (
            f"{self.kind} {self.price:+d}: ~{self.p_hit:.0%} to hit at -vig (EV {self.ev:+.1%}),"
            f" returns ${self.stake * sim.decimal(self.price):,.2f} on ${self.stake:,.2f}"
        )
        if self.tier.stake == "mix" and self.p_up is not None:
            horizon = sim.months_label(self.months)
            s += f"; {self.tier.name} ends {horizon} ahead ~{self.p_up:.0%} (sim)"
        elif self.p_reach is not None:
            s += (
                f"; {self.tier.name} reaches ${self.target:,.0f} in {sim.months_label(self.months)}"
                f" ~{_pct(self.p_reach)} (sim)"
            )
        return s

    @property
    def returns(self) -> float:
        return round(self.stake * sim.decimal(self.price), 2)

    def circa_line(self) -> str:
        if all(lg.source == "circa" for lg in self.legs):
            return "Price from Circa's screenshots" + (
                " (leg prices; check Circa's parlay price)" if len(self.legs) > 1 else ""
            )
        unchecked = [lg.label for lg in self.legs if lg.source == "unchecked"]
        if unchecked:
            return (f"{circa_mod.UNCHECKED}: {', '.join(unchecked)}; skip if Circa is worse than "
                    f"{self.price:+d}")  # fmt: skip
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
    circa_notes: list[str] = field(default_factory=list)
    budget: MonthBudget | None = None  # mix: this month's budget


@dataclass
class MonthBudget:
    """This month's deposit, what every tier (manual included) staked out of it, and pacing."""

    day: date
    deposit: float
    staked: float  # this month's stakes, all tiers, voids excluded
    staked_today: float
    gap: int  # days since the last bet before today (or since the month's money arrived)
    days_left: int  # days left in the month, today included
    tier_singles_today: int = 0
    tier_parlays_today: int = 0
    # other tiers' (manual) stakes placed before the month's latest deposit, voids excluded
    other_staked_before_top_up: float = 0.0

    @property
    def plan_money(self) -> float:
        """What the plan tier sizes its units from. A deposit resets the base to what is unstaked
        then: manual bets made before the latest deposit don't count, later ones only cut `left`.
        2026-11: $27 of manual picks, then $23 + $27 deposited, so $50 (DECISIONS 2026-11-14)."""
        return round(max(0.0, self.deposit - self.other_staked_before_top_up), 2)

    @property
    def left(self) -> float:
        return round(max(0.0, self.deposit - self.staked), 2)

    def allowance(self) -> float:
        """What today may still stake (today's earlier bets already taken off)."""
        a = tiers_mod.pace_allowance(self.left + self.staked_today, self.days_left, self.gap)
        return round(max(0.0, min(a - self.staked_today, self.left)), 2)


def _ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _local_day(ts: str) -> date:
    return datetime.fromisoformat(ts).astimezone(config.LOCAL_TZ).date()


def month_budget(rows: Sequence[Mapping[str, str]], tier_key: str, today: date) -> MonthBudget:
    """This month's budget from the ledger rows (pure). The month is the rows' `month` column;
    every live bet counts against the deposit, manual ones included. Results never refill it:
    winnings are not re-staked."""
    month = today.strftime("%Y-%m")
    live = [r for r in ledger.live_rows(rows) if r["month"] == month]
    deps = [r for r in live if r["kind"] == "deposit"]
    bets = [r for r in live if r["kind"] == "bet"]
    days_in = calendar.monthrange(today.year, today.month)[1]
    first = today.replace(day=1)
    before = [_local_day(b["created_at"]) for b in bets if _local_day(b["created_at"]) < today]
    if before:
        anchor = max(before)
    elif deps:
        anchor = min(_local_day(d["created_at"]) for d in deps) - timedelta(days=1)
    else:
        anchor = first - timedelta(days=1)
    anchor = max(anchor, first - timedelta(days=1))
    today_bets = [b for b in bets if _local_day(b["created_at"]) == today]
    last_dep = max((_ts(d["created_at"]) for d in deps), default=None)
    mine = [b for b in today_bets if b["tier"] == tier_key]
    return MonthBudget(
        day=today,
        deposit=round(sum(float(d["amount"] or 0) for d in deps), 2),
        staked=round(sum(float(b["stake"]) for b in bets), 2),
        staked_today=round(sum(float(b["stake"]) for b in today_bets), 2),
        gap=max(1, (today - anchor).days),
        days_left=days_in - today.day + 1,
        tier_singles_today=sum(b["market"] != "parlay" for b in mine),
        tier_parlays_today=sum(b["market"] == "parlay" for b in mine),
        other_staked_before_top_up=round(
            sum(
                float(b["stake"])
                for b in bets
                if b["tier"] != tier_key and last_dep and _ts(b["created_at"]) < last_dep
            ),
            2,
        ),  # fmt: skip
    )


def next_card_day(mb: MonthBudget, card: float) -> date | None:
    """The first later day this month a bet of `card` dollars fits if nothing else is bet."""
    left = mb.left
    if left < card - 1e-9:
        return mb.day + timedelta(days=mb.days_left - 1) if mb.days_left > 1 else None
    gap0 = 1 if mb.staked_today > 0 else mb.gap
    for k in range(1, mb.days_left):
        if tiers_mod.pace_allowance(left, mb.days_left - k, gap0 + k) >= card - 1e-9:
            return mb.day + timedelta(days=k)
    return None


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
    ref_price = int(pick["price"])
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
        ref_price=ref_price,
        away_names=tuple(x for x in (game["away"].get("abbr"), game["away"].get("name")) if x),
        home_names=tuple(x for x in (game["home"].get("abbr"), game["home"].get("name")) if x),
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
    months: int = 12,
    p_up: float | None = None,
    month_budget: MonthBudget | None = None,
    circa: Mapping[str, Any] | None = None,
) -> Plan:
    """Today's proposals for `tier` (pure). `bets_this_month` counts this tier's bets already
    logged this month (hand-placed `manual` bets don't count). `month_budget` is required by the
    `mix` tier. `circa`: a Circa lines payload to reprice the legs at (see `circa.reprice`)."""
    plan = Plan(tier, balance, month, budget=month_budget)
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
    if circa is not None:
        legs, plan.circa_notes = circa_mod.reprice(legs, circa)
    if tier.stake == "mix":
        return _propose_mix(plan, legs, month_budget, p_up, months)
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
        plan.proposals.append(
            Proposal(tier, stake, list(grp), price, p, ev, p_reach, target, months)
        )
    return plan


def mix_units(tier: Tier, deposit: float) -> tuple[float, float]:
    """($ per single, $ for the parlay) of a mix tier at this month's deposit."""
    return tiers_mod.unit_usd(tier.unit, deposit), tiers_mod.unit_usd(tier.parlay_unit, deposit)


def _propose_mix(
    plan: Plan, legs: list[Leg], mb: MonthBudget | None, p_up: float | None, months: int
) -> Plan:
    t, say = plan.tier, plan.messages.append
    if mb is None or mb.plan_money <= 0:
        say("No deposit logged this month: `log deposit --amount 50` first (the mix tier bets "
            "only this month's deposit).")  # fmt: skip
        return plan
    single, par = mix_units(t, mb.plan_money)
    smallest = min(u for u in (single, par) if u > 0)
    left = min(mb.left, plan.balance)
    allow = min(mb.allowance(), left)
    n, with_parlay = tiers_mod.mix_card(allow, left, single, par, t.per_day)
    n = int(min(n, t.per_day - mb.tier_singles_today))
    with_parlay = bool(with_parlay) and mb.tier_parlays_today == 0
    if n < 1 and not with_parlay:
        if left < sim.MIN_STAKE:
            say(f"This month's ${mb.deposit:,.0f} is all staked: next bets next month.")
            return plan
        nxt = next_card_day(mb, smallest)
        when = f" Next bet about {nxt:%a %b %-d} if nothing else is bet." if nxt else ""
        say(f"No bet today: today's share of the ${left:,.2f} left is ${allow:,.2f}, under the "
            f"smallest bet (${smallest:,.0f}).{when}")  # fmt: skip
        return plan
    if not legs:
        say("No qualifying pick today: no bet.")
        return plan
    singles = legs[:n]
    rest = legs[n:]
    plegs = rest[:2] if len(rest) >= 2 else legs[:2]
    for lg in singles:
        price, p, ev = parlay([lg])
        plan.proposals.append(Proposal(t, single, [lg], price, p, ev, None, 0.0, months, p_up))
    if with_parlay and len(plegs) == 2 and single * len(singles) + par <= left + 1e-9:
        price, p, ev = parlay(plegs)
        plan.proposals.append(Proposal(t, par, list(plegs), price, p, ev, None, 0.0, months, p_up))
        if plegs[0] in singles or plegs[1] in singles:
            say("Too few picks for separate parlay legs: the parlay repeats today's singles "
                "(it moves with them).")  # fmt: skip
    return plan


def _leg_spec(lg: Leg) -> str:
    return (f"{lg.game_id}:{lg.league}:{lg.market}:{lg.side}:"
            f"{'' if lg.line is None else f'{lg.line:g}'}:{lg.price}")  # fmt: skip


def log_command(prop: Proposal, *, base: str = "uv run python -m deepsports.moon",
                price: str = "<PRICE>") -> str:  # fmt: skip
    """The `log` command to copy after placing the bet (price/stake to be edited to the fill)."""
    base = f"{base} log"
    tier = f"--tier {prop.tier.key}"
    if len(prop.legs) == 1:
        lg = prop.legs[0]
        line = "" if lg.line is None else f" --line {lg.line:g}"
        return (
            f"{base} bet {tier} --game-id {lg.game_id} --league {lg.league} --market {lg.market}"
            f' --side {lg.side}{line} --bet "{lg.label}" --price {price} --stake {prop.stake:g}'
        )
    legs = " ".join(f"--leg {_leg_spec(lg)}" for lg in prop.legs)
    desc = " + ".join(lg.label for lg in prop.legs)
    return f'{base} parlay {tier} {legs} --bet "{desc}" --price {price} --stake {prop.stake:g}'


def render(plan: Plan, budget: float, target: float) -> str:
    t = plan.tier
    out = [
        f"To The Moon proposal (watch-only): tier {t.id} {t.name}, plan month {plan.month}, "
        f"balance ${plan.balance:,.2f}, target ${target:,.0f}, ${budget:,.0f}/month",
        f"Rule: {t.description}",
    ]
    if plan.budget is not None:
        out.append(budget_line(plan))
    out += plan.messages
    for i, pr in enumerate(plan.proposals, 1):
        out.append(f"{i}. Stake ${pr.stake:,.2f} on " + " + ".join(lg.label for lg in pr.legs))
        for lg in pr.legs:
            out.append(f"   - {lg.label} ({lg.price:+d}) {lg.game} {lg.tip} [{lg.league}]")
        out.append(f"   {pr.odds_line()}")
        out.append(f"   {pr.circa_line()}")
        out.append(f"   Log it after placing: {log_command(pr)}")
    out += [f"Circa: {n}" for n in plan.circa_notes]
    out.append(
        "Neither model has beaten the closing line: every bet loses the vig on average. "
        "You place every bet yourself; nothing here places a wager."
    )
    return "\n".join(out)


def budget_line(plan: Plan) -> str:
    mb = plan.budget
    assert mb is not None
    days = "1 day" if mb.days_left == 1 else f"{mb.days_left} days"
    return (f"{mb.day:%b} budget ${mb.deposit:,.0f}: ${mb.staked:,.2f} staked (manual included), "
            f"${mb.left:,.2f} left for {days}")  # fmt: skip


DISCORD_LIMIT = 2000
DISCORD_MAX = 1900  # leave room for whatever the poster adds
WATCH_ONLY = "Watch-only: you place every bet yourself; nothing here places a wager."


def _short_cmd(pr: Proposal) -> str:
    return log_command(pr, base="moon", price=f"{pr.price}")


def render_discord(plan: Plan, *, sim_line: str | None = None) -> str:
    """Short phone text for Discord (always under DISCORD_MAX characters)."""
    t, mb = plan.tier, plan.budget
    day = f"{mb.day:%a %b %-d}" if mb else ""
    head = [f"**To The Moon** {day} | {t.name} (tier {t.id})".replace("  ", " ")]
    bal = f"Balance ${plan.balance:,.2f}"
    if mb is not None:
        bal += f" | {mb.day:%b}: ${mb.left:,.2f} of ${mb.deposit:,.0f} left, {mb.days_left}d to go"
    head.append(bal)
    body = list(plan.messages)
    for i, pr in enumerate(plan.proposals, 1):
        what = " + ".join(
            f"{lg.game} {lg.label}" if lg.market == "total" else lg.label for lg in pr.legs
        )
        tag = "" if all(lg.source == "ref" for lg in pr.legs) else (
            " [Circa]" if all(lg.source == "circa" for lg in pr.legs) else " [check Circa]"
        )  # fmt: skip
        body.append(f"{i}. {what} {pr.price:+d}{tag}: ${pr.stake:g} -> ${pr.returns:,.2f}"
                    f" (~{_pct(pr.p_hit)})")  # fmt: skip
    if any(lg.source == "ref" for pr in plan.proposals for lg in pr.legs):
        body.append("Prices: reference books, not Circa. Skip a leg if Circa is worse.")
    body += [f"Circa: {n}" for n in plan.circa_notes]
    if sim_line:
        body.append(sim_line)
    tail = [WATCH_ONLY]
    cmds = [_short_cmd(pr) for pr in plan.proposals]
    log = []
    if cmds:
        log = ["Copy to log (from DeepSports/: `uv run deepsports` + line; edit price/stake "
               "to your fill):", "```", *cmds, "```"]  # fmt: skip
    text = "\n".join(head + body + log + tail)
    if len(text) > DISCORD_MAX and log:
        log = ["Log commands: run `uv run deepsports moon propose` in the terminal."]
        text = "\n".join(head + body + log + tail)
    if len(text) > DISCORD_MAX:
        keep = DISCORD_MAX - len(WATCH_ONLY) - 2
        text = text[:keep].rsplit("\n", 1)[0] + "\n" + WATCH_ONLY
    return text
