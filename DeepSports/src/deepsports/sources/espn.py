"""ESPN public site + core APIs for basketball leagues (NBA, men's college). See
docs/DATA_SOURCES.md."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from deepsports.http import PoliteClient

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues"
FINISHED_STATES = {"post"}  # final, postponed, canceled all report state "post"


@dataclass(frozen=True)
class League:
    code: str  # our league key: games.league, teams.league, raw cache prefix, calendar key
    slug: str  # ESPN's path segment
    label: str
    scoreboard_params: dict[str, Any] = field(default_factory=dict)
    teams_params: dict[str, Any] = field(default_factory=dict)
    # Also add scoreboard opponents missing from the league's team list (non-D1 schools), so
    # every game can be displayed. NBA scoreboards only add All-Star/exhibition teams: skipped.
    discover_teams: bool = False
    # (month, day) bounds of a season label like 2025-26: start in the first year, end in the next
    season_start: tuple[int, int] = (10, 1)
    season_end: tuple[int, int] = (6, 30)


LEAGUES: dict[str, League] = {
    "nba": League("nba", "nba", "NBA"),
    "ncaab": League(
        "ncaab",
        "mens-college-basketball",
        "NCAA men's D1",
        scoreboard_params={"groups": 50},  # 50 = all of Division I (default is a top-25 subset)
        teams_params={"limit": 1000},  # default page is 50 teams
        discover_teams=True,
        season_start=(11, 1),
        season_end=(4, 15),
    ),
}
_ALIASES = {"mens-college-basketball": "ncaab", "ncaam": "ncaab", "cbb": "ncaab"}


def get_league(name: str) -> League:
    key = _ALIASES.get(name, name)
    if key not in LEAGUES:
        raise ValueError(f"unknown league {name!r}; expected one of {sorted(LEAGUES)}")
    return LEAGUES[key]


def _scoreboard_settled(raw: dict) -> bool:
    """A day's scoreboard can be reused from cache once every game on it is over."""
    events = raw.get("events", [])
    return all(e["status"]["type"]["state"] in FINISHED_STATES for e in events)


def _summary_settled(raw: dict) -> bool:
    comps = raw.get("header", {}).get("competitions", [])
    return bool(comps) and comps[0]["status"]["type"].get("completed", False)


class EspnBasketball:
    def __init__(self, client: PoliteClient, league: str = "nba"):
        self.client = client
        self.spec = get_league(league)
        self.league = self.spec.code
        self.base = f"{SITE}/{self.spec.slug}"
        self.core = f"{CORE}/{self.spec.slug}"

    def _key(self, *parts: str) -> str:
        return "/".join(("espn", self.league, *parts))

    def teams(self) -> dict[str, Any]:
        return self.client.get_json(
            f"{self.base}/teams", self.spec.teams_params or None, cache_key=self._key("teams")
        )

    def scoreboard(self, day: date, refresh: bool = False) -> dict[str, Any]:
        """All games on one US/Eastern game day. ESPN rejects date ranges."""
        ymd = day.strftime("%Y%m%d")
        return self.client.get_json(
            f"{self.base}/scoreboard",
            {"dates": ymd, **self.spec.scoreboard_params, "limit": 1000},
            cache_key=self._key("scoreboard", ymd),
            cache_ok=None if refresh else _scoreboard_settled,
        )

    def summary(self, event_id: str, refresh: bool = False) -> dict[str, Any]:
        """Box score, closing odds, injuries, and more for one game."""
        return self.client.get_json(
            f"{self.base}/summary",
            {"event": event_id},
            cache_key=self._key("summary", event_id),
            cache_ok=None if refresh else _summary_settled,
        )

    def summary_snapshot(self, event_id: str, captured_at: datetime) -> dict[str, Any]:
        """Always-fresh summary for a game that hasn't started (for its injury report). Saved
        under its own timestamped key so later fetches of the same game don't overwrite it."""
        ts = captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        return self.client.get_json(
            f"{self.base}/summary",
            {"event": event_id},
            cache_key=self._key("summary_pregame", event_id, ts),
            cache_ok=None,
        )

    def core_odds(self, event_id: str, refresh: bool = False) -> dict[str, Any]:
        """Per-sportsbook odds with open/close lines (ESPN core API). Covers seasons where
        the summary's `pickcenter` is empty. Only call this for completed games: the result is
        cached forever."""
        return self.client.get_json(
            f"{self.core}/events/{event_id}/competitions/{event_id}/odds",
            {"limit": 100},
            cache_key=self._key("core_odds", event_id),
            cache_ok=None if refresh else (lambda raw: True),
        )
