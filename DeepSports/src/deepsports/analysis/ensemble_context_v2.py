"""ctx-v2: extra point-in-time facts for the ensemble-betting context (both live and backtest).

`attach_v2(con, slate, now)` adds, for each slate game and team, only information available at
the decision time `now`:

1. **Last season** (season_year - 1, finished before this season began): record, average
   margin, and the league model's final rating (NBA: Elo at season end; college: the ridge
   Massey net rating fit on the whole season). "n/a" for teams with no games last season.
2. **Ratings now:** NBA: Elo as of `now`; college: the prior model's ridge net rating
   (ncaab_prior: shrunk toward last season) on games finished before `now`, with its rank
   among rated D1 teams.
3. **Pace and efficiency** from box scores of games finished before `now` this season:
   possessions per game (FGA - OREB + TOV + 0.44 FTA, averaged over both teams) and points
   scored/allowed per 100 possessions (NBA net rating = off - def).
4. **NBA injury impact** of the listed out/doubtful players (the slate's point-in-time injury
   list): their share of the team's season minutes and points, and the v1.1 availability
   features computed from the list (top-3 / top-6 by mpg over the last 10 team games missing,
   missing-minutes share of the top 6). College has no injury data.
5. **Line timing** (live slates with >= 2 pregame snapshots at or before `now`): first seen,
   the biggest single move and when, and the move in the last 3 h.
6. **Base rates** (brief table) from closing lines of earlier seasons only
   (season_year < the slate's): home ATS cover rate, favorite cover rate by spread bucket,
   over rate by total bucket, each with a Wilson 95% CI.

"Finished before `now`" is start + FINISH_LAG (4 h) <= now everywhere, as in features.py.
Loaders read DuckDB read-only; renderers are pure.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb

from deepsports import config
from deepsports.analysis.backtest import wilson
from deepsports.analysis.features import FINISH_LAG

SPREAD_BUCKETS = ((0.0, 3.0, "0-3"), (3.5, 7.0, "3.5-7"), (7.5, 14.0, "7.5-14"),
                  (14.5, 24.0, "14.5-24"), (24.5, 1e9, "24.5+"))  # fmt: skip
TOTAL_BUCKETS = {
    "nba": ((0, 209.5, "<210"), (210, 219.5, "210-219.5"), (220, 229.5, "220-229.5"),
            (230, 239.5, "230-239.5"), (240, 1e9, "240+")),
    "ncaab": ((0, 134.5, "<135"), (135, 144.5, "135-144.5"), (145, 154.5, "145-154.5"),
              (155, 164.5, "155-164.5"), (165, 1e9, "165+")),
}  # fmt: skip
TIMING_WINDOW = timedelta(hours=3)
ROTATION_GAMES = 10  # players.PLAYER_WINDOW
TOP_N, TOP_K = 6, 3


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] = ()) -> list[dict]:
    cur = con.execute(sql, list(params))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _r(x: Any, nd: int = 1) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


# ---------- loaders (read-only, point-in-time) ----------


def season_record(
    con: duckdb.DuckDBPyConnection, league: str, season: int, cutoff: datetime
) -> dict[str, dict[str, Any]]:
    """team_id -> {gp, w, l, avg_margin} over finals of `season` that tipped by `cutoff`."""
    rows = _rows(
        con,
        """WITH tg AS (
             SELECT home_team_id AS team_id, home_score - away_score AS m FROM games
             WHERE league = ? AND season_year = ? AND season_type IN (2, 3) AND completed
               AND status = 'STATUS_FINAL' AND start_time_utc <= ?
             UNION ALL
             SELECT away_team_id, away_score - home_score FROM games
             WHERE league = ? AND season_year = ? AND season_type IN (2, 3) AND completed
               AND status = 'STATUS_FINAL' AND start_time_utc <= ?)
           SELECT team_id, count(*) AS gp, count(*) FILTER (m > 0) AS w,
                  count(*) FILTER (m < 0) AS l, avg(m) AS avg_margin
           FROM tg GROUP BY 1""",
        [league, season, cutoff] * 2,
    )
    return {r["team_id"]: r for r in rows}


def pace_efficiency(
    con: duckdb.DuckDBPyConnection, league: str, season: int, cutoff: datetime
) -> dict[str, dict[str, Any]]:
    """team_id -> {box_gp, pace, ortg, drtg} from box scores of `season` games that tipped by
    `cutoff` (both teams' box needed). Game possessions = mean of the two teams' estimates."""
    rows = _rows(
        con,
        """WITH tg AS (
             SELECT s.game_id, s.team_id,
                    CASE WHEN s.team_id = g.home_team_id THEN g.home_score ELSE g.away_score END
                      AS pf,
                    s.fga - s.oreb + s.tov + 0.44 * s.fta AS poss
             FROM team_game_stats s JOIN games g USING (game_id)
             WHERE g.league = ? AND g.season_year = ? AND g.season_type IN (2, 3)
               AND g.completed AND g.status = 'STATUS_FINAL' AND g.start_time_utc <= ?),
           pair AS (
             SELECT a.team_id, a.pf, b.pf AS pa, (a.poss + b.poss) / 2 AS poss
             FROM tg a JOIN tg b ON a.game_id = b.game_id AND a.team_id <> b.team_id
             WHERE a.poss > 0 AND b.poss > 0)
           SELECT team_id, count(*) AS box_gp, avg(poss) AS pace,
                  100 * sum(pf) / sum(poss) AS ortg, 100 * sum(pa) / sum(poss) AS drtg
           FROM pair GROUP BY 1""",
        [league, season, cutoff],
    )
    return {r["team_id"]: r for r in rows}


def _season_start(con: duckdb.DuckDBPyConnection, league: str, season: int) -> datetime | None:
    r = con.execute(
        "SELECT min(start_time_utc) FROM games WHERE league = ? AND season_year = ?"
        " AND season_type IN (2, 3)",
        [league, season],
    ).fetchone()
    return r[0] if r else None


def nba_elo(
    con: duckdb.DuckDBPyConnection, season: int, cutoff: datetime
) -> tuple[dict[str, float], dict[str, float]]:
    """(Elo as of `cutoff`, Elo at the end of last season). Elo as of `cutoff` applies the new
    season's carry-over to a team that hasn't played this season yet, as its next game would."""
    from deepsports.analysis.elo import elo_ratings

    now_r = elo_ratings(con, until=cutoff)
    last_season = {}
    for g in now_r.games:
        last_season[g["home_team_id"]] = g["season"]
        last_season[g["away_team_id"]] = g["season"]
    carry = 0.75  # elo_ratings default (the NBA model's setting)
    now_out = {}
    for t, r in now_r.ratings.items():
        if t in last_season and last_season[t] < season:
            r = carry * r + (1 - carry) * now_r.start(t)
        now_out[t] = r
    start = _season_start(con, "nba", season)
    end_r = {}
    if start is not None:
        prev = elo_ratings(con, until=min(start - timedelta(seconds=1), cutoff))
        played = {g["home_team_id"] for g in prev.games if g["season"] == season - 1} | {
            g["away_team_id"] for g in prev.games if g["season"] == season - 1
        }
        end_r = {t: r for t, r in prev.ratings.items() if t in played}
    return now_out, end_r


def college_ratings(
    con: duckdb.DuckDBPyConnection, season: int, cutoff: datetime
) -> tuple[dict[str, float], dict[str, int], int, dict[str, float]]:
    """(net rating now, rank among rated D1 teams, number ranked, last season's final net).
    Net = offense - defense of the ridge (Massey) ratings, in points vs an average team.
    Now: the prior model's ratings (ncaab_prior.PriorRidgeRatings, frozen config) on this
    season's games that tipped by `cutoff`; last season: ncaab_prior.final_ratings."""
    from deepsports.analysis import ncaab, ncaab_prior

    v1 = ncaab.load_config()
    pcfg = ncaab_prior.load_config()
    lam = float(v1["ridge_lambda"])
    d1 = ncaab.listed_teams(con)
    prev = ncaab._season_games(con, season - 1)
    last = ncaab_prior.final_ratings(prev, d1, lam) if prev else None
    last_net = {} if last is None else {t: last.off[t] - last.dfn[t] for t in last.off}
    last_net.pop("unlisted", None)
    games = [g for g in ncaab._season_games(con, season) if g[1] <= cutoff]

    def key(t: str) -> str:
        return t if t in d1 else "unlisted"

    teams = [key(t) for g in games for t in (g[2], g[3])]
    pr = pcfg["prior"]["ridge"]
    rr = ncaab_prior.PriorRidgeRatings(teams, lam, last, float(pr["rho"]), float(pr["lam_prior"]))
    for _, _, h, a, hs, as_, neutral in games:
        rr.add(key(h), key(a), hs, as_, bool(neutral))
    net: dict[str, float] = {}
    if not rr.empty() and rr.nt:
        th = rr.theta()
        for t, i in rr.idx.items():
            if t != "unlisted" and rr.n_games[t] > 0:
                net[t] = float(th[2 + i] - th[2 + rr.nt + i])
    order = sorted(net, key=lambda t: (-net[t], t))
    rank = {t: i + 1 for i, t in enumerate(order)}
    return net, rank, len(order), last_net


def nba_injury_impact(
    con: duckdb.DuckDBPyConnection,
    season: int,
    cutoff: datetime,
    injured: Mapping[str, Sequence[str]],
) -> dict[str, dict[str, Any]]:
    """team_id -> impact of its out/doubtful players (`injured`: team_id -> athlete_ids), from
    box scores of this season's games that tipped by `cutoff`: share of team minutes/points
    (season), and v1.1-style availability from the list: top-3 / top-6 (by mpg over the last
    ROTATION_GAMES team games, a missed game = 0) listed, missing-minutes share of the top 6."""
    teams = [t for t, ids in injured.items() if ids]
    if not teams:
        return {}
    rows = _rows(
        con,
        f"""WITH tgames AS (
              SELECT game_id, team_id, start_time_utc, row_number() OVER
                     (PARTITION BY team_id ORDER BY start_time_utc DESC) AS rn
              FROM (SELECT game_id, home_team_id AS team_id, start_time_utc FROM games
                    WHERE league = 'nba' AND season_year = ? AND season_type IN (2, 3)
                      AND completed AND start_time_utc <= ?
                    UNION ALL
                    SELECT game_id, away_team_id, start_time_utc FROM games
                    WHERE league = 'nba' AND season_year = ? AND season_type IN (2, 3)
                      AND completed AND start_time_utc <= ?)
              WHERE team_id IN ({", ".join("?" for _ in teams)}))
            SELECT t.team_id, t.rn, p.athlete_id, coalesce(p.minutes, 0) AS minutes,
                   coalesce(p.pts, 0) AS pts
            FROM tgames t JOIN player_game_stats p
              ON p.game_id = t.game_id AND p.team_id = t.team_id
            WHERE NOT coalesce(p.did_not_play, FALSE)""",
        [season, cutoff, season, cutoff, *teams],
    )
    by_team: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_team[r["team_id"]].append(r)
    out = {}
    for t in teams:
        rs = by_team.get(t, [])
        if not rs:
            continue
        out_ids = set(injured[t])
        tot_min = sum(r["minutes"] for r in rs)
        tot_pts = sum(r["pts"] for r in rs)
        n_recent = min(ROTATION_GAMES, max(r["rn"] for r in rs))
        recent: dict[str, float] = defaultdict(float)
        for r in rs:
            if r["rn"] <= ROTATION_GAMES:
                recent[r["athlete_id"]] += r["minutes"] / n_recent
        rot = sorted(recent, key=lambda a: (-recent[a], a))
        top6, top3 = rot[:TOP_N], rot[:TOP_K]
        top6_min = sum(recent[a] for a in top6)
        out[t] = {
            "min_share": None
            if tot_min == 0
            else sum(r["minutes"] for r in rs if r["athlete_id"] in out_ids) / tot_min,
            "pts_share": None
            if tot_pts == 0
            else sum(r["pts"] for r in rs if r["athlete_id"] in out_ids) / tot_pts,
            "top3_out": sum(a in out_ids for a in top3),
            "top6_out": sum(a in out_ids for a in top6),
            "miss_share": None
            if top6_min == 0
            else sum(recent[a] for a in top6 if a in out_ids) / top6_min,
        }
    return out


def line_timing(
    con: duckdb.DuckDBPyConnection, game_ids: Sequence[str], now: datetime
) -> dict[str, dict[str, Any]]:
    """game_id -> timing of its pregame snapshots captured at or before `now` (games with >= 2
    snapshots only): first seen, the biggest single spread/total move and when, and the move
    over the last TIMING_WINDOW."""
    if not game_ids:
        return {}
    rows = _rows(
        con,
        f"""SELECT game_id, captured_at, spread_home, over_under FROM odds_snapshots
            WHERE source = 'pregame' AND captured_at <= ?
              AND game_id IN ({", ".join("?" for _ in game_ids)})
            ORDER BY game_id, captured_at""",
        [now, *game_ids],
    )
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["game_id"]].append(r)
    out = {}
    for gid, snaps in by.items():
        if len(snaps) < 2:
            continue
        best = None
        for a, b in zip(snaps, snaps[1:], strict=False):
            for k, name in (("spread_home", "spread"), ("over_under", "total")):
                if a[k] is not None and b[k] is not None and a[k] != b[k]:
                    mv = abs(b[k] - a[k])
                    if best is None or mv > best["size"]:
                        best = {"market": name, "from": a[k], "to": b[k], "size": mv,
                                "at": b["captured_at"]}  # fmt: skip
        recent = [s for s in snaps if s["captured_at"] >= now - TIMING_WINDOW]
        base = [s for s in snaps if s["captured_at"] < now - TIMING_WINDOW]
        ref = base[-1] if base else snaps[0]
        last = snaps[-1]

        delta = {
            k: None if not recent or ref[k] is None or last[k] is None else last[k] - ref[k]
            for k in ("spread_home", "over_under")
        }
        out[gid] = {
            "first_seen": snaps[0]["captured_at"],
            "n": len(snaps),
            "biggest": best,
            "last3h_spread": delta["spread_home"],
            "last3h_total": delta["over_under"],
        }
    return out


def base_rates(con: duckdb.DuckDBPyConnection, league: str, before_season: int) -> dict[str, Any]:
    """Closing-line outcome rates over finals with season_year < `before_season` (college:
    D1 vs D1 only). Pushes are excluded. Each rate has a Wilson 95% CI."""
    d1 = (
        """AND coalesce(h.listed, TRUE) AND coalesce(a.listed, TRUE)""" if league == "ncaab" else ""
    )
    rows = con.execute(
        f"""WITH c AS (
              SELECT game_id, spread_home, over_under FROM odds_snapshots WHERE source = 'closing'
              QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) = 1)
            SELECT g.season_year, g.home_score - g.away_score, g.home_score + g.away_score,
                   c.spread_home, c.over_under
            FROM games g JOIN c USING (game_id)
            JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
            JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
            WHERE g.league = ? AND g.season_year < ? AND g.season_type IN (2, 3)
              AND g.completed AND g.status = 'STATUS_FINAL' {d1}""",
        [league, before_season],
    ).fetchall()
    from deepsports.store import SANE_LIMITS

    max_spread, lo, hi = SANE_LIMITS[league]
    home = [0, 0]
    fav = {b[2]: [0, 0] for b in SPREAD_BUCKETS}
    over = {b[2]: [0, 0] for b in TOTAL_BUCKETS[league]}
    seasons = set()
    for season, margin, total, sp, ou in rows:
        seasons.add(season)
        if sp is not None and abs(sp) <= max_spread:
            ats = margin + sp
            if ats != 0:
                home[0] += ats > 0
                home[1] += 1
                if sp != 0:
                    fav_covers = (ats < 0) if sp > 0 else (ats > 0)  # home is the dog if sp > 0
                    for a, b, name in SPREAD_BUCKETS:
                        if a <= abs(sp) <= b:
                            fav[name][0] += fav_covers
                            fav[name][1] += 1
        if ou is not None and lo <= ou <= hi and total != ou:
            for a, b, name in TOTAL_BUCKETS[league]:
                if a <= ou <= b:
                    over[name][0] += total > ou
                    over[name][1] += 1

    def rate(k: int, n: int) -> dict[str, Any]:
        lo_, hi_ = wilson(k, n)
        return {"k": k, "n": n, "rate": None if n == 0 else k / n, "lo": lo_, "hi": hi_}

    return {
        "league": league,
        "before_season": before_season,
        "seasons": sorted(seasons),
        "home_ats": rate(*home),
        "favorite_ats": {k: rate(*v) for k, v in fav.items()},
        "over": {k: rate(*v) for k, v in over.items()},
    }


# ---------- attach to a slate ----------


def attach_v2(
    con: duckdb.DuckDBPyConnection,
    slate: dict[str, Any],
    now: datetime,
    raw_games: Sequence[Mapping[str, Any]],
    injuries: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]] | None = None,
    timing: bool = True,
) -> dict[str, Any]:
    """Add the ctx-v2 blocks to `slate` in place (and return it).

    `raw_games`: the loader rows the slate was built from (team ids, season_year).
    `injuries`: (game_id, team_id) -> point-in-time injury rows (athlete_id, status), as the
    slate's own loader returned them; only out/doubtful players count toward impact.
    `timing`: line timing from pregame snapshots (live slates; backtests pass False)."""
    cutoff = now - FINISH_LAG
    meta = {g["game_id"]: g for g in raw_games}
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for g in slate["games"]:
        groups[(g["league"], meta[g["game_id"]]["season_year"])].append(g)
    slate["base_rates"] = {}
    for (league, season), gs in sorted(groups.items()):
        last = season_record(con, league, season - 1, cutoff)
        box = pace_efficiency(con, league, season, cutoff)
        elo_now: dict[str, float] = {}
        elo_end: dict[str, float] = {}
        impact: dict[str, dict[str, Any]] = {}
        net: dict[str, float] = {}
        rank: dict[str, int] = {}
        n_ranked, last_net = 0, {}
        if league == "nba":
            elo_now, elo_end = nba_elo(con, season, cutoff)
            listed: dict[str, list[str]] = defaultdict(list)
            for g in gs:
                for tid in (meta[g["game_id"]]["home_team_id"], meta[g["game_id"]]["away_team_id"]):
                    for i in (injuries or {}).get((g["game_id"], tid), []):
                        if i["status"] in ("out", "doubtful") and i.get("athlete_id"):
                            listed[tid].append(i["athlete_id"])
            impact = nba_injury_impact(con, season, cutoff, listed)
        else:
            net, rank, n_ranked, last_net = college_ratings(con, season, cutoff)
        for g in gs:
            m = meta[g["game_id"]]
            for side in ("home", "away"):
                tid = m[f"{side}_team_id"]
                ls = last.get(tid)
                b = box.get(tid) or {}
                final = elo_end.get(tid) if league == "nba" else last_net.get(tid)
                imp = impact.get(tid)
                g[side]["v2"] = {
                    "last_season": None
                    if not ls
                    else {
                        "record": f"{ls['w']}-{ls['l']}",
                        "avg_margin": _r(ls["avg_margin"]),
                        "final_rating": _r(final, 0 if league == "nba" else 1),
                    },
                    "elo": _r(elo_now.get(tid), 0) if league == "nba" else None,
                    "rating": _r(net.get(tid)) if league == "ncaab" else None,
                    "rank": rank.get(tid),
                    "n_ranked": n_ranked or None,
                    "box_gp": b.get("box_gp"),
                    "pace": _r(b.get("pace")),
                    "ortg": _r(b.get("ortg")),
                    "drtg": _r(b.get("drtg")),
                    "injury_impact": None
                    if not imp
                    else {k: (_r(v, 3) if isinstance(v, float) else v) for k, v in imp.items()},
                }
        if league not in slate["base_rates"]:
            seasons = min(s for (lg, s) in groups if lg == league)
            slate["base_rates"][league] = base_rates(con, league, seasons)
    if timing:
        lt = line_timing(con, [g["game_id"] for g in slate["games"]], now)
        for g in slate["games"]:
            t = lt.get(g["game_id"])
            g["line_timing"] = None if t is None else _timing_json(t)
    return slate


def _timing_json(t: Mapping[str, Any]) -> dict[str, Any]:
    b = t["biggest"]
    return {
        "first_seen": t["first_seen"].astimezone(UTC).isoformat(),
        "snapshots": t["n"],
        "biggest": None if b is None else {**b, "at": b["at"].astimezone(UTC).isoformat()},
        "last3h_spread": t["last3h_spread"],
        "last3h_total": t["last3h_total"],
    }


def strip_v2(slate: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `slate` without the ctx-v2 blocks (renders exactly as ctx-v1)."""
    out = {k: v for k, v in slate.items() if k != "base_rates"}
    games = []
    for g in slate["games"]:
        x = {k: v for k, v in g.items() if k != "line_timing"}
        for side in ("home", "away"):
            x[side] = {k: v for k, v in g[side].items() if k != "v2"}
        games.append(x)
    out["games"] = games
    return out


# ---------- rendering (pure) ----------


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def render_team_v2(t: Mapping[str, Any], league: str) -> list[str]:
    v = t.get("v2")
    if not v:
        return []
    ls = v["last_season"]
    if ls is None:
        last = "last season n/a"
    else:
        fr = ls["final_rating"]
        fr_s = "n/a" if fr is None else (f"Elo {fr:g}" if league == "nba" else f"rating {fr:+g}")
        last = f"last season {ls['record']} (avg margin {ls['avg_margin']:+g}, final {fr_s})"
    parts = [last]
    if league == "nba":
        now = f"Elo now {v['elo']:g}" if v["elo"] is not None else "Elo now n/a"
        if v["ortg"] is not None:
            now += f", net {v['ortg'] - v['drtg']:+.1f} per 100"
        parts.append(now)
    else:
        parts.append(
            "rating now n/a"
            if v["rating"] is None
            else f"rating now {v['rating']:+g} (#{v['rank']} of {v['n_ranked']} D1)"
        )
    if v["pace"] is not None:
        parts.append(f"pace {v['pace']:g}, off {v['ortg']:g} / def {v['drtg']:g} per 100")
    out = ["  - more: " + "; ".join(parts)]
    imp = v.get("injury_impact")
    if imp:
        out.append(
            f"  - injury impact: missing ~{_pct(imp['min_share'])} of usual minutes, "
            f"{_pct(imp['pts_share'])} of points; top-3 listed {imp['top3_out']}, top-6 listed "
            f"{imp['top6_out']} (missing-minutes share of top 6: {_pct(imp['miss_share'])})"
        )
    return out


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(config.LOCAL_TZ).strftime("%a %-I:%M %p")


def render_timing(g: Mapping[str, Any]) -> list[str]:
    t = g.get("line_timing")
    if not t:
        return []
    parts = [f"first seen {_local(t['first_seen'])} ({t['snapshots']} snapshots)"]
    b = t["biggest"]
    if b:
        parts.append(f"biggest move {b['market']} {b['from']:g} → {b['to']:g} at {_local(b['at'])}")
    mv = [
        f"{k} {v:+g}"
        for k, v in (("spread", t["last3h_spread"]), ("total", t["last3h_total"]))
        if v
    ]
    parts.append("last 3 h: " + (", ".join(mv) if mv else "no move"))
    return ["- line timing: " + "; ".join(parts)]


def _ci(r: Mapping[str, Any]) -> str:
    if not r["n"]:
        return "n/a"
    return f"{r['rate']:.1%} ({r['lo']:.1%}-{r['hi']:.1%}, n={r['n']})"


def render_base_rates(br: Mapping[str, Any]) -> str:
    league = br["league"].upper()
    lines = [
        f"Base rates, {league}, closing lines of {len(br['seasons'])} earlier seasons "
        "(95% CI, pushes excluded):",
        f"- home team covers the spread: {_ci(br['home_ats'])}",
        "- favorite covers, by spread size: "
        + "; ".join(f"{k}: {_ci(v)}" for k, v in br["favorite_ats"].items()),
        "- over hits, by total: " + "; ".join(f"{k}: {_ci(v)}" for k, v in br["over"].items()),
    ]
    return "\n".join(lines)


V2_BRIEF = """
More facts in this context version (all from before this slate):
- "more": last season's record, average margin and final rating; the rating now (NBA: Elo,
  plus net points per 100 possessions; college: an opponent-adjusted net rating in points per
  game with its rank among D1 teams); pace (possessions per game) and points scored / allowed
  per 100 possessions this season.
- NBA "injury impact": the listed out/doubtful players' share of the team's minutes and points,
  and how many of its top-3 / top-6 rotation players are listed. {injury_note}
- "line timing" (when the line was captured more than once): when it first appeared, its
  biggest single move, and the move in the last 3 hours.
- Base rates below are descriptive history, not edges: the market already prices them.
"""


def render_v2_brief(slate: Mapping[str, Any]) -> str:
    leagues = sorted(slate.get("base_rates") or {})
    note = "College games have no injury data." if "ncaab" in leagues else ""
    text = V2_BRIEF.format(injury_note=note).replace(" \n", "\n").rstrip("\n")
    tables = [render_base_rates(slate["base_rates"][lg]) for lg in leagues]
    return text + "\n\n" + "\n\n".join(tables) + "\n"
