"""The Odds API v4 historical odds (https://the-odds-api.com/liveapi/guides/v4/): plan the
snapshot timestamps, fetch them politely with a credit reserve, cache each response, and parse a
snapshot into one row per bookmaker outcome. The planner and the parser are pure.

Shapes we rely on:
- GET /v4/historical/sports/{sport}/odds?regions=..&markets=..&oddsFormat=american&date=<ISO>
  returns {"timestamp", "previous_timestamp", "next_timestamp", "data": [event, ...]}: the snapshot
  at or before `date` (10-minute snapshots from June 2020, 5-minute from September 2022).
  Paid plans only; cost 10 credits per market per region, nothing when `data` is empty.
- GET /v4/sports/{sport}/odds (live) returns a bare list of the same events; 1 credit per market
  per region. GET /v4/sports costs nothing and still carries the usage headers.
- event: id, sport_key, sport_title, commence_time, home_team, away_team, bookmakers[]; bookmaker:
  key, title, last_update, markets[]; market: key, last_update, outcomes[] of name, price, point
  (point only on spreads/totals). Bookmaker-level last_update is deprecated (market-level wins).
- Headers x-requests-remaining / x-requests-used / x-requests-last (credits).

The key comes from env ODDS_API_KEY or `config.ODDS_API_KEY_FILE` (mode 600). It is a query
parameter, so request URLs and params are never logged or put in error messages.
Nothing here touches DuckDB.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from deepsports import config
from deepsports.http import RETRY_STATUS, PoliteClient

BASE = "https://api.the-odds-api.com/v4"
SPORTS = {"ncaab": "basketball_ncaab", "nba": "basketball_nba"}
HIST_COST = 10  # credits per market per region per historical snapshot
LIVE_COST = 1
RAW_SUBDIR = Path("oddsapi") / "historical"
LIVE_SUBDIR = Path("oddsapi") / "live"
LEDGER_NAME = "ledger.jsonl"
# Scheduled live capture (owner-approved 2026-11-23): 10 books bill as one region.
LIVE_BOOKMAKERS = (
    "draftkings",
    "fanduel",
    "betmgm",
    "williamhill_us",
    "betrivers",
    "espnbet",
    "bovada",
    "betonlineag",
    "lowvig",
    "pinnacle",
)
PT = ZoneInfo("America/Los_Angeles")
# Season = end year (2022 = 2021-22). Defaults skip COVID 2020-21.
DEFAULT_SEASONS = {"ncaab": [2022, 2023, 2024, 2025, 2026], "nba": [2022, 2023, 2024, 2025, 2026]}
# Fallback game-day windows when the ESPN scoreboard cache lacks a season (month, day).
SEASON_WINDOWS = {"ncaab": ((11, 1), (4, 10)), "nba": ((10, 15), (6, 20))}
# (day offset from the ESPN game day, Pacific wall time): 21:00 PT the night before, 09:00 PT
# the morning of.
DEFAULT_TIMES: tuple[tuple[int, time], ...] = ((-1, time(21, 0)), (0, time(9, 0)))

# httpx logs request URLs at INFO, and ours carry the key as a query parameter.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


class OddsApiError(RuntimeError):
    """A fetch failed. The message never contains the key or the request URL's query.
    `status` is the HTTP status when the API answered (401 = missing/expired key or no credits)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Credits:
    remaining: int | None
    used: int | None
    last: int | None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> Credits:
        def num(name: str) -> int | None:
            v = headers.get(name)
            try:
                return int(float(v)) if v is not None else None
            except ValueError:
                return None

        return cls(num("x-requests-remaining"), num("x-requests-used"), num("x-requests-last"))


# ---------------------------------------------------------------- key


def read_key(path: Path | None = None, env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    if env.get("ODDS_API_KEY", "").strip():
        return env["ODDS_API_KEY"].strip()
    p = path or config.ODDS_API_KEY_FILE
    try:
        key = p.read_text().strip()
    except OSError as e:
        raise OddsApiError(
            f"no Odds API key: set ODDS_API_KEY or write it to {p} (mode 600) ({type(e).__name__})"
        ) from None
    if not key:
        raise OddsApiError(f"Odds API key file {p} is empty")
    if p.stat().st_mode & 0o077:
        log.warning("%s is readable by others; chmod 600 it", p)
    return key


# ---------------------------------------------------------------- plan (pure)


def season_window(league: str, season: int) -> tuple[date, date]:
    (m1, d1), (m2, d2) = SEASON_WINDOWS[league]
    return date(season - 1, m1, d1), date(season, m2, d2)


def season_of(league: str, day: date) -> int | None:
    for season in (day.year, day.year + 1):
        lo, hi = season_window(league, season)
        if lo <= day <= hi:
            return season
    return None


PRESEASON = 1  # ESPN season.type: 1 preseason, 2 regular, 3 postseason, 5 play-in


def _season_type(event: Mapping[str, Any]) -> int | None:
    return (event.get("season") or {}).get("type")


def scoreboard_game_days(scoreboard_dir: Path) -> dict[date, int]:
    """ESPN game day (US/Eastern, the file name) -> number of non-preseason events, from the
    raw scoreboard cache."""
    out: dict[date, int] = {}
    for f in sorted(scoreboard_dir.glob("*.json.gz")):
        stem = f.name.split(".")[0]
        if len(stem) != 8 or not stem.isdigit():
            continue
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                events = json.load(fh).get("events") or []
        except (OSError, ValueError):
            continue
        out[date(int(stem[:4]), int(stem[4:6]), int(stem[6:]))] = sum(
            _season_type(e) != PRESEASON for e in events
        )
    return out


def game_days(
    league: str, seasons: Iterable[int], cached: Mapping[date, int]
) -> dict[int, tuple[list[date], str]]:
    """Per season: the game days and where they came from ("espn" when the scoreboard cache
    covers the season, else "window", every day of the season window)."""
    out: dict[int, tuple[list[date], str]] = {}
    for season in seasons:
        lo, hi = season_window(league, season)
        in_season = {d: n for d, n in cached.items() if lo <= d <= hi}
        if len(in_season) >= 30:
            out[season] = (sorted(d for d, n in in_season.items() if n > 0), "espn")
        else:
            out[season] = ([lo + timedelta(days=i) for i in range((hi - lo).days + 1)], "window")
    return out


def parse_times(spec: str) -> tuple[tuple[int, time], ...]:
    """'-1@21:00,0@09:00' -> ((-1, 21:00), (0, 09:00)); offsets in days from the game day."""
    out = []
    for part in spec.split(","):
        off, _, hm = part.strip().partition("@")
        h, _, m = hm.partition(":")
        out.append((int(off), time(int(h), int(m or 0))))
    return tuple(out)


def snapshot_times(
    days: Iterable[date], times: Sequence[tuple[int, time]] = DEFAULT_TIMES, tz: ZoneInfo = PT
) -> list[datetime]:
    """Unique UTC request timestamps for the game days, sorted."""
    out = set()
    for d in days:
        for off, t in times:
            local = datetime.combine(d + timedelta(days=off), t, tzinfo=tz)
            out.add(local.astimezone(UTC))
    return sorted(out)


def region_units(regions: Sequence[str], bookmakers: Sequence[str] | None = None) -> int:
    """Billing regions: `bookmakers` (any region's books) wins over `regions` when given, and
    every 10 bookmakers count as one region."""
    if bookmakers:
        return -(-len(bookmakers) // 10)
    return len(regions)


def cost(
    n_snapshots: int,
    markets: Sequence[str],
    regions: Sequence[str],
    bookmakers: Sequence[str] | None = None,
) -> int:
    return HIST_COST * len(markets) * region_units(regions, bookmakers) * n_snapshots


def live_cost(
    markets: Sequence[str], regions: Sequence[str], bookmakers: Sequence[str] | None = None
) -> int:
    """Credits for one live /odds call: 1 per market per billing region."""
    return LIVE_COST * len(markets) * region_units(regions, bookmakers)


def scope_label(regions: Sequence[str], bookmakers: Sequence[str] | None = None) -> str:
    """Cache folder name for the book selection: 'us,eu' or 'books=draftkings,pinnacle'."""
    if bookmakers:
        return "books=" + ",".join(sorted(bookmakers))
    return ",".join(regions)


def scope_params(regions: Sequence[str], bookmakers: Sequence[str] | None = None) -> dict:
    if bookmakers:
        return {"bookmakers": ",".join(bookmakers)}
    return {"regions": ",".join(regions)}


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_stamp(ts: datetime) -> str:
    """Colon-free (the external drive is exFAT): 20211110T050000Z."""
    return ts.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------- cache


def combo_dir(
    sport: str,
    markets: Sequence[str],
    regions: Sequence[str],
    raw_dir: Path | None = None,
    bookmakers: Sequence[str] | None = None,
) -> Path:
    base = (raw_dir or config.RAW_DIR) / RAW_SUBDIR
    return base / sport / ",".join(markets) / scope_label(regions, bookmakers)


def cache_path(
    sport: str,
    markets: Sequence[str],
    regions: Sequence[str],
    ts: datetime,
    raw_dir: Path | None = None,
    bookmakers: Sequence[str] | None = None,
) -> Path:
    return combo_dir(sport, markets, regions, raw_dir, bookmakers) / f"{file_stamp(ts)}.json.gz"


def read_cached(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def write_cached(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(data, fh)
    tmp.replace(path)


def ledger_path(raw_dir: Path | None = None, subdir: Path = RAW_SUBDIR) -> Path:
    return (raw_dir or config.RAW_DIR) / subdir / LEDGER_NAME


def append_ledger(
    entry: Mapping[str, Any], raw_dir: Path | None = None, subdir: Path = RAW_SUBDIR
) -> None:
    p = ledger_path(raw_dir, subdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def read_ledger(raw_dir: Path | None = None, subdir: Path = RAW_SUBDIR) -> list[dict[str, Any]]:
    p = ledger_path(raw_dir, subdir)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- live capture files


def live_slot(ts: datetime, minutes: int = 30) -> datetime:
    """The capture slot a run belongs to: `ts` in UTC floored to `minutes`. The file name uses
    the slot, so a second run in the same slot finds the file and spends nothing."""
    ts = ts.astimezone(UTC).replace(second=0, microsecond=0)
    return ts - timedelta(minutes=ts.minute % minutes)


def live_path(sport: str, slot: datetime, raw_dir: Path | None = None) -> Path:
    """RAW_DIR/oddsapi/live/<sport>/<UTC slot stamp>.json.gz"""
    return (raw_dir or config.RAW_DIR) / LIVE_SUBDIR / sport / f"{file_stamp(slot)}.json.gz"


def live_envelope(
    data: list[dict[str, Any]],
    fetched_at: datetime,
    sport: str,
    markets: Sequence[str],
    regions: Sequence[str],
    bookmakers: Sequence[str] | None,
    credits: Credits,
) -> dict[str, Any]:
    """What a capture file holds: the bare live list under "data" (every upcoming event the API
    returns, next-day games included: no commenceTime filter), the request time as "timestamp"
    and "snapshot_ts" (so `parse_snapshot` reads it like a historical response) and the request."""
    return {
        "timestamp": iso(fetched_at),
        "snapshot_ts": iso(fetched_at),
        "sport": sport,
        "markets": ",".join(markets),
        "scope": scope_label(regions, bookmakers),
        "credits_last": credits.last,
        "credits_remaining": credits.remaining,
        "data": data,
    }


# ---------------------------------------------------------------- fetch


def _get(client: PoliteClient, url: str, params: dict[str, Any]) -> tuple[Any, Credits]:
    """One GET through the PoliteClient's throttle, returning the body and the credit headers
    (PoliteClient.get_json drops headers). Retries 429/5xx; errors never quote params."""
    for attempt in range(client.max_retries + 1):
        client._throttle()
        client.network_requests += 1
        try:
            resp = client.client.get(url, params=params)
        except httpx.TransportError as e:
            if attempt == client.max_retries:
                raise OddsApiError(f"{url}: {type(e).__name__}") from None
            client._backoff(attempt, None)
            continue
        credits = Credits.from_headers(resp.headers)
        if resp.status_code == 200:
            return resp.json(), credits
        if resp.status_code in RETRY_STATUS and attempt < client.max_retries:
            client._backoff(attempt, resp.headers.get("Retry-After"))
            continue
        try:
            detail = str(resp.json().get("message", ""))[:200]
        except ValueError:
            detail = ""
        key = params.get("apiKey")
        if key:
            detail = detail.replace(str(key), "***")
        raise OddsApiError(
            f"{url}: HTTP {resp.status_code} {detail}".rstrip(), status=resp.status_code
        )
    raise OddsApiError(f"{url}: retries exhausted")  # pragma: no cover


def check_quota(client: PoliteClient, key: str) -> Credits:
    """GET /v4/sports: free, and carries the usage headers."""
    _, credits = _get(client, f"{BASE}/sports", {"apiKey": key})
    return credits


def fetch_live(
    client: PoliteClient,
    key: str,
    sport: str,
    markets: Sequence[str],
    regions: Sequence[str],
    bookmakers: Sequence[str] | None = None,
) -> tuple[list[dict[str, Any]], Credits]:
    params = {
        "apiKey": key,
        **scope_params(regions, bookmakers),
        "markets": ",".join(markets),
        "oddsFormat": "american",
    }
    data, credits = _get(client, f"{BASE}/sports/{sport}/odds", params)
    return data, credits


def fetch_historical(
    client: PoliteClient,
    key: str,
    sport: str,
    ts: datetime,
    markets: Sequence[str],
    regions: Sequence[str],
    bookmakers: Sequence[str] | None = None,
) -> tuple[dict[str, Any], Credits]:
    params = {
        "apiKey": key,
        **scope_params(regions, bookmakers),
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "date": iso(ts),
    }
    data, credits = _get(client, f"{BASE}/historical/sports/{sport}/odds", params)
    if not isinstance(data, dict) or "data" not in data:
        raise OddsApiError(f"historical {sport} {iso(ts)}: unexpected response shape")
    return data, credits


# ---------------------------------------------------------------- parse (pure)

ROW_COLUMNS = (
    "snapshot_ts",
    "event_id",
    "sport_key",
    "commence_time",
    "home_team",
    "away_team",
    "book",
    "book_last_update",
    "market",
    "market_last_update",
    "outcome",
    "point",
    "price",
)


def _ts(v: Any) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def parse_snapshot(resp: Any, snapshot_ts: datetime | None = None) -> list[dict[str, Any]]:
    """A historical response ({"timestamp", "data": [...]}) or a live list -> one row per
    bookmaker x market x outcome. For a live list, pass the fetch time as `snapshot_ts`."""
    if isinstance(resp, dict):
        events = resp.get("data") or []
        snap = _ts(resp.get("timestamp")) or snapshot_ts
    else:
        events = resp or []
        snap = snapshot_ts
    rows = []
    for ev in events:
        base = {
            "snapshot_ts": snap,
            "event_id": ev.get("id"),
            "sport_key": ev.get("sport_key"),
            "commence_time": _ts(ev.get("commence_time")),
            "home_team": ev.get("home_team"),
            "away_team": ev.get("away_team"),
        }
        for bk in ev.get("bookmakers") or []:
            book_lu = _ts(bk.get("last_update"))
            for mk in bk.get("markets") or []:
                mk_lu = _ts(mk.get("last_update")) or book_lu
                for oc in mk.get("outcomes") or []:
                    point = oc.get("point")
                    price = oc.get("price")
                    rows.append(
                        {
                            **base,
                            "book": bk.get("key"),
                            "book_last_update": book_lu,
                            "market": mk.get("key"),
                            "market_last_update": mk_lu,
                            "outcome": oc.get("name"),
                            "point": float(point) if point is not None else None,
                            "price": int(price) if price is not None else None,
                        }
                    )
    return rows


def coverage(
    resp: Any, game_day: date, market: str = "totals", tz: ZoneInfo = config.LEAGUE_TZ
) -> dict[str, Any]:
    """How many of a game day's events (ESPN's US/Eastern day) have `market` in this snapshot,
    overall and per book. For probe reports."""
    events = resp.get("data") if isinstance(resp, dict) else resp
    day_events = [
        ev
        for ev in events or []
        if ev.get("commence_time") and _ts(ev["commence_time"]).astimezone(tz).date() == game_day
    ]
    per_book: dict[str, int] = {}
    with_market = 0
    for ev in day_events:
        books = {
            bk["key"]
            for bk in ev.get("bookmakers") or []
            if any(m.get("key") == market for m in bk.get("markets") or [])
        }
        with_market += bool(books)
        for b in books:
            per_book[b] = per_book.get(b, 0) + 1
    return {
        "events": len(day_events),
        "with_market": with_market,
        "per_book": dict(sorted(per_book.items(), key=lambda kv: -kv[1])),
    }
