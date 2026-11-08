"""Pre-game feature rows for every game: everything here is known before tip-off.

One row per game (completed finals and scheduled `pre` games), in tip-off order. Sources:
- Elo (elo.py): ratings recorded *before* each game; scheduled games use current ratings.
- `team_game_context` view (schedule context: rest, back-to-backs, travel). Optional: if the
  view is missing, those features are NULL and the model imputes them.
- Rolling team form from PRIOR games' box scores in the same season (last `window` games),
  shrunk toward a league-wide prior so early-season values are not wild.
- `injury_reports`: OFF by default (see `_injury_counts`), because historical rows may not
  have been captured before tip-off.
- `player_game_stats` (model v1.1, `include_players=True`): rotation, availability and top-N
  player features from prior box scores (players.py). OFF by default, so v1 rows are unchanged.

Leakage rule: a completed game only enters team or league history once it has *finished*
before the current game's tip (start + `FINISH_LAG` <= tip). A game's own result never feeds
its own features. No market (odds) inputs are features: the market is the benchmark.
"""

import math
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

import duckdb

from deepsports.analysis.elo import elo_ratings
from deepsports.analysis.market import (
    DEFAULT_SEASON_TYPES,
    _in,
    final_sql,
    sane_spread,
    sane_total,
)
from deepsports.analysis.metrics import devig_probability
from deepsports.analysis.players import (
    PlayerHistory,
    game_features,
    player_box,
    pregame_out,
)

FINISH_LAG = timedelta(hours=4)  # a game is treated as known only 4h after its tip-off
LEAGUE_WINDOW = 400  # team-games in the league-wide rolling prior (about 2.5 weeks)
SHRINK_GAMES = 3.0  # prior weight, in games, for early-season shrinkage
REST_CAP = 4  # extra rest beyond 4 days is treated as 4
ELO_HOME_ADV = 100.0
# League-wide priors used before any league history exists.
FALLBACKS = {
    "nba": {"pts": 110.0, "poss": 100.0, "eff": 110.0},
    "ncaab": {"pts": 72.0, "poss": 68.0, "eff": 105.0},
}
FALLBACK = FALLBACKS["nba"]

# Feature columns (all numeric; NaN = missing, imputed by the model).
FEATURES = [
    "elo_diff",  # home Elo - away Elo, pre-game, no home edge included
    "home_court",  # 1 normally, 0 on a neutral site
    "rest_diff",  # clipped rest days, home - away
    "b2b_home",
    "b2b_away",
    "g7_home",  # games in the last 7 days
    "g7_away",
    "travel_home",  # thousands of km travelled to this game
    "travel_away",
    "road_trip_away",  # length of the away team's current road trip
    "form_net_diff",  # shrunk last-N (points for - points against) per game, home - away
    "eff_net_diff",  # shrunk (off rating - def rating) per 100 possessions, home - away
    "lg_total",  # league-wide recent average game total
    "form_total",  # expected total from both teams' recent points for + against
    "pace_sum",  # both teams' recent possessions per game
    "eff_sum",  # both teams' recent off + def ratings (higher = more scoring)
]
# Optional, off by default (see _injury_counts).
INJURY_FEATURES = ["out_home", "out_away"]


def _nan(v: Any) -> float:
    return float("nan") if v is None else float(v)


def possessions(fga: Any, oreb: Any, tov: Any, fta: Any) -> float | None:
    """Possessions ~= FGA - OREB + TOV + 0.44 * FTA (None if any input is missing)."""
    if None in (fga, oreb, tov, fta):
        return None
    return fga - oreb + tov + 0.44 * fta


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    q = "SELECT count(*) FROM information_schema.tables WHERE table_name = ?"
    return con.execute(q, [name]).fetchone()[0] > 0


def _context(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], dict[str, Any]]:
    if not _table_exists(con, "team_game_context"):
        return {}
    cur = con.execute(
        """SELECT game_id, team_id, rest_days, back_to_back, games_last_7_days,
                  road_trip_length, travel_km FROM team_game_context"""
    )
    cols = [d[0] for d in cur.description]
    return {(r[0], r[1]): dict(zip(cols, r, strict=True)) for r in cur.fetchall()}


def _injury_counts(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], int]:
    """INJURY HOOK (off by default; enable with build_features(include_injuries=True)).

    Count of players listed 'Out' per (game, team) in the LATEST snapshot captured before
    tip-off (rows captured after tip are ignored).
    Historical rows may have been captured after the game, which would leak; that is why the
    filter on captured_before_tip is mandatory and the feature is off until enough truly
    pre-game snapshots exist. Rows for games with no reports get NaN (imputed), not 0.
    """
    if not _table_exists(con, "injury_reports"):
        return {}
    rows = con.execute(
        """
        WITH last AS (
            SELECT game_id, team_id, max(captured_at) AS captured_at
            FROM injury_reports WHERE captured_before_tip GROUP BY ALL
        )
        SELECT r.game_id, r.team_id, count(*) FILTER (WHERE lower(r.status) = 'out')
        FROM injury_reports r JOIN last USING (game_id, team_id, captured_at)
        WHERE r.captured_before_tip GROUP BY 1, 2
        """
    ).fetchall()
    return {(g, t): n for g, t, n in rows}


def _box(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], float | None]:
    rows = con.execute("SELECT game_id, team_id, fga, oreb, tov, fta FROM team_game_stats")
    return {(g, t): possessions(*rest) for g, t, *rest in rows.fetchall()}


def closing_lines(
    con: duckdb.DuckDBPyConnection, league: str = "nba"
) -> dict[str, dict[str, float | None]]:
    """game_id -> latest closing spread_home, over_under and vig-free home win probability for
    `league`'s games. Implausible spreads/totals become None (the league's filters in
    market.py). Benchmark only."""
    spread_ok = sane_spread(league).format(col="o.spread_home")
    total_ok = sane_total(league).format(col="o.over_under")
    rows = con.execute(
        f"""
        SELECT o.game_id,
               CASE WHEN {spread_ok} THEN o.spread_home END,
               CASE WHEN {total_ok} THEN o.over_under END,
               o.home_moneyline, o.away_moneyline
        FROM odds_snapshots o JOIN games g USING (game_id)
        WHERE o.source = 'closing' AND g.league = ?
        QUALIFY row_number() OVER (PARTITION BY o.game_id ORDER BY o.captured_at DESC) = 1
        """,
        [league],
    ).fetchall()
    return {
        g: {"spread_home": s, "over_under": t, "p_home": devig_probability(h, a)}
        for g, s, t, h, a in rows
    }


class _Rolling:
    """Per-team last-N history plus a league-wide rolling prior, fed only by finished games."""

    def __init__(self, window: int, fallback: dict[str, float] | None = None):
        self.window = window
        self.fallback = fallback or FALLBACK
        self.team: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
        self.team_season: dict[str, int] = {}
        self.league: deque = deque(maxlen=LEAGUE_WINDOW)  # (pts, poss | None)

    def add(self, team: str, season: int, pf: int, pa: int, poss: float | None, opp_poss):
        if self.team_season.get(team) != season:
            self.team[team].clear()
            self.team_season[team] = season
        # Use the average of both teams' possession estimates when available (less noisy).
        both = [p for p in (poss, opp_poss) if p]
        game_poss = sum(both) / len(both) if both else None
        self.team[team].append((pf, pa, game_poss))
        self.league.append((pf, game_poss))

    def league_prior(self) -> dict[str, float]:
        if not self.league:
            return dict(self.fallback)
        pts = sum(p for p, _ in self.league) / len(self.league)
        with_poss = [(p, q) for p, q in self.league if q]
        if not with_poss:
            return {"pts": pts, "poss": self.fallback["poss"], "eff": self.fallback["eff"]}
        poss = sum(q for _, q in with_poss) / len(with_poss)
        eff = 100 * sum(p for p, _ in with_poss) / sum(q for _, q in with_poss)
        return {"pts": pts, "poss": poss, "eff": eff}

    def form(self, team: str, season: int, prior: dict[str, float]) -> dict[str, float]:
        hist = list(self.team[team]) if self.team_season.get(team) == season else []
        k = SHRINK_GAMES
        n = len(hist)
        pf = (sum(h[0] for h in hist) + k * prior["pts"]) / (n + k)
        pa = (sum(h[1] for h in hist) + k * prior["pts"]) / (n + k)
        hp = [h for h in hist if h[2]]
        m = len(hp)
        poss_sum = sum(h[2] for h in hp)
        # Shrink efficiency by adding k prior games' worth of possessions and points.
        prior_poss = k * prior["poss"]
        prior_pts = prior_poss * prior["eff"] / 100
        ortg = 100 * (sum(h[0] for h in hp) + prior_pts) / (poss_sum + prior_poss)
        drtg = 100 * (sum(h[1] for h in hp) + prior_pts) / (poss_sum + prior_poss)
        pace = (poss_sum + prior_poss) / (m + k)
        return {"n": n, "pf": pf, "pa": pa, "ortg": ortg, "drtg": drtg, "pace": pace}


def _pre_game_elo(elo, season_of: dict[str, int], team: str, season: int, carry_over: float):
    r = elo.rating(team)
    if team in season_of and season_of[team] != season:
        r = carry_over * r + (1 - carry_over) * elo.start(elo.key(team))
    return r


def build_features(
    con: duckdb.DuckDBPyConnection,
    window: int = 10,
    include_injuries: bool = False,
    season_types: tuple[int, ...] = DEFAULT_SEASON_TYPES,
    carry_over: float = 0.75,
    include_players: bool = False,
    injury_override: bool = False,
    league: str = "nba",
    elo_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Feature rows for completed finals and scheduled games, in tip-off order.

    `include_players` adds PLAYER_FEATURES (model v1.1). `injury_override` (needs
    include_players; never used in the backtest) lets scheduled games use the pre-tip
    `pregame_injuries` snapshot instead of "played the previous game" (see players.py).

    Each row: ids, season, start time, `state` ('post' or 'pre'), `features` (dict of
    FEATURES [+ INJURY_FEATURES] [+ PLAYER_FEATURES]), targets `home_margin` / `total` /
    `home_win` (None for scheduled games), `elo_p_home` and `elo_margin` baselines, and
    `market` closing lines (benchmark only, never a feature).

    `league` scopes every query ('nba' default, 'ncaab' for college); `elo_params` are passed
    to elo_ratings (k, home_adv, pool_unlisted, pool_rating). Defaults reproduce model v1.
    """
    elo_params = dict(elo_params or {})
    home_adv = float(elo_params.get("home_adv", ELO_HOME_ADV))
    elo = elo_ratings(
        con, carry_over=carry_over, season_types=season_types, league=league, **elo_params
    )
    final = final_sql(league)
    pre_elo = {g["game_id"]: g for g in elo.games}
    last_season: dict[str, int] = {}
    for g in elo.games:
        last_season[g["home_team_id"]] = g["season"]
        last_season[g["away_team_id"]] = g["season"]

    ctx = _context(con)
    inj = _injury_counts(con) if include_injuries else {}
    poss = _box(con)
    market = closing_lines(con, league)
    pbox = player_box(con, league) if include_players else {}
    pouts = pregame_out(con, league) if include_players and injury_override else {}
    phist = PlayerHistory()
    games = con.execute(
        f"""
        SELECT g.game_id, g.season_year, g.season_type, g.start_time_utc, g.home_team_id,
               g.away_team_id, coalesce(g.neutral_site, false),
               CASE WHEN {final} THEN g.home_score END, CASE WHEN {final} THEN g.away_score END,
               CASE WHEN {final} THEN 'post' ELSE 'pre' END
        FROM games g
        WHERE g.league = $lg AND g.season_type IN ({_in(season_types)})
          AND (({final}) OR (g.state = 'pre'
               AND g.home_team_id IN (SELECT team_id FROM teams WHERE league = $lg)
               AND g.away_team_id IN (SELECT team_id FROM teams WHERE league = $lg)))
        ORDER BY g.start_time_utc, g.game_id
        """,
        {"lg": league},
    ).fetchall()

    roll = _Rolling(window, FALLBACKS[league])
    pending: deque = deque()  # finished games not yet visible (FIFO in tip-off order)
    out = []
    for gid, season, stype, start, home, away, neutral, hs, as_, state in games:
        while pending and pending[0][0] + FINISH_LAG <= start:
            _, s, h, a, phs, pas, ph, pa, pgid = pending.popleft()
            roll.add(h, s, phs, pas, ph, pa)
            roll.add(a, s, pas, phs, pa, ph)
            if include_players:
                phist.add(h, s, pbox.get((pgid, h)))
                phist.add(a, s, pbox.get((pgid, a)))

        if state == "post":
            e = pre_elo[gid]
            h_elo, a_elo, p_elo = e["home_elo_pre"], e["away_elo_pre"], e["p_home"]
        else:
            h_elo = _pre_game_elo(elo, last_season, home, season, carry_over)
            a_elo = _pre_game_elo(elo, last_season, away, season, carry_over)
            p_elo = 1 / (1 + 10 ** (-(h_elo - a_elo + (0 if neutral else home_adv)) / 400))

        prior = roll.league_prior()
        fh = roll.form(home, season, prior)
        fa = roll.form(away, season, prior)
        ch = ctx.get((gid, home), {})
        ca = ctx.get((gid, away), {})

        def rest(c):
            r = c.get("rest_days")
            return None if r is None else min(max(r, 0), REST_CAP)

        rh, ra = rest(ch), rest(ca)
        travel_h, travel_a = ch.get("travel_km"), ca.get("travel_km")
        feats = {
            "elo_diff": h_elo - a_elo,
            "home_court": 0.0 if neutral else 1.0,
            "rest_diff": _nan(None if rh is None or ra is None else rh - ra),
            "b2b_home": _nan(None if ch.get("back_to_back") is None else int(ch["back_to_back"])),
            "b2b_away": _nan(None if ca.get("back_to_back") is None else int(ca["back_to_back"])),
            "g7_home": _nan(ch.get("games_last_7_days")),
            "g7_away": _nan(ca.get("games_last_7_days")),
            "travel_home": _nan(None if travel_h is None else travel_h / 1000),
            "travel_away": _nan(None if travel_a is None else travel_a / 1000),
            "road_trip_away": _nan(ca.get("road_trip_length")),
            "form_net_diff": (fh["pf"] - fh["pa"]) - (fa["pf"] - fa["pa"]),
            "eff_net_diff": (fh["ortg"] - fh["drtg"]) - (fa["ortg"] - fa["drtg"]),
            "lg_total": 2 * prior["pts"],
            "form_total": (fh["pf"] + fh["pa"] + fa["pf"] + fa["pa"]) / 2,
            "pace_sum": fh["pace"] + fa["pace"],
            "eff_sum": fh["ortg"] + fh["drtg"] + fa["ortg"] + fa["drtg"],
        }
        if include_injuries:
            feats["out_home"] = _nan(inj.get((gid, home)))
            feats["out_away"] = _nan(inj.get((gid, away)))
        if include_players:
            over = pouts if state == "pre" else {}  # never for completed games
            feats.update(
                game_features(
                    phist.team_features(home, season, over.get((gid, home))),
                    phist.team_features(away, season, over.get((gid, away))),
                )
            )
        assert all(isinstance(v, float) for v in feats.values())

        done = state == "post"
        out.append(
            {
                "game_id": gid,
                "season": season,
                "season_type": stype,
                "start_time_utc": start,
                "state": state,
                "home_team_id": home,
                "away_team_id": away,
                "neutral_site": bool(neutral),
                "features": feats,
                "home_margin": hs - as_ if done else None,
                "total": hs + as_ if done else None,
                "home_win": int(hs > as_) if done else None,
                "elo_p_home": p_elo,
                "elo_margin": elo_implied_margin(h_elo - a_elo, neutral, home_adv),
                "market": market.get(gid, {}),
                "form_games": min(fh["n"], fa["n"]),
            }
        )
        if done:
            # Each side's own possession estimate; _Rolling averages the pair.
            ph, pa = poss.get((gid, home)), poss.get((gid, away))
            pending.append((start, season, home, away, hs, as_, ph, pa, gid))
    return out


ELO_PER_POINT = 28.0  # FiveThirtyEight: about 28 Elo points per point of margin


def elo_implied_margin(elo_diff: float, neutral: bool, home_adv: float = ELO_HOME_ADV) -> float:
    """Elo-only predicted home margin: (elo_diff + home edge) / 28."""
    return (elo_diff + (0.0 if neutral else home_adv)) / ELO_PER_POINT


def feature_matrix(rows: list[dict[str, Any]], names: list[str]) -> list[list[float]]:
    return [[r["features"].get(n, math.nan) for n in names] for r in rows]
