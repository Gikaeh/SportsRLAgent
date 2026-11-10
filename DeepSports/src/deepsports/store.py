"""DuckDB warehouse. Schema is documented in docs/DATA_MODEL.md; keep them in sync."""

import json
import logging
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.parse_espn import LINE_MATCH_COLS
from deepsports.venues import VENUE_CITIES

log = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    """json.dumps fallback for the bulk writer: dates/times as ISO strings, numpy scalars as
    Python numbers."""
    if isinstance(value, datetime | date | dt_time):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"can't store {type(value).__name__}: {value!r}")


# Table name -> column definitions. Team ids are only unique within a league (NBA team "5" is
# Cleveland, NCAA team "5" is UAB), so every team reference is (league, team_id). ESPN event ids
# are unique across leagues, so game_id alone keys games and everything hanging off a game.
TABLES: dict[str, str] = {
    "teams": """
    team_id VARCHAR NOT NULL,
    league VARCHAR NOT NULL,           -- nba | ncaab
    abbreviation VARCHAR NOT NULL,
    display_name VARCHAR NOT NULL,
    location VARCHAR,
    name VARCHAR,
    -- true: in ESPN's league team list (NBA franchises, NCAA D1). false: seen only as an
    -- opponent on a scoreboard (non-D1 schools)
    listed BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (league, team_id)
    """,
    "games": """
    game_id VARCHAR PRIMARY KEY,
    league VARCHAR NOT NULL,
    season_year INTEGER NOT NULL,      -- ESPN convention: 2027 = the 2026-27 season
    season_type INTEGER NOT NULL,      -- 1 preseason, 2 regular, 3 postseason, 5 play-in
    start_time_utc TIMESTAMPTZ NOT NULL,
    status VARCHAR NOT NULL,           -- e.g. STATUS_SCHEDULED, STATUS_FINAL, STATUS_POSTPONED
    state VARCHAR NOT NULL,            -- pre | in | post
    completed BOOLEAN NOT NULL,
    home_team_id VARCHAR NOT NULL,     -- -> teams (league, team_id)
    away_team_id VARCHAR NOT NULL,
    home_score INTEGER,
    away_score INTEGER,
    venue VARCHAR,
    venue_city VARCHAR,
    neutral_site BOOLEAN,
    attendance INTEGER,
    broadcasts VARCHAR,
    updated_at TIMESTAMPTZ NOT NULL
    """,
    # league columns below = the game's league (the default only covers old writers)
    "team_game_stats": """
    game_id VARCHAR NOT NULL,
    team_id VARCHAR NOT NULL,
    home_away VARCHAR,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER,
    tov INTEGER, pf INTEGER,
    points_off_turnovers INTEGER, fast_break_points INTEGER, points_in_paint INTEGER,
    largest_lead INTEGER,
    updated_at TIMESTAMPTZ NOT NULL,
    league VARCHAR NOT NULL DEFAULT 'nba',
    PRIMARY KEY (game_id, team_id)
    """,
    "player_game_stats": """
    game_id VARCHAR NOT NULL,
    team_id VARCHAR NOT NULL,
    athlete_id VARCHAR NOT NULL,
    athlete_name VARCHAR,
    starter BOOLEAN,
    did_not_play BOOLEAN,
    dnp_reason VARCHAR,
    ejected BOOLEAN,
    minutes INTEGER, pts INTEGER,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER,
    tov INTEGER, pf INTEGER, plus_minus INTEGER,
    updated_at TIMESTAMPTZ NOT NULL,
    league VARCHAR NOT NULL DEFAULT 'nba',
    PRIMARY KEY (game_id, athlete_id)
    """,
    "odds_snapshots": """
    game_id VARCHAR NOT NULL,
    source VARCHAR NOT NULL,           -- pregame (scoreboard, repeated) | opening | closing
    captured_at TIMESTAMPTZ NOT NULL,
    provider VARCHAR,
    details VARCHAR,
    spread_home DOUBLE,                -- negative = home team favored
    over_under DOUBLE,
    home_moneyline INTEGER,
    away_moneyline INTEGER,
    -- American prices of the spread and total (2026-11-06 on; NULL on older rows)
    spread_home_price INTEGER,
    spread_away_price INTEGER,
    over_price INTEGER,
    under_price INTEGER,
    PRIMARY KEY (game_id, source, captured_at)
    """,
    "ingest_runs": """
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    command VARCHAR NOT NULL,
    network_requests INTEGER,
    games_upserted INTEGER,
    boxscores_upserted INTEGER,
    errors INTEGER,
    notes VARCHAR
    """,
    # One row per team per summary fetch: lets "no injuries listed" be told apart from "not
    # captured". ESPN's injury list reflects the fetch time, so only captured_before_tip rows are
    # usable as pre-game information (docs/DATA_SOURCES.md).
    "injury_captures": """
    game_id VARCHAR NOT NULL,
    team_id VARCHAR NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    captured_before_tip BOOLEAN NOT NULL,
    n_listed INTEGER NOT NULL,
    league VARCHAR NOT NULL DEFAULT 'nba',
    PRIMARY KEY (game_id, team_id, captured_at)
    """,
    "injury_reports": """
    game_id VARCHAR NOT NULL,
    team_id VARCHAR NOT NULL,
    athlete_id VARCHAR NOT NULL,
    athlete_name VARCHAR,
    status VARCHAR,                    -- Out | Day-To-Day
    injury_type VARCHAR,               -- body part or reason, e.g. Ankle, Rest, Illness
    detail VARCHAR,                    -- e.g. Sprain
    side VARCHAR,
    return_date DATE,                  -- ESPN's estimated return
    reported_at TIMESTAMPTZ,           -- when ESPN last updated this player's status
    captured_at TIMESTAMPTZ NOT NULL,
    captured_before_tip BOOLEAN NOT NULL,
    league VARCHAR NOT NULL DEFAULT 'nba',
    PRIMARY KEY (game_id, athlete_id, captured_at)
    """,
    "predictions": """
    game_id VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    p_home_win DOUBLE,
    pred_home_margin DOUBLE,
    pred_total DOUBLE,
    features_json VARCHAR,
    PRIMARY KEY (game_id, model, model_version)
    """,
    # Forward paper-trade log (watch-only, no money): one frozen bet per (rule, game, market),
    # written before tip-off by `deepsports paper log` and never updated (insert-only).
    "paper_bets": """
    rule VARCHAR NOT NULL,             -- e.g. nba-total-t4 (analysis/paper.py RULES)
    rule_version VARCHAR NOT NULL,     -- frozen definition version (docs/DECISIONS.md)
    game_id VARCHAR NOT NULL,
    league VARCHAR NOT NULL,
    market VARCHAR NOT NULL,           -- spread | total | moneyline
    side VARCHAR NOT NULL,             -- home | away | over | under
    line DOUBLE,                       -- spread_home convention for spreads; NULL for moneyline
    price INTEGER NOT NULL,            -- American odds (-110 for spread/total)
    stake DOUBLE NOT NULL,             -- units
    model_value DOUBLE,                -- the rule's signal (pred_total, load minutes, ...)
    line_source VARCHAR NOT NULL,      -- odds_snapshots.source of the line used (pregame)
    line_provider VARCHAR,
    line_captured_at TIMESTAMPTZ NOT NULL,
    logged_at TIMESTAMPTZ NOT NULL,
    start_time_utc TIMESTAMPTZ NOT NULL, -- scheduled tip when logged
    inputs_json VARCHAR,               -- what the decision used (prediction version/time, loads)
    PRIMARY KEY (rule, game_id, market)
    """,
    # Static: seeded from deepsports/venues.py on every writer open.
    "venue_cities": """
    city VARCHAR PRIMARY KEY,
    lat DOUBLE NOT NULL,
    lon DOUBLE NOT NULL
    """,
}
# Tables whose team references became league-scoped in the 2026-11 migration.
LEAGUE_SCOPED = (
    "teams",
    "team_game_stats",
    "player_game_stats",
    "injury_captures",
    "injury_reports",
)

VIEWS = """
-- The latest pre-tip injury snapshot per game and team.
CREATE OR REPLACE VIEW pregame_injuries AS
WITH last AS (
    SELECT game_id, team_id, max(captured_at) AS captured_at
    FROM injury_captures WHERE captured_before_tip GROUP BY ALL
)
SELECT r.* FROM injury_reports r JOIN last USING (game_id, team_id, captured_at);

-- Schedule context per team per game, computed only from the team's earlier games. Games
-- need both teams in `teams` (drops NBA All-Star/exhibition teams); rows are emitted only for
-- listed teams (a D1 school's game against a non-D1 opponent still counts for its rest days).
CREATE OR REPLACE VIEW team_game_context AS
WITH g AS (
    SELECT * FROM games
    WHERE season_type IN (2, 3, 5)
      AND status NOT IN ('STATUS_POSTPONED', 'STATUS_CANCELED')
      AND (league, home_team_id) IN (SELECT league, team_id FROM teams)
      AND (league, away_team_id) IN (SELECT league, team_id FROM teams)
),
tg AS (
    SELECT league, game_id, season_year, season_type, start_time_utc, venue_city,
           home_team_id AS team_id, away_team_id AS opponent_id, TRUE AS is_home FROM g
    UNION ALL
    SELECT league, game_id, season_year, season_type, start_time_utc, venue_city,
           away_team_id AS team_id, home_team_id AS opponent_id, FALSE AS is_home FROM g
),
d AS (
    -- game day in US/Eastern, the league's calendar
    SELECT *, CAST(timezone('America/New_York', start_time_utc) AS DATE) AS game_date FROM tg
),
w AS (
    SELECT *,
        lag(game_date) OVER ts AS prev_date,
        lag(venue_city) OVER ts AS prev_city,
        count(*) OVER (
            PARTITION BY league, team_id, season_year ORDER BY game_date
            RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING
        ) AS games_last_7_days,
        sum(is_home::INTEGER) OVER (ts ROWS UNBOUNDED PRECEDING) AS home_block
    FROM d
    WINDOW ts AS (PARTITION BY league, team_id, season_year ORDER BY start_time_utc, game_id)
),
ctx AS (
SELECT
    w.game_id, w.team_id, w.opponent_id, w.is_home, w.start_time_utc, w.season_year,
    w.season_type,
    -- least() skips NULLs in DuckDB, so keep the first game's NULL explicitly
    CASE WHEN w.prev_date IS NOT NULL
         THEN least(date_diff('day', w.prev_date, w.game_date), 7) END AS rest_days,
    coalesce(date_diff('day', w.prev_date, w.game_date) = 1, false) AS back_to_back,
    w.games_last_7_days,
    CASE WHEN w.is_home THEN 0 ELSE sum((NOT w.is_home)::INTEGER) OVER (
        PARTITION BY w.league, w.team_id, w.season_year, w.home_block
        ORDER BY w.start_time_utc, w.game_id ROWS UNBOUNDED PRECEDING
    ) END AS road_trip_length,
    round(2 * 6371 * asin(sqrt(
        pow(sin(radians(b.lat - a.lat) / 2), 2)
        + cos(radians(a.lat)) * cos(radians(b.lat)) * pow(sin(radians(b.lon - a.lon) / 2), 2)
    )), 1) AS travel_km,
    w.league
FROM w
LEFT JOIN venue_cities a ON a.city = w.prev_city
LEFT JOIN venue_cities b ON b.city = w.venue_city
)
SELECT * FROM ctx
WHERE (league, team_id) IN (SELECT league, team_id FROM teams WHERE listed);
"""
# Per-league sanity limits for closing lines: (max |spread|, total low, total high). Guards
# against obviously bad lines (e.g. a decimal price parsed as a total). College lines are real
# up to about +-45 points (D1 mismatches) and totals run ~120-195. Owned here so the grading
# view can use them without importing the analysis package; analysis.market re-exports them.
SANE_LIMITS = {"nba": (40, 150, 320), "ncaab": (60, 100, 220)}
_LIMITS_VALUES = ", ".join(
    f"('{lg}', {sp}, {lo}, {hi})" for lg, (sp, lo, hi) in SANE_LIMITS.items()
)

# The prediction_results query, also usable inline on a read-only connection to an older
# warehouse that doesn't have the view yet (deepsports.analysis.record does that).
# Only finals between two listed teams of the game's league (drops All-Star/exhibitions);
# predictions created at or after tip are never graded. Closing spread/total use the same
# per-league sanity filters as the analysis code (SANE_LIMITS; a league without limits gets
# no market columns); market_p_home is the de-vigged closing moneyline.
PREDICTION_RESULTS_SQL = f"""
WITH pre AS (
    SELECT p.* FROM predictions p JOIN games g USING (game_id)
    WHERE p.created_at < g.start_time_utc
    QUALIFY row_number() OVER (
        PARTITION BY p.game_id, p.model, p.model_version ORDER BY p.created_at DESC
    ) = 1
),
lim (league, max_spread, total_lo, total_hi) AS (VALUES {_LIMITS_VALUES}),
closing AS (
    SELECT o.game_id,
           CASE WHEN abs(o.spread_home) <= lim.max_spread THEN o.spread_home END
               AS market_spread_home,
           CASE WHEN o.over_under BETWEEN lim.total_lo AND lim.total_hi THEN o.over_under END
               AS market_total,
           CASE WHEN o.home_moneyline >= 100 THEN 1 + o.home_moneyline / 100.0
                WHEN o.home_moneyline <= -100 THEN 1 + 100.0 / -o.home_moneyline END AS dec_home,
           CASE WHEN o.away_moneyline >= 100 THEN 1 + o.away_moneyline / 100.0
                WHEN o.away_moneyline <= -100 THEN 1 + 100.0 / -o.away_moneyline END AS dec_away
    FROM odds_snapshots o
    JOIN games g ON g.game_id = o.game_id
    LEFT JOIN lim ON lim.league = g.league
    WHERE o.source = 'closing'
    QUALIFY row_number() OVER (PARTITION BY o.game_id ORDER BY o.captured_at DESC) = 1
)
SELECT
    g.game_id, g.league, pre.model, pre.model_version, pre.created_at, g.start_time_utc,
    h.abbreviation AS home_abbr, a.abbreviation AS away_abbr,
    pre.p_home_win, pre.pred_home_margin, pre.pred_total,
    g.home_score, g.away_score,
    g.home_score - g.away_score AS actual_home_margin,
    g.home_score + g.away_score AS actual_total,
    (pre.p_home_win >= 0.5) = (g.home_score > g.away_score) AS winner_correct,
    abs(pre.pred_home_margin - (g.home_score - g.away_score)) AS margin_error,
    abs(pre.pred_total - (g.home_score + g.away_score)) AS total_error,
    c.market_spread_home, c.market_total,
    (1 / c.dec_home) / (1 / c.dec_home + 1 / c.dec_away) AS market_p_home
FROM pre
JOIN games g USING (game_id)
JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id AND h.listed
JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id AND a.listed
LEFT JOIN closing c USING (game_id)
WHERE g.completed AND g.status = 'STATUS_FINAL'
  AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
"""
VIEWS += (
    "\n-- Grading: per final game and (model, model_version), the latest prediction created\n"
    "-- strictly before tip-off, with the result and the closing line.\n"
    "CREATE OR REPLACE VIEW prediction_results AS" + PREDICTION_RESULTS_SQL + ";\n"
)

# Grading for the paper-trade log: finished games only; a bet logged at or after tip, or on a
# line captured after logging, is never graded. CLV is against the latest closing line
# (sanity-filtered like prediction_results; positive = the close moved toward the bet) for
# spread and total bets; NULL for moneyline (only one side's price is logged).
PAPER_RESULTS_SQL = f"""
WITH lim (league, max_spread, total_lo, total_hi) AS (VALUES {_LIMITS_VALUES}),
closing AS (
    SELECT o.game_id,
           CASE WHEN abs(o.spread_home) <= lim.max_spread THEN o.spread_home END
               AS close_spread_home,
           CASE WHEN o.over_under BETWEEN lim.total_lo AND lim.total_hi THEN o.over_under END
               AS close_total,
           o.home_moneyline AS close_home_ml, o.away_moneyline AS close_away_ml
    FROM odds_snapshots o
    JOIN games g ON g.game_id = o.game_id
    LEFT JOIN lim ON lim.league = g.league
    WHERE o.source = 'closing'
    QUALIFY row_number() OVER (PARTITION BY o.game_id ORDER BY o.captured_at DESC) = 1
),
fin AS (
    SELECT b.*, g.season_year, g.season_type, g.home_score, g.away_score,
           g.home_score - g.away_score AS actual_home_margin,
           g.home_score + g.away_score AS actual_total,
           CAST(timezone('America/New_York', g.start_time_utc) AS DATE) AS tip_date,
           h.abbreviation AS home_abbr, a.abbreviation AS away_abbr,
           c.close_spread_home, c.close_total, c.close_home_ml, c.close_away_ml
    FROM paper_bets b
    JOIN games g USING (game_id)
    LEFT JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
    LEFT JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
    LEFT JOIN closing c USING (game_id)
    WHERE g.completed AND g.status = 'STATUS_FINAL'
      AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
      AND b.logged_at < g.start_time_utc AND b.line_captured_at <= b.logged_at
),
res AS (
    SELECT *,
        CASE
            WHEN market = 'spread' THEN CASE
                WHEN actual_home_margin + line = 0 THEN 'push'
                WHEN (actual_home_margin + line > 0) = (side = 'home') THEN 'win'
                ELSE 'loss' END
            WHEN market = 'total' THEN CASE
                WHEN actual_total = line THEN 'push'
                WHEN (actual_total > line) = (side = 'over') THEN 'win'
                ELSE 'loss' END
            WHEN (actual_home_margin > 0) = (side = 'home') THEN 'win'
            ELSE 'loss'
        END AS result,
        CASE
            WHEN market = 'spread' AND side = 'home' THEN line - close_spread_home
            WHEN market = 'spread' THEN close_spread_home - line
            WHEN market = 'total' AND side = 'over' THEN close_total - line
            WHEN market = 'total' THEN line - close_total
        END AS clv
    FROM fin
)
SELECT *,
    CASE result
        WHEN 'win' THEN CASE WHEN price >= 100 THEN stake * price / 100.0
                             WHEN price <= -100 THEN stake * 100.0 / -price
                             ELSE stake END
        WHEN 'push' THEN 0.0
        ELSE -stake
    END AS profit
FROM res
"""
VIEWS += (
    "\n-- Paper-trade grading: per logged bet on a final game, the result, profit and CLV.\n"
    "CREATE OR REPLACE VIEW paper_results AS" + PAPER_RESULTS_SQL + ";\n"
)
VIEW_NAMES = ("pregame_injuries", "team_game_context", "prediction_results", "paper_results")


def _create_sql(table: str, as_name: str | None = None) -> str:
    return f"CREATE TABLE IF NOT EXISTS {as_name or table} ({TABLES[table]})"


SCHEMA = ";\n".join(_create_sql(t) for t in TABLES) + ";\n" + VIEWS


def _table_shape(con, table: str) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """(column names, primary-key columns) of a table, or None if it doesn't exist."""
    cols = con.execute(
        "SELECT column_name FROM duckdb_columns() WHERE table_name = ? AND NOT internal "
        "AND schema_name = 'main' ORDER BY column_index",
        [table],
    ).fetchall()
    if not cols:
        return None
    pk = con.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name = ? AND constraint_type = 'PRIMARY KEY' AND schema_name = 'main'",
        [table],
    ).fetchone()
    return tuple(c[0] for c in cols), tuple(pk[0]) if pk else ()


_EXPECTED: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}


def expected_shapes() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    if not _EXPECTED:
        con = duckdb.connect()
        for t in TABLES:
            con.execute(_create_sql(t))
            _EXPECTED[t] = _table_shape(con, t)
        con.close()
    return _EXPECTED


# Tables without an updated_at column (they carry their own capture/creation time).
NO_UPDATED_AT = {
    "odds_snapshots",
    "injury_captures",
    "injury_reports",
    "predictions",
    "paper_bets",
}
PREDICTION_COLS = (
    "game_id",
    "model",
    "model_version",
    "created_at",
    "p_home_win",
    "pred_home_margin",
    "pred_total",
    "features_json",
)
PAPER_BET_COLS = (
    "rule",
    "rule_version",
    "game_id",
    "league",
    "market",
    "side",
    "line",
    "price",
    "stake",
    "model_value",
    "line_source",
    "line_provider",
    "line_captured_at",
    "logged_at",
    "start_time_utc",
    "inputs_json",
)
# A pregame/opening row is stored only when one of these differs from the game's latest row:
# a juice-only move (same line, new price) counts as a line move (docs/DECISIONS.md 2026-11-06).
ODDS_PRICE_COLS = ("spread_home_price", "spread_away_price", "over_price", "under_price")
ODDS_VALUE_COLS = (
    "provider",
    "spread_home",
    "over_under",
    "home_moneyline",
    "away_moneyline",
    *ODDS_PRICE_COLS,
)
ODDS_COLS = ("game_id", "source", "captured_at", "details", *ODDS_VALUE_COLS)


def is_lock_conflict(exc: BaseException) -> bool:
    """True if a DuckDB open failed because another process holds the file lock.

    Other IOErrors (e.g. macOS "Operation not permitted" on the external drive, seen while a
    macOS update was pending on 2026-11-08) are not transient lock waits and must not be
    reported as "busy"."""
    msg = str(exc)
    return "Could not set lock" in msg or "Conflicting lock" in msg


class Store:
    def __init__(
        self, path: Path | str = config.DB_PATH, read_only: bool = False, lock_wait: float = 15.0
    ):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The API server takes brief read-only connections; wait them out instead of failing.
        deadline = time.monotonic() + lock_wait
        while True:
            try:
                self.con = duckdb.connect(str(path), read_only=read_only)
                break
            except duckdb.IOException as e:
                # Only a lock conflict is worth waiting out; access errors fail at once.
                if not is_lock_conflict(e) or time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        self._types: dict[str, dict[str, str]] = {}
        self._pks: dict[str, tuple[str, ...]] = {}
        # {table: (rows before, rows after)} if opening this writer migrated the schema
        self.migration_report: dict[str, tuple[int, int]] = {}
        if not read_only:
            for t in TABLES:
                self.con.execute(_create_sql(t))
            if self.stale_tables():
                # A warehouse created by older code: rebuild its tables in place (idempotent,
                # every row kept), so any writer command leaves the schema current.
                # `deepsports migrate` does only this step and prints the report.
                self.migration_report = self.migrate()
                log.warning("migrated warehouse schema: %s", self.migration_report)
            self.con.execute(VIEWS)
            self._write(
                "venue_cities",
                [{"city": c, "lat": lat, "lon": lon} for c, (lat, lon) in VENUE_CITIES.items()],
            )

    def close(self) -> None:
        self.con.close()

    # ---------- schema migration ----------

    def stale_tables(self) -> list[str]:
        """Existing tables whose columns or primary key differ from TABLES."""
        expected = expected_shapes()
        return [
            t
            for t in TABLES
            if (shape := _table_shape(self.con, t)) is not None and shape != expected[t]
        ]

    def migrate(self) -> dict[str, tuple[int, int]]:
        """Rebuild tables created by older code to the current definitions in TABLES, keeping
        every row. DuckDB can't change a primary key in place, so each stale table is copied
        into a new one, dropped, and the copy renamed, all in one transaction (any failure
        rolls back everything). New `league` columns are filled from the row's game (all
        legacy rows are NBA; orphans default to 'nba'); other new columns take their default.
        Returns {table: (rows before, rows after)}; empty when nothing was stale (a no-op)."""
        stale = self.stale_tables()
        if not stale:
            return {}
        expected = expected_shapes()
        report: dict[str, tuple[int, int]] = {}
        self.con.execute("BEGIN TRANSACTION")
        try:
            for view in VIEW_NAMES:
                self.con.execute(f"DROP VIEW IF EXISTS {view}")
            for t in stale:
                old_cols = set(_table_shape(self.con, t)[0])
                new_cols, _ = expected[t]
                tmp = f"{t}__migrating"
                self.con.execute(f"DROP TABLE IF EXISTS {tmp}")
                self.con.execute(_create_sql(t, tmp))
                cols, exprs, join = [], [], ""
                for c in new_cols:
                    if c in old_cols:
                        cols.append(c)
                        exprs.append(f"o.{c}")
                    elif c == "league" and "game_id" in old_cols and t != "games":
                        cols.append(c)
                        exprs.append("coalesce(g.league, 'nba')")
                        join = " LEFT JOIN games g ON g.game_id = o.game_id"
                before = self.con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                self.con.execute(
                    f"INSERT INTO {tmp} ({', '.join(cols)}) "
                    f"SELECT {', '.join(exprs)} FROM {t} o{join}"
                )
                after = self.con.execute(f"SELECT count(*) FROM {tmp}").fetchone()[0]
                if after != before:
                    raise RuntimeError(f"migrate {t}: {before} rows before, {after} after")
                self.con.execute(f"DROP TABLE {t}")
                self.con.execute(f"ALTER TABLE {tmp} RENAME TO {t}")
                report[t] = (before, after)
            self.con.execute(VIEWS)
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        self._types.clear()
        self._pks.clear()
        self.con.execute("CHECKPOINT")
        return report

    # ---------- bulk writes ----------

    def _column_types(self, table: str) -> dict[str, str]:
        if table not in self._types:
            rows = self.con.execute(f"DESCRIBE {table}").fetchall()
            self._types[table] = {r[0]: r[1] for r in rows}
        return self._types[table]

    def _primary_key(self, table: str) -> tuple[str, ...]:
        if table not in self._pks:
            shape = _table_shape(self.con, table)
            self._pks[table] = shape[1] if shape else ()
        return self._pks[table]

    def _write(
        self, table: str, rows: list[dict[str, Any]], mode: str = "replace", chunk: int = 20000
    ) -> int:
        """Bulk INSERT [OR REPLACE | OR IGNORE] of row dicts (keys of the first row = columns).

        The rows travel as a single JSON string parameter that DuckDB unpacks with from_json,
        instead of one bound parameter per value: DuckDB's Python binding probes for pandas on
        every bound value (a failed import each time when pandas isn't installed), which made
        executemany ~3 ms/row on a box score. Rows sharing a primary key keep the last one,
        as row-by-row upserts would."""
        if not rows:
            return 0
        cols = list(rows[0].keys())
        pk = self._primary_key(table)
        if pk and all(k in cols for k in pk):
            rows = list({tuple(r[k] for k in pk): r for r in rows}.values())
        types = self._column_types(table)
        struct = json.dumps([{c: types[c] for c in cols}]).replace("'", "''")
        verb = {"replace": "INSERT OR REPLACE", "ignore": "INSERT OR IGNORE", "insert": "INSERT"}
        sql = (
            f"{verb[mode]} INTO {table} ({', '.join(cols)}) "
            f"SELECT {', '.join(f'r.{c}' for c in cols)} "
            f"FROM (SELECT unnest(from_json(?::JSON, '{struct}')) AS r)"
        )
        for i in range(0, len(rows), chunk):
            part = rows[i : i + chunk]
            payload = json.dumps([{c: r[c] for c in cols} for r in part], default=_jsonable)
            self.con.execute(sql, [payload])
        return len(rows)

    def _upsert(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        if table not in NO_UPDATED_AT:
            now = datetime.now(UTC)
            rows = [{**r, "updated_at": now} for r in rows]
        return self._write(table, rows)

    def upsert_teams(self, rows: Iterable[dict[str, Any]]) -> int:
        return self._upsert("teams", rows)

    def add_discovered_teams(self, rows: Iterable[dict[str, Any]]) -> int:
        """Teams seen on a scoreboard (`listed = false`): insert only those not stored yet, so
        a row from the league's team list is never downgraded."""
        rows = list(rows)
        if not rows:
            return 0
        now = datetime.now(UTC)
        return self._write("teams", [{**r, "updated_at": now} for r in rows], mode="ignore")

    def team_count(self, league: str = "nba") -> int:
        return self.con.execute("SELECT count(*) FROM teams WHERE league = ?", [league]).fetchone()[
            0
        ]

    def upsert_games(self, rows: Iterable[dict[str, Any]]) -> int:
        return self._upsert("games", rows)

    def upsert_team_stats(self, rows: Iterable[dict[str, Any]]) -> int:
        return self._upsert("team_game_stats", rows)

    def upsert_player_stats(self, rows: Iterable[dict[str, Any]]) -> int:
        return self._upsert("player_game_stats", rows)

    def add_odds(self, rows: Iterable[dict[str, Any]]) -> int:
        """Pregame odds form a time series, but only store a snapshot when the line moved.
        Closing odds keep one row per game. Missing columns (e.g. prices) are stored as NULL."""
        rows = [{c: r.get(c) for c in ODDS_COLS} for r in rows]
        closing = [r for r in rows if r["source"] == "closing"]
        pregame = [r for r in rows if r["source"] != "closing"]
        kept = []
        if closing:
            ids = sorted({r["game_id"] for r in closing})
            self.con.execute(
                "DELETE FROM odds_snapshots WHERE source = 'closing' AND list_contains(?, game_id)",
                [ids],
            )
            kept += closing
        if pregame:
            ids = sorted({r["game_id"] for r in pregame})
            last = {
                (g, src): tuple(vals)
                for g, src, *vals in self.con.execute(
                    f"SELECT game_id, source, {', '.join(ODDS_VALUE_COLS)} FROM odds_snapshots "
                    "WHERE source <> 'closing' AND list_contains(?, game_id) "
                    "QUALIFY row_number() OVER "
                    "(PARTITION BY game_id, source ORDER BY captured_at DESC) = 1",
                    [ids],
                ).fetchall()
            }
            for r in sorted(pregame, key=lambda r: r["captured_at"]):
                key, vals = (r["game_id"], r["source"]), tuple(r[c] for c in ODDS_VALUE_COLS)
                if last.get(key) != vals:
                    kept.append(r)
                    last[key] = vals
        return self._upsert("odds_snapshots", kept)

    def odds_missing_prices(self, league: str) -> list[dict[str, Any]]:
        """Opening/closing odds rows of `league` with at least one NULL price, with the game's
        start time (input for `deepsports prices-backfill`)."""
        cols = ", ".join(f"o.{c}" for c in ODDS_COLS)
        cur = self.con.execute(
            f"""
            SELECT {cols}, g.start_time_utc FROM odds_snapshots o JOIN games g USING (game_id)
            WHERE g.league = ? AND o.source IN ('opening', 'closing')
              AND ({" OR ".join(f"o.{c} IS NULL" for c in ODDS_PRICE_COLS)})
            ORDER BY o.game_id, o.source
            """,
            [league],
        )
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]

    def fill_odds_prices(self, rows: Iterable[dict[str, Any]]) -> int:
        """Fill NULL prices on existing odds rows, keyed by (game_id, source, captured_at).
        Each row carries the line values it was matched against: a stored row whose line has
        changed since is left alone, a non-NULL price is never overwritten, and no row is
        inserted. Idempotent. Returns the number of rows changed."""
        keys = ("game_id", "source", "captured_at", *LINE_MATCH_COLS)
        rows = [{c: r.get(c) for c in (*keys, *ODDS_PRICE_COLS)} for r in rows]
        if not rows:
            return 0
        self.con.execute("DROP TABLE IF EXISTS _price_fill")
        self.con.execute(
            "CREATE TEMP TABLE _price_fill AS SELECT "
            + ", ".join(f"{c}" for c in (*keys, *ODDS_PRICE_COLS))
            + " FROM odds_snapshots LIMIT 0"
        )
        self.con.executemany(
            f"INSERT INTO _price_fill VALUES ({', '.join('?' * (len(keys) + 4))})",
            [list(r.values()) for r in rows],
        )
        some_null = " OR ".join(f"o.{c} IS NULL" for c in ODDS_PRICE_COLS)
        some_new = " OR ".join(f"(o.{c} IS NULL AND f.{c} IS NOT NULL)" for c in ODDS_PRICE_COLS)
        where = (
            "o.game_id = f.game_id AND o.source = f.source AND o.captured_at = f.captured_at AND "
            + " AND ".join(f"o.{c} IS NOT DISTINCT FROM f.{c}" for c in LINE_MATCH_COLS)
            + f" AND ({some_null}) AND ({some_new})"
        )
        n = self.con.execute(f"SELECT count(*) FROM odds_snapshots o, _price_fill f WHERE {where}")
        changed = n.fetchone()[0]
        sets = ", ".join(f"{c} = coalesce(o.{c}, f.{c})" for c in ODDS_PRICE_COLS)
        self.con.execute(f"UPDATE odds_snapshots o SET {sets} FROM _price_fill f WHERE {where}")
        self.con.execute("DROP TABLE _price_fill")
        return changed

    def games_missing_boxscores(self, limit: int | None = None, league: str = "nba") -> list[str]:
        sql = """
            SELECT g.game_id FROM games g
            WHERE g.league = ? AND g.completed AND g.status = 'STATUS_FINAL'
              AND NOT EXISTS (SELECT 1 FROM team_game_stats t WHERE t.game_id = g.game_id)
            ORDER BY g.start_time_utc
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [r[0] for r in self.con.execute(sql, [league]).fetchall()]

    def games_needing_core_odds(
        self, include_opening: bool = False, limit: int | None = None, league: str = "nba"
    ) -> list[tuple[str, Any, bool]]:
        """Final games lacking a closing line (or, with include_opening, an opening line).
        Returns (game_id, start_time_utc, has_closing)."""
        want = "has_opening" if include_opening else "has_closing"
        sql = f"""
            WITH o AS (
                SELECT game_id,
                       bool_or(source = 'closing') AS has_closing,
                       bool_or(source = 'opening') AS has_opening
                FROM odds_snapshots GROUP BY game_id
            )
            SELECT g.game_id, g.start_time_utc, coalesce(o.has_closing, false)
            FROM games g LEFT JOIN o USING (game_id)
            WHERE g.league = ? AND g.completed AND g.status = 'STATUS_FINAL'
              AND NOT coalesce(o.{want}, false)
            ORDER BY g.start_time_utc
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.con.execute(sql, [league]).fetchall()

    def upcoming_games(
        self,
        start: datetime,
        end: datetime,
        team_abbrs: list[str] | None = None,
        league: str = "nba",
    ) -> list[dict[str, Any]]:
        """Not-yet-started games in [start, end) for one league, optionally only those involving
        the given team abbreviations (abbreviations are unique within a league)."""
        sql = """
            WITH latest_odds AS (
                SELECT * FROM odds_snapshots WHERE source = 'pregame'
                QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) = 1
            )
            SELECT g.game_id, g.league, g.start_time_utc, g.status, g.venue, g.venue_city,
                   g.neutral_site, g.broadcasts,
                   h.abbreviation AS home_abbr, h.display_name AS home_name,
                   a.abbreviation AS away_abbr, a.display_name AS away_name,
                   o.details AS odds_details, o.spread_home, o.over_under,
                   o.home_moneyline, o.away_moneyline, o.provider AS odds_provider
            FROM games g
            JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
            JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
            LEFT JOIN latest_odds o ON o.game_id = g.game_id
            WHERE g.league = ? AND g.state = 'pre' AND g.start_time_utc >= ?
              AND g.start_time_utc < ?
        """
        params: list[Any] = [league, start, end]
        if team_abbrs:
            marks = ", ".join("?" for _ in team_abbrs)
            sql += f" AND (h.abbreviation IN ({marks}) OR a.abbreviation IN ({marks}))"
            params += team_abbrs + team_abbrs
        sql += " ORDER BY g.start_time_utc, g.game_id"
        cur = self.con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def add_injuries(
        self, reports: Iterable[dict[str, Any]], captures: Iterable[dict[str, Any]]
    ) -> int:
        """Store injury snapshots. Re-adding the same (game, team, captured_at) replaces that
        team's snapshot, dropping players no longer listed (idempotent). Returns the number
        of injury rows written."""
        captures = {(c["game_id"], c["team_id"], c["captured_at"]): c for c in captures}
        reports = {(r["game_id"], r["athlete_id"], r["captured_at"]): r for r in reports}
        if captures:
            self.con.execute(
                "CREATE OR REPLACE TEMP TABLE _capture_keys "
                "(game_id VARCHAR, team_id VARCHAR, captured_at TIMESTAMPTZ)"
            )
            self._write(
                "_capture_keys",
                [{"game_id": g, "team_id": t, "captured_at": c} for g, t, c in captures],
                mode="insert",
            )
            self.con.execute(
                "DELETE FROM injury_reports WHERE (game_id, team_id, captured_at) IN "
                "(SELECT game_id, team_id, captured_at FROM _capture_keys)"
            )
            self.con.execute("DROP TABLE _capture_keys")
            self._types.pop("_capture_keys", None)
            self._pks.pop("_capture_keys", None)
        self._write("injury_captures", list(captures.values()))
        return self._write("injury_reports", list(reports.values()))

    def games_for_injury_snapshot(
        self,
        start: datetime,
        end: datetime,
        league: str = "nba",
        team_abbrs: list[str] | None = None,
    ) -> list[tuple[str, Any]]:
        """Not-yet-started games tipping off in [start, end): (game_id, start_time_utc),
        optionally only games involving the given team abbreviations."""
        sql = """
            SELECT g.game_id, g.start_time_utc FROM games g
            LEFT JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
            LEFT JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
            WHERE g.league = ? AND g.state = 'pre'
              AND g.start_time_utc >= ? AND g.start_time_utc < ?
        """
        params: list[Any] = [league, start, end]
        if team_abbrs:
            sql += " AND (list_contains(?, h.abbreviation) OR list_contains(?, a.abbreviation))"
            params += [list(team_abbrs), list(team_abbrs)]
        sql += " ORDER BY g.start_time_utc, g.game_id"
        return self.con.execute(sql, params).fetchall()

    def add_predictions(self, rows: Iterable[dict[str, Any]]) -> int:
        """Upsert on (game_id, model, model_version). `features_json` may be a dict (dumped
        to JSON) or a string; `created_at` defaults to now."""
        now = datetime.now(UTC)
        clean = []
        for r in rows:
            unknown = set(r) - set(PREDICTION_COLS)
            if unknown:
                raise ValueError(f"unknown prediction columns: {sorted(unknown)}")
            row = {c: r.get(c) for c in PREDICTION_COLS}
            row["created_at"] = row["created_at"] or now
            if row["features_json"] is not None and not isinstance(row["features_json"], str):
                row["features_json"] = json.dumps(row["features_json"], sort_keys=True, default=str)
            clean.append(row)
        return self._upsert("predictions", clean)

    def latest_predictions(
        self,
        game_ids: Iterable[str],
        include_early: bool = True,
        exclude_versions: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        """The most recently created prediction per (game_id, model). `include_early=False`
        leaves out early-season college versions (`*-early`), and `exclude_versions` those
        versions (e.g. config.HIDDEN_MODEL_VERSIONS), before picking the latest."""
        ids = list(game_ids)
        if not ids:
            return []
        hidden = list(exclude_versions)
        early = "" if include_early else "AND model_version NOT LIKE '%-early'"
        if hidden:
            early += f" AND model_version NOT IN ({', '.join('?' for _ in hidden)})"
        cur = self.con.execute(
            f"""SELECT {", ".join(PREDICTION_COLS)} FROM predictions
                WHERE game_id IN ({", ".join("?" for _ in ids)}) {early}
                QUALIFY row_number() OVER (
                    PARTITION BY game_id, model ORDER BY created_at DESC, model_version DESC
                ) = 1
                ORDER BY game_id, model""",
            [*ids, *hidden],
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def add_paper_bets(self, rows: Iterable[dict[str, Any]]) -> int:
        """Insert-only: a (rule, game_id, market) already logged keeps its first row (a frozen
        bet is never updated). `inputs_json` may be a dict. Returns the number of new rows."""
        clean = []
        for r in rows:
            unknown = set(r) - set(PAPER_BET_COLS)
            if unknown:
                raise ValueError(f"unknown paper_bets columns: {sorted(unknown)}")
            row = {c: r.get(c) for c in PAPER_BET_COLS}
            if row["inputs_json"] is not None and not isinstance(row["inputs_json"], str):
                row["inputs_json"] = json.dumps(row["inputs_json"], sort_keys=True, default=str)
            clean.append(row)
        if not clean:
            return 0
        count = "SELECT count(*) FROM paper_bets"
        before = self.con.execute(count).fetchone()[0]
        # first row per key wins within the batch too (_write keeps the last one)
        first = {(r["rule"], r["game_id"], r["market"]): r for r in reversed(clean)}
        self._write("paper_bets", list(first.values()), mode="ignore")
        return self.con.execute(count).fetchone()[0] - before

    def has_table(self, name: str) -> bool:
        """Read-only connections never run SCHEMA, so newer tables may not exist yet."""
        return bool(
            self.con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
            ).fetchone()[0]
        )

    def log_run(self, row: dict[str, Any]) -> None:
        cols = list(row.keys())
        self.con.execute(
            f"INSERT INTO ingest_runs ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [row[c] for c in cols],
        )

    def counts(self) -> dict[str, int]:
        tables = ["teams", "games", "team_game_stats", "player_game_stats", "odds_snapshots"]
        # absent until a writer applies SCHEMA
        optional = ["injury_reports", "predictions", "paper_bets"]
        tables += [t for t in optional if self.has_table(t)]
        return {t: self.con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
