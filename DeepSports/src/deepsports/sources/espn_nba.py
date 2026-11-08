"""ESPN NBA source: a thin alias of the league-parameterized `sources.espn` module, kept so
existing imports keep working."""

from deepsports.http import PoliteClient
from deepsports.sources.espn import CORE as _CORE
from deepsports.sources.espn import FINISHED_STATES, EspnBasketball, _scoreboard_settled
from deepsports.sources.espn import SITE as _SITE

BASE = f"{_SITE}/nba"
CORE = f"{_CORE}/nba"
LEAGUE = "nba"

__all__ = ["BASE", "CORE", "FINISHED_STATES", "LEAGUE", "EspnNba", "_scoreboard_settled"]


class EspnNba(EspnBasketball):
    def __init__(self, client: PoliteClient):
        super().__init__(client, "nba")
