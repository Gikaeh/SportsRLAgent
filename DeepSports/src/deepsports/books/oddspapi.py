"""OddsPapi v4 (https://oddspapi.io/en/docs): fetch one book's pre-match basketball odds and
parse them into side lines. The parser is pure and tested against saved real responses.

Shapes we rely on (saved in tests/fixtures/oddspapi_*):
- /v4/odds-by-tournaments?tournamentIds=132,648&bookmaker=<slug>: a list of fixtures, each with
  participant1Name/participant2Name, tournamentId, statusId (0 = not started), startTime and
  bookmakerOdds[<slug>].markets[<marketId>].outcomes[<outcomeId>].players["0"] =
  {price, priceAmerican, active, mainLine, changedAt}.
- /v4/markets?sportId=11: marketId -> marketType (spreads | totals | moneyline | ...), period
  ("result" = full game incl. overtime), handicap, outcomes [{outcomeId, outcomeName}].
  A spread market's handicap is participant 1's line; outcome "1" is participant 1.
Which participant is home isn't in the payload: `grab` decides that by matching to ESPN games.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from deepsports import config
from deepsports.http import FetchError, PoliteClient

BASE = "https://api.oddspapi.io/v4"
SPORT_ID = 11  # basketball
TOURNAMENTS = {132: "nba", 648: "ncaab"}  # "NBA", "NCAA, Regular Season" (checked 2026-11-14)
MARKET_TYPES = {"spreads": "spread", "totals": "total", "moneyline": "moneyline"}
# Each odds-by-tournaments call costs 1 of the free tier's 250 monthly requests. The documented
# per-endpoint cooldowns are 0.5-2 s; 2.5 s between calls keeps us clear of them.
MIN_INTERVAL = 2.5

# httpx logs request URLs at INFO, and ours carry the key as a query parameter.
logging.getLogger("httpx").setLevel(logging.WARNING)


class OddsPapiError(RuntimeError):
    """A fetch failed. The message never contains the key."""


def read_key(path=None) -> str:
    p = path or config.ODDSPAPI_KEY_FILE
    try:
        key = p.read_text().strip()
    except OSError as e:
        raise OddsPapiError(f"no OddsPapi key at {p} ({type(e).__name__})") from None
    if not key:
        raise OddsPapiError(f"OddsPapi key file {p} is empty")
    return key


def _get(client: PoliteClient, key: str, path: str, params: dict, cache_key: str, cache_ok=None):
    try:
        return client.get_json(
            f"{BASE}/{path}", {**params, "apiKey": key}, cache_key=cache_key, cache_ok=cache_ok
        )
    except FetchError as e:
        raise OddsPapiError(str(e).replace(key, "***")) from None  # FetchError quotes the params


def fetch_markets(client: PoliteClient, key: str, refresh: bool = False) -> list[dict]:
    """The basketball market catalogue (1 request; cached, refetched only when asked)."""
    ok = None if refresh else (lambda d: isinstance(d, list) and len(d) > 0)
    return _get(client, key, "markets", {"sportId": SPORT_ID}, "markets-basketball", ok)


def fetch_book(client: PoliteClient, key: str, slug: str, cache_key: str) -> list[dict]:
    """Every not-started NBA + NCAAB fixture with this book's odds (1 request)."""
    params = {"tournamentIds": ",".join(map(str, TOURNAMENTS)), "bookmaker": slug, "verbosity": 3}
    data = _get(client, key, "odds-by-tournaments", params, cache_key)
    if not isinstance(data, list):
        raise OddsPapiError(f"odds-by-tournaments for {slug}: unexpected {type(data).__name__}")
    return data


# ---------- pure ----------


def market_index(markets: Sequence[Mapping[str, Any]]) -> dict[int, dict]:
    """marketId -> {type, handicap, outcomes: {outcomeId: name}} for full-game sides only."""
    out = {}
    for m in markets:
        mtype = MARKET_TYPES.get(m.get("marketType"))
        if mtype is None or m.get("period") != "result" or m.get("playerProp"):
            continue
        out[int(m["marketId"])] = {
            "type": mtype,
            "handicap": m.get("handicap"),
            "outcomes": {int(o["outcomeId"]): str(o["outcomeName"]) for o in m["outcomes"]},
        }
    return out


def unknown_markets(
    fixtures: Sequence[Mapping[str, Any]], slug: str, markets: Sequence[Mapping[str, Any]]
) -> int:
    """How many market ids in the payload aren't in the catalogue (0 = no refresh needed)."""
    known = {int(m["marketId"]) for m in markets}
    seen = {
        int(mid)
        for f in fixtures
        for mid in (((f.get("bookmakerOdds") or {}).get(slug) or {}).get("markets") or {})
    }
    return len(seen - known)


def _american(p: Mapping[str, Any]) -> int | None:
    try:
        n = int(str(p.get("priceAmerican")).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return n if 100 <= abs(n) <= 100_000 else None


def parse_fixtures(
    fixtures: Sequence[Mapping[str, Any]], slug: str, index: Mapping[int, Mapping]
) -> list[dict[str, Any]]:
    """Active main-line full-game sides, one per (fixture, market, outcome):
    {fixture_id, league, start_time, p1, p2, market, who ("1" | "2" | "over" | "under"),
    line (from that side's view; None for a moneyline), price (American int)}.
    Skips started fixtures, suspended books, pulled prices and alternate lines. When a book shows
    two main lines for the same side, the most recently changed one wins."""
    best: dict[tuple, tuple[str, dict]] = {}
    for f in fixtures:
        league = TOURNAMENTS.get(f.get("tournamentId"))
        bo = (f.get("bookmakerOdds") or {}).get(slug)
        if league is None or f.get("statusId") != 0 or not bo or bo.get("suspended"):
            continue
        for mid, mk in (bo.get("markets") or {}).items():
            m = index.get(int(mid))
            if m is None or mk.get("marketActive") is False:
                continue
            for oid, oc in (mk.get("outcomes") or {}).items():
                p = ((oc or {}).get("players") or {}).get("0") or {}
                name = m["outcomes"].get(int(oid))
                price = _american(p)
                if not p.get("active") or not p.get("mainLine") or name is None or price is None:
                    continue
                who = name.lower() if m["type"] == "total" else name
                if who not in ("1", "2", "over", "under"):
                    continue
                h = m["handicap"]
                line = None
                if m["type"] == "spread":
                    line = float(h) if who == "1" else -float(h)
                elif m["type"] == "total":
                    line = float(h)
                row = {
                    "fixture_id": f["fixtureId"],
                    "league": league,
                    "start_time": f.get("startTime"),
                    "p1": f.get("participant1Name"),
                    "p2": f.get("participant2Name"),
                    "market": m["type"],
                    "who": who,
                    "line": line,
                    "price": price,
                }
                k = (f["fixtureId"], m["type"], who)
                changed = str(p.get("changedAt") or "")
                if k not in best or changed > best[k][0]:
                    best[k] = (changed, row)
    return [row for _, row in best.values()]
