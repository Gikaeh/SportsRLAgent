"""Data-quality checks over the warehouse. `deepsports check` runs them all.

Queries take the league from `games` (never from child tables) so they also run on a
read-only open of a warehouse that hasn't been migrated yet."""

from dataclasses import dataclass

from deepsports.store import Store

FINAL = "g.completed AND g.status = 'STATUS_FINAL'"

# Final games whose ESPN summary returns HTTP 404 (checked 2026-11-03, see DATA_SOURCES.md).
KNOWN_NO_BOXSCORE = frozenset(
    {"401869391", "401869377", "401869373", "401869402",
     "401871334", "401871154", "401871337", "401873343"}
)  # fmt: skip

# College team-games (game_id, team_id) whose ESPN raw box disagrees with the score by more
# than 2 points; the stored rows match the raw summaries (checked 2026-11-05, DATA_SOURCES.md).
# Keyed by team-game so any new mismatch, including the other team of the same game, still fails.
KNOWN_POINTS_MISMATCH = frozenset(
    {("401597895", "3169"), ("401597922", "2893"), ("401608976", "2726"),
     ("401720664", "2491"), ("401722030", "130198"), ("401722338", "62"),
     ("401727325", "2565")}
)  # fmt: skip


@dataclass
class Check:
    name: str
    failures: int
    detail: str
    hard: bool = True  # hard failures make `deepsports check` exit 1


def run_checks(db: Store) -> list[Check]:
    q = db.con.execute
    checks = []

    known = ", ".join(f"'{g}'" for g in sorted(KNOWN_NO_BOXSCORE)) or "''"
    missing = f"""
        SELECT g.game_id FROM games g WHERE {FINAL} AND
            (SELECT count(*) FROM team_game_stats t WHERE t.game_id = g.game_id) <> 2"""
    n = q(f"SELECT count(*) FROM ({missing}) m WHERE m.game_id NOT IN ({known})").fetchone()[0]
    checks.append(Check("final games with 2 team box scores", n, f"{n} games missing/extra rows"))
    n = q(f"SELECT count(*) FROM ({missing}) m WHERE m.game_id IN ({known})").fetchone()[0]
    checks.append(Check("known ESPN gaps: no box score (summary 404)", n, f"{n} games", hard=False))

    # Team-games whose player points don't add up to the score. Hard only for real
    # (regular/post-season) games where ESPN identified every player. Upstream gaps: preseason
    # boxes with all-zero points, boxes with an unidentified player, and college boxes off by
    # <= 2 points (ESPN college scorekeeping slips, verified in the raw summaries, ~0.1%).
    mismatch = f"""
        SELECT g.game_id, p.team_id, g.season_type, g.league,
               bool_or(p.athlete_id LIKE 'noid:%') AS has_noid,
               sum(p.pts) AS s,
               CASE WHEN p.team_id = g.home_team_id THEN g.home_score ELSE g.away_score END AS score
        FROM games g JOIN player_game_stats p USING (game_id) WHERE {FINAL}
        GROUP BY g.game_id, p.team_id, g.season_type, g.league, g.home_team_id, g.home_score,
                 g.away_score
        HAVING s <> score"""
    listed = ", ".join(f"('{g}', '{t}')" for g, t in sorted(KNOWN_POINTS_MISMATCH))
    known_gap = (
        "(m.season_type = 1 OR m.has_noid OR (m.league = 'ncaab' AND abs(m.s - m.score) <= 2)"
        + (f" OR (m.game_id, m.team_id) IN ({listed})" if listed else "")
        + ")"
    )
    n = q(f"SELECT count(*) FROM ({mismatch}) m WHERE NOT {known_gap}").fetchone()[0]
    checks.append(Check("player points sum to team score", n, f"{n} team-games mismatch"))
    n = q(f"SELECT count(*) FROM ({mismatch}) m WHERE {known_gap}").fetchone()[0]
    checks.append(
        Check(
            "known ESPN gaps: points don't add up",
            n,
            f"{n} team-games (preseason boxes without points, an unidentified player, "
            f"a college box off by <= 2, or one of {len(KNOWN_POINTS_MISMATCH)} listed "
            "college boxes ESPN got wrong)",
            hard=False,
        )
    )

    n = q("""
        SELECT count(*) FROM games g WHERE
            (g.league, g.home_team_id) NOT IN (SELECT league, team_id FROM teams)
            OR (g.league, g.away_team_id) NOT IN (SELECT league, team_id FROM teams)
    """).fetchone()[0]
    checks.append(
        Check("games reference known teams", n, f"{n} games (often All-Star/exhibitions)", False)
    )

    n = q(
        f"SELECT count(*) FROM games g WHERE {FINAL} AND (home_score IS NULL OR away_score IS NULL)"
    ).fetchone()[0]
    checks.append(Check("final games have scores", n, f"{n} games"))

    rows = q(f"""SELECT g.league, g.season_year,
                    count(*) AS games,
                    count(*) FILTER (WHERE EXISTS (SELECT 1 FROM odds_snapshots o
                        WHERE o.game_id = g.game_id AND o.source = 'closing')) AS with_close
                 FROM games g WHERE {FINAL} AND g.season_type IN (2, 3, 5)
                 GROUP BY 1, 2 ORDER BY g.league <> 'nba', 1, 2""").fetchall()
    for league, season, games, with_close in rows:
        missing = games - with_close
        pct = 100 * with_close / games if games else 0
        checks.append(
            Check(
                f"closing-line coverage {_label(league, season)}",
                missing,
                f"{with_close}/{games} regular+postseason games ({pct:.0f}%)",
                False,
            )
        )
    checks += injury_coverage(db)
    return checks


def _label(league: str, season: int) -> str:
    """2026 -> '2025-26' (NBA, unchanged names) or 'ncaab 2025-26'."""
    label = f"{season - 1}-{str(season)[2:]}"
    return label if league == "nba" else f"{league} {label}"


def injury_coverage(db: Store) -> list[Check]:
    """Soft: per season, how many final games have a pre-tip injury snapshot for both teams.
    Only games after the league's first pre-tip snapshot count as gaps: earlier seasons can't
    be captured retroactively (post-game summaries show fetch-time injuries). Leagues with no
    snapshots at all (college: ESPN publishes no college injury reports) are skipped."""
    if not db.has_table("injury_captures"):  # read-only open of a warehouse not yet migrated
        return [Check("injury coverage", 0, "injury tables not created yet", False)]
    rows = db.con.execute(f"""
        WITH c AS (
            SELECT game_id,
                   count(DISTINCT team_id) FILTER (WHERE captured_before_tip) AS pre_teams,
                   count(*) > 0 AS any_capture
            FROM injury_captures GROUP BY 1
        ),
        first_pre AS (
            SELECT g.league, min(i.captured_at) AS t
            FROM injury_captures i JOIN games g USING (game_id)
            WHERE i.captured_before_tip GROUP BY 1
        )
        SELECT g.league, g.season_year,
               count(*) AS games,
               count(*) FILTER (WHERE c.pre_teams = 2) AS with_pre,
               count(*) FILTER (WHERE c.any_capture) AS with_any,
               count(*) FILTER (WHERE coalesce(c.pre_teams, 0) < 2
                                  AND g.start_time_utc > f.t) AS gaps
        FROM games g LEFT JOIN c USING (game_id) LEFT JOIN first_pre f USING (league)
        WHERE {FINAL} AND g.season_type IN (2, 3, 5)
          AND (g.league = 'nba' OR f.t IS NOT NULL)
        GROUP BY 1, 2 ORDER BY g.league <> 'nba', 1, 2""").fetchall()
    checks = []
    for league, season, games, with_pre, with_any, gaps in rows:
        pct = 100 * with_pre / games if games else 0
        checks.append(
            Check(
                f"pre-tip injury coverage {_label(league, season)}",
                gaps,
                f"{with_pre}/{games} games ({pct:.0f}%) with a pre-tip snapshot for both teams; "
                f"{with_any} with any capture; {gaps} gaps since snapshots began",
                False,
            )
        )
    return checks
