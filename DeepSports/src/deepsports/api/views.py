"""Pure functions: raw ESPN JSON / warehouse rows -> API response shapes (docs/API.md)."""

from datetime import datetime
from typing import Any

from deepsports import config
from deepsports.parse_espn import _num, parse_summary, parse_time

EAST = {"ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DET", "IND", "MIA", "MIL", "NY", "ORL", "PHI",
        "TOR", "WSH"}  # fmt: skip
WEST = {"DAL", "DEN", "GS", "HOU", "LAC", "LAL", "MEM", "MIN", "NO", "OKC", "PHX", "POR", "SA",
        "SAC", "UTAH"}  # fmt: skip


def conference(abbr: str) -> str:
    return "East" if abbr in EAST else "West" if abbr in WEST else "Other"


def local_time(dt: datetime) -> datetime:
    return dt.astimezone(config.LOCAL_TZ)


def _clock_text(period: int | None, clock: str | None, league: str = "nba") -> str:
    if not period:
        return ""
    regulation = 2 if league == "ncaab" else 4  # college plays two halves
    if period <= regulation:
        label = ("1st", "2nd")[period - 1] if league == "ncaab" else f"Q{period}"
    else:
        ot = period - regulation
        label = "OT" if ot == 1 else f"{ot}OT"
    return f"{label} {clock}".strip() if clock else label


def status_text(status: dict, start: datetime, league: str = "nba") -> str:
    t = status.get("type", {})
    name, state = t.get("name", ""), t.get("state")
    period, clock = status.get("period"), status.get("displayClock")
    if state == "pre":
        if name == "STATUS_POSTPONED":
            return "Postponed"
        return local_time(start).strftime("%-I:%M %p")
    if state == "in":
        if name == "STATUS_HALFTIME":
            return "Halftime"
        if name == "STATUS_END_PERIOD":
            return f"End {_clock_text(period, None, league)}"
        return _clock_text(period, clock, league) or t.get("shortDetail", "Live")
    if name == "STATUS_POSTPONED":
        return "Postponed"
    if name in ("STATUS_CANCELED", "STATUS_CANCELLED"):
        return "Canceled"
    return t.get("shortDetail") or "Final"


def _logo(team: dict) -> str | None:
    if team.get("logo"):
        return team["logo"]
    logos = team.get("logos") or []
    return logos[0].get("href") if logos else None


def _record(competitor: dict) -> str | None:
    for r in competitor.get("records") or competitor.get("record") or []:
        if r.get("type") == "total" or r.get("name") == "overall":
            return r.get("summary")
    return None


def _side(c: dict, followed: set[str], started: bool) -> dict[str, Any]:
    t = c["team"]
    return {
        "id": t["id"],
        "abbr": t["abbreviation"],
        "name": t.get("displayName"),
        "short_name": t.get("shortDisplayName") or t.get("name"),
        "logo": _logo(t),
        "record": _record(c),
        "followed": t["abbreviation"] in followed,
        "score": _num(c.get("score")) if started else None,
        "linescores": [
            _num(ls.get("value", ls.get("displayValue"))) for ls in c.get("linescores") or []
        ],
    }


def _broadcasts(comp: dict) -> list[str]:
    names: list[str] = []
    for b in comp.get("broadcasts") or []:
        for n in b.get("names") or ([b["media"]["shortName"]] if b.get("media") else []):
            if n not in names:
                names.append(n)
    return names


def game_card(
    comp: dict,
    status: dict,
    game_id: str,
    start_iso: str,
    followed: set[str],
    league: str = "nba",
) -> dict[str, Any]:
    """Works for both a scoreboard competition and a summary header competition."""
    start = parse_time(start_iso)
    state = status.get("type", {}).get("state")
    started = state != "pre"
    sides = {c["homeAway"]: _side(c, followed, started) for c in comp["competitors"]}
    odds = None
    if state == "pre" and comp.get("odds"):
        o = comp["odds"][0]
        odds = o.get("details")
        if odds and o.get("overUnder") is not None:
            odds += f", O/U {o['overUnder']}"
    return {
        "id": game_id,
        "league": league,
        "state": state,
        "status": status.get("type", {}).get("name"),
        "status_text": status_text(status, start, league),
        "period": status.get("period") if started else None,
        "clock": status.get("displayClock") if state == "in" else None,
        "start_time": local_time(start).isoformat(),
        "home": sides["home"],
        "away": sides["away"],
        "broadcasts": _broadcasts(comp),
        "odds": odds,
        "venue": (comp.get("venue") or {}).get("fullName"),
        "neutral_site": bool(comp.get("neutralSite")),
        "followed": sides["home"]["followed"] or sides["away"]["followed"],
        "prediction": None,  # filled from the warehouse by the API layer (attach_predictions)
    }


def scoreboard_cards(raw: dict, followed: set[str], league: str = "nba") -> list[dict[str, Any]]:
    cards = []
    for e in raw.get("events", []):
        comp = e["competitions"][0]
        cards.append(game_card(comp, e["status"], e["id"], e["date"], followed, league))
    cards.sort(key=lambda c: (not c["followed"], c["start_time"], c["id"]))
    return cards


def game_detail(raw: dict, followed: set[str], league: str = "nba") -> dict[str, Any]:
    comp = raw["header"]["competitions"][0]
    card = game_card(comp, comp["status"], raw["header"]["id"], comp["date"], followed, league)
    card["venue"] = card["venue"] or (raw.get("gameInfo") or {}).get("venue", {}).get("fullName")
    teams, players, _ = parse_summary(raw)
    abbr = {c["team"]["id"]: c["team"]["abbreviation"] for c in comp["competitors"]}
    team_box = [
        {k: v for k, v in {**t, "abbr": abbr.get(t["team_id"])}.items() if k != "game_id"}
        for t in teams
    ]
    by_team: dict[str, list[dict]] = {}
    for p in players:
        line = {k: v for k, v in p.items() if k not in ("game_id", "team_id")}
        line["name"] = line.pop("athlete_name")
        by_team.setdefault(p["team_id"], []).append(line)
    for lines in by_team.values():
        lines.sort(key=lambda p: (p["did_not_play"], not p["starter"], -(p["minutes"] or 0)))
    if card["state"] == "pre":  # ESPN sends empty stat rows before tip; the contract says none
        team_box, by_team = [], {}
    return {"game": card, "teams": team_box, "players": by_team}


def glance_lines(cards: list[dict[str, Any]], max_len: int = 30) -> list[str]:
    """Compact lines for the glasses: followed teams' games only, away first."""
    lines = []
    for c in cards:
        if not c["followed"]:
            continue
        a, h = c["away"], c["home"]
        sep = "vs" if c.get("neutral_site") else "@"
        if c["state"] == "pre":
            line = f"{a['abbr']} {sep} {h['abbr']}  {c['status_text']}"
        else:
            line = f"{a['abbr']} {a['score']}-{h['score']} {h['abbr']}  {c['status_text']}"
        lines.append(line[:max_len])
    return lines or ["No followed games today"]


def prediction_view(row: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """One `predictions` row -> the API Prediction shape (docs/API.md v2), graded if final."""
    p = float(row["p_home_win"])
    home, away = card["home"], card["away"]
    fav, fav_p = (home["abbr"], p) if p >= 0.5 else (away["abbr"], 1 - p)
    out: dict[str, Any] = {
        "model": row["model"],
        "model_version": row["model_version"],
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else str(row["created_at"]),
        "p_home_win": round(p, 4),
        "pred_home_margin": round(float(row["pred_home_margin"]), 1),
        "pred_total": round(float(row["pred_total"]), 1),
        "favorite_abbr": fav,
        "favorite_prob": round(fav_p, 4),
        # Early-season college prediction (fewer than 5 games for a team); clients hide it
        # unless the owner turns on "early-season predictions".
        "early": str(row["model_version"]).endswith("-early"),
    }
    if card["status"] == "STATUS_FINAL" and home["score"] is not None and away["score"] is not None:
        margin = home["score"] - away["score"]
        out["result"] = {
            "winner_correct": (margin > 0) == (p >= 0.5) if margin != 0 else False,
            "margin_error": round(abs(margin - float(row["pred_home_margin"])), 1),
            "total_error": round(abs(home["score"] + away["score"] - float(row["pred_total"])), 1),
        }
    return out
