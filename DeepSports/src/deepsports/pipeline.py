"""Collection jobs: fetch -> land raw -> parse -> upsert. Each job is idempotent."""

import gzip
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from deepsports import config
from deepsports.http import FetchError, PoliteClient
from deepsports.parse_espn import (
    LINE_MATCH_COLS,
    match_cached_prices,
    parse_core_odds,
    parse_injuries,
    parse_pickcenter,
    parse_scoreboard,
    parse_scoreboard_teams,
    parse_summary,
    parse_teams,
    price_origin,
)
from deepsports.quality import KNOWN_NO_BOXSCORE
from deepsports.sources.espn import EspnBasketball, get_league
from deepsports.store import Store

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    games: int = 0
    boxscores: int = 0
    odds: int = 0
    injuries: int = 0
    skipped_started: int = 0  # pre-tip fetches dropped: the game tipped off or moved earlier
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "RunStats") -> "RunStats":
        self.games += other.games
        self.boxscores += other.boxscores
        self.odds += other.odds
        self.injuries += other.injuries
        self.skipped_started += other.skipped_started
        self.errors += other.errors
        return self


def league_today() -> date:
    return datetime.now(config.LEAGUE_TZ).date()


def daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def season_dates(label: str, league: str = "nba") -> tuple[date, date]:
    """'2025-26' -> NBA: Oct 1 2025 .. Jun 30 2026 (preseason through the Finals);
    college: Nov 1 2025 .. Apr 15 2026 (opening night through the title game)."""
    spec = get_league(league)
    first = int(label.split("-")[0])
    return date(first, *spec.season_start), date(first + 1, *spec.season_end)


def collect_teams(src: EspnBasketball, db: Store) -> int:
    return db.upsert_teams(parse_teams(src.teams(), src.league))


def collect_schedule(
    src: EspnBasketball, db: Store, start: date, end: date, refresh: bool = False
) -> RunStats:
    stats = RunStats()
    for day in daterange(start, end):
        try:
            raw = src.scoreboard(day, refresh=refresh)
        except FetchError as e:
            log.error("scoreboard %s: %s", day, e)
            stats.errors.append(f"scoreboard {day}: {e}")
            continue
        games, odds = parse_scoreboard(raw, league=src.league)
        if src.spec.discover_teams:
            db.add_discovered_teams(parse_scoreboard_teams(raw, src.league))
        stats.games += db.upsert_games(games)
        stats.odds += db.add_odds(odds)
        log.info("%s: %d games", day, len(games))
    return stats


def fetch_pregame_odds(
    src: EspnBasketball, days: int = 2, today: date | None = None
) -> tuple[list[dict], RunStats]:
    """Fresh scoreboards for `days` US/Eastern game days from today (default today + tomorrow)
    -> pregame odds rows for games not yet started, each stamped with its fetch time. Touches
    no database, so `deepsports odds-snapshot` can fetch first and hold the DuckDB writer lock
    only for the short write. Scoreboards are always refetched (an upcoming day is never
    settled) and saved to the raw zone like every response."""
    stats = RunStats()
    rows: list[dict] = []
    start = today or league_today()
    for day in daterange(start, start + timedelta(days=days - 1)):
        try:
            raw = src.scoreboard(day, refresh=True)
        except FetchError as e:
            log.error("scoreboard %s: %s", day, e)
            stats.errors.append(f"scoreboard {src.league} {day}: {e}")
            continue
        _, odds = parse_scoreboard(raw, datetime.now(UTC), league=src.league)
        rows += odds
    return rows, stats


def collect_boxscores(src: EspnBasketball, db: Store, limit: int | None = None) -> RunStats:
    stats = RunStats()
    for game_id in db.games_missing_boxscores(limit, league=src.league):
        if game_id in KNOWN_NO_BOXSCORE:  # ESPN 404s these; don't re-request every run
            continue
        try:
            raw = src.summary(game_id)
        except FetchError as e:
            log.error("summary %s: %s", game_id, e)
            stats.errors.append(f"summary {game_id}: {e}")
            continue
        try:
            teams, players, odds = parse_summary(raw, league=src.league)
        except (KeyError, TypeError, ValueError, IndexError) as e:
            # One malformed game must not abort a season; it stays "missing" for a retry.
            log.error("parse summary %s: %r", game_id, e)
            stats.errors.append(f"parse summary {game_id}: {e!r}")
            continue
        if not teams:
            stats.errors.append(f"summary {game_id}: no box score")
            continue
        db.upsert_team_stats(teams)
        db.upsert_player_stats(players)
        stats.odds += db.add_odds(odds)
        stats.boxscores += 1
    return stats


def collect_core_odds(
    src: EspnBasketball, db: Store, include_opening: bool = False, limit: int | None = None
) -> RunStats:
    """Historical lines from the ESPN core API for final games missing them. A closing line
    already taken from the game summary is kept; the core API only fills gaps."""
    stats = RunStats()
    for game_id, start, has_closing in db.games_needing_core_odds(
        include_opening, limit, league=src.league
    ):
        try:
            raw = src.core_odds(game_id)
        except FetchError as e:
            log.error("core odds %s: %s", game_id, e)
            stats.errors.append(f"core odds {game_id}: {e}")
            continue
        rows = parse_core_odds(raw, game_id, start)
        if has_closing:
            rows = [r for r in rows if r["source"] != "closing"]
        stats.odds += db.add_odds(rows)
    return stats


def fetch_injury_snapshots(
    src: EspnBasketball,
    game_ids: list[str],
    now: datetime | None = None,
    skip_started: bool = False,
) -> tuple[list[dict], list[dict], RunStats]:
    """Fetch one fresh summary per game and parse its injury report. Touches no database, so
    `deepsports pretip` can fetch without holding the DuckDB writer lock. Returns (reports,
    captures, stats). Only pre-tip snapshots are kept: a game whose summary shows it tipped
    off (or was moved earlier) is dropped. With `skip_started`, a game whose summary status is
    no longer `pre` is also dropped (counted in stats.skipped_started). `stats.injuries` is
    left 0: the caller sets it from Store.add_injuries."""
    stats = RunStats()
    reports: list[dict] = []
    captures: list[dict] = []
    for game_id in game_ids:
        captured_at = now or datetime.now(UTC)
        try:
            raw = src.summary_snapshot(game_id, captured_at)
        except FetchError as e:
            log.error("injury summary %s: %s", game_id, e)
            stats.errors.append(f"injury summary {game_id}: {e}")
            continue
        try:
            rep, cap = parse_injuries(raw, captured_at, league=src.league)
            if skip_started:
                state = raw["header"]["competitions"][0]["status"]["type"].get("state")
        except (KeyError, TypeError, ValueError, IndexError) as e:
            stats.errors.append(f"parse injuries {game_id}: {e!r}")
            continue
        if skip_started and state != "pre":
            stats.skipped_started += 1
            continue
        if not cap:
            continue  # no injury report in the summary (college)
        if not cap[0]["captured_before_tip"]:
            stats.skipped_started += 1
            continue  # tipped off (or rescheduled earlier) since the schedule was read
        reports += rep
        captures += cap
    return reports, captures, stats


def collect_injury_snapshots(
    src: EspnBasketball,
    db: Store,
    days_ahead: int = 2,
    now: datetime | None = None,
    teams: list[str] | None = None,
) -> RunStats:
    """Pre-tip injury reports for games starting in the next `days_ahead` days (optionally only
    games involving `teams`, by abbreviation). Every run adds a new timestamped snapshot; a game
    that has already tipped off is skipped. ESPN's list is only trustworthy before tip-off
    (docs/DATA_SOURCES.md), so this must run before games. Fetch (fetch_injury_snapshots),
    then one write."""
    start = now or datetime.now(UTC)
    window = db.games_for_injury_snapshot(
        start, start + timedelta(days=days_ahead), league=src.league, team_abbrs=teams
    )
    reports, captures, stats = fetch_injury_snapshots(src, [g for g, _ in window], now)
    stats.injuries += db.add_injuries(reports, captures)
    return stats


def _summary_files(raw_dir: Path, league: str = "nba"):
    """(path, captured_at, from_pregame_snapshot) for every cached summary under raw_dir."""
    base = raw_dir / "espn" / league
    for path in sorted((base / "summary").glob("*.json.gz")):
        if not path.name.startswith("._"):
            yield path, datetime.fromtimestamp(path.stat().st_mtime, UTC), False
    for path in sorted((base / "summary_pregame").glob("*/*.json.gz")):
        if path.name.startswith("._"):
            continue
        ts = datetime.strptime(path.name.split(".")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        yield path, ts, True


def backfill_injuries_from_raw(
    db: Store, raw_dir: Path = config.RAW_DIR, league: str = "nba"
) -> RunStats:
    """Offline: re-parse injuries from cached summaries under `raw_dir` (the raw zone root).

    Completed-game summaries were fetched after the game, so their injury lists show the
    status at fetch time, not before tip: they're stored with captured_before_tip = false
    and captured_at = the file's modification time. Timestamped pre-game snapshots
    (summary_pregame/) are re-parsed as-is, so pre-tip history can be rebuilt from raw.
    Idempotent: a re-run replaces the same (game, team, captured_at) snapshots."""
    stats = RunStats()
    reports: list[dict] = []
    captures: list[dict] = []

    def flush() -> None:
        stats.injuries += db.add_injuries(reports, captures)
        reports.clear()
        captures.clear()

    for path, captured_at, pregame in _summary_files(raw_dir, league):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                raw = json.load(f)
            completed = raw["header"]["competitions"][0]["status"]["type"].get("completed")
            if not pregame and not completed:
                continue
            rep, cap = parse_injuries(raw, captured_at, league=league)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
            stats.errors.append(f"injuries {path.name}: {e!r}")
            continue
        if not pregame:
            for r in (*rep, *cap):
                r["captured_before_tip"] = False
        reports += rep
        captures += cap
        if len(captures) >= 2000:
            flush()
    flush()
    return stats


def plan_price_backfill(
    rows: list[dict], raw_dir: Path = config.RAW_DIR, league: str = "nba"
) -> tuple[list[dict], Counter, list[str]]:
    """Offline, no network: re-parse each odds row's cached response (`price_origin`: the
    summary pickcenter or the core API) and match it to the stored row. Touches no database.
    Returns (fills: stored rows with their NULL prices filled, counts by status, mismatch
    notes). Statuses: fill, no_prices, mismatch, missing (no row of that source in the cache),
    no_cache (file absent or unreadable), no_origin (pregame rows: not backfillable)."""
    cache = PoliteClient(raw_dir=raw_dir)
    counts: Counter = Counter()
    fills: list[dict] = []
    notes: list[str] = []
    parsed: dict[tuple[str, str], list[dict] | None] = {}
    for row in rows:
        origin = price_origin(row["source"], row["captured_at"], row["start_time_utc"])
        if origin is None:
            counts["no_origin"] += 1
            continue
        key = (origin, row["game_id"])
        if key not in parsed:
            try:
                raw = cache.read_cache(
                    f"espn/{league}/{'core_odds' if origin == 'core' else 'summary'}/{key[1]}"
                )
                if raw is None:
                    parsed[key] = None
                elif origin == "core":
                    parsed[key] = parse_core_odds(raw, key[1], row["start_time_utc"])
                else:
                    parsed[key] = parse_pickcenter(raw, row["captured_at"])
            except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
                log.error("prices %s %s: %r", origin, key[1], e)
                parsed[key] = None
        if parsed[key] is None:
            counts["no_cache"] += 1
            continue
        status, fill = match_cached_prices(row, parsed[key])
        counts[status] += 1
        if status == "mismatch" and len(notes) < 50:
            cached = next(r for r in parsed[key] if r["source"] == row["source"])
            diff = {
                c: (row.get(c), cached.get(c))
                for c in LINE_MATCH_COLS
                if row.get(c) != cached.get(c)
            }
            notes.append(f"{league} {row['game_id']} {row['source']} ({origin}): {diff}")
        if fill:
            fills.append({**row, **fill})
    return fills, counts, notes


def update(
    src: EspnBasketball,
    db: Store,
    days_back: int = 3,
    days_ahead: int = 14,
    injuries: bool = True,
    injury_teams: list[str] | None = None,
) -> RunStats:
    """Routine refresh: recent results, upcoming schedule + odds, pre-tip injury snapshots for
    the next 2 days (all games, or only `injury_teams`), then missing box scores."""
    if not db.team_count(src.league):
        collect_teams(src, db)
    today = league_today()
    stats = collect_schedule(
        src,
        db,
        today - timedelta(days=days_back),
        today + timedelta(days=days_ahead),
        refresh=True,
    )
    if injuries:
        stats.merge(collect_injury_snapshots(src, db, days_ahead=2, teams=injury_teams))
    return stats.merge(collect_boxscores(src, db))


def backfill_season(src: EspnBasketball, db: Store, label: str) -> RunStats:
    if not db.team_count(src.league):
        collect_teams(src, db)
    start, end = season_dates(label, src.league)
    end = min(end, league_today() - timedelta(days=1))
    stats = collect_schedule(src, db, start, end)
    return stats.merge(collect_boxscores(src, db))


TITLE_PREFIX = {"nba": "🏀", "ncaab": "🏀🎓"}


def upcoming(
    db: Store, days: int = 7, teams: list[str] | None = None, league: str = "nba"
) -> list[dict]:
    now = datetime.now(UTC)
    rows = db.upcoming_games(now, now + timedelta(days=days), teams, league=league)
    for r in rows:
        start_local = r["start_time_utc"].astimezone(config.LOCAL_TZ)
        r["start_time_utc"] = r["start_time_utc"].astimezone(UTC).isoformat()
        r["start_local"] = start_local.isoformat()
        r["end_local"] = (start_local + timedelta(hours=2, minutes=30)).isoformat()
        r["calendar_key"] = f"deepsports:{league}:{r['game_id']}"
        # ESPN's home/away is nominal at college neutral sites (tournaments): show "vs"
        sep = "vs" if league != "nba" and r["neutral_site"] else "@"
        r["title"] = f"{TITLE_PREFIX.get(league, '🏀')} {r['away_abbr']} {sep} {r['home_abbr']}"
    return rows
