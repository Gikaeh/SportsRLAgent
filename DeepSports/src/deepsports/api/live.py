"""Live data from ESPN with a short in-memory TTL. Never writes to DuckDB.

TTL is 30s while any game on the day is in progress, 5 minutes otherwise, so polling from
any number of phones/glasses costs at most ~2 ESPN requests a minute per day viewed.
One PoliteClient is shared by all leagues, so the 1 req/s limit holds across them.
"""

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any

from deepsports import config
from deepsports.http import PoliteClient
from deepsports.sources.espn import EspnBasketball

LIVE_TTL = 30
IDLE_TTL = 300
LEAGUES = ("nba", "ncaab")


def _any_live(events: list[dict]) -> bool:
    return any(e["status"]["type"]["state"] == "in" for e in events)


class UnknownLeague(ValueError):
    pass


class LiveService:
    def __init__(
        self,
        src: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        sources: dict[str, Any] | None = None,
    ):
        """`src` (back-compat) is the NBA source; `sources` maps league -> source. Leagues
        without an explicit source are built lazily on a shared client."""
        self._sources: dict[str, Any] = dict(sources or {})
        if src is not None:
            self._sources.setdefault("nba", src)
        self._client: PoliteClient | None = None
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}

    @property
    def src(self) -> Any:  # back-compat: the NBA source
        return self.source("nba")

    def source(self, league: str) -> Any:
        if league not in LEAGUES:
            raise UnknownLeague(league)
        if league not in self._sources:
            if self._client is None:
                self._client = PoliteClient(raw_dir=config.LIVE_CACHE_DIR)
            self._sources[league] = EspnBasketball(self._client, league)
        return self._sources[league]

    def _get(self, key: str, fetch: Callable[[], Any], ttl_for: Callable[[Any], int]) -> Any:
        with self._lock:  # also serializes ESPN requests (PoliteClient isn't thread-safe)
            hit = self._cache.get(key)
            if hit and hit[0] > self._clock():
                return hit[1]
            data = fetch()
            self._cache[key] = (self._clock() + ttl_for(data), data)
            return data

    def scoreboard(self, day: date, league: str = "nba") -> dict:
        src = self.source(league)
        return self._get(
            f"sb:{league}:{day.isoformat()}",
            lambda: src.scoreboard(day, refresh=True),
            lambda raw: LIVE_TTL if _any_live(raw.get("events", [])) else IDLE_TTL,
        )

    def summary(self, game_id: str, league: str = "nba") -> dict:
        src = self.source(league)

        def ttl(raw: dict) -> int:
            comp = (raw.get("header", {}).get("competitions") or [{}])[0]
            state = comp.get("status", {}).get("type", {}).get("state")
            return LIVE_TTL if state == "in" else IDLE_TTL

        # completed games come from the on-disk raw cache (src.summary's cache rule)
        return self._get(f"sum:{league}:{game_id}", lambda: src.summary(game_id), ttl)

    @staticmethod
    def refresh_seconds(live: bool) -> int:
        return LIVE_TTL if live else IDLE_TTL
