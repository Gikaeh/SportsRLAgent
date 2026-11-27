"""The owner's parlays and how each leg is going, for the apps' Parlays tab.

Reads the To The Moon ledger (`../logs/moon/bets.csv`, append-only; written by `deepsports moon log
parlay`), read-only. Exposes labels, odds and per-leg status only: never the stake or the payout
(BetDesk's rule: no amounts leave the Mac). Pure functions here; the endpoint in `app.py` joins them
with live scoreboard cards.

Leg status: `won`/`lost`/`push` once decided, `pending` before tip or while undecided. A live total
is decided early when it can no longer change: an over that's already past the line is `won`, an
under that's already past it is `lost`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from deepsports.analysis.betting.grading import outcome
from deepsports.moon import ledger

LOCAL = ZoneInfo(
    "America/Los_Angeles"
)  # a graded parlay stays visible through its placement day (PT)
FINAL = {"win": "won", "loss": "lost", "push": "push"}


def leg_label(leg: Mapping[str, Any]) -> str:
    line = leg.get("line")
    if leg["market"] == "total":
        return f"{leg['side'].capitalize()} {float(line):g}"
    if leg["market"] == "moneyline":
        return f"{leg['side'].capitalize()} ML"
    return f"{leg['side'].capitalize()} {float(line):+g}"


def leg_status(leg: Mapping[str, Any], card: Mapping[str, Any] | None) -> dict[str, Any]:
    """{status, note} for one leg given its game card (None when the game isn't on a scoreboard)."""
    if card is None or card.get("state") == "pre":
        return {"status": "pending", "note": None}
    hs, as_ = card["home"].get("score"), card["away"].get("score")
    if hs is None or as_ is None:
        return {"status": "pending", "note": None}
    total, margin = hs + as_, hs - as_
    if card["state"] == "post":
        home_line = ledger._home_line(leg)
        res = outcome(leg["market"], leg["side"], home_line, margin, total)
        return {"status": FINAL[res], "note": f"{total} pts" if leg["market"] == "total" else None}
    if leg["market"] == "total":
        line = float(leg["line"])
        if leg["side"] == "over":
            if total > line:
                return {"status": "won", "note": f"{total} pts"}
            return {"status": "pending", "note": f"{total} pts, needs {int(line - total) + 1} more"}
        if total > line:
            return {"status": "lost", "note": f"{total} pts"}
        return {"status": "pending", "note": f"{total} pts, {line - total:g} under"}
    return {"status": "pending", "note": f"margin {margin:+d} (home)"}


def overall(statuses: Sequence[str]) -> str:
    if "lost" in statuses:
        return "lost"
    if all(s in ("won", "push") for s in statuses):
        return "push" if all(s == "push" for s in statuses) else "won"
    return "alive"


def recent_parlays(rows: Sequence[Mapping[str, str]], now: datetime) -> list[dict[str, Any]]:
    """Parlay bets (voids dropped), ungraded or graded but placed today (PT), newest first."""
    graded = ledger.results_by_bet(rows)
    out = []
    for r in ledger.live_rows(rows):
        if r["kind"] != "bet" or r["market"] != "parlay":
            continue
        placed = datetime.fromisoformat(r["created_at"])
        if r["id"] in graded and placed.astimezone(LOCAL).date() < now.astimezone(LOCAL).date():
            continue
        out.append(
            {
                "id": r["id"],
                "placed_at": r["created_at"],
                "book": r["book"] or None,
                "tier": r["tier"] or None,
                "price": int(float(r["price"])),
                "graded": graded[r["id"]]["result"] if r["id"] in graded else None,
                "legs": ledger.bet_legs(r),
            }
        )
    out.sort(key=lambda p: p["placed_at"], reverse=True)
    return out


def team_name(team: Mapping[str, Any]) -> str:
    return team.get("name") or team.get("short_name") or team.get("abbr") or "?"


def view(parlay: Mapping[str, Any], cards: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The API shape of one parlay: legs in tip order with their game, score and status."""
    legs = []
    for lg in parlay["legs"]:
        card = cards.get(str(lg["game_id"]))
        st = leg_status(lg, card)
        legs.append(
            {
                "game_id": str(lg["game_id"]),
                "label": leg_label(lg),
                "matchup": (
                    f"{team_name(card['away'])} @ {team_name(card['home'])}" if card else None
                ),
                "away_abbr": card["away"].get("abbr") if card else None,
                "home_abbr": card["home"].get("abbr") if card else None,
                "start_time": card.get("start_time") if card else None,
                "state": card.get("state") if card else None,
                "status_text": card.get("status_text") if card else None,
                "away_score": card["away"].get("score") if card else None,
                "home_score": card["home"].get("score") if card else None,
                **st,
            }
        )
    legs.sort(key=lambda x: (x["start_time"] or "9999", x["game_id"]))
    statuses = [x["status"] for x in legs]
    return {
        "id": parlay["id"],
        "placed_at": parlay["placed_at"],
        "book": parlay["book"],
        "tier": parlay["tier"],
        "price": parlay["price"],
        "status": parlay["graded"] or overall(statuses),
        "won": statuses.count("won"),
        "lost": statuses.count("lost"),
        "push": statuses.count("push"),
        "pending": statuses.count("pending"),
        "legs": legs,
    }
