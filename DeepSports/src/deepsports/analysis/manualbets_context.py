"""ManualBets' view of the slate, attached to an ensemble-betting slate (pure).

ManualBets runs in its own environment; `ManualBets/tools/export_predictions.py` writes a JSON
file, and this module only reads that file (boundary edge 4, root docs/DECISIONS.md 2026-11-11).
No ManualBets code is imported. NBA games are matched by home/away team and tip date (ManualBets
uses NBA.com codes), college games by ESPN game id (ManualBets reads this warehouse).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from deepsports import config

# NBA.com code -> ESPN abbreviation, where they differ.
NBA_CODES = {"NYK": "NY", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "GSW": "GS", "WAS": "WSH"}
SUFFIX = "+mb1"  # appended to the slate's context_version when ManualBets facts are attached


def load_export(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _espn(code: str) -> str:
    return NBA_CODES.get(code, code)


def _local_date(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(config.LOCAL_TZ).date().isoformat()


def attach_manualbets(slate: dict[str, Any], export: Mapping[str, Any] | None) -> dict[str, Any]:
    """Adds `manualbets` to each matched slate game and a summary under `slate['manualbets']`.

    A missing export, or a league that failed in ManualBets, is reported in the summary so the
    bettors know the facts are absent rather than empty."""
    if export is None:
        slate["manualbets"] = {"available": False, "errors": {"all": "no ManualBets export"}}
        return slate
    nba: dict[tuple[str, str, str], dict] = {}
    for g in (export.get("nba") or {}).get("games", []):
        tip = g.get("tip")
        day = _local_date(tip.replace(" ", "T")) if tip else g.get("date")
        nba[(_espn(g["home"]), _espn(g["away"]), day)] = g
    ncaab = {str(g["game_id"]): g for g in (export.get("ncaab") or {}).get("games", [])}
    matched = 0
    for game in slate["games"]:
        if game["league"] == "nba":
            key = (game["home"]["abbr"], game["away"]["abbr"], _local_date(game["tip_utc"]))
            mb = nba.get(key)
        else:
            mb = ncaab.get(str(game["game_id"]))
        if mb is not None:
            game["manualbets"] = mb
            matched += 1
    slate["manualbets"] = {
        "available": True,
        "created_at": export.get("created_at"),
        "errors": dict(export.get("errors") or {}),
        "matched_games": matched,
        "ncaab_gate": (export.get("ncaab") or {}).get("min_games_played_gate"),
    }
    slate["context_version"] = slate["context_version"] + SUFFIX
    return slate


def render_brief(slate: Mapping[str, Any]) -> str:
    """Extra brief lines describing the ManualBets facts (empty when none were attached)."""
    mb = slate.get("manualbets")
    if not mb:
        return ""
    if not mb.get("available"):
        return "- ManualBets facts are unavailable for this slate (its export did not run).\n"
    out = [
        "- `ManualBets` lines come from the project's second, independent pipeline: XGBoost models"
        " (NBA h2h + spread from nba_api stats; college from this warehouse), its Kelly-sized"
        " recommendations (stake as a fraction of bankroll), and the best price per side across"
        " all US books from The Odds API. Its models use no injury information and have no"
        " proven edge either; where it and the project model disagree, neither is known to be"
        " better.",
        "- A better price at another book doesn't change your grading: picks are graded at the"
        " slate's listed line and price.",
    ]
    if mb.get("ncaab_gate"):
        out.append(
            f"- ManualBets withholds college bets until both teams have played"
            f" {mb['ncaab_gate']} games."
        )
    for league, err in (mb.get("errors") or {}).items():
        out.append(f"- ManualBets {league.upper()} facts are missing today ({err[:80]}).")
    return "".join(f"{line}\n" for line in out)


def _price(p: Mapping[str, Any] | None, abbr: str, with_point: bool) -> str | None:
    if not p:
        return None
    pt = f" {p['point']:+g}" if with_point and p.get("point") is not None else ""
    return f"{abbr}{pt} {p['price']:+d} ({p['book']})"


def render_game(g: Mapping[str, Any]) -> list[str]:
    mb = g.get("manualbets")
    if not mb:
        return []
    h, a = g["home"]["abbr"], g["away"]["abbr"]
    md = mb.get("model") or {}
    parts = []
    if md.get("home_win_prob") is not None:
        parts.append(f"{h} {md['home_win_prob']:.0%} to win")
    if md.get("home_margin") is not None:
        parts.append(f"margin {h} {md['home_margin']:+g}")
    if md.get("total") is not None:
        parts.append(f"total {md['total']:g}")
    if mb.get("gated"):
        parts.append(f"bets withheld: a team has played only {mb.get('min_games_played')} games")
    lines = [f"- ManualBets model: {', '.join(parts) if parts else 'no numbers'}"]
    best = mb.get("best_prices") or {}
    shop = []
    for market, with_point in (("spread", True), ("moneyline", False)):
        b = best.get(market) or {}
        sides = [
            s
            for s in (_price(b.get("away"), a, with_point), _price(b.get("home"), h, with_point))
            if s
        ]
        if sides:
            shop.append(f"{market} " + " / ".join(sides) + f" across {b.get('books', '?')} books")
    if shop:
        lines.append("- best prices (Odds API): " + "; ".join(shop))
    recs = mb.get("recommendations") or []
    if recs:
        txt = []
        for r in recs:
            if "market" in r:  # NBA
                bet = f"{r['team']} {r['market']}" + (
                    f" {r['line']:+g}" if r.get("line") is not None else ""
                )
                pts = r.get("edge_unit") == "points"
                edge = f", edge {r['edge']:.1f} pts" if pts else f", edge {r['edge']:.1%}"
            else:  # college
                bet, edge = f"{r['bet']} ({r['type']})", ""
            txt.append(
                f"{bet} {r['price']:+d} ({r['book']}): win prob {r['win_prob']:.0%}{edge},"
                f" Kelly {r['kelly_fraction']:.1%} of bankroll"
            )
        lines.append("- ManualBets recommends: " + "; ".join(txt))
    elif "recommendations" in mb and not mb.get("gated"):
        lines.append("- ManualBets recommends: nothing on this game")
    return lines
