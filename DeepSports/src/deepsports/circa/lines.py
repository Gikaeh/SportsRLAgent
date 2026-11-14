"""Parse and validate the JSON lines Claude reads off the Circa screenshots. Pure."""

from __future__ import annotations

import json
import math
from typing import Any

MARKETS = {"spread": ("home", "away"), "total": ("over", "under"), "moneyline": ("home", "away")}
LEAGUE_ALIASES = {
    "nba": "nba",
    "ncaab": "ncaab",
    "cbb": "ncaab",
    "ncaam": "ncaab",
    "ncaa": "ncaab",
    "college": "ncaab",
    "college basketball": "ncaab",
}
FIELDS = ("game_id", "league", "away", "home", "market", "side", "line", "price", "rotation")


def _half(x: float) -> bool:
    return math.isclose(x * 2, round(x * 2))


def _team(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    v = " ".join(v.upper().split())
    return v if 0 < len(v) <= 40 else None


def _number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        s = v.strip().upper()
        if s in ("PK", "PICK", "EVEN"):
            return 0.0
        s = s.replace("½", ".5")
        try:
            v = float(s)
        except ValueError:
            return None
    if isinstance(v, int | float) and math.isfinite(v):
        return float(v)
    return None


def _price(v: Any) -> int | None:
    if isinstance(v, str) and v.strip().upper() == "EVEN":
        return 100
    n = _number(v)
    if n is None or not n.is_integer():
        return None
    n = int(n)
    return n if 100 <= abs(n) <= 100_000 else None


def validate_line(raw: Any) -> tuple[dict | None, str | None]:
    """(clean line, None) or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "not an object"
    away, home = _team(raw.get("away")), _team(raw.get("home"))
    if not away or not home or away == home:
        return None, "missing team names"
    market = str(raw.get("market", "")).strip().lower()
    side = str(raw.get("side", "")).strip().lower()
    if market not in MARKETS:
        return None, f"bad market {market!r}"
    if side not in MARKETS[market]:
        return None, f"bad side {side!r} for {market}"
    price = _price(raw.get("price"))
    if price is None:
        return None, "bad price"
    line = None
    if market == "spread":
        line = _number(raw.get("line"))
        if line is None or abs(line) > 60 or not _half(line):
            return None, "bad spread line"
    elif market == "total":
        line = _number(raw.get("line"))
        if line is None or not 80 <= line <= 400 or not _half(line):
            return None, "bad total line"
    league = raw.get("league")
    league = LEAGUE_ALIASES.get(str(league).strip().lower()) if league else None
    rot = raw.get("rotation")
    rot = str(rot).strip() if isinstance(rot, int | str) and not isinstance(rot, bool) else None
    if rot is not None and (not rot.isdigit() or len(rot) > 5):
        rot = None
    return {
        "game_id": None,
        "league": league,
        "away": away,
        "home": home,
        "market": market,
        "side": side,
        "line": None if line is None else (int(line) if line.is_integer() else line),
        "price": price,
        "rotation": rot,
    }, None


def parse_output(text: str) -> tuple[list[dict], list[str]]:
    """Claude's reply -> (lines, problems). One JSON object per line; code fences, blank lines
    and a top-level JSON array are tolerated. Later duplicates of a (game, market, side) win
    (screenshots are read oldest first). Spread pairs must mirror and total pairs must agree,
    else both sides are dropped."""
    problems: list[str] = []
    objs: list[Any] = []
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            objs = list(json.loads(stripped))
        except ValueError:
            problems.append("unparseable JSON array")
    else:
        for raw in stripped.splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("```"):
                continue
            try:
                objs.append(json.loads(raw))
            except ValueError:
                problems.append(f"not JSON: {raw[:60]}")
    by_key: dict[tuple, dict] = {}
    for o in objs:
        line, why = validate_line(o)
        if line is None:
            problems.append(f"dropped ({why}): {json.dumps(o)[:80]}")
            continue
        by_key[(line["away"], line["home"], line["market"], line["side"])] = line
    for (away, home, market, side), ln in list(by_key.items()):
        if market not in ("spread", "total") or side not in ("home", "over"):
            continue
        other = by_key.get((away, home, market, "away" if side == "home" else "under"))
        if other is None:
            continue
        ok = ln["line"] == -other["line"] if market == "spread" else ln["line"] == other["line"]
        if not ok:
            problems.append(f"dropped inconsistent {market} pair {away} @ {home}")
            del by_key[(away, home, market, side)]
            del by_key[(away, home, market, other["side"])]
    return list(by_key.values()), problems
