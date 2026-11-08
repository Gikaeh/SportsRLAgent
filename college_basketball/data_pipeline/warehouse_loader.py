"""Read men's D1 college basketball games from the DeepSports DuckDB warehouse.

SportsRLAgent has no college fetcher of its own: DeepSports already collects this
data (ESPN), so this reads it read-only. It never writes to the warehouse and never
reads the betting-line tables, so market data cannot reach the features.
"""
import os
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WAREHOUSE = ROOT / 'DeepSports' / 'data' / 'deepsports.duckdb'
LOCK_WAIT_SECONDS = 120

GAMES_SQL = """
SELECT g.game_id, g.season_year, g.season_type,
       timezone('UTC', g.start_time_utc) AS start_time,
       g.state, g.completed, g.neutral_site,
       g.home_team_id, g.away_team_id, g.home_score, g.away_score,
       h.abbreviation AS home_abbr, a.abbreviation AS away_abbr,
       h.display_name AS home_name, a.display_name AS away_name,
       h.listed AS home_listed, a.listed AS away_listed
FROM games g
JOIN teams h ON h.team_id = g.home_team_id AND h.league = g.league
JOIN teams a ON a.team_id = g.away_team_id AND a.league = g.league
WHERE g.league = 'ncaab'
  AND ((g.completed AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL)
       OR g.state = 'pre')
ORDER BY start_time, g.game_id
"""

TEAM_STATS_SQL = """
SELECT game_id, team_id, fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, reb, ast, stl, blk, tov, pf
FROM team_game_stats WHERE league = 'ncaab'
"""

PLAYER_STATS_SQL = """
SELECT game_id, team_id, athlete_id, minutes, pts, plus_minus
FROM player_game_stats
WHERE league = 'ncaab' AND NOT coalesce(did_not_play, FALSE) AND minutes > 0
"""


def warehousePath():
    return Path(os.environ.get('COLLEGE_WAREHOUSE_DB', DEFAULT_WAREHOUSE))


def connectReadOnly(path=None, lock_wait=LOCK_WAIT_SECONDS):
    """A running DeepSports job holds the writer lock, so wait instead of failing."""
    path = Path(path) if path else warehousePath()
    if not path.exists():
        raise FileNotFoundError(f"College warehouse not found: {path} (external drive not mounted?)")
    deadline = time.monotonic() + lock_wait
    while True:
        try:
            return duckdb.connect(str(path), read_only=True)
        except duckdb.IOException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)


def loadCollegeData(path=None):
    """Returns (games, team_stats, player_stats) as dataframes."""
    con = connectReadOnly(path)
    try:
        games = con.execute(GAMES_SQL).df()
        team_stats = con.execute(TEAM_STATS_SQL).df()
        player_stats = con.execute(PLAYER_STATS_SQL).df()
    finally:
        con.close()
    return games, team_stats, player_stats
