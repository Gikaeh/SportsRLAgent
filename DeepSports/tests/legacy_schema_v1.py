"""The warehouse schema as of 2026-11-03, before league-scoped team keys (copied verbatim from
store.py). Tests build a database with it to exercise `Store.migrate()`."""

LEGACY_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS teams (
    team_id VARCHAR PRIMARY KEY,
    league VARCHAR NOT NULL,
    abbreviation VARCHAR NOT NULL,
    display_name VARCHAR NOT NULL,
    location VARCHAR,
    name VARCHAR,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    game_id VARCHAR PRIMARY KEY,
    league VARCHAR NOT NULL,
    season_year INTEGER NOT NULL,      -- ESPN convention: 2027 = the 2026-27 season
    season_type INTEGER NOT NULL,      -- 1 preseason, 2 regular, 3 postseason, 5 play-in
    start_time_utc TIMESTAMPTZ NOT NULL,
    status VARCHAR NOT NULL,           -- e.g. STATUS_SCHEDULED, STATUS_FINAL, STATUS_POSTPONED
    state VARCHAR NOT NULL,            -- pre | in | post
    completed BOOLEAN NOT NULL,
    home_team_id VARCHAR NOT NULL,
    away_team_id VARCHAR NOT NULL,
    home_score INTEGER,
    away_score INTEGER,
    venue VARCHAR,
    venue_city VARCHAR,
    neutral_site BOOLEAN,
    attendance INTEGER,
    broadcasts VARCHAR,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS team_game_stats (
    game_id VARCHAR NOT NULL,
    team_id VARCHAR NOT NULL,
    home_away VARCHAR,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER,
    tov INTEGER, pf INTEGER,
    points_off_turnovers INTEGER, fast_break_points INTEGER, points_in_paint INTEGER,
    largest_lead INTEGER,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (game_id, team_id)
);

CREATE TABLE IF NOT EXISTS player_game_stats (
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
    PRIMARY KEY (game_id, athlete_id)
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    game_id VARCHAR NOT NULL,
    source VARCHAR NOT NULL,           -- pregame (scoreboard, repeated) | closing (summary)
    captured_at TIMESTAMPTZ NOT NULL,
    provider VARCHAR,
    details VARCHAR,
    spread_home DOUBLE,                -- negative = home team favored
    over_under DOUBLE,
    home_moneyline INTEGER,
    away_moneyline INTEGER,
    PRIMARY KEY (game_id, source, captured_at)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    command VARCHAR NOT NULL,
    network_requests INTEGER,
    games_upserted INTEGER,
    boxscores_upserted INTEGER,
    errors INTEGER,
    notes VARCHAR
);

-- One row per team per summary fetch: lets "no injuries listed" be told apart from "not
-- captured". ESPN's injury list reflects the fetch time, so only captured_before_tip rows are
-- usable as pre-game information (docs/DATA_SOURCES.md).
CREATE TABLE IF NOT EXISTS injury_captures (
    game_id VARCHAR NOT NULL,
    team_id VARCHAR NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    captured_before_tip BOOLEAN NOT NULL,
    n_listed INTEGER NOT NULL,
    PRIMARY KEY (game_id, team_id, captured_at)
);

CREATE TABLE IF NOT EXISTS injury_reports (
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
    PRIMARY KEY (game_id, athlete_id, captured_at)
);

CREATE TABLE IF NOT EXISTS predictions (
    game_id VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    p_home_win DOUBLE,
    pred_home_margin DOUBLE,
    pred_total DOUBLE,
    features_json VARCHAR,
    PRIMARY KEY (game_id, model, model_version)
);

-- Static: seeded from deepsports/venues.py on every writer open.
CREATE TABLE IF NOT EXISTS venue_cities (
    city VARCHAR PRIMARY KEY,
    lat DOUBLE NOT NULL,
    lon DOUBLE NOT NULL
);

-- The latest pre-tip injury snapshot per game and team.
CREATE OR REPLACE VIEW pregame_injuries AS
WITH last AS (
    SELECT game_id, team_id, max(captured_at) AS captured_at
    FROM injury_captures WHERE captured_before_tip GROUP BY ALL
)
SELECT r.* FROM injury_reports r JOIN last USING (game_id, team_id, captured_at);

-- Schedule context per team per game, computed only from the team's earlier games.
CREATE OR REPLACE VIEW team_game_context AS
WITH g AS (
    SELECT * FROM games
    WHERE season_type IN (2, 3, 5)
      AND status NOT IN ('STATUS_POSTPONED', 'STATUS_CANCELED')
      AND home_team_id IN (SELECT team_id FROM teams)
      AND away_team_id IN (SELECT team_id FROM teams)
),
tg AS (
    SELECT game_id, season_year, season_type, start_time_utc, venue_city,
           home_team_id AS team_id, away_team_id AS opponent_id, TRUE AS is_home FROM g
    UNION ALL
    SELECT game_id, season_year, season_type, start_time_utc, venue_city,
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
            PARTITION BY team_id, season_year ORDER BY game_date
            RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING
        ) AS games_last_7_days,
        sum(is_home::INTEGER) OVER (ts ROWS UNBOUNDED PRECEDING) AS home_block
    FROM d
    WINDOW ts AS (PARTITION BY team_id, season_year ORDER BY start_time_utc, game_id)
)
SELECT
    w.game_id, w.team_id, w.opponent_id, w.is_home, w.start_time_utc, w.season_year,
    w.season_type,
    -- least() skips NULLs in DuckDB, so keep the first game's NULL explicitly
    CASE WHEN w.prev_date IS NOT NULL
         THEN least(date_diff('day', w.prev_date, w.game_date), 7) END AS rest_days,
    coalesce(date_diff('day', w.prev_date, w.game_date) = 1, false) AS back_to_back,
    w.games_last_7_days,
    CASE WHEN w.is_home THEN 0 ELSE sum((NOT w.is_home)::INTEGER) OVER (
        PARTITION BY w.team_id, w.season_year, w.home_block
        ORDER BY w.start_time_utc, w.game_id ROWS UNBOUNDED PRECEDING
    ) END AS road_trip_length,
    round(2 * 6371 * asin(sqrt(
        pow(sin(radians(b.lat - a.lat) / 2), 2)
        + cos(radians(a.lat)) * cos(radians(b.lat)) * pow(sin(radians(b.lon - a.lon) / 2), 2)
    )), 1) AS travel_km
FROM w
LEFT JOIN venue_cities a ON a.city = w.prev_city
LEFT JOIN venue_cities b ON b.city = w.venue_city;
"""
