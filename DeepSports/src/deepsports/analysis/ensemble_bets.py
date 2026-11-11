"""Ensemble betting: N independent agents pick bets from the same slate; a majority vote decides.

Watch-only. Nothing here places a bet. The flow (see `.claude/skills/ensemble-betting/SKILL.md`):

1. `deepsports ensemble-bets context --days 3 --agents N` writes a run directory with
   `slate.json` (machine-readable) and one `context-<agent>.md` per agent (same facts, games in
   a different shuffled order so no agent's choices depend on list position).
2. The orchestrator launches N `bettor` subagents at once, each reading only its own context
   file and returning picks as JSON; it saves each reply as `picks-<agent>.json`.
3. `deepsports ensemble-bets tally <run>` validates the picks against the slate (the line and
   price always come from the slate, never from the agent) and reports what a majority agrees on.
4. `deepsports ensemble-bets grade` grades every finished run's consensus and agent picks.

The slate assembly, rendering, validation and tally are pure functions; only the `load_*`
functions touch DuckDB (read-only).
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.analysis.betting.grading import outcome, profit_on_win
from deepsports.analysis.metrics import devig_probability
from deepsports.store import SANE_LIMITS

RUNS_DIR = config.REPORTS_DIR / "ensemble-bets"
MARKETS = ("spread", "total", "moneyline")
SIDES = {"spread": ("home", "away"), "total": ("over", "under"), "moneyline": ("home", "away")}
# Bump whenever the brief or the facts given to bettors change (new fields, wording, rules), and
# log what changed in docs/DECISIONS.md: each context version keeps its own graded record.
# ctx-v1 (2026-11-06): lines + prices, movement since first seen, display-model prediction, season
# form, rest/travel, NBA pre-tip injuries with mpg/ppg, project backtest facts in the brief.
CONTEXT_VERSION = "ctx-v1"
# ctx-v1-sim1 (2026-11-06): historical backtest slates (load_historical_slate): ctx-v1's facts as
# of a past decision time, final pre-tip (closing) lines, and the one-pick brief (render_context
# one_pick=True: exactly one pick, stake 1).
SIM_CONTEXT_VERSION = "ctx-v1-sim1"
# ctx-v2 (2026-11-06): ctx-v1 plus last season, opponent-adjusted ratings now, pace/efficiency,
# NBA injury impact, line timing (live), and closing-line base rates from earlier seasons
# (analysis/ensemble_context_v2.py). Built with `context="v2"`; the live default stays v1 until
# the matched test is graded (`deepsports ensemble-bets context --context v2`).
CONTEXT_VERSIONS = {"v1": CONTEXT_VERSION, "v2": "ctx-v2"}
SIM_CONTEXT_VERSIONS = {"v1": SIM_CONTEXT_VERSION, "v2": "ctx-v2-sim1"}
MAX_PICKS = 8
MAX_STAKE = 3
MIN_LEAD = timedelta(minutes=60)  # skip games tipping sooner: picks must predate tip
DISPLAY_VERSIONS = {"nba": ("v1.1",), "ncaab": ("ncaab-v1", "ncaab-v1-early")}
INJURY_STATUSES = ("out", "doubtful", "questionable", "day-to-day")


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] = ()) -> list[dict]:
    cur = con.execute(sql, list(params))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _marks(xs: Sequence[Any]) -> str:
    return ", ".join("?" for _ in xs)


# ---------- loading (read-only DuckDB) ----------


def load_games(
    con: duckdb.DuckDBPyConnection, league: str, now: datetime, days: int
) -> list[dict[str, Any]]:
    """Not-started regular/postseason games tipping in the next `days` days, both teams known."""
    return _rows(
        con,
        """SELECT g.game_id, g.league, g.season_year, g.start_time_utc, g.neutral_site,
                  g.venue, g.broadcasts, g.home_team_id, g.away_team_id,
                  h.abbreviation AS home_abbr, h.display_name AS home_name, h.listed AS home_d1,
                  a.abbreviation AS away_abbr, a.display_name AS away_name, a.listed AS away_d1
           FROM games g
           JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
           JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
           WHERE g.league = ? AND g.state = 'pre' AND g.season_type IN (2, 3)
             AND g.start_time_utc > ? AND g.start_time_utc <= ?
           ORDER BY g.start_time_utc, g.game_id""",
        [league, now + MIN_LEAD, now + timedelta(days=days)],
    )


def load_lines(
    con: duckdb.DuckDBPyConnection, game_ids: Sequence[str], now: datetime
) -> dict[str, dict[str, Any]]:
    """Latest pregame snapshot per game (at or before `now`) plus the first one, for movement."""
    if not game_ids:
        return {}
    rows = _rows(
        con,
        f"""SELECT game_id, captured_at, provider, spread_home, over_under, home_moneyline,
                   away_moneyline, spread_home_price, spread_away_price, over_price, under_price,
                   row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) AS rn_last,
                   row_number() OVER (PARTITION BY game_id ORDER BY captured_at) AS rn_first
            FROM odds_snapshots
            WHERE source = 'pregame' AND captured_at <= ? AND game_id IN ({_marks(game_ids)})""",
        [now, *game_ids],
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        slot = out.setdefault(r["game_id"], {})
        if r["rn_last"] == 1:
            slot["last"] = r
        if r["rn_first"] == 1:
            slot["first"] = r
    return out


def load_predictions(
    con: duckdb.DuckDBPyConnection, league: str, game_ids: Sequence[str], now: datetime
) -> dict[str, dict[str, Any]]:
    """The league's display model prediction per game (first listed version that has one)."""
    if not game_ids:
        return {}
    versions = DISPLAY_VERSIONS[league]
    rows = _rows(
        con,
        f"""SELECT game_id, model_version, p_home_win, pred_home_margin, pred_total
            FROM predictions
            WHERE model = 'v1' AND created_at <= ? AND model_version IN ({_marks(versions)})
              AND game_id IN ({_marks(game_ids)})
            QUALIFY row_number() OVER (PARTITION BY game_id, model_version
                                       ORDER BY created_at DESC) = 1""",
        [now, *versions, *game_ids],
    )
    out: dict[str, dict[str, Any]] = {}
    for v in versions:  # display order: the first version wins
        for r in rows:
            if r["model_version"] == v:
                out.setdefault(r["game_id"], r)
    return out


def load_team_form(
    con: duckdb.DuckDBPyConnection, league: str, season: int, now: datetime
) -> dict[str, dict[str, Any]]:
    """Season-to-date record, home/away split, last-5 and average margin per team."""
    rows = _rows(
        con,
        """WITH tg AS (
             SELECT g.home_team_id AS team_id, g.start_time_utc, TRUE AS home,
                    g.home_score - g.away_score AS margin, g.home_score + g.away_score AS total
             FROM games g WHERE g.league = ? AND g.season_year = ? AND g.completed
               AND g.status = 'STATUS_FINAL' AND g.season_type IN (2, 3) AND g.start_time_utc < ?
             UNION ALL
             SELECT g.away_team_id, g.start_time_utc, FALSE, g.away_score - g.home_score,
                    g.home_score + g.away_score
             FROM games g WHERE g.league = ? AND g.season_year = ? AND g.completed
               AND g.status = 'STATUS_FINAL' AND g.season_type IN (2, 3) AND g.start_time_utc < ?),
           ranked AS (SELECT *, row_number() OVER (PARTITION BY team_id
                                                   ORDER BY start_time_utc DESC) AS rn FROM tg)
           SELECT team_id, count(*) AS gp, count(*) FILTER (margin > 0) AS w,
                  count(*) FILTER (margin < 0) AS l,
                  count(*) FILTER (home AND margin > 0) AS hw,
                  count(*) FILTER (home AND margin < 0) AS hl,
                  count(*) FILTER (NOT home AND margin > 0) AS aw,
                  count(*) FILTER (NOT home AND margin < 0) AS al,
                  count(*) FILTER (rn <= 5 AND margin > 0) AS l5w,
                  count(*) FILTER (rn <= 5 AND margin < 0) AS l5l,
                  avg(margin) AS avg_margin, avg(total) AS avg_total,
                  avg(margin) FILTER (rn <= 5) AS l5_margin
           FROM ranked GROUP BY team_id""",
        [league, season, now] * 2,
    )
    return {r["team_id"]: r for r in rows}


def load_context(
    con: duckdb.DuckDBPyConnection, league: str, game_ids: Sequence[str]
) -> dict[tuple[str, str], dict[str, Any]]:
    if not game_ids:
        return {}
    rows = _rows(
        con,
        f"""SELECT game_id, team_id, rest_days, back_to_back, games_last_7_days,
                   road_trip_length, travel_km
            FROM team_game_context WHERE league = ? AND game_id IN ({_marks(game_ids)})""",
        [league, *game_ids],
    )
    return {(r["game_id"], r["team_id"]): r for r in rows}


def load_injuries(
    con: duckdb.DuckDBPyConnection, league: str, game_ids: Sequence[str]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Latest pre-tip injury list per game and team, with each player's season minutes/points."""
    if not game_ids:
        return {}
    rows = _rows(
        con,
        f"""SELECT i.game_id, i.team_id, i.athlete_id, i.athlete_name,
                   lower(i.status) AS status, i.detail,
                   s.gp, s.mpg, s.ppg
            FROM pregame_injuries i
            JOIN games g ON g.game_id = i.game_id
            LEFT JOIN (SELECT p.athlete_id, g2.season_year, count(*) AS gp,
                              avg(p.minutes) AS mpg, avg(p.pts) AS ppg
                       FROM player_game_stats p JOIN games g2 USING (game_id)
                       WHERE p.league = ? AND NOT coalesce(p.did_not_play, FALSE)
                       GROUP BY ALL) s
              ON s.athlete_id = i.athlete_id AND s.season_year = g.season_year
            WHERE i.league = ? AND i.game_id IN ({_marks(game_ids)})
            ORDER BY s.mpg DESC NULLS LAST""",
        [league, league, *game_ids],
    )
    out: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["status"] in INJURY_STATUSES:
            out[(r["game_id"], r["team_id"])].append(r)
    return out


def load_slate(
    con: duckdb.DuckDBPyConnection,
    now: datetime,
    days: int = 3,
    leagues: Sequence[str] = ("nba", "ncaab"),
    context: str = "v1",
) -> dict[str, Any]:
    """The live slate. `context` 'v1' (default, ctx-v1) or 'v2' (adds the ctx-v2 blocks)."""
    if context not in CONTEXT_VERSIONS:
        raise ValueError(f"unknown context {context!r}")
    games: list[dict[str, Any]] = []
    unlined = 0
    raws: list[dict[str, Any]] = []
    injuries: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for league in leagues:
        raw = load_games(con, league, now, days)
        ids = [g["game_id"] for g in raw]
        lines = load_lines(con, ids, now)
        preds = load_predictions(con, league, ids, now)
        ctx = load_context(con, league, ids)
        inj = load_injuries(con, league, ids)
        forms = {s: load_team_form(con, league, s, now) for s in {g["season_year"] for g in raw}}
        raws += raw
        injuries.update(inj)
        for g in raw:
            row = build_game(
                g, lines.get(g["game_id"], {}), preds.get(g["game_id"]),
                forms[g["season_year"]], ctx, inj,
            )  # fmt: skip
            if row is None:
                unlined += 1
            else:
                games.append(row)
    slate = {
        "created_at": now.astimezone(UTC).isoformat(),
        "context_version": CONTEXT_VERSIONS[context],
        "days": days,
        "leagues": list(leagues),
        "unlined_games": unlined,
        "games": games,
    }
    if context == "v2":
        from deepsports.analysis.ensemble_context_v2 import attach_v2

        attach_v2(con, slate, now, raws, injuries, timing=True)
    return slate


# ---------- historical (point-in-time) slates for backtests ----------
#
# A historical slate is what a bettor could have known at a past decision time `now`. Every
# fact is filtered to `now`: games are selected by schedule only (no score, state or status
# column is read), form counts games that finished before `now` (start + FINISH_LAG <= now),
# injuries are snapshots captured before tip and at or before `now`, with season averages from
# games finished before `now`, and team_game_context is computed from earlier games only.
# One documented exception: the line. Most past days have no pregame snapshot, so the slate
# uses the stored `closing` row (the final pre-tip line, one a bettor could take just before
# tip), whose `captured_at` is often a later backfill time; the slate does not carry that time.
# Model numbers are passed in (ensemble_sim fits them walk-forward on games before `now`).

HIST_FINISH_LAG = timedelta(hours=4)  # same rule as features.FINISH_LAG


def load_historical_games(
    con: duckdb.DuckDBPyConnection,
    league: str,
    now: datetime,
    until: datetime,
    season_types: Sequence[int] = (2,),
) -> list[dict[str, Any]]:
    """Games scheduled to tip in (now, until], both teams known. Reads only schedule columns."""
    return _rows(
        con,
        f"""SELECT g.game_id, g.league, g.season_year, g.start_time_utc, g.neutral_site,
                   g.venue, g.broadcasts, g.home_team_id, g.away_team_id,
                   h.abbreviation AS home_abbr, h.display_name AS home_name, h.listed AS home_d1,
                   a.abbreviation AS away_abbr, a.display_name AS away_name, a.listed AS away_d1
            FROM games g
            JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
            JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
            WHERE g.league = ? AND g.season_type IN ({_marks(season_types)})
              AND g.start_time_utc > ? AND g.start_time_utc <= ?
            ORDER BY g.start_time_utc, g.game_id""",
        [league, *season_types, now, until],
    )


def load_historical_lines(
    con: duckdb.DuckDBPyConnection, game_ids: Sequence[str], line_source: str = "closing"
) -> dict[str, dict[str, Any]]:
    """{'last': latest `line_source` row, 'first': earliest opening row (or the last row when
    there is no opening row, so no movement is shown)} per game."""
    if not game_ids:
        return {}
    cols = """game_id, captured_at, provider, spread_home, over_under, home_moneyline,
              away_moneyline, spread_home_price, spread_away_price, over_price, under_price"""
    out: dict[str, dict[str, Any]] = {}
    for key, source, order in (("last", line_source, "DESC"), ("first", "opening", "ASC")):
        rows = _rows(
            con,
            f"""SELECT {cols} FROM odds_snapshots
                WHERE source = ? AND game_id IN ({_marks(game_ids)})
                QUALIFY row_number() OVER (PARTITION BY game_id
                                           ORDER BY captured_at {order}) = 1""",
            [source, *game_ids],
        )
        for r in rows:
            out.setdefault(r["game_id"], {})[key] = r
    return {gid: v for gid, v in out.items() if "last" in v}


def load_injuries_as_of(
    con: duckdb.DuckDBPyConnection, league: str, game_ids: Sequence[str], now: datetime
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], datetime | None]:
    """The latest injury snapshot per game and team captured before tip and at or before `now`
    (the `pregame_injuries` view could pick a later capture), with season minutes/points from
    games finished before `now`. Returns (injuries, latest capture time used or None)."""
    if not game_ids:
        return {}, None
    last = _rows(
        con,
        f"""SELECT game_id, team_id, max(captured_at) AS captured_at FROM injury_captures
            WHERE league = ? AND captured_before_tip AND captured_at <= ?
              AND game_id IN ({_marks(game_ids)})
            GROUP BY ALL""",
        [league, now, *game_ids],
    )
    if not last:
        return {}, None
    rows = _rows(
        con,
        f"""WITH last AS (
              SELECT game_id, team_id, max(captured_at) AS captured_at FROM injury_captures
              WHERE league = ? AND captured_before_tip AND captured_at <= ?
                AND game_id IN ({_marks(game_ids)})
              GROUP BY ALL)
            SELECT r.game_id, r.team_id, r.athlete_id, r.athlete_name,
                   lower(r.status) AS status, r.detail,
                   s.gp, s.mpg, s.ppg
            FROM injury_reports r
            JOIN last USING (game_id, team_id, captured_at)
            JOIN games g ON g.game_id = r.game_id
            LEFT JOIN (SELECT p.athlete_id, g2.season_year, count(*) AS gp,
                              avg(p.minutes) AS mpg, avg(p.pts) AS ppg
                       FROM player_game_stats p JOIN games g2 USING (game_id)
                       WHERE p.league = ? AND NOT coalesce(p.did_not_play, FALSE)
                         AND g2.start_time_utc <= ?
                       GROUP BY ALL) s
              ON s.athlete_id = r.athlete_id AND s.season_year = g.season_year
            WHERE r.league = ?
            ORDER BY s.mpg DESC NULLS LAST""",
        [league, now, *game_ids, league, now - HIST_FINISH_LAG, league],
    )
    out: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["status"] in INJURY_STATUSES:
            out[(r["game_id"], r["team_id"])].append(r)
    return out, max(r["captured_at"] for r in last)


def load_historical_slate(
    con: duckdb.DuckDBPyConnection,
    now: datetime,
    until: datetime,
    league: str = "nba",
    predictions: Mapping[str, Mapping[str, Any]] | None = None,
    line_source: str = "closing",
    model_source: str | None = None,
    game_ids: Sequence[str] | None = None,
    context: str = "v1",
) -> dict[str, Any]:
    """A point-in-time slate for a backtest: games tipping in (now, until] with only what was
    known at `now` (see the section comment), the one-pick rules (max_picks = max_stake = 1)
    and `brief_notes` that say where the lines and injuries come from.

    `predictions`: game_id -> {model_version, p_home_win, pred_home_margin, pred_total}, made
    without information from after `now` (the caller's responsibility; ensemble_sim fits them
    walk-forward). Games with no line in `line_source` count as unlined. `game_ids` keeps only
    those games of the window (a sampled slate). `context='v2'` adds the ctx-v2 blocks (no
    line timing: past days have no pregame snapshots)."""
    if context not in SIM_CONTEXT_VERSIONS:
        raise ValueError(f"unknown context {context!r}")
    raw = load_historical_games(con, league, now, until)
    if game_ids is not None:
        keep = set(game_ids)
        raw = [g for g in raw if g["game_id"] in keep]
    ids = [g["game_id"] for g in raw]
    lines = load_historical_lines(con, ids, line_source)
    ctx = load_context(con, league, ids)
    inj, inj_at = load_injuries_as_of(con, league, ids, now)
    cutoff = now - HIST_FINISH_LAG  # a game counts toward form only once it has finished
    forms = {s: load_team_form(con, league, s, cutoff) for s in {g["season_year"] for g in raw}}
    games, unlined = [], 0
    for g in raw:
        row = build_game(
            g, lines.get(g["game_id"], {}), (predictions or {}).get(g["game_id"]),
            forms[g["season_year"]], ctx, inj,
        )  # fmt: skip
        if row is None:
            unlined += 1
            continue
        row["line_captured_at"] = None  # stored capture time can postdate `now`; not a fact
        row["line_source"] = line_source
        games.append(row)
    notes = [
        "Lines are the final pre-tip lines (the last line before tip-off, available to bet at "
        "decision time); line movement compares them with the opening line (first seen).",
        "No injury data for this date."
        if inj_at is None
        else "Injury lists are the latest captured before this slate "
        f"({inj_at.astimezone(UTC):%Y-%m-%d %H:%M} UTC); a team with no injuries line had none "
        "listed or none captured.",
    ]
    slate = {
        "created_at": now.astimezone(UTC).isoformat(),
        "context_version": SIM_CONTEXT_VERSIONS[context],
        "historical": True,
        "until": until.astimezone(UTC).isoformat(),
        "days": None,
        "leagues": [league],
        "line_source": line_source,
        "model_source": model_source,
        "injuries_captured_at": None if inj_at is None else inj_at.astimezone(UTC).isoformat(),
        "max_picks": 1,
        "max_stake": 1,
        "brief_notes": notes,
        "unlined_games": unlined,
        "games": games,
    }
    if context == "v2":
        from deepsports.analysis.ensemble_context_v2 import attach_v2

        attach_v2(con, slate, now, raw, inj, timing=False)
    return slate


# ---------- slate assembly (pure) ----------


def _sane(league: str, spread: float | None, total: float | None) -> tuple[Any, Any]:
    max_spread, lo, hi = SANE_LIMITS[league]
    sp = spread if spread is not None and abs(spread) <= max_spread else None
    tot = total if total is not None and lo <= total <= hi else None
    return sp, tot


def _price(p: Any) -> int | None:
    return int(p) if p is not None and abs(p) >= 100 else None


def _r(x: Any, nd: int = 1) -> float | None:
    return None if x is None else round(float(x), nd)


def _team(prefix: str, g: Mapping[str, Any], form: Mapping, ctx: Mapping, inj: Mapping) -> dict:
    tid = g[f"{prefix}_team_id"]
    f = form.get(tid) or {}
    c = ctx.get((g["game_id"], tid)) or {}
    return {
        "abbr": g[f"{prefix}_abbr"],
        "name": g[f"{prefix}_name"],
        "record": f"{f.get('w', 0)}-{f.get('l', 0)}",
        "home_record": f"{f.get('hw', 0)}-{f.get('hl', 0)}",
        "away_record": f"{f.get('aw', 0)}-{f.get('al', 0)}",
        "last5": f"{f.get('l5w', 0)}-{f.get('l5l', 0)}",
        "avg_margin": _r(f.get("avg_margin")),
        "last5_margin": _r(f.get("l5_margin")),
        "avg_game_total": _r(f.get("avg_total")),
        "rest_days": c.get("rest_days"),
        "back_to_back": bool(c.get("back_to_back")),
        "games_last_7_days": c.get("games_last_7_days"),
        "road_trip_length": c.get("road_trip_length"),
        "travel_km": None if c.get("travel_km") is None else round(c["travel_km"]),
        "injuries": [
            {
                "player": i["athlete_name"],
                "status": i["status"],
                "detail": i["detail"],
                "mpg": _r(i["mpg"]),
                "ppg": _r(i["ppg"]),
            }
            for i in inj.get((g["game_id"], tid), [])
        ],
    }


def build_game(
    g: Mapping[str, Any],
    lines: Mapping[str, Mapping[str, Any]],
    pred: Mapping[str, Any] | None,
    form: Mapping[str, Mapping[str, Any]],
    ctx: Mapping[tuple[str, str], Mapping[str, Any]],
    inj: Mapping[tuple[str, str], list[Mapping[str, Any]]],
) -> dict[str, Any] | None:
    """One slate game, or None when there is no bettable line (no current spread, total or
    pair of moneylines). Markets hold the exact line and price a pick will be graded at."""
    last = lines.get("last")
    if last is None:
        return None
    league = g["league"]
    spread, total = _sane(league, last["spread_home"], last["over_under"])
    hml, aml = _price(last["home_moneyline"]), _price(last["away_moneyline"])
    markets: dict[str, dict[str, Any]] = {}
    if spread is not None:
        markets["spread"] = {
            "home_line": spread,
            "home_price": _price(last["spread_home_price"]) or -110,
            "away_line": -spread,
            "away_price": _price(last["spread_away_price"]) or -110,
        }
    if total is not None:
        markets["total"] = {
            "line": total,
            "over_price": _price(last["over_price"]) or -110,
            "under_price": _price(last["under_price"]) or -110,
        }
    if hml is not None and aml is not None:
        p = devig_probability(hml, aml)
        markets["moneyline"] = {
            "home_price": hml,
            "away_price": aml,
            "market_home_win_prob": None if p is None else round(p, 3),
        }
    if not markets:
        return None
    first = lines.get("first") or last
    f_spread, f_total = _sane(league, first["spread_home"], first["over_under"])
    tip: datetime = g["start_time_utc"]
    return {
        "game_id": g["game_id"],
        "league": league,
        "tip_utc": tip.astimezone(UTC).isoformat(),
        "tip_local": tip.astimezone(config.LOCAL_TZ).strftime("%a %b %-d %-I:%M %p %Z"),
        "neutral_site": bool(g["neutral_site"]),
        "venue": g["venue"],
        "tv": g["broadcasts"],
        "home": _team("home", g, form, ctx, inj),
        "away": _team("away", g, form, ctx, inj),
        "non_d1_opponent": league == "ncaab" and not (g["home_d1"] and g["away_d1"]),
        "markets": markets,
        "line_provider": last["provider"],
        "line_captured_at": last["captured_at"].astimezone(UTC).isoformat(),
        "first_seen": {"spread_home": f_spread, "total": f_total},
        "model": None
        if pred is None
        else {
            "version": pred["model_version"],
            "home_win_prob": _r(pred["p_home_win"], 3),
            "home_margin": _r(pred["pred_home_margin"]),
            "total": _r(pred["pred_total"]),
        },
    }


# ---------- agent context (pure) ----------

BRIEF = """# Ensemble betting: your slate

You are one of several independent bettors. You will not see the others' picks and they will
not see yours. {decide}

Rules:
- Only games and markets listed below can be bet, at exactly the listed line and price.
- Markets: `spread` (side home|away), `total` (side over|under), `moneyline` (side home|away).
- {limits}
- This is a watch-only experiment: no money is placed. Results are graded after the games.

What we know from this project's own backtests (use it however you like):
- The betting market is hard to beat. Our models beat simple baselines (Elo, always-home) but
  NOT the closing line: on the NBA, the line's win probabilities and margins are more accurate
  than the model's. When our model disagrees with the line, the line has usually been right.
- At -110 you need to win 52.4% to break even; at -115, 53.5%. Moneyline favorites pay little.
- Home court is worth about 2 points in the NBA. Closing-line favorites win about 68% of NBA games.
- Model numbers below are the project's model (NBA `v1.1`, college `ncaab-v1`/`ncaab-v1-early`);
  "early" college predictions use last season as a prior and are less reliable.
- Injuries: "out" and "doubtful" players usually don't play; the line may already reflect them.
  mpg/ppg are their season averages. College games have no injury data.
- Line movement (first seen → now) can signal where informed money went.

Answer with ONLY a JSON object, no prose around it:
{{"picks": [{{"game_id": "...", "market": "spread|total|moneyline", "side": "...",
  "stake": 1, "confidence": 0.55, "reason": "one short sentence"}}],
 "notes": "optional: your overall approach in one or two sentences"}}

`confidence` is your probability that the bet wins.

Slate created {created_at}. {n_games} bettable games; {unlined} more in the window have
no line yet and can't be bet.
"""
DECIDE = (
    "Decide on your own which games to bet and what to bet on them. Passing is allowed;\n"
    "betting nothing is a valid answer if you see no value."
)
LIMITS = "At most {max_picks} picks, at most one per game. Stake 1-{max_stake} units each."
DECIDE_ONE = (
    "Decide on your own which single bet is the best of the day.\n"
    "You must make exactly one pick; passing is not allowed."
)
LIMITS_ONE = (
    "Make EXACTLY ONE pick: the single best bet of the day (one game, one market, one side),\n"
    "  stake 1 unit. Extra picks are dropped (only the first counts)."
)


def _fmt_team(t: Mapping[str, Any], side: str) -> list[str]:
    sched = []
    if t["rest_days"] is not None:
        sched.append(f"rest {t['rest_days']}d")
    if t["back_to_back"]:
        sched.append("BACK-TO-BACK")
    if t["games_last_7_days"]:
        sched.append(f"{t['games_last_7_days']} games in last 7 days")
    if t["road_trip_length"]:
        sched.append(f"road trip game {t['road_trip_length']}")
    if t["travel_km"]:
        sched.append(f"traveled {t['travel_km']} km")
    rec = t["home_record"] if side == "home" else t["away_record"]
    if t["avg_margin"] is None:
        form = "no games this season yet"
    else:
        form = (
            f"{t['record']} ({side} {rec}), last 5 {t['last5']}; avg margin {t['avg_margin']:+g}, "
            f"last-5 margin {t['last5_margin']:+g}, avg game total {t['avg_game_total']:g}"
        )
    out = [
        f"- {side.upper()} {t['abbr']} ({t['name']}): {form}"
        + (f"; {', '.join(sched)}" if sched else "")
    ]
    if t["injuries"]:
        inj = "; ".join(
            f"{i['player']} {i['status']}"
            + (f" ({i['mpg']} mpg, {i['ppg']} ppg)" if i["mpg"] is not None else "")
            for i in t["injuries"]
        )
        out.append(f"  - injuries: {inj}")
    return out


def _v2_team(t: Mapping[str, Any], league: str) -> list[str]:
    if not t.get("v2"):
        return []
    from deepsports.analysis.ensemble_context_v2 import render_team_v2

    return render_team_v2(t, league)


def render_game(g: Mapping[str, Any]) -> str:
    h, a, m = g["home"], g["away"], g["markets"]
    where = "neutral site" if g["neutral_site"] else "home"
    lines = [
        f"## {g['game_id']} · {g['league'].upper()} · {a['abbr']} @ {h['abbr']} · {g['tip_local']}"
        f" ({where}{', TV ' + g['tv'] if g['tv'] else ''})",
        *_fmt_team(a, "away"),
        *_v2_team(a, g["league"]),
        *_fmt_team(h, "home"),
        *_v2_team(h, g["league"]),
    ]
    if g["non_d1_opponent"]:
        lines.append("- note: one team is not Division I (stats for it are thin)")
    mk = []
    if "spread" in m:
        s = m["spread"]
        mk.append(
            f"spread {h['abbr']} {s['home_line']:+g} ({s['home_price']:+d}) / "
            f"{a['abbr']} {s['away_line']:+g} ({s['away_price']:+d})"
        )
    if "total" in m:
        t = m["total"]
        mk.append(f"total {t['line']:g} (over {t['over_price']:+d} / under {t['under_price']:+d})")
    if "moneyline" in m:
        ml = m["moneyline"]
        prob = ml["market_home_win_prob"]
        mk.append(
            f"moneyline {h['abbr']} {ml['home_price']:+d} / {a['abbr']} {ml['away_price']:+d}"
            + (f" (market: {h['abbr']} {prob:.0%} to win, vig removed)" if prob else "")
        )
    lines.append("- lines: " + "; ".join(mk))
    fs = g["first_seen"]
    moved = []
    if (
        "spread" in m
        and fs["spread_home"] is not None
        and fs["spread_home"] != m["spread"]["home_line"]
    ):
        moved.append(f"spread {h['abbr']} {fs['spread_home']:+g} → {m['spread']['home_line']:+g}")
    if "total" in m and fs["total"] is not None and fs["total"] != m["total"]["line"]:
        moved.append(f"total {fs['total']:g} → {m['total']['line']:g}")
    lines.append("- line movement: " + ("; ".join(moved) if moved else "none since first seen"))
    if g.get("line_timing"):
        from deepsports.analysis.ensemble_context_v2 import render_timing

        lines += render_timing(g)
    if g["model"]:
        md = g["model"]
        lines.append(
            f"- model ({md['version']}): {h['abbr']} {md['home_win_prob']:.0%} to win, "
            f"margin {h['abbr']} {md['home_margin']:+g}, total {md['total']:g}"
        )
    else:
        lines.append("- model: no prediction for this game")
    if g.get("manualbets"):
        from deepsports.analysis.manualbets_context import render_game as render_mb

        lines += render_mb(g)
    return "\n".join(lines)


def render_context(slate: Mapping[str, Any], seed: int, one_pick: bool = False) -> str:
    """The agent's context file: the brief, then every bettable game in a seed-shuffled order.

    `one_pick` (backtest slates): the rules ask for exactly one pick at stake 1. A slate's
    `brief_notes` (historical slates: where the lines and injuries come from) follow the brief."""
    games = list(slate["games"])
    random.Random(seed).shuffle(games)
    head = BRIEF.format(
        decide=DECIDE_ONE if one_pick else DECIDE,
        limits=LIMITS_ONE if one_pick else LIMITS.format(max_picks=MAX_PICKS, max_stake=MAX_STAKE),
        created_at=slate.get("created_label") or f"{slate['created_at']} (UTC)",
        n_games=len(games),
        unlined=slate["unlined_games"],
    )
    notes = slate.get("brief_notes") or []
    if notes:
        head += "\n" + "".join(f"- {n}\n" for n in notes)
    if slate.get("base_rates"):  # ctx-v2
        from deepsports.analysis.ensemble_context_v2 import render_v2_brief

        head += render_v2_brief(slate)
    if slate.get("manualbets"):  # +mb1
        from deepsports.analysis.manualbets_context import render_brief as render_mb_brief

        head += render_mb_brief(slate)
    return head + "\n" + "\n\n".join(render_game(g) for g in games) + "\n"


def agent_names(n: int) -> list[str]:
    return [f"a{i:02d}" for i in range(1, n + 1)]


# ---------- picks: parse, validate, tally (pure) ----------


def parse_reply(text: str) -> dict[str, Any]:
    """The JSON object in an agent's reply (tolerates code fences or prose around it)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in reply")
    obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict) or not isinstance(obj.get("picks"), list):
        raise ValueError("reply has no 'picks' list")
    return obj


def priced(game: Mapping[str, Any], market: str, side: str) -> tuple[float | None, int] | None:
    """(line, price) of a side from the slate, or None if that market/side isn't offered.
    Spread lines are from the bet side's view (home -3.5 / away +3.5); grading converts."""
    m = game["markets"].get(market)
    if m is None or side not in SIDES[market]:
        return None
    if market == "spread":
        return m[f"{side}_line"], m[f"{side}_price"]
    if market == "total":
        return m["line"], m[f"{side}_price"]
    return None, m[f"{side}_price"]


def validate_picks(
    reply: Mapping[str, Any], slate: Mapping[str, Any], now: datetime | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """(valid picks with slate line/price attached, problems). Keeps the first pick per game and
    the first MAX_PICKS valid picks; stakes are clamped to 1..MAX_STAKE (a slate's own
    `max_picks` / `max_stake` override both). With `now`, picks on
    games that tipped at or before `now` are dropped (they'd be graded with hindsight)."""
    games = {g["game_id"]: g for g in slate["games"]}
    max_picks = slate.get("max_picks", MAX_PICKS)  # backtest (one-pick) slates set 1
    max_stake = slate.get("max_stake", MAX_STAKE)
    picks: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, p in enumerate(reply.get("picks") or []):
        if not isinstance(p, dict):
            problems.append(f"pick {i}: not an object")
            continue
        gid = str(p.get("game_id", ""))
        market = str(p.get("market", "")).lower()
        side = str(p.get("side", "")).lower()
        game = games.get(gid)
        if game is None:
            problems.append(f"pick {i}: game {gid!r} not on the slate")
            continue
        if now is not None and datetime.fromisoformat(game["tip_utc"]) <= now:
            problems.append(f"pick {i}: {gid} already tipped off before the tally, dropped")
            continue
        if market not in MARKETS:
            problems.append(f"pick {i}: unknown market {market!r}")
            continue
        lp = priced(game, market, side)
        if lp is None:
            problems.append(f"pick {i}: {market}/{side} not offered for {gid}")
            continue
        if gid in seen:
            problems.append(f"pick {i}: second pick on {gid} dropped")
            continue
        if len(picks) >= max_picks:
            problems.append(f"pick {i}: over the {max_picks}-pick limit, dropped")
            continue
        try:
            stake = int(round(float(p.get("stake", 1))))
        except (TypeError, ValueError):
            stake = 1
        conf = p.get("confidence")
        seen.add(gid)
        picks.append(
            {
                "game_id": gid,
                "league": game["league"],
                "market": market,
                "side": side,
                "line": lp[0],
                "price": lp[1],
                "stake": min(max(stake, 1), max_stake),
                "confidence": float(conf) if isinstance(conf, int | float) else None,
                "reason": str(p.get("reason", ""))[:300],
            }
        )
    return picks, problems


def label(game: Mapping[str, Any], market: str, side: str, line: float | None) -> str:
    h, a = game["home"]["abbr"], game["away"]["abbr"]
    if market == "spread":
        return f"{h if side == 'home' else a} {line:+g}"
    if market == "total":
        return f"{side.capitalize()} {line:g}"
    return f"{h if side == 'home' else a} ML"


@dataclass(frozen=True)
class Consensus:
    game_id: str
    market: str
    side: str
    votes: int
    against: int
    agents: tuple[str, ...]


def tally(
    picks_by_agent: Mapping[str, Sequence[Mapping[str, Any]]], n_agents: int
) -> dict[str, Any]:
    """Votes per (game, market, side). A consensus pick has a strict majority of all agents
    (votes > n_agents / 2). `against` counts agents on the other side of the same market."""
    votes: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for agent, picks in picks_by_agent.items():
        for p in picks:
            votes[(p["game_id"], p["market"], p["side"])].append(agent)
    rows = []
    for (gid, market, side), agents in votes.items():
        other = next(s for s in SIDES[market] if s != side)
        rows.append(
            Consensus(
                gid,
                market,
                side,
                len(agents),
                len(votes.get((gid, market, other), [])),
                tuple(sorted(agents)),
            )  # fmt: skip
        )
    rows.sort(key=lambda c: (-c.votes, c.against, c.game_id, c.market))
    majority = [c for c in rows if c.votes * 2 > n_agents]
    per_game: dict[str, int] = defaultdict(int)
    for picks in picks_by_agent.values():
        for p in picks:
            per_game[p["game_id"]] += 1
    return {
        "n_agents": n_agents,
        "majority": majority,
        "all": rows,
        "games_bet_by_anyone": len(per_game),
        "picks_per_agent": {a: len(p) for a, p in picks_by_agent.items()},
    }


def render_tally(
    result: Mapping[str, Any],
    slate: Mapping[str, Any],
    picks_by_agent: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    games = {g["game_id"]: g for g in slate["games"]}
    by_key = {
        (a, p["game_id"], p["market"], p["side"]): p for a, ps in picks_by_agent.items() for p in ps
    }
    n = result["n_agents"]
    out = [
        f"# Ensemble betting: {n} agents, slate of {len(games)} games",
        "",
        "Watch-only. Lines and prices are the slate's, captured at "
        f"{slate['created_at'][:16]} UTC.",
        "",
        f"## Majority picks (more than {n // 2} of {n} agents)",
    ]
    if not result["majority"]:
        out.append("No pick has a majority.")
    for c in result["majority"]:
        g = games[c.game_id]
        p0 = by_key[(c.agents[0], c.game_id, c.market, c.side)]
        confs = [
            by_key[(a, c.game_id, c.market, c.side)]["confidence"]
            for a in c.agents
            if by_key[(a, c.game_id, c.market, c.side)]["confidence"] is not None
        ]
        conf = f", avg confidence {sum(confs) / len(confs):.0%}" if confs else ""
        out.append(
            f"- **{label(g, c.market, c.side, p0['line'])}** ({p0['price']:+d}) · "
            f"{g['away']['abbr']} @ {g['home']['abbr']} {g['tip_local']} · "
            f"{c.votes}/{n} agree{f', {c.against} took the other side' if c.against else ''}{conf}"
        )
        for a in c.agents:
            reason = by_key[(a, c.game_id, c.market, c.side)]["reason"]
            if reason:
                out.append(f"  - {a}: {reason}")
    near = [c for c in result["all"] if c not in result["majority"] and c.votes >= 2]
    if near:
        out += ["", "## Close but no majority"]
        for c in near[:10]:
            g = games[c.game_id]
            p0 = by_key[(c.agents[0], c.game_id, c.market, c.side)]
            out.append(
                f"- {label(g, c.market, c.side, p0['line'])} · {g['away']['abbr']} @ "
                f"{g['home']['abbr']}: {c.votes}/{n}"
                + (f" ({c.against} on the other side)" if c.against else "")
            )
    out += [
        "",
        "## Per agent",
        *(f"- {a}: {k} picks" for a, k in result["picks_per_agent"].items()),
        f"- games anyone bet: {result['games_bet_by_anyone']}",
    ]
    return "\n".join(out) + "\n"


# ---------- grading ----------


def grade_pick(pick: Mapping[str, Any], final: Mapping[str, Any]) -> dict[str, Any]:
    """Grade at the slate's line/price. Spread lines are stored from the bet side's view."""
    margin = final["home_score"] - final["away_score"]
    total = final["home_score"] + final["away_score"]
    line = pick["line"]
    if pick["market"] == "spread":
        line = line if pick["side"] == "home" else -line  # home-view line for outcome()
    result = outcome(pick["market"], pick["side"], line, margin, total)
    stake = pick["stake"]
    profit = (
        profit_on_win(pick["price"], stake)
        if result == "win"
        else (0.0 if result == "push" else -stake)
    )
    return {**pick, "grade": result, "profit": round(profit, 3)}


def summarize_graded(graded: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    w = sum(g["grade"] == "win" for g in graded)
    lo = sum(g["grade"] == "loss" for g in graded)
    pu = sum(g["grade"] == "push" for g in graded)
    staked = sum(g["stake"] for g in graded)
    profit = sum(g["profit"] for g in graded)
    return {
        "bets": len(graded),
        "record": f"{w}-{lo}-{pu}",
        "win_pct": None if w + lo == 0 else round(w / (w + lo), 3),
        "units_staked": staked,
        "units_profit": round(profit, 2),
        "roi": None if staked == 0 else round(profit / staked, 3),
    }


def load_finals(con: duckdb.DuckDBPyConnection, game_ids: Sequence[str]) -> dict[str, dict]:
    if not game_ids:
        return {}
    rows = _rows(
        con,
        f"""SELECT game_id, home_score, away_score FROM games
            WHERE completed AND status = 'STATUS_FINAL' AND game_id IN ({_marks(game_ids)})""",
        list(game_ids),
    )
    return {r["game_id"]: r for r in rows}


# ---------- run directory I/O ----------


def new_run_dir(now: datetime, root: Path = RUNS_DIR) -> Path:
    d = root / now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    d.mkdir(parents=True, exist_ok=False)
    return d


def write_context(
    run: Path, slate: Mapping[str, Any], n_agents: int, seed: int = 0, one_pick: bool = False
) -> list[Path]:
    (run / "slate.json").write_text(json.dumps(slate, indent=1, default=str))
    paths = []
    for i, name in enumerate(agent_names(n_agents)):
        p = run / f"context-{name}.md"
        p.write_text(render_context(slate, seed=seed * 1000 + i, one_pick=one_pick))
        paths.append(p)
    return paths


def read_run(
    run: Path, now: datetime | None = None
) -> tuple[dict[str, Any], dict[str, list[dict]], dict[str, list[str]]]:
    """(slate, valid picks per agent, problems per agent) from a run directory. Agents are the
    context files written; an agent without a readable picks file counts as passing on everything
    (it still counts in the majority denominator) and is reported as a problem."""
    slate = json.loads((run / "slate.json").read_text())
    picks: dict[str, list[dict]] = {}
    problems: dict[str, list[str]] = {}
    for ctx in sorted(run.glob("context-*.md")):
        name = ctx.stem.removeprefix("context-")
        f = run / f"picks-{name}.json"
        try:
            reply = parse_reply(f.read_text())
        except (OSError, ValueError) as e:
            picks[name], problems[name] = [], [f"no usable picks file: {e}"]
            continue
        picks[name], problems[name] = validate_picks(reply, slate, now=now)
    return slate, picks, problems


def tally_run(run: Path, now: datetime | None = None) -> tuple[str, dict[str, Any]]:
    """Tally once: a run's votes are fixed by its first tally (re-running would drop picks on
    games that have since tipped). Delete tally.json to force a recount."""
    if (run / "tally.json").exists():
        return (run / "tally.md").read_text(), json.loads((run / "tally.json").read_text())
    now = now or datetime.now(UTC)
    slate, picks, problems = read_run(run, now=now)
    result = tally(picks, n_agents=len(picks))
    md = render_tally(result, slate, picks)
    bad = {a: p for a, p in problems.items() if p}
    if bad:
        md += "\n## Problems\n" + "".join(f"- {a}: {'; '.join(p)}\n" for a, p in bad.items())
    games = {g["game_id"]: g for g in slate["games"]}
    majority = []
    for c in result["majority"]:
        p = next(
            x for x in picks[c.agents[0]] if (x["game_id"], x["market"]) == (c.game_id, c.market)
        )
        majority.append(
            {
                "game_id": c.game_id, "league": p["league"], "market": c.market, "side": c.side,
                "line": p["line"], "price": p["price"], "stake": 1, "votes": c.votes,
                "against": c.against, "agents": list(c.agents),
                "label": label(games[c.game_id], c.market, c.side, p["line"]),
            }
        )  # fmt: skip
    out = {
        "tallied_at": now.astimezone(UTC).isoformat(),
        "context_version": slate.get("context_version", "ctx-v1"),
        "n_agents": result["n_agents"],
        "majority": majority,
        "picks": picks,
        "problems": bad,
    }
    (run / "tally.json").write_text(json.dumps(out, indent=1))
    (run / "tally.md").write_text(md)
    return md, out


def grade_runs(con: duckdb.DuckDBPyConnection, root: Path = RUNS_DIR) -> dict[str, Any]:
    """Grade every tallied run: the majority picks (1 unit each) and each agent's own picks,
    overall and per context version (runs from before versioning count as ctx-v1)."""
    consensus: dict[str, list[dict]] = defaultdict(list)
    agents: dict[str, list[dict]] = defaultdict(list)
    pending = 0
    runs = sorted(root.glob("*/tally.json"))
    for tf in runs:
        t = json.loads(tf.read_text())
        ver = t.get("context_version", "ctx-v1")
        ids = {p["game_id"] for p in t["majority"]} | {
            p["game_id"] for ps in t["picks"].values() for p in ps
        }
        finals = load_finals(con, sorted(ids))
        for p in t["majority"]:
            if p["game_id"] in finals:
                consensus[ver].append(grade_pick(p, finals[p["game_id"]]))
            else:
                pending += 1
        for ps in t["picks"].values():
            agents[ver] += [
                grade_pick(p, finals[p["game_id"]]) for p in ps if p["game_id"] in finals
            ]
    every = lambda d: [g for gs in d.values() for g in gs]  # noqa: E731
    return {
        "runs": len(runs),
        "pending_majority_picks": pending,
        "majority": summarize_graded(every(consensus)),
        "all_agent_picks": summarize_graded(every(agents)),
        "by_context_version": {
            v: {
                "majority": summarize_graded(consensus[v]),
                "all_agent_picks": summarize_graded(agents[v]),
            }
            for v in sorted(set(consensus) | set(agents))
        },
    }
