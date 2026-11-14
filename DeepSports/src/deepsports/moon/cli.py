"""`python -m deepsports.moon`: To The Moon (betting) in the terminal. Watch-only.

Subcommands: tiers, sim, propose, log, status, grade. Guide: docs/TO_THE_MOON.md.
Entry point for wiring elsewhere: `main(argv) -> int`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.moon import circa as circa_mod
from deepsports.moon import ledger, picks, sim
from deepsports.moon import tiers as tiers_mod

# The owner's plan: straights + a parlay out of each month's deposit (2026-11-14 results file
# docs/results/2026-11-14-moon-mix-tier.md; root docs/DECISIONS.md).
DEFAULT_TIER = "mix"


def _signed(x: float) -> str:
    return f"{'-' if x < 0 else '+'}${abs(x):,.2f}"


def _common(p: argparse.ArgumentParser, *, sim_opts: bool = True) -> None:
    p.add_argument("--budget", type=float, default=tiers_mod.DEFAULT_BUDGET, help="$ per month")
    p.add_argument("--target", type=float, default=tiers_mod.DEFAULT_TARGET, help="$ goal")
    if sim_opts:
        p.add_argument("--months", type=int, default=tiers_mod.MONTHS,
                       help="horizon in months (1 = this month only; default 12)")  # fmt: skip
        p.add_argument("--paths", type=int, default=sim.DEFAULT_PATHS)
        p.add_argument("--seed", type=int, default=sim.DEFAULT_SEED)
        p.add_argument(
            "--edge",
            type=float,
            default=None,
            help="HYPOTHETICAL EV per leg (e.g. 0.02); default is -vig (-4.55%%), "
            "the measured reality. Shown side by side with the -vig numbers.",
        )


def cmd_tiers(args) -> int:
    print("To The Moon (betting) risk ladder. Watch-only: you place every bet.\n")
    rows = [["#", "Key", "Tier", "Bet", "Rule"]]
    rows += [[str(t.id), t.key, t.name, t.bet_kind, t.description] for t in tiers_mod.TIERS]
    print(sim.table(rows))
    print("Every betting tier stops betting once the balance touches the target (cash-out).\n")
    _print_ladder(args)
    return 0


def _print_ladder(args) -> None:
    res = sim.ladder(args.budget, args.target, months=args.months, paths=args.paths,
                     seed=args.seed)  # fmt: skip
    print(sim.headline(res))
    print(sim.render_ladder(res))
    best = sim.best_tier(res)
    print(f"\nHighest P(reach): tier {best.tier_id} {best.tier} ({best.p_reach:.1%}, "
          f"P(lose > half) {best.p_lose_half:.0%}).")  # fmt: skip
    if res[0].p_reach == 1:
        print("Deposits alone reach the target: keeping the cash is the sure way.")
    if args.edge is not None:
        hyp = sim.ladder(args.budget, args.target, months=args.months, paths=args.paths,
                         seed=args.seed, ev_leg=args.edge)  # fmt: skip
        print("\n" + sim.headline(hyp))
        print(sim.render_ladder(hyp))
        print("HYPOTHETICAL: no model has shown this edge against the closing line.")
    print("\nEvery bet loses the vig on average (EV -4.55% per -110 leg; parlays compound it).")


def cmd_sim(args) -> int:
    t = tiers_mod.get(args.tier)
    runs = [("at -vig", sim.DEFAULT_EV)]
    if args.edge is not None:
        runs.append((f"HYPOTHETICAL edge {args.edge:+.1%}/leg", args.edge))
    out = []
    for label, ev in runs:
        r = sim.simulate(t, args.budget, args.target, months=args.months, paths=args.paths,
                         seed=args.seed, ev_leg=ev, cash_out=args.cash_out)  # fmt: skip
        out.append((label, r))
    if args.json:
        print(json.dumps([r.as_dict() | {"label": lab} for lab, r in out], indent=1))
        return 0
    odds = sim.bet_odds(t.legs, t.leg_price)
    print(f"Tier {t.id} {t.name}: {t.description}")
    if t.stake == "mix":
        single, par = picks.mix_units(t, args.budget)
        print(f"A card: {t.per_day} singles -110 at ${single:g} + one 2-leg parlay +264 at "
              f"${par:g}, when the paced share of the month's deposit covers it; "
              f"{tiers_mod.DAYS_PER_MONTH} slate days a month")  # fmt: skip
    elif t.stake != "none":
        print(f"One bet: {t.bet_kind} {odds.american:+d}, ~{odds.p_hit:.1%} to hit at -vig, "
              f"EV {odds.ev:+.1%} per $1; ${args.budget:,.0f} returns "
              f"${args.budget * odds.decimal:,.0f} if it hits")  # fmt: skip
    for label, r in out:
        print(f"\n{label}: ${r.budget:,.0f}/month x {r.months} = ${r.deposits:,.0f} deposited, "
              f"target ${r.target:,.0f}, cash-out {'on' if r.cash_out else 'off'}, "
              f"{r.paths:,} runs (seed {r.seed})")  # fmt: skip
        print(sim.table([
            ["P(reach target)", f"{r.p_reach:.1%} (+/- {1.96 * r.se_reach:.1%})"],
            ["P(ahead of keeping the cash)", f"{r.p_up:.1%}"],
            ["P(touch target)", f"{r.p_touch:.1%}"],
            ["P(lose > half of deposits)", f"{r.p_lose_half:.1%}"],
            ["P(end at $0)", f"{r.p_zero:.1%}"],
            ["Ending balance p10 / median / p90",
             f"${r.p10:,.0f} / ${r.median:,.0f} / ${r.p90:,.0f}"],
            ["Mean ending balance", f"${r.mean_end:,.0f} (keep the cash: ${r.deposits:,.0f})"],
            ["Months where most new money is lost", f"{r.months_mostly_lost:.0%}"],
            [f"Bets / $ staked over {sim.months_label(r.months)} (mean)",
             f"{r.bets_per_path:.0f} / ${r.staked_per_path:,.0f}"],
        ]))  # fmt: skip
    return 0


def _ledger_state(path: Path | None) -> tuple[list[dict], dict[str, Any]]:
    rows = ledger.read_rows(path)
    return rows, ledger.summary(rows)


def _circa_payload(arg: str, day: date) -> tuple[dict | None, str | None]:
    """(lines payload, None) or (None, the one fallback note)."""
    if arg == "off":
        return None, "Circa check off: reference prices shown; check Circa by hand."
    path = circa_mod.default_path(day) if arg == "auto" else Path(arg)
    data, why = circa_mod.load(path)
    if data is None:
        return None, f"{why}: reference prices shown; check Circa by hand."
    return data, None


def cmd_propose(args) -> int:
    t = tiers_mod.get(args.tier)
    rows, s = _ledger_state(args.ledger)
    today = date.fromisoformat(args.date) if args.date else ledger._now(None).astimezone(
        config.LOCAL_TZ).date()  # fmt: skip
    month_now = today.strftime("%Y-%m")
    notes = []
    if args.balance is not None:
        balance = args.balance
    elif s["deposits"] > 0:
        balance = s["balance"]
    else:
        balance = args.budget
        notes.append(f"Ledger has no deposits: assuming this month's ${args.budget:,.0f}.")
    month = args.month or ledger.plan_month(s["first_month"])
    bets_now = sum(1 for r in ledger.live_rows(rows) if r["kind"] == "bet"
                   and r["month"] == month_now and r["tier"] == t.key)  # fmt: skip
    mb = None
    sim_budget = args.budget
    if t.stake == "mix":
        mb = picks.month_budget(rows, t.key, today)
        if mb.deposit <= 0 and s["deposits"] <= 0:  # nothing logged at all: assume --budget
            mb.deposit = args.budget
        if mb.plan_money > 0:
            sim_budget = mb.plan_money
    run = Path(args.run) if args.run else picks.latest_run()
    payload = slate = None
    if run is not None:
        payload, slate = picks.load_run(run)
        notes.append(f"Picks: model-picks run {run.name} (lines as of {slate['created_at']}).")
    lines, circa_note = _circa_payload(args.circa, today)
    if lines is not None:
        notes.append(f"Circa lines read {lines.get('read_at', '?')} ({len(lines['lines'])} lines).")
    r = sim.simulate(t, sim_budget, args.target, months=args.months, paths=args.paths,
                     seed=args.seed)  # fmt: skip
    plan = picks.propose(t, payload, slate, balance=balance, month=month, budget=sim_budget,
                         target=args.target, bets_this_month=bets_now,
                         p_reach=r.p_reach, months=args.months, p_up=r.p_up,
                         month_budget=mb, circa=lines)  # fmt: skip
    if circa_note:
        plan.circa_notes.append(circa_note)
    if args.format == "discord":
        sim_line = (f"Sim, {sim.months_label(r.months)} at ${sim_budget:,.0f}: P(up) "
                    f"{r.p_up:.0%}, P(lose>1/2) {r.p_lose_half:.0%}, mean end "
                    f"${r.mean_end:,.0f} (-vig)")  # fmt: skip
        print(picks.render_discord(plan, sim_line=sim_line))
        return 0
    print(picks.render(plan, sim_budget, args.target))
    for n in notes:
        print(n)
    if t.stake == "mix":
        print(f"Sim ({sim.months_label(r.months)}, ${sim_budget:,.0f}, -vig): P(up) {r.p_up:.0%}, "
              f"P(lose > half) {r.p_lose_half:.0%}, mean end ${r.mean_end:,.2f}, "
              f"{r.bets_per_path:.0f} bets a month.")  # fmt: skip
    if args.edge is not None:
        h = sim.simulate(t, sim_budget, args.target, months=args.months, paths=args.paths,
                         seed=args.seed, ev_leg=args.edge)  # fmt: skip
        print(f"HYPOTHETICAL edge {args.edge:+.1%}/leg: this tier reaches "
              f"${args.target:,.0f} ~{h.p_reach:.0%} (vs {r.p_reach:.0%} at -vig).")  # fmt: skip
    return 0


# ---------- log ----------


def _ask(value, prompt: str, cast: Callable = str, required: bool = True):
    if value is not None:
        return value
    if not sys.stdin.isatty():
        if required:
            raise ledger.LedgerError(f"missing {prompt} (pass it as a flag)")
        return None
    raw = input(f"{prompt}: ").strip()
    if not raw:
        if required:
            raise ledger.LedgerError(f"{prompt} is required")
        return None
    return cast(raw)


def parse_leg(spec: str) -> dict[str, Any]:
    """'GAME_ID:LEAGUE:MARKET:SIDE:LINE[:PRICE]' (LINE empty for a moneyline)."""
    parts = spec.split(":")
    if len(parts) not in (5, 6):
        raise ledger.LedgerError(f"bad --leg {spec!r}: GAME_ID:LEAGUE:MARKET:SIDE:LINE[:PRICE]")
    gid, league, market, side, line = parts[:5]
    price = parts[5] if len(parts) == 6 and parts[5] else None
    return {
        "game_id": gid,
        "league": league,
        "market": market,
        "side": side,
        "line": float(line) if line else None,
        "price": int(price) if price else None,
    }


def cmd_log(args) -> int:
    p = args.ledger
    k = args.what
    if k == "init":
        print(f"Ledger ready: {ledger.init(p)}")
        return 0
    if k == "deposit":
        row = ledger.add_deposit(_ask(args.amount, "amount ($)", float), path=p,
                                 month=args.month, note=args.note)  # fmt: skip
    elif k in ("bet", "parlay"):
        stake = _ask(args.stake, "stake ($)", float)
        price = _ask(args.price, "price actually taken (American, e.g. -110)", int)
        common = {"stake": stake, "price": price, "tier": args.tier, "book": args.book,
                  "bet": args.bet, "path": p, "month": args.month, "note": args.note}  # fmt: skip
        if k == "parlay":
            legs = [parse_leg(s) for s in args.leg or []]
            row = ledger.add_bet(market="parlay", legs=legs, **common)
        else:
            row = ledger.add_bet(
                market=_ask(args.market, "market (spread/total/moneyline)"),
                game_id=_ask(args.game_id, "game id"),
                league=_ask(args.league, "league (nba/ncaab)", required=False),
                side=_ask(args.side, "side (home/away/over/under)"),
                line=_ask(
                    args.line, "line (bet side's view; blank for moneyline)", float, required=False
                ),  # fmt: skip
                **common,
            )
        _, s = _ledger_state(p)
        if s["balance"] < 0:
            print(f"Warning: the moon balance is now ${s['balance']:,.2f}; log the deposit too.")
    elif k == "result":
        row = ledger.add_result(_ask(args.ref, "bet id"), _ask(args.result, "win/loss/push/void"),
                                payout=args.payout, path=p, note=args.note)  # fmt: skip
    elif k == "void":
        row = ledger.add_void(_ask(args.ref, "row id"), _ask(args.note, "why"), path=p)
    elif k == "adjust":
        row = ledger.add_adjust(_ask(args.amount, "amount ($, +/-)", float),
                                _ask(args.note, "why"), path=p)  # fmt: skip
    else:
        row = ledger.add_note(_ask(args.note, "note"), path=p)
    print(f"Appended row {row['id']} ({row['kind']}) to {p or config.MOON_LEDGER_PATH}")
    return 0


# ---------- status / grade ----------


def manual_staked(rows) -> dict[str, float]:
    """$ staked per month on hand-placed picks (tier `manual`), voids excluded."""
    out: dict[str, float] = {}
    for r in ledger.live_rows(rows):
        if r["kind"] == "bet" and r["tier"] == tiers_mod.MANUAL_TIER:
            out[r["month"]] = out.get(r["month"], 0.0) + float(r["stake"])
    return out


def cmd_status(args) -> int:
    rows, s = _ledger_state(args.ledger)
    print(f"To The Moon ledger: {args.ledger or config.MOON_LEDGER_PATH}")
    if not rows:
        print("Empty: no deposits or bets yet. Start with `log deposit --amount 75`.")
        return 0
    print(sim.table([
        ["Balance", f"${s['balance']:,.2f} (open stakes ${s['open_stake']:,.2f} counted as spent)"],
        ["Deposited", f"${s['deposits']:,.2f}"],
        ["vs keeping the cash", _signed(s["vs_cash"])],
        ["Settled bets", f"{s['settled']} ({s['record']} W-L-P), staked ${s['staked']:,.2f}"],
        ["Betting P&L", _signed(s["profit"])
         + ("" if s["roi"] is None else f" (ROI {s['roi']:+.1%})")],
        ["Plan month", f"{ledger.plan_month(s['first_month'])} "
         f"(first deposit {s['first_month'] or '-'})"],
    ]))  # fmt: skip
    manual = manual_staked(rows)
    if s["months"]:
        print()
        rows_m = [["Month", "Deposits", "Bets", "Staked", "of it manual", "Net from bets"]]
        rows_m += [[m, f"${v['deposits']:,.2f}", str(int(v["bets"])), f"${v['staked']:,.2f}",
                    f"${manual.get(m, 0.0):,.2f}", _signed(v["net"])]
                   for m, v in sorted(s["months"].items())]  # fmt: skip
        print(sim.table(rows_m))
        cur = s["months"].get(ledger._month(ledger._now(None)))
        if cur and cur["staked"] > cur["deposits"] + 0.005:
            print(f"This month's stakes (${cur['staked']:,.2f}, manual picks included) are over "
                  f"this month's deposit (${cur['deposits']:,.2f}): the excess is re-staked "
                  f"winnings or an unlogged deposit. "
                  f"The plan caps a month's risk at its deposit.")  # fmt: skip
    if s["open"]:
        print("\nOpen bets:")
        print(sim.table([["Id", "Placed", "Bet", "Price", "Stake", "Book"]] + [
            [b["id"], b["created_at"][:10], b["bet"], f"{int(b['price']):+d}",
             f"${float(b['stake']):,.2f}",
             b["book"]] for b in s["open"]
        ]))  # fmt: skip
    print("\nSample sizes this small say nothing about skill; the vig is the expected result.")
    return 0


def cmd_grade(args) -> int:
    from deepsports.analysis.ensemble_bets import load_finals
    from deepsports.store import Store

    rows = ledger.read_rows(args.ledger)
    ids = ledger.game_ids(rows)
    if not ids:
        print("No open bets to grade.")
        return 0
    st = Store(read_only=True, lock_wait=args.lock_wait)
    try:
        finals = load_finals(st.con, ids)
    finally:
        st.close()
    out = ledger.grade(finals, path=args.ledger, dry_run=args.dry_run)
    verb = "Would append" if args.dry_run else "Appended"
    for r in out:
        print(f"{verb} result for bet {r['ref']}: {r['bet']} -> {r['result']}, "
              f"payout ${float(r['payout']):,.2f}")  # fmt: skip
    pending = len(ledger.open_bets(rows)) - len(out)
    print(f"{len(out)} graded, {pending} still open (games not final in the warehouse).")
    return 0


# ---------- parser ----------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="deepsports moon",
        description="To The Moon (betting): risk ladder, proposals and a ledger. Watch-only.",
    )
    ap.add_argument("--ledger", type=Path, default=None,
                    help=f"ledger CSV (default {config.MOON_LEDGER_PATH})")  # fmt: skip
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("tiers", help="the risk ladder for a budget and target")
    _common(p)
    p.set_defaults(fn=cmd_tiers)

    p = sub.add_parser("sim", help="simulate one tier")
    p.add_argument("--tier", default=DEFAULT_TIER, help="id (1-12) or key")
    _common(p)
    p.add_argument("--cash-out", dest="cash_out", action=argparse.BooleanOptionalAction,
                   default=None, help="override the tier's cash-out-at-target rule")  # fmt: skip
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_sim)

    p = sub.add_parser("propose", help="today's bets for a tier from the models-only picks")
    p.add_argument("--tier", default=DEFAULT_TIER, help="id (1-12) or key")
    _common(p)
    p.add_argument("--balance", type=float, default=None, help="override the ledger balance")
    p.add_argument("--month", type=int, default=None, help="plan month (default: from the ledger)")
    p.add_argument("--run", default=None, help="model-picks run dir (default: latest)")
    p.add_argument("--circa", default="auto",
                   help="Circa lines: auto (today's file in $DEEPSPORTS_CIRCA_LINES, else "
                   "$DEEPSPORTS_CIRCA_DIR/lines, default "
                   f"{circa_mod.DEFAULT_DIR}), a JSON path, or off")  # fmt: skip
    p.add_argument("--format", choices=["text", "discord"], default="text")
    p.add_argument("--date", default=None,
                   help="today YYYY-MM-DD (pacing, Circa file)")  # fmt: skip
    p.set_defaults(fn=cmd_propose, paths=5_000)

    p = sub.add_parser("log", help="append a row to the ledger (after you placed the bet)")
    p.add_argument("what", choices=["init", "deposit", "bet", "parlay", "result", "void",
                                    "adjust", "note"])  # fmt: skip
    p.add_argument("--amount", type=float)
    p.add_argument("--stake", type=float)
    p.add_argument("--price", type=int, help="American price actually taken")
    p.add_argument("--market", choices=["spread", "total", "moneyline"])
    p.add_argument("--game-id", dest="game_id")
    p.add_argument("--league", choices=["nba", "ncaab"])
    p.add_argument("--side", choices=["home", "away", "over", "under"])
    p.add_argument("--line", type=float, help="from the bet side's view (home -1.5)")
    p.add_argument(
        "--leg", action="append", help="parlay leg GAME_ID:LEAGUE:MARKET:SIDE:LINE[:PRICE]"
    )
    p.add_argument("--bet", help="description, e.g. 'IDHO -1.5'")
    p.add_argument("--tier", default=None)
    p.add_argument("--book", default=ledger.DEFAULT_BOOK)
    p.add_argument("--ref", help="row id a result/void refers to")
    p.add_argument("--result", choices=list(ledger.RESULTS))
    p.add_argument("--payout", type=float, help="override the computed payout (stake included)")
    p.add_argument("--month", default=None, help="YYYY-MM (default: today, local time)")
    p.add_argument("--note", default=None)
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("status", help="balance, P&L and open bets")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("grade", help="append results for open bets whose games are final")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lock-wait", type=float, default=60.0)
    p.set_defaults(fn=cmd_grade)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "tier", None) and args.cmd != "log":
        tiers_mod.get(args.tier)
    try:
        return args.fn(args)
    except ledger.LedgerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
