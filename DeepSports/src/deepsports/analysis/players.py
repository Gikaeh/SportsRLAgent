"""Player-availability and top-N player features (model v1.1), from box scores only.

Per team per game, using only that team's games that finished before this game's tip (the
caller, `build_features`, feeds history through the same FINISH_LAG queue as team form):

1. **Rotation:** rank the team's players by minutes per game over the team's last
   `PLAYER_WINDOW` games this season (a game the player missed counts as 0 minutes). The game
   being predicted is never used to select or rank players.
2. **Availability:** among the top-6 (and top-3): how many did not play in the team's previous
   game, how many missed at least 2 of the last 3, the missing-minutes share (the absent
   top-6 players' mpg / the top-6's total mpg), and the games since each top-3 player last
   played (capped at `SINCE_CAP`). "Did not play" = absent from the box score or
   `did_not_play` is true.
3. **Quality:** per-game plus-minus summed over the top-6, top-3 points per game, the spread
   (std) of the top-6's points per game, and the top-6 plus-minus counting only players who
   played the previous game. Per-game rates use games played, shrunk by `PLAYER_SHRINK`
   prior games (plus-minus toward 0, points toward `PTS_PRIOR`) so a player with one game in
   the window doesn't get a wild rate. Shrinking minutes would not change the ranking or the
   missing share (both use a common denominator), so mpg is not shrunk.

A team game with no player rows at all (a missing box score) is skipped, not treated as
"everyone missed it". Before a team's first game of a season every value is NaN (imputed).

Injury hook (OFF by default and always OFF in the backtest, since there is no pre-tip history
before 2026-11-03): with `injury_override`, a scheduled game whose team has a pre-tip snapshot
in `pregame_injuries` uses the snapshot instead of "played last game": a top-6 player counts
as missing iff he is listed `Out`. The 2-of-3 and games-since values stay history-based.
"""

import math
import statistics
from collections import defaultdict, deque

import duckdb

PLAYER_WINDOW = 10  # team games in the rotation window
TOP_N = 6
TOP_K = 3
PLAYER_SHRINK = 2.0  # prior weight, in games played, for per-game pts / plus-minus
PTS_PRIOR = 10.0  # points per game a rotation player is shrunk toward
SINCE_CAP = 5  # games since last played is capped here

# Home - away differences (win and margin models).
PLAYER_DIFF_FEATURES = [
    "top6_out_last_diff",  # top-6 players who did not play the previous game
    "top3_out_last_diff",
    "top6_out_2of3_diff",  # top-6 players who missed >= 2 of the last 3 games
    "miss_share_diff",  # missing-minutes share of the top-6 (previous game)
    "top3_since_diff",  # sum over the top-3 of games since last played (capped)
    "top6_pm_diff",  # sum of the top-6's per-game plus-minus
    "top3_pts_diff",  # sum of the top-3's points per game
    "top6_pts_std_diff",  # std of the top-6's points per game (lower = deeper)
    "avail_top6_pm_diff",  # top-6 plus-minus, only players who played the previous game
]
# Both teams combined (total model).
PLAYER_SUM_FEATURES = ["miss_share_sum", "top3_pts_sum"]
PLAYER_FEATURES = PLAYER_DIFF_FEATURES + PLAYER_SUM_FEATURES

TEAM_KEYS = (
    "top6_out_last",
    "top3_out_last",
    "top6_out_2of3",
    "miss_share",
    "top3_since",
    "top6_pm",
    "top3_pts",
    "top6_pts_std",
    "avail_top6_pm",
)

assert [f"{k}_diff" for k in TEAM_KEYS] == PLAYER_DIFF_FEATURES

# One player line in one game: (played, minutes, pts, plus_minus).
Line = tuple[bool, float, float, float]


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    q = "SELECT count(*) FROM information_schema.tables WHERE table_name = ?"
    return con.execute(q, [name]).fetchone()[0] > 0


def player_box(
    con: duckdb.DuckDBPyConnection, league: str = "nba"
) -> dict[tuple[str, str], dict[str, Line]]:
    """(game_id, team_id) -> {athlete_id: (played, minutes, pts, plus_minus)} for `league`.
    A row with did_not_play false but NULL minutes (a few hundred) counts as played, 0 min."""
    if not _table_exists(con, "player_game_stats"):
        return {}
    rows = con.execute(
        """SELECT game_id, team_id, athlete_id, coalesce(did_not_play, false),
                  minutes, pts, plus_minus
           FROM player_game_stats WHERE league = ?""",
        [league],
    ).fetchall()
    out: dict[tuple[str, str], dict[str, Line]] = defaultdict(dict)
    for g, t, a, dnp, mins, pts, pm in rows:
        played = not dnp
        out[(g, t)][a] = (
            played,
            float(mins or 0) if played else 0.0,
            float(pts or 0) if played else 0.0,
            float(pm or 0) if played else 0.0,
        )
    return dict(out)


def pregame_out(
    con: duckdb.DuckDBPyConnection, league: str = "nba"
) -> dict[tuple[str, str], set[str]]:
    """(game_id, team_id) -> athlete_ids listed Out in the latest pre-tip snapshot. A team with
    a snapshot but nobody Out maps to an empty set (snapshot exists, nobody missing)."""
    if not (_table_exists(con, "pregame_injuries") and _table_exists(con, "injury_captures")):
        return {}
    caps = con.execute(
        """SELECT game_id, team_id FROM injury_captures WHERE captured_before_tip
           AND league = ? GROUP BY ALL""",
        [league],
    ).fetchall()
    out: dict[tuple[str, str], set[str]] = {(g, t): set() for g, t in caps}
    for g, t, a in con.execute(
        "SELECT game_id, team_id, athlete_id FROM pregame_injuries WHERE lower(status) = 'out'"
    ).fetchall():
        out.setdefault((g, t), set()).add(a)
    return out


def _nan_team() -> dict[str, float]:
    return dict.fromkeys(TEAM_KEYS, math.nan)


class PlayerHistory:
    """Per-team last-N box scores in the current season, fed only by finished games."""

    def __init__(self, window: int = PLAYER_WINDOW):
        self.window = window
        self.games: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
        self.season: dict[str, int] = {}

    def add(self, team: str, season: int, box: dict[str, Line] | None) -> None:
        if self.season.get(team) != season:
            self.games[team].clear()
            self.season[team] = season
        if box:  # a missing box score is skipped, not read as "everyone missed it"
            self.games[team].append(box)

    def team_features(
        self, team: str, season: int, out_override: set[str] | None = None
    ) -> dict[str, float]:
        hist = list(self.games[team]) if self.season.get(team) == season else []
        n = len(hist)
        if n == 0:
            return _nan_team()
        mins: dict[str, float] = defaultdict(float)
        for box in hist:
            for a, (played, m, _, _) in box.items():
                if played:
                    mins[a] += m
        # Rank by mpg over the window (missed games count 0); ties by athlete id.
        ranked = sorted(mins, key=lambda a: (-mins[a], a))[:TOP_N]
        if not ranked:
            return _nan_team()
        mpg = {a: mins[a] / n for a in ranked}
        top3 = ranked[:TOP_K]

        def played(box: dict[str, Line], a: str) -> bool:
            line = box.get(a)
            return bool(line and line[0])

        last = hist[-1]
        if out_override is None:
            missing = {a for a in ranked if not played(last, a)}
        else:
            missing = {a for a in ranked if a in out_override}
        last3 = hist[-3:]
        miss2of3 = sum(1 for a in ranked if sum(not played(b, a) for b in last3) >= 2)

        def since(a: str) -> int:
            k = 0
            for box in reversed(hist):
                if played(box, a):
                    break
                k += 1
            return min(k, SINCE_CAP)

        pm, pts = {}, {}
        for a in ranked:
            lines = [b[a] for b in hist if played(b, a)]
            gp = len(lines)
            pm[a] = sum(x[3] for x in lines) / (gp + PLAYER_SHRINK)
            pts[a] = (sum(x[2] for x in lines) + PLAYER_SHRINK * PTS_PRIOR) / (gp + PLAYER_SHRINK)
        total_mpg = sum(mpg.values())
        top6_pts = [pts[a] for a in ranked]
        return {
            "top6_out_last": float(len(missing)),
            "top3_out_last": float(sum(a in missing for a in top3)),
            "top6_out_2of3": float(miss2of3),
            "miss_share": sum(mpg[a] for a in missing) / total_mpg if total_mpg else math.nan,
            "top3_since": float(sum(since(a) for a in top3)),
            "top6_pm": sum(pm.values()),
            "top3_pts": sum(pts[a] for a in top3),
            "top6_pts_std": statistics.pstdev(top6_pts) if len(top6_pts) > 1 else 0.0,
            "avail_top6_pm": sum(pm[a] for a in ranked if a not in missing),
        }


def game_features(home: dict[str, float], away: dict[str, float]) -> dict[str, float]:
    """Home - away differences plus the two combined values. NaN if either side is NaN."""
    out = {f"{k}_diff": float(home[k] - away[k]) for k in TEAM_KEYS}
    out["miss_share_sum"] = float(home["miss_share"] + away["miss_share"])
    out["top3_pts_sum"] = float(home["top3_pts"] + away["top3_pts"])
    assert list(out) == PLAYER_FEATURES
    return out
