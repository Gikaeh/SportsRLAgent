"""Model v1 in daily use: pre-tip predictions for upcoming games, and the graded record.

- `pretip_predictions(con, now, days, league=...)`: rows for `Store.add_predictions`, only for
  games that have not started (start_time_utc > now). NBA v1 or college v1 (`league='ncaab'`).
  Read-only; the `deepsports predict` CLI writes them.
- `prediction_record(con, league, days)`: the `/api/predictions/record` payload (docs/API.md),
  read from the `prediction_results` view (or its SQL inline on an older warehouse). Always
  one league and one model version (college and NBA records are never mixed).
- `prediction_card(pred, home_abbr, away_abbr)`: the API `Prediction` object for one game.

History policy: the `predictions` primary key is (game_id, model, model_version), so each run
overwrites the row for a game with a fresh prediction. Because only not-yet-started games are
ever written, the stored row is always the latest pre-tip prediction. The view also guards
this: a row created at or after tip (e.g. the game was moved earlier) is never graded.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb

from deepsports import config
from deepsports.analysis.model import (
    DEFAULT_VERSION,
    MODEL_NAME,
    predict_upcoming,
    uses_injury_override,
)
from deepsports.store import PREDICTION_RESULTS_SQL

RECENT_LIMIT = 20


# Default model_version per league for `deepsports predict`.
DEFAULT_VERSIONS = {"nba": DEFAULT_VERSION, "ncaab": "ncaab-v1"}


def pretip_predictions(
    con: duckdb.DuckDBPyConnection,
    now: datetime | None = None,
    days: int = 14,
    model_version: str | None = None,
    league: str = "nba",
    gated: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Train the league's model on every completed game and predict the scheduled games
    tipping off in (now, now + days]. Returns (rows for Store.add_predictions, number of
    scheduled games skipped because their tip time has already passed). `created_at` is `now`
    for every row.

    NBA: model v1 (`model_version` v1.0 / v1.1 / v1.1i). `v1.1i` rows are written only for
    games with a pre-tip injury capture for at least one team (gate reason
    `no_injury_capture`); a team without one keeps the box-score "played last game" rule.
    College (`league='ncaab'`): one of
    ncaab.VERSIONS (see ncaab.predict_upcoming_versions), only for D1-vs-D1 games past that
    version's games-played gate. Pass a dict as `gated` to get the in-horizon count of
    not-started games skipped per reason (`non_d1`, `few_games`)."""
    model_version = model_version or DEFAULT_VERSIONS[league]
    out = pretip_predictions_versions(
        con, [model_version], now, days, league, None if gated is None else {model_version: gated}
    )
    return out[model_version]


def pretip_predictions_versions(
    con: duckdb.DuckDBPyConnection,
    versions: list[str],
    now: datetime | None = None,
    days: int = 14,
    league: str = "nba",
    gated: dict[str, dict[str, int]] | None = None,
) -> dict[str, tuple[list[dict[str, Any]], int]]:
    """pretip_predictions for several versions of one league: version -> (rows, started).
    College versions that share a model (`ncaab-v1p` and `ncaab-v1-early`) are fit once.
    `gated`, if given, is filled per version."""
    now = now or datetime.now(UTC)
    if league == "nba":
        raw = {v: predict_upcoming(con, v) for v in versions}
        captured = None
        for v in versions:
            if uses_injury_override(v):
                if captured is None:
                    captured = injury_capture_teams(con, [r["game_id"] for r in raw[v]])
                raw[v] = [
                    r if r["game_id"] in captured else {**r, "skip_reason": "no_injury_capture"}
                    for r in raw[v]
                ]
    elif league == "ncaab":
        from deepsports.analysis import ncaab

        raw = ncaab.predict_upcoming_versions(con, versions)
    else:
        raise ValueError(f"no model for league {league!r}")
    out = {}
    for v in versions:
        g = None
        if gated is not None:
            g = gated.setdefault(v, {})
        out[v] = _pretip(con, raw[v], now, days, g)
    return out


def injury_capture_teams(
    con: duckdb.DuckDBPyConnection, game_ids: list[str], league: str = "nba"
) -> dict[str, set[str]]:
    """game_id -> team_ids with at least one pre-tip injury capture (captured_before_tip).
    Games without any capture are absent."""
    if not game_ids or not _has(con, "injury_captures"):
        return {}
    out: dict[str, set[str]] = {}
    for gid, team in con.execute(
        f"""SELECT DISTINCT game_id, team_id FROM injury_captures
            WHERE captured_before_tip AND league = ?
              AND game_id IN ({", ".join("?" for _ in game_ids)})""",
        [league, *game_ids],
    ).fetchall():
        out.setdefault(gid, set()).add(team)
    return out


def _pretip(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict[str, Any]],
    now: datetime,
    days: int,
    gated: dict[str, int] | None,
) -> tuple[list[dict[str, Any]], int]:
    """Keep rows for games tipping off in (now, now + days] that pass their gate."""
    if not rows:
        return [], 0
    ids = [r["game_id"] for r in rows]
    starts = dict(
        con.execute(
            f"SELECT game_id, start_time_utc FROM games WHERE game_id IN "
            f"({', '.join('?' for _ in ids)})",
            ids,
        ).fetchall()
    )
    horizon = now + timedelta(days=days)
    out, started = [], 0
    for r in rows:
        start = starts[r["game_id"]]
        if start <= now:
            started += 1  # still 'pre' in the warehouse, but tip time has passed: never write
            continue
        if start > horizon:
            continue
        why = r.get("skip_reason")
        if why is not None:
            if gated is not None:
                gated[why] = gated.get(why, 0) + 1
            continue
        out.append({**{k: x for k, x in r.items() if k != "skip_reason"}, "created_at": now})
    return out, started


def prediction_card(pred: dict[str, Any], home_abbr: str, away_abbr: str) -> dict[str, Any]:
    """API `Prediction` (docs/API.md) from a predictions row (e.g. Store.latest_predictions)."""
    p = float(pred["p_home_win"])
    home_fav = p >= 0.5
    created = pred["created_at"]
    return {
        "model": pred["model"],
        "model_version": pred["model_version"],
        "created_at": created.astimezone(UTC).isoformat() if created else None,
        "p_home_win": round(p, 3),
        "pred_home_margin": round(float(pred["pred_home_margin"]), 1),
        "pred_total": round(float(pred["pred_total"]), 1),
        "favorite_abbr": home_abbr if home_fav else away_abbr,
        "favorite_prob": round(max(p, 1 - p), 3),
    }


def _has(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    q = "SELECT count(*) FROM information_schema.tables WHERE table_name = ?"
    return con.execute(q, [name]).fetchone()[0] > 0


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _r(x: float | None, nd: int) -> float | None:
    return None if x is None else round(x, nd)


def prediction_record(
    con: duckdb.DuckDBPyConnection,
    league: str = "nba",
    days: int = 30,
    model: str = MODEL_NAME,
    model_version: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Graded record of pre-tip predictions for games that tipped off in the last `days` days.

    Shape = `/api/predictions/record` in docs/API.md. `model_version` defaults to the version
    with the newest prediction in that league. Model metrics use every graded game; `market`
    uses the same games where a closing line exists (its winner_accuracy = how often the
    closing favorite won: moneyline favorite, or the spread favorite if no moneyline), and is
    None when no graded game has a closing line. Accuracy/MAE are None with 0 games.
    """
    now = now or datetime.now(UTC)
    empty = {
        "model": model,
        "model_version": model_version,
        "window_days": days,
        "games": 0,
        "winner_accuracy": None,
        "margin_mae": None,
        "total_mae": None,
        "market": None,
        "recent": [],
    }
    if not _has(con, "predictions"):
        return empty
    if model_version is None:
        row = con.execute(
            """SELECT p.model_version FROM predictions p JOIN games g USING (game_id)
               WHERE g.league = ? AND p.model = ? ORDER BY p.created_at DESC LIMIT 1""",
            [league, model],
        ).fetchone()
        if row is None:
            return empty
        model_version = row[0]
        empty["model_version"] = model_version
    source = (
        "prediction_results" if _has(con, "prediction_results") else (f"({PREDICTION_RESULTS_SQL})")
    )
    cur = con.execute(
        f"""SELECT * FROM {source} r
            WHERE r.league = ? AND r.model = ? AND r.model_version = ?
              AND r.start_time_utc >= ? AND r.start_time_utc <= ?
            ORDER BY r.start_time_utc DESC, r.game_id DESC""",
        [league, model, model_version, now - timedelta(days=days), now],
    )
    cols = [d[0] for d in cur.description]
    graded = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    if not graded:
        return empty

    market_games, fav_hits, m_err, t_err = 0, [], [], []
    for g in graded:
        spread, total, p_mkt = g["market_spread_home"], g["market_total"], g["market_p_home"]
        if spread is None and total is None and p_mkt is None:
            continue
        market_games += 1
        home_won = g["actual_home_margin"] > 0
        if p_mkt is not None and p_mkt != 0.5:
            fav_hits.append((p_mkt > 0.5) == home_won)
        elif spread is not None and spread != 0:
            fav_hits.append((spread < 0) == home_won)
        if spread is not None:
            m_err.append(abs(-spread - g["actual_home_margin"]))
        if total is not None:
            t_err.append(abs(total - g["actual_total"]))
    market = None
    if market_games:
        market = {
            "games": market_games,
            "winner_accuracy": _r(_mean([float(x) for x in fav_hits]), 3),
            "margin_mae": _r(_mean(m_err), 2),
            "total_mae": _r(_mean(t_err), 2),
        }

    recent = []
    for g in graded[:RECENT_LIMIT]:
        p = g["p_home_win"]
        home_fav = p >= 0.5
        recent.append(
            {
                "game_id": g["game_id"],
                "date": g["start_time_utc"].astimezone(config.LOCAL_TZ).date().isoformat(),
                "matchup": f"{g['away_abbr']} @ {g['home_abbr']}",
                "favorite_abbr": g["home_abbr"] if home_fav else g["away_abbr"],
                "favorite_prob": round(max(p, 1 - p), 3),
                "pred_home_margin": round(g["pred_home_margin"], 1),
                "actual_home_margin": g["actual_home_margin"],
                "winner_correct": bool(g["winner_correct"]),
            }
        )
    return {
        "model": model,
        "model_version": model_version,
        "window_days": days,
        "games": len(graded),
        "winner_accuracy": _r(_mean([float(g["winner_correct"]) for g in graded]), 3),
        "margin_mae": _r(_mean([g["margin_error"] for g in graded]), 2),
        "total_mae": _r(_mean([g["total_error"] for g in graded]), 2),
        "market": market,
        "recent": recent,
    }
