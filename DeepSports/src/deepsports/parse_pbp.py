"""Pure parser: raw ESPN game summary (NBA + college) -> play-by-play events.

`parse_summary(raw, league)` turns a raw ESPN summary JSON dict (the decompressed content of a
cached `data/raw/espn/{nba,ncaab}/summary/{game_id}.json.gz`; load one with
`deepsports.analysis.betting.read_raw_summary`) into game metadata plus a list of event dicts.
No I/O, stdlib only; tested against trimmed real summaries in tests/fixtures/. Ported from the
DeepSeek edge study (collab/deepseek/lab/pbp.py: 13.6k games parsed, 0 failures). Nothing is
stored in the warehouse yet: callers parse on demand.

Learned schema notes (verified on real files, 2021-2025 NBA + 2025-26 college):

- `plays` is present in ~100% of NBA and 99.7% of college summaries; a few
  college files have `plays == []` (parser returns no events).
- Plays in the JSON list are NOT always in chronological order. The true order
  is by `sequenceNumber` (falls back to the numeric suffix of `id`).
- Score fields on a play (`homeScore`/`awayScore`) are the cumulative score
  AFTER that play, in true sequence order. Sum of `scoreValue` over
  `scoringPlay == true` plays equals the final total score (validated).
  HOWEVER the per-play annotations are occasionally stale (a play or two
  behind; ~1.3% of NBA events, ~2.6% of college events dip in seq order).
  `parse_summary` therefore applies a running-max fixup (cumulative scores
  can only increase) and anchors the last event to the header's final score.
- NBA: `made` == `scoringPlay`; `scoreValue` is 2/3 on makes, 0 on misses;
  `pointsAttempted` is always 0. Shot value of a missed NBA shot must be
  inferred: text contains "two" -> 2, text contains "three" or distance
  >= 24.5 ft -> 3 (validated against made shots; see test).
- College: `scoreValue` and `pointsAttempted` both carry the shot's point
  value (2/3, or 1 for free throws) whether made or missed; `made` is still
  `scoringPlay`. Missed college free throws can carry type text
  "MadeFreeThrow" — trust `scoringPlay`, not the type text.
- Coordinates are in feet: x in [0, 50] across the court (hoop line at x=25),
  y in [0, ~47] from the baseline (hoop at y=0); shot distance in feet =
  hypot(x - 25, y). Negative coordinates (-214748340 etc.) are sentinels for
  "missing" and become None.
- Clock: `clock.displayValue` "MM:SS" = time REMAINING in the period. Period
  lengths come from `format` (NBA regulation 4 x 720 s, OT 300 s; college
  regulation 2 x 1200 s, OT 300 s). NBA OT periods have `period.number` >= 5;
  college OT periods have number >= 3.
- `boxscore.players` is a list of two team blocks (team id + statistics[0]
  with `athletes` and `keys`). Stats arrays align with `keys`; minutes are
  strings ("20" or "31:00" or "").

Output schema
-------------
parse_summary returns::

    {
      "game_id": str | None,
      "home_team_id": str | None, "away_team_id": str | None,
      "home_score": int | None, "away_score": int | None,   # final, from header
      "start_time_utc": str | None,        # competitions[0].date (ISO 8601)
      "neutral_site": bool | None,
      "conference_competition": bool | None,   # college only
      "regulation_periods": int, "regulation_clock": float, "overtime_clock": float,
      "events": [event, ...],   # sorted by seq, chronological
      "players": [player, ...],
    }

Event fields::

    seq            int       play order (sequenceNumber)
    period         int       period number (1-based)
    clock          str|None  raw clock display ("12:00")
    clock_sec      float|None  seconds REMAINING in the period
    team_id        str|None  team the play belongs to (offense for shots)
    event_type     str       one of JUMPBALL SHOT FREETHROW REBOUND TURNOVER
                             SUBSTITUTION FOUL TIMEOUT ENDPERIOD ENDGAME OTHER
    subtype        str       original type.text
    made           bool|None shot/free-throw result (scoringPlay)
    points         int       points scored on this play (0 for non-scoring)
    shot_value     int|None  1/2/3 point value of a shot or free throw
    x, y           float|None  shot coordinate in feet
    distance       float|None  shot distance from the hoop in feet
    player_ids     list[str] participants' athlete ids
    home_score     int|None  cumulative home score AFTER this play
    away_score     int|None  cumulative away score AFTER this play
    text           str       play text
    wallclock      str|None  absolute timestamp

Player fields::

    team_id, player_id, name, minutes (float, None if unparseable),
    points (int), starter (bool), did_not_play (bool), ejected (bool)

Utilities: `clock_to_seconds`, `garbage_time` (pure helper: boolean array of
garbage stretches per the pre-registered rule).
"""

from __future__ import annotations

import contextlib
import math
import re
from typing import Any

__all__ = [
    "EVENT_TYPES",
    "clock_to_seconds",
    "garbage_time",
    "parse_events",
    "parse_players",
    "parse_summary",
    "shot_distance",
    "shot_value_nba",
]

EVENT_TYPES = (
    "JUMPBALL",
    "SHOT",
    "FREETHROW",
    "REBOUND",
    "TURNOVER",
    "SUBSTITUTION",
    "FOUL",
    "TIMEOUT",
    "ENDPERIOD",
    "ENDGAME",
    "OTHER",
)

#: NBA: lead >= 20 in the last 12 min of regulation (the whole 4th quarter) or OT.
#: College: lead >= 25 anywhere in the 2nd half or OT.
GARBAGE = {
    "nba": {"min_period": 4, "lead": 20},
    "ncaab": {"min_period": 2, "lead": 25},
}

_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})(?:\.\d+)?$")
_CLOCK_DEC_RE = re.compile(r"^\d+(?:\.\d+)?$")


def clock_to_seconds(display: Any) -> float | None:
    """'MM:SS' (or decimal 'SS.s') clock display -> seconds remaining.
    None when unparseable."""
    if not isinstance(display, str):
        return None
    s = display.strip()
    m = _CLOCK_RE.match(s)
    if m:
        return float(int(m.group(1)) * 60 + int(m.group(2)))
    # Sub-second displays in the final second of a period ("0.9", "56.8").
    if _CLOCK_DEC_RE.match(s):
        return float(s)
    return None


def shot_distance(x: Any, y: Any) -> float | None:
    """ESPN feet coordinates -> distance from the hoop (hoop at x=25, y=0).
    Negative coordinates are ESPN's 'missing' sentinel -> None."""
    if x is None or y is None:
        return None
    try:
        xf, yf = float(x), float(y)
    except (TypeError, ValueError):
        return None
    if xf < 0 or yf < 0:
        return None
    return math.hypot(xf - 25.0, yf)


def shot_value_nba(text: str, distance: float | None) -> int:
    """Point value (2 or 3) of an NBA shot whose scoreValue is 0 (misses).
    Validated against made shots: "two" in text -> 2; "three" in text or
    distance >= 24.5 ft -> 3; else 2."""
    t = text.lower()
    if "two" in t:
        return 2
    if "three" in t or (distance is not None and distance >= 24.5):
        return 3
    return 2


def _classify(subtype: str, shooting_play: bool) -> str:
    t = subtype.lower()
    if t in ("jumpball", "jump ball"):
        return "JUMPBALL"
    if t == "substitution":
        return "SUBSTITUTION"
    if t == "end period":
        return "ENDPERIOD"
    if t == "end game":
        return "ENDGAME"
    if "free throw" in t or "freethrow" in t:
        return "FREETHROW"
    if "rebound" in t:
        return "REBOUND"
    if "turnover" in t:
        return "TURNOVER"
    if "foul" in t:
        return "FOUL"
    if "timeout" in t:
        return "TIMEOUT"
    if shooting_play:
        return "SHOT"
    return "OTHER"


def _seq(raw_play: dict[str, Any], game_id: str | None, index: int) -> int:
    """True play order: sequenceNumber, else id suffix, else list index."""
    sn = raw_play.get("sequenceNumber")
    if sn is not None:
        try:
            return int(sn)
        except (TypeError, ValueError):
            pass
    pid = raw_play.get("id")
    if isinstance(pid, str) and game_id and pid.startswith(game_id):
        try:
            return int(pid[len(game_id) :])
        except ValueError:
            pass
    return index


def _player_ids(raw_play: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for part in raw_play.get("participants") or []:
        ath = part.get("athlete") if isinstance(part, dict) else None
        if isinstance(ath, dict) and ath.get("id") is not None:
            out.append(str(ath["id"]))
    return out


def parse_events(raw_plays: list[dict[str, Any]], game_id: str | None) -> list[dict[str, Any]]:
    """Normalize the raw `plays` list into chronological event dicts."""
    indexed = [(_seq(p, game_id, i), p) for i, p in enumerate(raw_plays)]
    indexed.sort(key=lambda pair: pair[0])
    events: list[dict[str, Any]] = []
    for seq, p in indexed:
        period = p.get("period") or {}
        try:
            period_num = int(period.get("number", 1))
        except (TypeError, ValueError):
            period_num = 1
        clock_dict = p.get("clock") or {}
        clock = clock_dict.get("displayValue") if isinstance(clock_dict, dict) else None
        team = p.get("team") or {}
        team_id = str(team.get("id")) if team.get("id") is not None else None
        subtype = (p.get("type") or {}).get("text") or ""
        shooting = bool(p.get("shootingPlay"))
        scoring = bool(p.get("scoringPlay"))
        event_type = _classify(subtype, shooting)
        made = scoring if event_type in ("SHOT", "FREETHROW") else None
        points = int(p.get("scoreValue") or 0) if scoring else 0
        coord = p.get("coordinate") or {}
        x = y = None
        if isinstance(coord, dict):
            x = coord.get("x")
            y = coord.get("y")
        dist = shot_distance(x, y) if event_type == "SHOT" else None
        sv = None
        if event_type == "SHOT":
            attempted = p.get("pointsAttempted")
            scored = p.get("scoreValue")
            if attempted and int(attempted) in (2, 3):
                sv = int(attempted)
            elif scored and int(scored) in (2, 3):
                sv = int(scored)
            else:  # NBA misses carry neither: infer from text/distance
                sv = shot_value_nba(p.get("text") or "", dist)
        elif event_type == "FREETHROW":
            sv = 1
        try:
            hs = int(p.get("homeScore")) if p.get("homeScore") is not None else None
        except (TypeError, ValueError):
            hs = None
        try:
            aws = int(p.get("awayScore")) if p.get("awayScore") is not None else None
        except (TypeError, ValueError):
            aws = None
        events.append(
            {
                "seq": seq,
                "period": period_num,
                "clock": clock,
                "clock_sec": clock_to_seconds(clock),
                "team_id": team_id,
                "event_type": event_type,
                "subtype": subtype,
                "made": made,
                "points": points,
                "shot_value": sv,
                "x": x,
                "y": y,
                "distance": dist,
                "player_ids": _player_ids(p),
                "home_score": hs,
                "away_score": aws,
                "text": p.get("text") or "",
                "wallclock": p.get("wallclock"),
            }
        )
    return events


def _minutes(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if ":" in s:
        try:
            mm, ss = s.split(":", 1)
            return float(int(mm)) + float(ss) / 60.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_players(boxscore: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten boxscore.players into per-player rows (empty list when absent)."""
    if not isinstance(boxscore, dict):
        return []
    out: list[dict[str, Any]] = []
    for team_block in boxscore.get("players") or []:
        team = team_block.get("team") or {}
        team_id = str(team.get("id")) if team.get("id") is not None else None
        stats_list = team_block.get("statistics") or []
        if not stats_list or not isinstance(stats_list, list):
            continue
        stats = stats_list[0]
        if not isinstance(stats, dict):
            continue
        keys = stats.get("keys") or []
        athletes = stats.get("athletes") or []
        for a in athletes:
            if not isinstance(a, dict):
                continue
            ath = a.get("athlete") or {}
            values = a.get("stats") or []
            row: dict[str, Any] = {
                "team_id": team_id,
                "player_id": str(ath.get("id")) if ath.get("id") is not None else None,
                "name": ath.get("displayName"),
                "minutes": None,
                "points": None,
                "starter": bool(a.get("starter")),
                "did_not_play": bool(a.get("didNotPlay")),
                "ejected": bool(a.get("ejected")),
            }
            for k, v in zip(keys, values, strict=False):
                if k == "minutes":
                    row["minutes"] = _minutes(v)
                elif k == "points":
                    with contextlib.suppress(TypeError, ValueError):
                        row["points"] = int(v)
            out.append(row)
    return out


def _fixup_scores(
    events: list[dict[str, Any]], home_final: int | None, away_final: int | None
) -> None:
    """Repair stale cumulative-score annotations in place: running max (scores
    can only increase), then anchor the last event to the header final score."""
    ph = pa = 0
    for e in events:
        hs, aws = e.get("home_score"), e.get("away_score")
        if hs is not None:
            ph = max(ph, int(hs))
            e["home_score"] = ph
        if aws is not None:
            pa = max(pa, int(aws))
            e["away_score"] = pa
    if events:
        last = events[-1]
        if home_final is not None:
            last["home_score"] = home_final
        if away_final is not None:
            last["away_score"] = away_final


def parse_summary(raw: dict[str, Any], league: str = "nba") -> dict[str, Any]:
    """Parse one raw ESPN summary JSON dict. See the module docstring."""
    competitions = ((raw.get("header") or {}).get("competitions")) or []
    comp = competitions[0] if competitions else {}
    game_id = str(comp.get("id")) if comp.get("id") is not None else None
    home_id = away_id = None
    home_score = away_score = None
    start_time = None
    neutral = None
    conference = None
    for competition in competitions:
        if start_time is None:
            start_time = competition.get("date")
        if neutral is None:
            neutral = competition.get("neutralSite")
        if conference is None:
            conference = competition.get("conferenceCompetition")
        for c in competition.get("competitors") or []:
            ha = c.get("homeAway")
            tid = c.get("id")
            score = c.get("score")
            try:
                score_int = int(score) if score is not None else None
            except (TypeError, ValueError):
                score_int = None
            if ha == "home":
                home_id = str(tid) if tid is not None else None
                home_score = score_int
            elif ha == "away":
                away_id = str(tid) if tid is not None else None
                away_score = score_int

    fmt = raw.get("format") or {}
    reg = fmt.get("regulation") or {}
    ot = fmt.get("overtime") or {}
    regulation_periods = int(reg.get("periods", 4 if league == "nba" else 2))
    regulation_clock = float(reg.get("clock", 720.0 if league == "nba" else 1200.0))
    overtime_clock = float(ot.get("clock", 300.0))

    raw_plays = raw.get("plays") or []
    events = parse_events(raw_plays, game_id)
    _fixup_scores(events, home_score, away_score)
    players = parse_players(raw.get("boxscore"))

    return {
        "game_id": game_id,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_score": home_score,
        "away_score": away_score,
        "start_time_utc": start_time,
        "neutral_site": neutral,
        "conference_competition": conference,
        "regulation_periods": regulation_periods,
        "regulation_clock": regulation_clock,
        "overtime_clock": overtime_clock,
        "events": events,
        "players": players,
    }


def garbage_time(events: list[dict[str, Any]], league: str) -> list[bool]:
    """Per-event garbage-stretch mask per the pre-registered rule.

    NBA: lead >= 20 while in the 4th quarter or later (last 12 min of
    regulation) or OT. College: lead >= 25 while in the 2nd half or OT.
    Returns a list of bools aligned with `events` (chronological).
    """
    rule = GARBAGE.get(league)
    if rule is None:
        raise ValueError(f"unknown league {league!r}")
    min_period, lead_thr = rule["min_period"], rule["lead"]
    out: list[bool] = []
    prev_home = prev_away = 0
    for ev in events:
        hs = ev.get("home_score")
        aws = ev.get("away_score")
        if hs is not None and aws is not None:
            prev_home, prev_away = hs, aws
        lead = abs(prev_home - prev_away)
        is_garbage = (ev["period"] >= min_period) and (lead >= lead_thr)
        out.append(is_garbage)
    return out
