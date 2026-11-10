"""Read-only warehouse queries for the API: standings and team pages."""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.api.views import conference, local_time
from deepsports.store import is_lock_conflict


class WarehouseBusy(RuntimeError):
    """A collection job holds the DuckDB write lock."""


class WarehouseUnavailable(RuntimeError):
    """The DB can't be opened: the external drive isn't mounted, or macOS hasn't (yet) granted this
    process access to removable volumes, in which case file access blocks instead of failing."""


OPEN_TIMEOUT = 5.0
# Small pool: if opens hang on a pending macOS permission, at most 2 threads are stuck and later
# requests still get a fast 503 from the timeout.
_opener = ThreadPoolExecutor(max_workers=2, thread_name_prefix="warehouse-open")


def _open(path: str):
    if path != ":memory:" and not Path(path).exists():
        raise WarehouseUnavailable(f"{path} not found (is the external drive mounted?)")
    return duckdb.connect(path, read_only=True)


@contextmanager
def connect(path: Path | str = config.DB_PATH, timeout: float = OPEN_TIMEOUT):
    try:
        con = _opener.submit(_open, str(path)).result(timeout=timeout)
    except FutureTimeout as e:
        raise WarehouseUnavailable(f"opening {path} timed out (drive permission?)") from e
    except duckdb.IOException as e:
        if not is_lock_conflict(e):  # e.g. macOS "Operation not permitted" on the drive
            raise WarehouseUnavailable(f"cannot open {path}: {e}") from e
        raise WarehouseBusy(str(e)) from e
    try:
        yield con
    finally:
        con.close()


def current_season(con) -> int | None:
    row = con.execute(
        "SELECT max(season_year) FROM games WHERE league = 'nba' AND season_type = 2 AND completed"
    ).fetchone()
    return row[0] if row else None


def season_label(year: int) -> str:
    return f"{year - 1}-{str(year)[2:]}"


# One row per team per completed regular-season game, newest first.
TEAM_GAMES = """
    WITH tg AS (
        SELECT g.game_id, g.start_time_utc, g.home_team_id AS team_id, true AS is_home,
               g.home_score > g.away_score AS won
        FROM games g WHERE g.league = 'nba' AND g.season_year = ? AND g.season_type = 2
                       AND g.completed
                       AND g.status = 'STATUS_FINAL'
        UNION ALL
        SELECT g.game_id, g.start_time_utc, g.away_team_id, false, g.away_score > g.home_score
        FROM games g WHERE g.league = 'nba' AND g.season_year = ? AND g.season_type = 2
                       AND g.completed
                       AND g.status = 'STATUS_FINAL'
    )
    SELECT tg.*, row_number() OVER (PARTITION BY team_id ORDER BY start_time_utc DESC) AS rn
    FROM tg
"""


def standings(con, followed: set[str]) -> dict[str, Any]:
    season = current_season(con)
    if season is None:
        return {"season": None, "conferences": []}
    rows = con.execute(
        f"""
        WITH t AS ({TEAM_GAMES})
        SELECT tm.abbreviation, tm.display_name, tm.team_id,
               count(*) FILTER (WHERE won) AS w, count(*) FILTER (WHERE NOT won) AS l,
               count(*) FILTER (WHERE won AND is_home) AS hw,
               count(*) FILTER (WHERE NOT won AND is_home) AS hl,
               count(*) FILTER (WHERE won AND NOT is_home) AS aw,
               count(*) FILTER (WHERE NOT won AND NOT is_home) AS al,
               count(*) FILTER (WHERE won AND rn <= 10) AS l10w,
               count(*) FILTER (WHERE NOT won AND rn <= 10) AS l10l,
               list(won ORDER BY rn) AS results
        FROM t JOIN teams tm ON tm.team_id = t.team_id AND tm.league = 'nba'
        GROUP BY ALL
        """,
        [season, season],
    ).fetchall()
    confs: dict[str, list[dict]] = {"East": [], "West": []}
    for abbr, name, _team_id, w, l, hw, hl, aw, al, l10w, l10l, results in rows:  # noqa: E741
        streak_n = 1
        while streak_n < len(results) and results[streak_n] == results[0]:
            streak_n += 1
        conf = conference(abbr)
        if conf not in confs:
            continue
        confs[conf].append(
            {
                "abbr": abbr,
                "name": name,
                "logo": f"https://a.espncdn.com/i/teamlogos/nba/500/{abbr.lower()}.png",
                "conference": conf,
                "wins": w,
                "losses": l,
                "pct": round(w / (w + l), 3) if w + l else 0.0,
                "home": f"{hw}-{hl}",
                "away": f"{aw}-{al}",
                "last10": f"{l10w}-{l10l}",
                "streak": f"{'W' if results[0] else 'L'}{streak_n}" if results else "",
                "followed": abbr in followed,
            }
        )
    out = []
    for conf, teams in confs.items():
        teams.sort(key=lambda r: (-r["pct"], -r["wins"], r["abbr"]))
        if teams:
            lw, ll = teams[0]["wins"], teams[0]["losses"]
            for r in teams:
                r["games_back"] = ((lw - r["wins"]) + (r["losses"] - ll)) / 2
        out.append({"name": conf, "teams": teams})
    return {"season": season_label(season), "conferences": out}


def team_page(con, abbr: str, followed: set[str]) -> dict[str, Any] | None:
    team = con.execute(
        "SELECT team_id, abbreviation, display_name, name FROM teams "
        "WHERE abbreviation = ? AND league = 'nba'",
        [abbr],
    ).fetchone()
    if not team:
        return None
    team_id = team[0]
    table = standings(con, followed)
    standing = next(
        (r for c in table["conferences"] for r in c["teams"] if r["abbr"] == abbr), None
    )

    def games(where: str, order: str, limit: int) -> list[dict]:
        rows = con.execute(
            f"""
            SELECT g.game_id, g.start_time_utc, g.home_team_id = ? AS is_home,
                   h.abbreviation, a.abbreviation, g.home_score, g.away_score, g.status, g.state
            FROM games g
            JOIN teams h ON h.team_id = g.home_team_id AND h.league = g.league
            JOIN teams a ON a.team_id = g.away_team_id AND a.league = g.league
            WHERE g.league = 'nba' AND (g.home_team_id = ? OR g.away_team_id = ?)
              AND g.season_type IN (2, 3, 5)
              AND {where}
            ORDER BY g.start_time_utc {order} LIMIT {limit}
            """,
            [team_id, team_id, team_id],
        ).fetchall()
        out = []
        for gid, start, is_home, h, a, hs, as_, status, _state in rows:
            mine, theirs = (hs, as_) if is_home else (as_, hs)
            final = status == "STATUS_FINAL"
            out.append(
                {
                    "id": gid,
                    "date": local_time(start).isoformat(),
                    "opponent": a if is_home else h,
                    "home": bool(is_home),
                    "result": ("W" if mine > theirs else "L") if final else None,
                    "score": f"{mine}-{theirs}" if final else None,
                    "status_text": "Final"
                    if final
                    else "Postponed"
                    if status == "STATUS_POSTPONED"
                    else local_time(start).strftime("%a %-m/%-d %-I:%M %p"),
                }
            )
        return out

    return {
        "team": {
            "id": team_id,
            "abbr": team[1],
            "name": team[2],
            "short_name": team[3],
            "logo": f"https://a.espncdn.com/i/teamlogos/nba/500/{abbr.lower()}.png",
            "record": f"{standing['wins']}-{standing['losses']}" if standing else None,
            "followed": abbr in followed,
        },
        "standing": standing,
        "recent": games("g.completed", "DESC", 10),
        "upcoming": games("g.state = 'pre'", "ASC", 5),
    }


def pre_tip_predictions(
    con, game_ids: list[str], model: str = "v1", prefer_version: str | None = None
) -> dict[str, dict[str, Any]]:
    """Latest prediction per game made strictly before tip-off (never one made after).
    With `prefer_version`, that version wins when it exists for a game; else the latest.
    Versions in config.HIDDEN_MODEL_VERSIONS (graded side by side, e.g. `ncaab-v1p`) are
    never picked."""
    if not game_ids:
        return {}
    has = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'predictions'"
    ).fetchone()[0]
    if not has:
        return {}
    marks = ", ".join("?" for _ in game_ids)
    hidden = list(config.HIDDEN_MODEL_VERSIONS)
    not_hidden = f"AND p.model_version NOT IN ({', '.join('?' for _ in hidden)})" if hidden else ""
    rows = con.execute(
        f"""
        SELECT p.game_id, p.model, p.model_version, p.created_at, p.p_home_win,
               p.pred_home_margin, p.pred_total
        FROM predictions p JOIN games g ON g.game_id = p.game_id
        WHERE p.game_id IN ({marks}) AND p.model = ? AND p.created_at < g.start_time_utc
          {not_hidden}
        QUALIFY row_number() OVER (
            PARTITION BY p.game_id
            ORDER BY (p.model_version = ?) DESC, p.created_at DESC
        ) = 1
        """,
        [*game_ids, model, *hidden, prefer_version or ""],
    ).fetchall()
    cols = ["game_id", "model", "model_version", "created_at", "p_home_win",
            "pred_home_margin", "pred_total"]  # fmt: skip
    return {r[0]: dict(zip(cols, r, strict=True)) for r in rows}
