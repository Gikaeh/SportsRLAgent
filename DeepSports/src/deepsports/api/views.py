"""Pure functions: raw ESPN JSON / warehouse rows -> API response shapes (docs/API.md)."""

import re
from datetime import datetime
from typing import Any

from deepsports import config
from deepsports.parse_espn import _num, parse_summary, parse_time
from deepsports.parse_pbp import _classify, _seq, clock_to_seconds

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


_EVENT_KINDS = {
    "REBOUND": "rebound",
    "TURNOVER": "turnover",
    "FOUL": "foul",
    "TIMEOUT": "timeout",
    "SUBSTITUTION": "substitution",
    "ENDPERIOD": "period_end",
    "ENDGAME": "period_end",
}
_FT_OF_SET = re.compile(r"\b(\d+) of (\d+)\b")
_STEAL = re.compile(r"\bsteal\b", re.IGNORECASE)
# The shooting team keeps the ball after these free throws, so the last make doesn't flip it.
_FT_KEEPS_BALL = ("technical", "flagrant", "clear path")
# status.type.name values during which nobody has the ball, though state is still "in".
_BREAK_STATUSES = {"STATUS_HALFTIME", "STATUS_END_PERIOD"}


def _play_kind(subtype: str, text: str, shooting: bool, scoring: bool) -> str:
    event = _classify(subtype, shooting)
    if event == "SHOT":
        return "shot_made" if scoring else "shot_missed"
    if event == "FREETHROW":  # scoringPlay, not type text: college misses say "MadeFreeThrow"
        return "free_throw_made" if scoring else "free_throw_missed"
    if event != "OTHER":
        return _EVENT_KINDS.get(event, "other")
    # Types parse_pbp files under OTHER: "Offensive Charge", "Flopping Technical", "Traveling"
    sub = subtype.lower()
    if "charge" in sub or "technical" in sub:
        return "foul"
    if "turnover" in text.lower() and "challenge" not in sub and "review" not in sub:
        return "turnover"
    return "other"


def _shot_coord(raw_coord: Any) -> dict[str, float] | None:
    """Feet on the half court; ESPN's negative sentinels (-214748340) and off-court x are None."""
    if not isinstance(raw_coord, dict):
        return None
    x, y = _num(raw_coord.get("x")), _num(raw_coord.get("y"))
    if x is None or y is None or not 0 <= x <= 50 or y < 0:
        return None
    return {"x": x, "y": y}


def parse_plays(raw: dict) -> list[dict[str, Any]]:
    """Raw ESPN summary -> the API's Play list (docs/API.md), oldest first. Applies the fixes in
    parse_pbp's header: sequence order, running-max scores, `scoringPlay` over type text. Unlike
    parse_pbp, the last play isn't anchored to the header score: a live header can run ahead of
    the plays, and anchoring could make scores fall."""
    game_id = (raw.get("header") or {}).get("id")
    numbered = [(_seq(p, game_id, i), p) for i, p in enumerate(raw.get("plays") or [])]
    numbered.sort(key=lambda pair: pair[0])
    plays = []
    away = home = 0
    for seq, p in numbered:
        team_id = (p.get("team") or {}).get("id")
        text = p.get("text") or ""
        scoring = bool(p.get("scoringPlay"))
        clock = p.get("clock")
        kind = _play_kind(
            (p.get("type") or {}).get("text") or "", text, bool(p.get("shootingPlay")), scoring
        )
        away = max(away, int(_num(p.get("awayScore")) or 0))
        home = max(home, int(_num(p.get("homeScore")) or 0))
        plays.append(
            {
                "id": str(p.get("id") or seq),
                "seq": seq,
                "period": int(_num((p.get("period") or {}).get("number")) or 1),
                "clock": clock.get("displayValue") if isinstance(clock, dict) else None,
                "text": text,
                "team_id": str(team_id) if team_id is not None else None,
                "away_score": away,
                "home_score": home,
                "scoring": scoring,
                "points": int(_num(p.get("scoreValue")) or 0) if scoring else 0,
                "kind": kind,
                "coord": _shot_coord(p.get("coordinate"))
                if kind in ("shot_made", "shot_missed")
                else None,
            }
        )
    return plays


def _espn_possession(raw: dict, comp: dict, team_ids: list[str]) -> str | None:
    for c in comp.get("competitors") or []:
        if c.get("possession") is True:
            team_id = str((c.get("team") or {}).get("id") or c.get("id"))
            if team_id in team_ids:
                return team_id
    for situation in (raw.get("situation"), comp.get("situation")):
        value = situation.get("possession") if isinstance(situation, dict) else None
        if isinstance(value, dict):
            value = value.get("id") or (value.get("team") or {}).get("id")
        if value is not None and str(value) in team_ids:
            return str(value)
    return None


def _free_throw_ends_trip(play: dict[str, Any]) -> bool:
    """True only on the last make of a normal set ("2 of 2"). Older college text has no count,
    so those stay unknown."""
    text = play["text"].lower()
    if any(word in text for word in _FT_KEEPS_BALL):
        return False
    m = _FT_OF_SET.search(text)
    return bool(m) and m.group(1) == m.group(2)


def infer_possession(
    plays: list[dict[str, Any]], team_ids: list[str], period: int | None = None
) -> str | None:
    """Who has the ball after the latest meaningful play, or None if that can't be said honestly.
    Substitutions change nothing, so they're skipped; a missed shot (ball in the air), timeout,
    tip, or foul other than an offensive one is None."""
    for play in reversed(plays):
        if play["kind"] != "substitution":
            break
    else:
        return None
    if period is not None and play["period"] != period:
        return None  # a new period started and its first play hasn't posted yet
    if clock_to_seconds(play["clock"]) == 0:
        return None  # buzzer: the period is over, even if "End Period" hasn't posted yet
    team_id, kind, text = play["team_id"], play["kind"], play["text"].lower()
    if team_id not in team_ids or len(team_ids) != 2:
        return None
    other = team_ids[1] if team_id == team_ids[0] else team_ids[0]
    if kind == "rebound":
        return team_id
    if kind == "other" and _STEAL.search(text):  # college logs steals as their own play
        return team_id
    if kind in ("shot_made", "turnover"):
        return other
    if kind == "foul" and ("offensive foul" in text or "offensive charge" in text):
        return other
    if kind == "free_throw_made" and _free_throw_ends_trip(play):
        return other
    return None


def game_possession(raw: dict, plays: list[dict[str, Any]]) -> dict[str, str] | None:
    """The API's `possession` field: ESPN's value if it sends one, else inferred from plays. Only
    for a game in progress."""
    comp = (raw.get("header", {}).get("competitions") or [{}])[0]
    status = comp.get("status") or {}
    status_type = status.get("type") or {}
    if status_type.get("state") != "in":
        return None
    team_ids = [
        str(c["team"]["id"]) for c in comp.get("competitors") or [] if c.get("team", {}).get("id")
    ]
    espn = _espn_possession(raw, comp, team_ids)
    if espn is not None:
        return {"team_id": espn, "source": "espn"}
    if status_type.get("name") in _BREAK_STATUSES:
        return None
    inferred = infer_possession(plays, team_ids, status.get("period"))
    return {"team_id": inferred, "source": "inferred"} if inferred else None


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
    plays = [] if card["state"] == "pre" else parse_plays(raw)
    return {
        "game": card,
        "teams": team_box,
        "players": by_team,
        "plays": plays,
        "possession": game_possession(raw, plays),
    }


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
