"""Lines-only helpers for the et-v2 backtest on The Odds API history
(`docs/results/2026-11-23-et-v2-preregistration.md`): which cached snapshot belongs to a game and
time, each book's full-game total in it, matching Odds API events to ESPN game ids, and the
line-agreement summary used by the sanity report. Pure apart from `load_snapshot`.

Nothing here reads scores or results. Phase 2 (scoring) reuses these to pick the line L at T.

Notes on the data (seen in the 2026-11-23 pull):
- A snapshot also lists games already in progress (live in-play lines). Only events with
  `commence_time` after the snapshot timestamp are pre-game quotes; `book_totals` drops the rest.
- Team names are the vendor's ("Boston Univ. Terriers", "Loyola (Chi) Ramblers",
  "San José St Spartans"); they are matched to ESPN teams with `circa.match.side_score` after
  accent folding plus the `ALIASES` table, both teams required, start within 3 h.
"""

from __future__ import annotations

import gzip
import json
import statistics
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from deepsports.circa.match import side_score
from deepsports.store import SANE_LIMITS

PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")
# The pulled request times: (day offset from the ESPN game day D, Pacific wall time).
TIMES: dict[str, tuple[int, time]] = {
    "-1@15:00": (-1, time(15, 0)),
    "-1@18:00": (-1, time(18, 0)),
    "-1@21:00": (-1, time(21, 0)),
    "0@09:00": (0, time(9, 0)),
}
T_KEY = "-1@21:00"  # the log time T
MAX_MATCH_GAP = timedelta(hours=3)
SNAPSHOT_TOLERANCE = timedelta(minutes=30)
MIN_LEAD = timedelta(minutes=60)  # games must tip >= T + 60 min

# Vendor names that the generic scorer misses or gets wrong: vendor name -> ESPN display_name.
# Filled from the 2026-11-23 sanity run's unmatched list (see the sanity report).
ALIASES: dict[str, str] = {
    # school renames: the vendor keeps the old name, ESPN's teams table has the current one
    "Fort Wayne Mastodons": "Purdue Fort Wayne Mastodons",
    "Appalachian St Mountaineers": "App State Mountaineers",
    "Arkansas-Little Rock Trojans": "Little Rock Trojans",
    "UMKC Kangaroos": "Kansas City Roos",
    "Texas A&M-CC Islanders": "Texas A&M-Corpus Christi Islanders",
    "Texas A&M-Commerce Lions": "East Texas A&M Lions",
    "Houston Baptist Huskies": "Houston Christian Huskies",
    "Dixie State Trailblazers": "Utah Tech Trailblazers",
    "Mcneese St Mcneese": "McNeese Cowboys",
}


def ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


# ---------------------------------------------------------------- time


def game_day(start_utc: datetime) -> date:
    """ESPN's game day: the US/Eastern date of the tip."""
    return start_utc.astimezone(ET).date()


def requested_ts(day: date, key: str) -> datetime:
    """UTC request time of snapshot `key` for game day `day` (DST-aware)."""
    off, t = TIMES[key]
    return datetime.combine(day + timedelta(days=off), t, tzinfo=PT).astimezone(UTC)


def log_time(day: date) -> datetime:
    return requested_ts(day, T_KEY)


def file_stamp(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def snapshot_path(combo_dir: Path, day: date, key: str) -> Path:
    return combo_dir / f"{file_stamp(requested_ts(day, key))}.json.gz"


def load_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def timestamp_ok(requested: datetime, snapshot: datetime | None) -> bool:
    """The returned snapshot is at or before the request and at most 30 min earlier."""
    return snapshot is not None and requested - SNAPSHOT_TOLERANCE <= snapshot <= requested


# ---------------------------------------------------------------- totals


def sane_total(v: float | None, league: str = "ncaab") -> float | None:
    lim = SANE_LIMITS.get(league)
    if v is None or lim is None:
        return v
    return v if lim[1] <= v <= lim[2] else None


def book_totals(resp: Mapping[str, Any], pregame_only: bool = True) -> list[dict[str, Any]]:
    """One row per event x book with a totals market: the over's point as `point` (None when
    over and under disagree), both prices, the market's last_update, the snapshot time.
    In-play events (commence_time <= snapshot) are dropped when `pregame_only`."""
    snap = ts(resp.get("timestamp"))
    out = []
    for ev in resp.get("data") or []:
        start = ts(ev.get("commence_time"))
        if pregame_only and (start is None or snap is None or start <= snap):
            continue
        for bk in ev.get("bookmakers") or []:
            for mk in bk.get("markets") or []:
                if mk.get("key") != "totals":
                    continue
                by = {(o.get("name") or "").lower(): o for o in mk.get("outcomes") or []}
                ov, un = by.get("over"), by.get("under")
                if ov is None and un is None:
                    continue
                po = ov.get("point") if ov else None
                pu = un.get("point") if un else None
                consistent = po is not None and po == pu
                out.append(
                    {
                        "snapshot_ts": snap,
                        "event_id": ev.get("id"),
                        "commence_time": start,
                        "home_team": ev.get("home_team"),
                        "away_team": ev.get("away_team"),
                        "book": bk.get("key"),
                        "last_update": ts(mk.get("last_update")) or ts(bk.get("last_update")),
                        "point": float(po) if consistent else None,
                        "over_price": ov.get("price") if ov else None,
                        "under_price": un.get("price") if un else None,
                        "consistent": consistent,
                    }
                )
    return out


def events(resp: Mapping[str, Any], pregame_only: bool = True) -> list[dict[str, Any]]:
    """Unique events of a snapshot (id, commence_time, home_team, away_team)."""
    snap = ts(resp.get("timestamp"))
    out = []
    for ev in resp.get("data") or []:
        start = ts(ev.get("commence_time"))
        if pregame_only and (start is None or snap is None or start <= snap):
            continue
        out.append(
            {
                "event_id": ev.get("id"),
                "commence_time": start,
                "home_team": ev.get("home_team"),
                "away_team": ev.get("away_team"),
            }
        )
    return out


# ---------------------------------------------------------------- matching


def fold(name: str) -> str:
    """Accents off ("San José" -> "San Jose"), '(Chi)' style qualifiers kept as words."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.replace("(", " ").replace(")", " ")


def team_score(vendor: str, team: Mapping[str, Any]) -> float:
    """2 exact alias, 1 close, 0 no match (`circa.match.side_score` on folded names).
    `team` has abbr, display_name, location, name."""
    alias = ALIASES.get(vendor)
    if alias is not None:
        return 3.0 if alias == team.get("display_name") else 0.0
    folded = {k: fold(v) if isinstance(v, str) else v for k, v in team.items()}
    return side_score(fold(vendor), folded)


def match_event(
    event: Mapping[str, Any], games: Sequence[Mapping[str, Any]], max_gap: timedelta = MAX_MATCH_GAP
) -> tuple[str | None, bool]:
    """(game_id, swapped) of the one ESPN game whose two teams both match and whose start is
    within `max_gap` of the event's commence_time; (None, False) if none or ambiguous.
    games: game_id, start_time_utc, home, away (team dicts)."""
    start = event["commence_time"]
    scored = []
    for g in games:
        if abs(g["start_time_utc"] - start) > max_gap:
            continue
        straight = (
            team_score(event["home_team"], g["home"]),
            team_score(event["away_team"], g["away"]),
        )
        flipped = (
            team_score(event["home_team"], g["away"]),
            team_score(event["away_team"], g["home"]),
        )
        for pair, swapped in ((straight, False), (flipped, True)):
            if min(pair) > 0:
                gap = abs((g["start_time_utc"] - start).total_seconds())
                scored.append((-sum(pair), gap, swapped, g["game_id"]))
    if not scored:
        return None, False
    scored.sort()
    best = scored[0]
    if len(scored) > 1 and scored[1][:2] == best[:2] and scored[1][3] != best[3]:
        return None, False
    return best[3], best[2]


# ---------------------------------------------------------------- agreement


def agreement(pairs: Iterable[tuple[float, float]]) -> dict[str, Any]:
    """a - b over pairs: n, mean, mean abs, share identical, share |diff| > 2."""
    diffs = [a - b for a, b in pairs if a is not None and b is not None]
    if not diffs:
        return {"n": 0, "mean": None, "mean_abs": None, "identical": None, "gt2": None}
    n = len(diffs)
    return {
        "n": n,
        "mean": statistics.fmean(diffs),
        "mean_abs": statistics.fmean(abs(d) for d in diffs),
        "identical": sum(d == 0 for d in diffs) / n,
        "gt2": sum(abs(d) > 2 for d in diffs) / n,
    }


def grading_book(wh_share: float | None, dk_share: float | None, floor: float = 0.60) -> str | None:
    """Pre-registered 60% rule: WH if it covers >= 60%, else DraftKings if it does, else None
    (season dropped)."""
    if wh_share is not None and wh_share >= floor:
        return "williamhill_us"
    if dk_share is not None and dk_share >= floor:
        return "draftkings"
    return None
