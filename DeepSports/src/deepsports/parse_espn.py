"""Pure functions: raw ESPN JSON -> row dicts matching the tables in store.py.

No I/O here, so every parser is unit-tested against fixtures in tests/fixtures.
"""

from datetime import UTC, datetime
from typing import Any

LEAGUE = "nba"  # default league for every parser; pass league="ncaab" for college

# ESPN team box-score stat name -> our column(s). "a-b" values split into two columns.
TEAM_STAT_MAP: dict[str, tuple[str, ...]] = {
    "fieldGoalsMade-fieldGoalsAttempted": ("fgm", "fga"),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("fg3m", "fg3a"),
    "freeThrowsMade-freeThrowsAttempted": ("ftm", "fta"),
    "offensiveRebounds": ("oreb",),
    "defensiveRebounds": ("dreb",),
    "totalRebounds": ("reb",),
    "assists": ("ast",),
    "steals": ("stl",),
    "blocks": ("blk",),
    "totalTurnovers": ("tov",),
    "fouls": ("pf",),
    "turnoverPoints": ("points_off_turnovers",),
    "fastBreakPoints": ("fast_break_points",),
    "pointsInPaint": ("points_in_paint",),
    "largestLead": ("largest_lead",),
}

# ESPN player box-score key -> our column(s).
PLAYER_STAT_MAP: dict[str, tuple[str, ...]] = {
    "minutes": ("minutes",),
    "points": ("pts",),
    "fieldGoalsMade-fieldGoalsAttempted": ("fgm", "fga"),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("fg3m", "fg3a"),
    "freeThrowsMade-freeThrowsAttempted": ("ftm", "fta"),
    "offensiveRebounds": ("oreb",),
    "defensiveRebounds": ("dreb",),
    "rebounds": ("reb",),
    "assists": ("ast",),
    "steals": ("stl",),
    "blocks": ("blk",),
    "turnovers": ("tov",),
    "fouls": ("pf",),
    "plusMinus": ("plus_minus",),
}


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return value
    s = str(value).strip().replace("+", "")
    if s in ("", "-", "--"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _split_stat(columns: tuple[str, ...], value: Any) -> dict[str, Any]:
    if len(columns) == 1:
        return {columns[0]: _num(value)}
    parts = str(value).split("-") if value is not None else []
    if len(parts) != 2:
        return dict.fromkeys(columns)
    return {columns[0]: _num(parts[0]), columns[1]: _num(parts[1])}


def parse_moneyline(value: Any) -> int | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    if s == "EVEN":
        return 100
    n = _num(s)
    return int(n) if n is not None else None


def parse_price(value: Any) -> int | None:
    """An American price ("-111", -105.0, "+100", "EVEN") as an int. Anything with |x| < 100
    (e.g. a decimal price like 1.91 in the wrong field) is not an American price: None."""
    n = parse_moneyline(value)
    return n if n is not None and abs(n) >= 100 else None


PRICE_COLS = ("spread_home_price", "spread_away_price", "over_price", "under_price")


def _path(block: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(block, dict):
            return None
        block = block.get(key)
    return block


def _first_price(*values: Any) -> int | None:
    for v in values:
        price = parse_price(v)
        if price is not None:
            return price
    return None


def _site_prices(o: dict, phase: str = "close", flat: bool = False) -> dict[str, int | None]:
    """Spread and total prices from a site-API odds block (scoreboard `odds[]` or summary
    `pickcenter[]`): `pointSpread.home/away.<phase>.odds`, `total.over/under.<phase>.odds`.
    `flat=True` (pickcenter) reads the flat `homeTeamOdds.spreadOdds` / `overOdds` first."""
    ps, tot = o.get("pointSpread") or {}, o.get("total") or {}
    home, away = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
    return {
        "spread_home_price": _first_price(
            home.get("spreadOdds") if flat else None, _path(ps, "home", phase, "odds")
        ),
        "spread_away_price": _first_price(
            away.get("spreadOdds") if flat else None, _path(ps, "away", phase, "odds")
        ),
        "over_price": _first_price(
            o.get("overOdds") if flat else None, _path(tot, "over", phase, "odds")
        ),
        "under_price": _first_price(
            o.get("underOdds") if flat else None, _path(tot, "under", phase, "odds")
        ),
    }


def parse_time(value: str) -> datetime:
    """ESPN times look like 2026-11-05T00:30Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def parse_teams(raw: dict, league: str = LEAGUE) -> list[dict[str, Any]]:
    """The league's team list (NBA franchises, NCAA D1 schools): `listed = true`."""
    rows = []
    for group in raw["sports"][0]["leagues"]:
        for item in group["teams"]:
            t = item["team"]
            rows.append(
                {
                    "team_id": t["id"],
                    "league": league,
                    "abbreviation": t["abbreviation"],
                    "display_name": t["displayName"],
                    "location": t.get("location"),
                    "name": t.get("name"),
                    "listed": True,
                }
            )
    return rows


def parse_scoreboard_teams(raw: dict, league: str = LEAGUE) -> list[dict[str, Any]]:
    """Every competitor on a scoreboard as a team row with `listed = false`. College
    scoreboards include non-D1 opponents that ESPN's D1 team list doesn't have; storing them
    (without overwriting listed rows) keeps those games displayable."""
    rows = {}
    for e in raw.get("events", []):
        for c in e["competitions"][0]["competitors"]:
            t = c.get("team") or {}
            if not t.get("id"):
                continue
            rows[t["id"]] = {
                "team_id": t["id"],
                "league": league,
                "abbreviation": t.get("abbreviation") or t["id"],
                "display_name": t.get("displayName") or t.get("name") or t["id"],
                "location": t.get("location"),
                "name": t.get("name"),
                "listed": False,
            }
    return list(rows.values())


def parse_scoreboard(
    raw: dict, captured_at: datetime | None = None, league: str = LEAGUE
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (games, odds_snapshots). Odds are only kept for games not yet started."""
    captured_at = captured_at or datetime.now(UTC)
    games, odds = [], []
    for e in raw.get("events", []):
        comp = e["competitions"][0]
        status = e["status"]["type"]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = teams["home"], teams["away"]
        started = status["state"] != "pre"
        venue = comp.get("venue") or {}
        tv = sorted({n for b in comp.get("broadcasts") or [] for n in b.get("names", [])})
        games.append(
            {
                "game_id": e["id"],
                "league": league,
                "season_year": e["season"]["year"],
                "season_type": e["season"]["type"],
                "start_time_utc": parse_time(e["date"]),
                "status": status["name"],
                "state": status["state"],
                "completed": bool(status.get("completed")),
                "home_team_id": home["team"]["id"],
                "away_team_id": away["team"]["id"],
                "home_score": _num(home.get("score")) if started else None,
                "away_score": _num(away.get("score")) if started else None,
                "venue": venue.get("fullName"),
                "venue_city": (venue.get("address") or {}).get("city"),
                "neutral_site": bool(comp.get("neutralSite")),
                "attendance": comp.get("attendance") or None,
                "broadcasts": ", ".join(tv) or None,
            }
        )
        if status["state"] == "pre":
            for o in comp.get("odds") or []:
                odds.append(_scoreboard_odds(e["id"], o, captured_at))
    return games, odds


def _scoreboard_odds(game_id: str, o: dict, captured_at: datetime) -> dict[str, Any]:
    ml = o.get("moneyline") or {}
    return {
        "game_id": game_id,
        "source": "pregame",
        "captured_at": captured_at,
        "provider": (o.get("provider") or {}).get("name"),
        "details": o.get("details"),
        "spread_home": _num(o.get("spread")),  # negative = home favored
        "over_under": _num(o.get("overUnder")),
        "home_moneyline": parse_moneyline(((ml.get("home") or {}).get("close") or {}).get("odds")),
        "away_moneyline": parse_moneyline(((ml.get("away") or {}).get("close") or {}).get("odds")),
        **_site_prices(o, "close"),  # `close` = the current line while the game is upcoming
    }


def _athlete_id(athlete: dict, team_id: str) -> str:
    """ESPN occasionally omits the id (seen on DNP two-way players); use a stable placeholder."""
    if athlete.get("id"):
        return athlete["id"]
    name = athlete.get("displayName") or athlete.get("shortName") or "unknown"
    return f"noid:{team_id}:{name}"


def parse_summary(
    raw: dict, captured_at: datetime | None = None, league: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (team_game_stats, player_game_stats, closing_odds) for a completed game.
    With `league`, box-score rows carry a `league` column (the warehouse rows); without it
    they don't (the API's live box score)."""
    captured_at = captured_at or datetime.now(UTC)
    game_id = raw["header"]["id"]
    box = raw.get("boxscore") or {}
    tag = {"league": league} if league else {}

    team_rows = []
    for t in box.get("teams", []):
        row: dict[str, Any] = {
            "game_id": game_id,
            "team_id": t["team"]["id"],
            "home_away": t.get("homeAway"),
            **tag,
        }
        for cols in TEAM_STAT_MAP.values():
            row.update(dict.fromkeys(cols))
        for s in t.get("statistics", []):
            if s["name"] in TEAM_STAT_MAP:
                row.update(_split_stat(TEAM_STAT_MAP[s["name"]], s.get("displayValue")))
        team_rows.append(row)

    player_rows = []
    for team in box.get("players", []):
        team_id = team["team"]["id"]
        for group in team.get("statistics", []):
            keys = group.get("keys", [])
            for a in group.get("athletes", []):
                row = {
                    "game_id": game_id,
                    "team_id": team_id,
                    "athlete_id": _athlete_id(a["athlete"], team_id),
                    "athlete_name": a["athlete"].get("displayName")
                    or a["athlete"].get("shortName"),
                    "starter": bool(a.get("starter")),
                    "did_not_play": bool(a.get("didNotPlay")),
                    "dnp_reason": a.get("reason") or None,
                    "ejected": bool(a.get("ejected")),
                    **tag,
                }
                for cols in PLAYER_STAT_MAP.values():
                    row.update(dict.fromkeys(cols))
                for key, value in zip(keys, a.get("stats") or [], strict=False):
                    if key in PLAYER_STAT_MAP:
                        row.update(_split_stat(PLAYER_STAT_MAP[key], value))
                player_rows.append(row)

    odds_rows = parse_pickcenter(raw, captured_at)
    return team_rows, player_rows, odds_rows


def parse_pickcenter(raw: dict, captured_at: datetime) -> list[dict[str, Any]]:
    """A summary's `pickcenter` -> at most one 'closing' odds row (the first pick)."""
    pick = (raw.get("pickcenter") or [None])[0]
    if not pick:
        return []
    return [
        {
            "game_id": raw["header"]["id"],
            "source": "closing",
            "captured_at": captured_at,
            "provider": (pick.get("provider") or {}).get("name"),
            "details": pick.get("details"),
            "spread_home": _num(pick.get("spread")),
            "over_under": _num(pick.get("overUnder")),
            "home_moneyline": parse_moneyline((pick.get("homeTeamOdds") or {}).get("moneyLine")),
            "away_moneyline": parse_moneyline((pick.get("awayTeamOdds") or {}).get("moneyLine")),
            **_site_prices(pick, "close", flat=True),
        }
    ]


# Sportsbooks in order of preference for the single line we store per game. DraftKings first
# to match the site API's pickcenter; "Live Odds" feeds are in-game lines and never used.
# College lines come from "Draft Kings" (with a space).
PREFERRED_BOOKS = (
    "DraftKings",
    "Draft Kings",
    "ESPN BET",
    "Caesars Sportsbook",
    "FanDuel",
    "BetMGM",
)


def choose_book(items: list[dict]) -> dict | None:
    pregame = [o for o in items if "live" not in (o.get("provider") or {}).get("name", "").lower()]
    if not pregame:
        return None
    for book in PREFERRED_BOOKS:
        for o in pregame:
            if (o.get("provider") or {}).get("name") == book:
                return o
    return pregame[0]


def _american(block: dict | None, *path: str) -> Any:
    return _path(block, *path)


def _home_spread(value: Any, home_favorite: bool | None) -> float | None:
    spread = _num(value)
    if spread is None:
        return None
    if home_favorite is True and spread > 0:  # sanity: a favorite gives points
        spread = -spread
    return spread


def parse_core_odds(raw: dict, game_id: str, captured_at: datetime) -> list[dict[str, Any]]:
    """ESPN core API odds -> up to two rows: 'opening' and 'closing' for one sportsbook.

    Newer games carry explicit open/close blocks per side; older ones only flat fields
    (treated as the closing line). `captured_at` should be the game's start time so
    re-parsing is deterministic.
    """
    o = choose_book(raw.get("items") or [])
    if o is None:
        return []
    home, away = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
    base = {
        "game_id": game_id,
        "captured_at": captured_at,
        "provider": (o.get("provider") or {}).get("name"),
    }
    rows = []
    for source, phase in (("opening", "open"), ("closing", "close")):
        if phase not in o and phase not in home:
            continue
        spread = _american(home, phase, "pointSpread", "american")
        total = _american(o, phase, "total", "american")
        row = {
            **base,
            "source": source,
            "details": o.get("details") if source == "closing" else None,
            "spread_home": _home_spread(spread, (home.get(phase) or {}).get("favorite")),
            "over_under": _num(total),
            "home_moneyline": parse_moneyline(_american(home, phase, "moneyLine", "american")),
            "away_moneyline": parse_moneyline(_american(away, phase, "moneyLine", "american")),
            # per-side `spread` is the spread *price*; `over`/`under` are the total prices
            "spread_home_price": parse_price(_american(home, phase, "spread", "american")),
            "spread_away_price": parse_price(_american(away, phase, "spread", "american")),
            "over_price": parse_price(_american(o, phase, "over", "american")),
            "under_price": parse_price(_american(o, phase, "under", "american")),
        }
        if any(row[k] is not None for k in ("spread_home", "over_under", "home_moneyline")):
            rows.append(row)
    if not any(r["source"] == "closing" for r in rows):
        # older format: flat fields only
        row = {
            **base,
            "source": "closing",
            "details": o.get("details"),
            "spread_home": _home_spread(o.get("spread"), home.get("favorite")),
            "over_under": _num(o.get("overUnder")),
            "home_moneyline": parse_moneyline(home.get("moneyLine")),
            "away_moneyline": parse_moneyline(away.get("moneyLine")),
            "spread_home_price": parse_price(home.get("spreadOdds")),
            "spread_away_price": parse_price(away.get("spreadOdds")),
            "over_price": parse_price(o.get("overOdds")),
            "under_price": parse_price(o.get("underOdds")),
        }
        if any(row[k] is not None for k in ("spread_home", "over_under", "home_moneyline")):
            rows.append(row)
    return rows


def _date(value: Any):
    """'2026-11-08' (or a full timestamp) -> date; None if missing or malformed."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def parse_injuries(
    raw: dict, captured_at: datetime, start_time: datetime | None = None, league: str = LEAGUE
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (injury_reports, injury_captures) from a game summary's `injuries` array.

    ESPN's list is the team's injury report *as of the fetch*, not as of the game: a summary
    fetched after the game shows whoever is hurt at fetch time (see docs/DATA_SOURCES.md).
    So every row carries `captured_before_tip`, and only those rows are safe model inputs.
    One capture row per team is written even when the list is empty, so "no injuries" is
    distinguishable from "not captured". College summaries have no `injuries` key (ESPN
    publishes no college injury reports), so they yield nothing.
    """
    header = raw["header"]
    game_id = header["id"]
    if start_time is None:
        start_time = parse_time(header["competitions"][0]["date"])
    before_tip = captured_at < start_time
    reports, captures = [], []
    for team in raw.get("injuries") or []:
        team_id = (team.get("team") or {}).get("id")
        if not team_id:
            continue
        listed = team.get("injuries") or []
        captures.append(
            {
                "game_id": game_id,
                "league": league,
                "team_id": team_id,
                "captured_at": captured_at,
                "captured_before_tip": before_tip,
                "n_listed": len(listed),
            }
        )
        for i in listed:
            athlete = i.get("athlete") or {}
            details = i.get("details") or {}
            reports.append(
                {
                    "game_id": game_id,
                    "league": league,
                    "team_id": team_id,
                    "athlete_id": _athlete_id(athlete, team_id),
                    "athlete_name": athlete.get("displayName") or athlete.get("shortName"),
                    "status": i.get("status"),
                    "injury_type": details.get("type"),
                    "detail": details.get("detail"),
                    "side": details.get("side"),
                    "return_date": _date(details.get("returnDate")),
                    "reported_at": parse_time(i["date"]) if i.get("date") else None,
                    "captured_at": captured_at,
                    "captured_before_tip": before_tip,
                }
            )
    return reports, captures


# ---------- offline price backfill (docs/DECISIONS.md 2026-11-06) ----------

# A cached response is the one a stored row was built from only if every one of these agrees.
LINE_MATCH_COLS = ("provider", "spread_home", "over_under", "home_moneyline", "away_moneyline")


def price_origin(source: str, captured_at: datetime, start_time: datetime) -> str | None:
    """Which cached response a historical odds row was parsed from: 'core' (core API, stamped
    with the game's start time: every opening row and gap-filled closing rows) or 'summary'
    (the summary's pickcenter, stamped with the fetch time). Pregame rows: None (one cached
    scoreboard per day is overwritten on every fetch, so their responses aren't kept)."""
    if source == "opening":
        return "core"
    if source == "closing":
        return "core" if captured_at == start_time else "summary"
    return None


def match_cached_prices(
    stored: dict[str, Any], cached: list[dict[str, Any]]
) -> tuple[str, dict[str, int]]:
    """Prices to fill on a stored odds row from rows re-parsed from its cached response.

    Returns (status, fill): 'missing' (no cached row with this source), 'mismatch' (a line
    value or provider differs: the cache isn't the response this row came from), 'no_prices'
    (nothing new to fill) or 'fill'. `fill` holds only columns that are NULL on the stored row
    and priced in the cache: a stored price is never overwritten."""
    row = next((r for r in cached if r["source"] == stored["source"]), None)
    if row is None:
        return "missing", {}
    if any(stored.get(c) != row.get(c) for c in LINE_MATCH_COLS):
        return "mismatch", {}
    fill = {c: row[c] for c in PRICE_COLS if stored.get(c) is None and row.get(c) is not None}
    return ("fill" if fill else "no_prices"), fill
