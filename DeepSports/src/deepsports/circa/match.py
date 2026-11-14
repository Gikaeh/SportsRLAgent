"""Match Circa board lines to warehouse games by team names. Pure, apart from `load_candidates`.

Circa's rotation numbers aren't in the warehouse, so they can't name a game by themselves. They
group the board instead: a game's two teams share the rotation pair (2k-1, 2k), so every line of
that pair gets the game matched for any of them.
"""

from __future__ import annotations

import difflib
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from deepsports import config

_TOKEN_MAP = {
    "STATE": "ST",
    "SAINT": "ST",
    "UNIVERSITY": "U",
    "UNIV": "U",
    "MOUNT": "MT",
    "FORT": "FT",
    "INTERNATIONAL": "INTL",
}
_FIRST_TOKEN = {
    "N": "NORTH",
    "S": "SOUTH",
    "E": "EAST",
    "W": "WEST",
    "C": "CENTRAL",
    "NE": "NORTHEAST",
    "NW": "NORTHWEST",
    "SE": "SOUTHEAST",
    "SW": "SOUTHWEST",
}


def norm(name: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", name.upper().replace("&", " ").replace("'", ""))
    toks = s.split()
    if toks and toks[0] in _FIRST_TOKEN and len(toks) > 1:
        toks[0] = _FIRST_TOKEN[toks[0]]
    return " ".join(_TOKEN_MAP.get(t, t) for t in toks)


def _aliases(team: dict) -> set[str]:
    out = set()
    for key in ("abbr", "display_name", "location", "name"):
        v = team.get(key)
        if v:
            out.add(norm(v))
    loc, nm = team.get("location") or "", team.get("name") or ""
    if loc.upper() == "LOS ANGELES" and nm:
        out.add(norm(f"LA {nm}"))
    if team.get("abbr") and nm:
        out.add(norm(f"{team['abbr']} {nm}"))
    out.discard("")
    return out


def side_score(circa: str, team: dict) -> float:
    """2 = an alias matches exactly, 1 = close (prefix or fuzzy), 0 = no match."""
    c = norm(circa)
    aliases = _aliases(team)
    if c in aliases:
        return 2.0
    best = 0.0
    for a in aliases:
        if (
            len(c) >= 4
            and (a.startswith(c + " ") or c.startswith(a + " "))
            or difflib.SequenceMatcher(None, c, a).ratio() >= 0.86
        ):
            best = max(best, 1.0)
    return best


def match_game(away: str, home: str, candidates: list[dict], league: str | None = None):
    """(game, swapped) for the one best candidate where both names match, else (None, False).
    `swapped` means Circa's away/home is the warehouse's home/away."""
    scored = []
    for g in candidates:
        if league and g["league"] != league:
            continue
        straight = (side_score(away, g["away"]), side_score(home, g["home"]))
        flipped = (side_score(away, g["home"]), side_score(home, g["away"]))
        for pair, swapped in ((straight, False), (flipped, True)):
            if min(pair) > 0:
                scored.append((sum(pair), swapped, g))
    if not scored:
        return None, False
    scored.sort(key=lambda t: -t[0])
    if len(scored) > 1 and scored[1][0] == scored[0][0] and scored[1][2] is not scored[0][2]:
        return None, False  # ambiguous
    return scored[0][2], scored[0][1]


def _rot_pair(rot: str | None) -> int | None:
    return (int(rot) + 1) // 2 if rot else None


_FLIP = {"home": "away", "away": "home", "over": "over", "under": "under"}


def match_lines(lines: list[dict], candidates: list[dict]) -> list[dict]:
    """Fill game_id and league; orient away/home (and the side) to the warehouse game."""
    by_names: dict[tuple, tuple] = {}
    by_rot: dict[int, tuple] = {}
    for ln in lines:
        key = (ln["away"], ln["home"], ln["league"])
        if key not in by_names:
            by_names[key] = match_game(ln["away"], ln["home"], candidates, ln["league"])
        rp = _rot_pair(ln["rotation"])
        if by_names[key][0] is not None and rp is not None:
            by_rot.setdefault(rp, by_names[key])
    out = []
    for ln in lines:
        ln = dict(ln)
        game, swapped = by_names[(ln["away"], ln["home"], ln["league"])]
        if game is None and ln["rotation"]:
            hit = by_rot.get(_rot_pair(ln["rotation"]))
            if hit is not None:
                game, swapped = hit  # same rotation pair as a matched line: same game
        if game is not None:
            ln["game_id"], ln["league"] = game["game_id"], game["league"]
            if swapped:
                ln["away"], ln["home"] = ln["home"], ln["away"]
                ln["side"] = _FLIP[ln["side"]]
        out.append(ln)
    return out


def window(day: date) -> tuple[datetime, datetime]:
    """Today + tomorrow, local time."""
    start = datetime.combine(day, time(0), config.LOCAL_TZ)
    return start, start + timedelta(days=2)


CANDIDATES_SQL = """
    SELECT g.game_id, g.league, g.start_time_utc,
           h.abbreviation, h.display_name, h.location, h.name,
           a.abbreviation, a.display_name, a.location, a.name
    FROM games g
    JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
    JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
    WHERE g.state = 'pre' AND g.start_time_utc >= ? AND g.start_time_utc < ?
    ORDER BY g.start_time_utc, g.game_id
"""


def candidates_from_rows(rows: list[tuple]) -> list[dict[str, Any]]:
    out = []
    for gid, lg, start, *teams in rows:
        h = dict(zip(("abbr", "display_name", "location", "name"), teams[:4], strict=True))
        a = dict(zip(("abbr", "display_name", "location", "name"), teams[4:], strict=True))
        out.append({"game_id": gid, "league": lg, "start_time_utc": start, "home": h, "away": a})
    return out


def load_candidates(day: date, lock_wait: float = 20.0, db_path=None) -> list[dict[str, Any]]:
    """Not-started games today + tomorrow (local), both leagues. A brief read-only open that waits
    up to 20 s for a writer's lock (the 300 s script cap > Claude's 240 s + this). Raises duckdb
    errors to the caller, which keeps the lines with game_id null."""
    from deepsports.store import Store

    start, end = window(day)
    db = Store(db_path or config.DB_PATH, read_only=True, lock_wait=lock_wait)
    try:
        return candidates_from_rows(db.con.execute(CANDIDATES_SQL, [start, end]).fetchall())
    finally:
        db.close()
