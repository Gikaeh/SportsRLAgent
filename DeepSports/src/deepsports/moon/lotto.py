"""To The Moon, lotto card: small-stake parlays built from the night's et-v1 legs. Watch-only.

Each night, after the 21:00 et-v1 log, `deepsports moon lotto` turns tomorrow's et-v1 bets
(college totals at William Hill's night-before line; `analysis/early_totals.py`), ranked by
et-v1's average edge, into a card (rule `lotto-v2`, pre-registered in
docs/results/2026-11-23-lotto-v2-preregistration.md):
- the **test ticket**: the top 7 legs, $1 (nights with 7+ legs);
- **spread tickets** at $0.25: with 9+ legs, 18 tickets of 7 of the top 9, each leaving out a
  different pair (i, i+1) or (i, i+2) around the circle of 9, so each leg sits out 4 tickets;
  with 8 legs, the 8 tickets that each leave out one leg; with 7, none.
Under 7 legs: no card. The owner places any ticket by hand and logs it with
`moon log parlay --tier lotto`.

History (docs/results/2026-11-23-lotto-investigation.md): et-v1's legs have no per-leg edge, and
their same-night sweeps were well above chance in 2022-23 to 2024-25 but not in other seasons. The
card is entertainment money that doubles as the forward test of that clustering.

Files (append-only, no real stakes; amounts are notional): `<REPORTS_DIR>/moon/lotto/cards.jsonl`,
one card per (rule, game date), the first one wins. `grade` settles tickets from warehouse finals
(read-only) and writes nothing.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.moon import ledger
from deepsports.moon.sim import american, decimal

RULE = "lotto-v2"
SOURCE = "et-v1"
TEST_LEGS = 7
TEST_STAKE = 1.0
SPREAD_POOL = 9
SPREAD_STAKE = 0.25
DEFAULT_PRICE = -110


def cards_path() -> Path:
    return config.REPORTS_DIR / "moon" / "lotto" / "cards.jsonl"


def et_bets_path() -> Path:
    return config.REPORTS_DIR / "early-totals" / "bets.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def legs_for(et_rows: Iterable[Mapping[str, Any]], game_date: str) -> list[dict[str, Any]]:
    """The night's et-v1 legs, one per game (first row per game is the bet), strongest first."""
    seen: dict[str, Mapping[str, Any]] = {}
    for r in et_rows:
        if r.get("rule_version") == SOURCE and r.get("game_date") == game_date:
            seen.setdefault(r["game_id"], r)
    rows = sorted(seen.values(), key=lambda r: (-float(r["avg_edge"]), r["tip_utc"], r["game_id"]))
    return [
        {
            "rank": i,
            "game_id": r["game_id"],
            "league": r.get("league", "ncaab"),
            "market": r["market"],
            "side": r["side"],
            "line": float(r["line"]),
            "price": int(r.get("price") or DEFAULT_PRICE),
            "away": r.get("away"),
            "home": r.get("home"),
            "tip_utc": r.get("tip_utc"),
            "avg_edge": float(r["avg_edge"]),
        }
        for i, r in enumerate(rows, 1)
    ]


def ticket(
    legs: Sequence[Mapping[str, Any]], stake: float, kind: str, left_out: Sequence[int] = ()
) -> dict[str, Any]:
    dec = math.prod(decimal(lg["price"]) for lg in legs)
    name = f"top-{len(legs)}" if not left_out else "7 w/o " + "+".join(map(str, left_out))
    return {
        "kind": kind,
        "name": name,
        "ranks": [lg["rank"] for lg in legs],
        "left_out": list(left_out),
        "stake": stake,
        "decimal": round(dec, 4),
        "american": american(dec),
        "returns": round(stake * dec, 2),
        "p_coinflip": 0.5 ** len(legs),
    }


def leave_out_sets(n: int) -> list[tuple[int, ...]]:
    """Ranks each spread ticket leaves out: 9+ legs -> the 18 pairs (i, i+1), (i, i+2) on a
    circle of 9 (each leg out 4 times); 8 legs -> each single leg; fewer -> none."""
    if n >= SPREAD_POOL:
        out = {tuple(sorted((i % 9 + 1, (i + k) % 9 + 1))) for k in (1, 2) for i in range(9)}
        return sorted(out)
    if n == TEST_LEGS + 1:
        return [(r,) for r in range(1, n + 1)]
    return []


def build_card(
    legs: Sequence[Mapping[str, Any]], game_date: str, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    n = len(legs)
    tickets: list[dict[str, Any]] = []
    pool = list(legs[: min(n, SPREAD_POOL)])
    if n >= TEST_LEGS:
        tickets.append(ticket(legs[:TEST_LEGS], TEST_STAKE, "test"))
        for out in leave_out_sets(n):
            chosen = [lg for lg in pool if lg["rank"] not in out]
            tickets.append(ticket(chosen, SPREAD_STAKE, "spread", out))
    return {
        "rule": RULE,
        "source": SOURCE,
        "made_at": now.isoformat(timespec="seconds"),
        "game_date": game_date,
        "n_legs_available": n,
        "legs": pool if tickets else [],
        "tickets": tickets,
    }


def get_or_make(
    game_date: str,
    *,
    et_rows: Sequence[Mapping[str, Any]],
    cards: Sequence[Mapping[str, Any]],
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """(card, is_new). An existing card for the date is returned unchanged (first one wins)."""
    for c in cards:
        if c.get("rule") == RULE and c.get("game_date") == game_date:
            return dict(c), False
    return build_card(legs_for(et_rows, game_date), game_date, now), True


def append_card(card: Mapping[str, Any], path: Path | None = None) -> Path:
    path = path or cards_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(card, separators=(",", ":")) + "\n")
    return path


# ---------- grading ----------


def _bet_like(card: Mapping[str, Any], t: Mapping[str, Any]) -> dict[str, Any]:
    by_rank = {lg["rank"]: lg for lg in card["legs"]}
    legs = [by_rank[r] for r in t["ranks"]]
    return {
        "market": "parlay",
        "legs": json.dumps(legs),
        "stake": t["stake"],
        "price": t["american"],
    }


def game_ids(cards: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted({lg["game_id"] for c in cards for lg in c["legs"]})


def grade_cards(
    cards: Sequence[Mapping[str, Any]], finals: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One row per ticket: result win/loss/push or None (games not final) and payout."""
    out = []
    for c in cards:
        if c.get("rule") != RULE:
            continue
        for t in c["tickets"]:
            bet = _bet_like(c, t)
            s = ledger.settle(bet, finals)
            result, legs_res = s if s is not None else (None, [])
            out.append(
                {
                    "game_date": c["game_date"],
                    "kind": t["kind"],
                    "name": t["name"],
                    "american": t["american"],
                    "stake": t["stake"],
                    "result": result,
                    "legs_won": sum(r == "win" for r in legs_res),
                    "legs_lost": sum(r == "loss" for r in legs_res),
                    "payout": None if result is None else ledger.payout_for(bet, result, legs_res),
                }
            )
    return out


def summarize(graded: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Totals per ticket kind, plus the pre-registered test: top-7 sweeps vs the number expected
    if legs were independent at the observed leg win rate of the test tickets (pushes excluded)."""
    done = [g for g in graded if g["result"] is not None]
    by: dict[str, dict[str, float]] = {}
    for g in done:
        b = by.setdefault(g["kind"], {"tickets": 0, "hits": 0, "staked": 0.0, "returned": 0.0})
        b["tickets"] += 1
        b["hits"] += g["result"] == "win"
        b["staked"] += g["stake"]
        b["returned"] += g["payout"]
    tests = [g for g in done if g["kind"] == "test"]
    won = sum(g["legs_won"] for g in tests)
    lost = sum(g["legs_lost"] for g in tests)
    p = won / (won + lost) if won + lost else None
    return {
        "settled": len(done),
        "open": len(graded) - len(done),
        "staked": sum(b["staked"] for b in by.values()),
        "returned": sum(b["returned"] for b in by.values()),
        "by_kind": by,
        "test_nights": len(tests),
        "test_sweeps": sum(g["result"] == "win" for g in tests),
        "test_leg_win": p,
        "test_expected": None if p is None else len(tests) * p**TEST_LEGS,
    }


# ---------- rendering ----------


def _local_tip(tip: str | None) -> str:
    if not tip:
        return "?"
    t = datetime.fromisoformat(tip).astimezone(config.LOCAL_TZ)
    return t.strftime("%I:%M%p").lstrip("0").lower().replace(":00", "")


def leg_text(lg: Mapping[str, Any]) -> str:
    side = "O" if lg["side"] == "over" else "U"
    return (f"{lg['away']} @ {lg['home']} {side}{lg['line']:g} {lg['price']:+d} "
            f"({_local_tip(lg.get('tip_utc'))})")  # fmt: skip


def render(card: Mapping[str, Any], fmt: str = "text") -> str:
    day = datetime.fromisoformat(card["game_date"]).strftime("%a %b %d").replace(" 0", " ")
    if not card["tickets"]:
        n = card["n_legs_available"]
        return f"Lotto parlays {day}: no card ({n} et-v1 leg{'s' * (n != 1)}, need {TEST_LEGS}+)."
    head = "🎟️ " if fmt == "discord" else ""
    cost = sum(t["stake"] for t in card["tickets"])
    lines = [
        f"{head}Lotto parlays {day}: et-v1 legs at William Hill's night-before lines, "
        f"${cost:,.2f} in all (watch-only, you place them)",
        "Legs, strongest first:",
    ]
    lines += [f"{lg['rank']}. {leg_text(lg)}" for lg in card["legs"]]
    test = [t for t in card["tickets"] if t["kind"] == "test"]
    spread = [t for t in card["tickets"] if t["kind"] == "spread"]
    for t in test:
        lines.append(
            f"Test ticket: legs 1-{TEST_LEGS}, ${t['stake']:g} at {t['american']:+,d} "
            f"(${t['returns']:,.2f} back; 1 in {round(1 / t['p_coinflip']):,} at coin flips)"
        )
    if spread:
        lo = min(t["returns"] for t in spread)
        hi = max(t["returns"] for t in spread)
        outs = ", ".join("+".join(map(str, t["left_out"])) for t in spread)
        lines.append(
            f"Spread: {len(spread)} x ${spread[0]['stake']:g} tickets of 7 legs from legs "
            f"1-{len(card['legs'])}, each leaving out: {outs} "
            f"(${lo:,.2f}-${hi:,.2f} back per winning ticket)"
        )
    lines.append(
        "Check WH's own parlay payout before placing (it can pay less than the leg prices). "
        "Log a placed ticket: `deepsports moon log parlay --tier lotto --book WilliamHill ...`."
    )
    return "\n".join(lines)


def render_grade(graded: Sequence[Mapping[str, Any]]) -> str:
    s = summarize(graded)
    if not graded:
        return "Lotto: no cards yet."
    out = [f"Lotto ({RULE}, notional stakes): {s['settled']} tickets settled, {s['open']} open."]
    for kind in ("test", "spread"):
        b = s["by_kind"].get(kind)
        if b:
            out.append(
                f"- {kind}: {b['hits']}/{b['tickets']} hit, staked ${b['staked']:,.2f}, "
                f"returned ${b['returned']:,.2f}"
            )
    if s["settled"]:
        net = s["returned"] - s["staked"]
        out.append(f"Total: staked ${s['staked']:,.2f}, returned ${s['returned']:,.2f} "
                   f"({'+' if net >= 0 else '-'}${abs(net):,.2f}).")  # fmt: skip
    if s["test_nights"]:
        out.append(
            f"Pre-registered test: {s['test_sweeps']} top-7 sweeps in {s['test_nights']} nights vs "
            f"{s['test_expected']:.2f} expected if legs were independent at their "
            f"{s['test_leg_win']:.1%} win rate (verdict at 150 nights)."
        )
    out.append("Small samples say nothing; a 7-leg ticket hits about 1 in 128 at coin flips.")
    return "\n".join(out)
