"""Player impact ratings and injury impact in points (NBA), from box scores only.

    DEEPSPORTS_DB=/path/copy.duckdb uv run python -m deepsports.analysis.player_impact \\
        report --out /Volumes/ExFATStorag/DeepSports/reports/player-impact/report.md

The backtest, market tests and report live in `player_impact_eval.py` (this CLI forwards
there). Results and the decision: `docs/results/2026-11-11-player-impact.md`. This is research
tooling: nothing here is wired into a model, job, the API or the ensemble context.

**Ratings.** Each player gets an on-court value in points per 48 minutes of team margin (about
per 100 possessions), fitted only on games that finished before the as-of time (tip + FINISH_LAG
<= as_of), with exponential time decay (`HALF_LIFE_DAYS`) over a `WINDOW_DAYS` window. A rating
follows the player (athlete_id) across teams: after a trade the RATING carries over, but his
expected minutes at the new team start from zero (rotations are per team). Methods:
- `pm48`: shrunk on-court plus-minus per 48, divided by 5 (one of five on the floor), shrunk by
  `PM_PRIOR_MINUTES` minutes at 0.
- `rapm10` / `rapm40`: game-level ridge ("RAPM-lite"): each game's margin per 48 is regressed
  on both teams' minute shares (5 per side, home +, away -) plus a home-edge column; ridge
  lambda 10 or 40 pulls low-minute players toward 0.
Ratings are recentred so the decayed minutes-weighted mean is 0. Unknown players (no minutes
in the window) and minutes nobody in the rotation can absorb get `REPLACEMENT`.

**Team impact.** The expected rotation is the team's last `ROTATION_WINDOW` games this season
(finished before as-of): weight = minutes per game played x min(1, games played / FULL_GP),
allocated to 240 minutes with a `MINUTE_CAP` cap. Full strength = sum(minutes/48 x rating).
OUT players are removed and their minutes **redistributed** by re-allocating the remaining
weights to 240 (not just subtracted). Missing impact = full - available, in points.

OUT comes from (a) an explicit list (live use: `pregame_injuries` Out), (b) the honest proxy:
rotation players who did not play the team's previous game, or (c) the ORACLE (who did not play
this very game): LEAKED, for measuring a ceiling only, never a model input.

**Known limitations (read before any live use).**
- Departed players linger: a player traded away, waived or out for the season stays in his old
  team's rotation for up to `ROTATION_WINDOW` games (he looks "OUT" under the proxy, so his
  minutes are redistributed, but he still inflates full strength and missing impact). "No row
  in the latest box score" can't be read as "off the roster": in the warehouse, 73% of
  rotation-player absences with no box-score row (vs a DNP row) end with the player returning
  to the same team, i.e. ESPN often omits injured players entirely.
- Ratings are game-level ridge on minute shares, with no stints or box-score prior: star
  ratings are noisy and often implausible (see the results doc), so missing impact for a star
  is usually understated.
"""

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import duckdb
import numpy as np
import scipy.sparse as sp

from deepsports.analysis.features import FINISH_LAG
from deepsports.analysis.market import DEFAULT_SEASON_TYPES, _in, final_sql
from deepsports.analysis.players import Line, player_box, pregame_out

HALF_LIFE_DAYS = 365.0
WINDOW_DAYS = 730
PM_PRIOR_MINUTES = 500.0
REPLACEMENT = -2.0  # points per 48 for unknown players and overflow minutes
ROTATION_WINDOW = 10  # team games
FULL_GP = 3  # games played in the window for full rotation weight
TEAM_MINUTES = 240.0
MINUTE_CAP = 40.0
# tip - 10h (UTC) -> slate date: one US evening = one slate. ensemble._eastern_date uses -5h;
# for NBA tip times (about 16:00-04:00 UTC) both give the same grouping. 10h keeps a late West
# Coast tip (and its 4h finish lag) on the same slate with margin to spare.
SLATE_SHIFT = timedelta(hours=10)

METHODS = {
    "pm48": {"kind": "pm48"},
    "rapm10": {"kind": "rapm", "lam": 10.0},
    "rapm40": {"kind": "rapm", "lam": 40.0},
}
# Chosen on test seasons 2024-25 only by the pre-registered rule (lowest v1.2 margin MAE,
# `python -m deepsports.analysis.player_impact select`), frozen before the 2025-26 holdout was
# scored. Numbers: docs/results/2026-11-11-player-impact.md.
CHOSEN_METHOD = "rapm10"

IMPACT_FEATURES = ["imp_avail_diff", "imp_missing_diff"]  # proxy OUT (pre-tip, usable)
ORACLE_FEATURES = ["orc_avail_diff", "orc_missing_diff"]  # actual OUT (LEAKED, ceiling only)
FULL_FEATURE = "imp_full_diff"  # full-strength diff, no availability (diagnostic only)


def slate_date(start: datetime) -> date:
    return (start.astimezone(UTC) - SLATE_SHIFT).date()


@dataclass
class Game:
    game_id: str
    season: int
    start: datetime
    home: str
    away: str
    neutral: bool
    margin: float | None  # None for scheduled games
    state: str


@dataclass
class Data:
    """Games (tip order) and per-team box scores; the input every rating/impact uses."""

    games: list[Game]
    box: dict[tuple[str, str], dict[str, Line]]
    by_id: dict[str, Game] = field(init=False)
    starts: list[float] = field(init=False)  # epoch seconds, aligned with games

    def __post_init__(self) -> None:
        self.games = sorted(self.games, key=lambda g: (g.start, g.game_id))  # caller's list kept
        self.by_id = {g.game_id: g for g in self.games}
        self.starts = [g.start.timestamp() for g in self.games]
        # (team, season) -> indices of that team's games that have a box score for it
        self.team_idx: dict[tuple[str, int], list[int]] = defaultdict(list)
        for i, g in enumerate(self.games):
            for t in (g.home, g.away):
                if self.box.get((g.game_id, t)):
                    self.team_idx[(t, g.season)].append(i)
        self.team_starts = {k: [self.starts[i] for i in v] for k, v in self.team_idx.items()}


def load_data(
    con: duckdb.DuckDBPyConnection,
    league: str = "nba",
    season_types: tuple[int, ...] = DEFAULT_SEASON_TYPES,
) -> Data:
    """Final games and scheduled games of `league` plus their player box scores (read-only).
    Like build_features, both teams must be in `teams` for the league: final_sql enforces it
    for finished games (All-Star / exhibition teams are absent from `teams`), and the scheduled
    branch checks it explicitly."""
    final = final_sql(league)
    teams = "(SELECT team_id FROM teams WHERE league = $lg)"
    rows = con.execute(
        f"""SELECT g.game_id, g.season_year, g.start_time_utc, g.home_team_id, g.away_team_id,
                   coalesce(g.neutral_site, false),
                   CASE WHEN {final} THEN g.home_score - g.away_score END,
                   CASE WHEN {final} THEN 'post' ELSE 'pre' END
            FROM games g
            WHERE g.league = $lg AND g.season_type IN ({_in(season_types)})
              AND (({final}) OR (g.state = 'pre' AND g.home_team_id IN {teams}
                                   AND g.away_team_id IN {teams}))""",
        {"lg": league},
    ).fetchall()
    games = [
        Game(gid, s, st, h, a, bool(n), None if m is None else float(m), state)
        for gid, s, st, h, a, n, m, state in rows
    ]
    return Data(games, player_box(con, league))


# ---------- ratings ----------


def _decay(age_days: np.ndarray) -> np.ndarray:
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


class Ratings:
    """As-of player ratings for one method, cached by as-of timestamp."""

    def __init__(self, data: Data, method: str = CHOSEN_METHOD):
        if method not in METHODS:
            raise ValueError(f"unknown method {method!r}")
        self.data, self.method, self.spec = data, method, METHODS[method]
        self.cache: dict[float, dict[str, float]] = {}

    def window(self, as_of: datetime) -> list[Game]:
        """Finished games with box scores for both teams, start + FINISH_LAG <= as_of, within
        WINDOW_DAYS. Never a game that had not finished by as_of."""
        hi = bisect.bisect_right(self.data.starts, (as_of - FINISH_LAG).timestamp())
        lo = bisect.bisect_left(self.data.starts, (as_of - timedelta(days=WINDOW_DAYS)).timestamp())
        out = []
        for g in self.data.games[lo:hi]:
            if g.margin is None or g.start + FINISH_LAG > as_of:
                continue
            if self.data.box.get((g.game_id, g.home)) and self.data.box.get((g.game_id, g.away)):
                out.append(g)
        return out

    def as_of(self, as_of: datetime) -> dict[str, float]:
        key = as_of.timestamp()
        if key not in self.cache:
            games = self.window(as_of)
            params = {k: v for k, v in self.spec.items() if k != "kind"}
            fit = _fit_pm48 if self.spec["kind"] == "pm48" else _fit_rapm
            self.cache[key] = fit(self.data, games, as_of, **params) if games else {}
        return self.cache[key]


def _recentre(
    ratings: dict[str, float], wmin: dict[str, float]
) -> dict[str, float]:  # decayed minutes-weighted mean -> 0
    tot = sum(wmin.get(a, 0.0) for a in ratings)
    if tot <= 0:
        return ratings
    mean = sum(r * wmin.get(a, 0.0) for a, r in ratings.items()) / tot
    return {a: r - mean for a, r in ratings.items()}


def _fit_pm48(data: Data, games: list[Game], as_of: datetime) -> dict[str, float]:
    pm: dict[str, float] = defaultdict(float)
    mins: dict[str, float] = defaultdict(float)
    for g in games:
        w = float(_decay(np.array((as_of - g.start).total_seconds() / 86400.0)))
        for t in (g.home, g.away):
            for a, line in data.box[(g.game_id, t)].items():
                if line[0] and line[1] > 0:
                    pm[a] += w * line[3]
                    mins[a] += w * line[1]
    r = {a: 48.0 / 5.0 * pm[a] / (mins[a] + PM_PRIOR_MINUTES) for a in mins}
    return _recentre(r, mins)


def _shares(box: dict[str, Line]) -> tuple[list[str], list[float], float]:
    """Players with minutes, their shares (sum 5) and the game length in minutes."""
    ids = [a for a, line in box.items() if line[0] and line[1] > 0]
    tot = sum(box[a][1] for a in ids)
    if tot <= 0:
        return [], [], 48.0
    return ids, [5.0 * box[a][1] / tot for a in ids], tot / 5.0


def _fit_rapm(data: Data, games: list[Game], as_of: datetime, lam: float) -> dict[str, float]:
    col: dict[str, int] = {}
    rows, cols, vals, y, w = [], [], [], [], []
    wmin: dict[str, float] = defaultdict(float)
    hca_rows = []
    for i, g in enumerate(games):
        wi = float(_decay(np.array((as_of - g.start).total_seconds() / 86400.0)))
        length = None
        for t, sign in ((g.home, 1.0), (g.away, -1.0)):
            ids, sh, glen = _shares(data.box[(g.game_id, t)])
            if t == g.home:
                length = glen
            for a, s in zip(ids, sh, strict=True):
                j = col.setdefault(a, len(col))
                rows.append(i)
                cols.append(j)
                vals.append(sign * s)
                wmin[a] += wi * data.box[(g.game_id, t)][a][1]
        length = min(max(length or 48.0, 48.0), 73.0)  # OT games are longer; clip noise
        y.append(g.margin * 48.0 / length)
        w.append(wi)
        hca_rows.append(0.0 if g.neutral else 1.0)
    n, p = len(games), len(col)
    rows += list(range(n))
    cols += [p] * n
    vals += hca_rows
    x = sp.csr_matrix((vals, (rows, cols)), shape=(n, p + 1))
    wv = np.asarray(w)
    xw = x.multiply(wv[:, None]).tocsr()
    a_mat = (x.T @ xw).toarray()
    a_mat[np.arange(p), np.arange(p)] += lam
    a_mat[p, p] += 1e-6  # home edge essentially unpenalized
    b = x.T @ (wv * np.asarray(y))
    beta = np.linalg.solve(a_mat, b)
    ids = sorted(col, key=col.get)
    return _recentre({a: float(beta[col[a]]) for a in ids}, wmin)


# ---------- rotation and team impact ----------


def allocate(
    weights: dict[str, float], total: float = TEAM_MINUTES, cap: float = MINUTE_CAP
) -> tuple[dict[str, float], float]:
    """Scale weights to `total` minutes with a per-player cap (water-filling). Returns
    (minutes per player, leftover minutes nobody could absorb)."""
    free = {a: v for a, v in weights.items() if v > 0}
    alloc: dict[str, float] = {}
    remaining = total
    while free and remaining > 1e-9:
        scale = remaining / sum(free.values())
        over = [a for a, v in free.items() if v * scale > cap]
        if not over:
            alloc.update({a: v * scale for a, v in free.items()})
            remaining = 0.0
            break
        for a in over:
            alloc[a] = cap
            remaining -= cap
            del free[a]
    return alloc, max(remaining, 0.0)


def rotation_weights(hist: list[dict[str, Line]]) -> dict[str, float]:
    """Expected-role weights from the team's recent box scores (oldest first)."""
    gp: dict[str, int] = defaultdict(int)
    mins: dict[str, float] = defaultdict(float)
    for box in hist:
        for a, line in box.items():
            if line[0] and line[1] > 0:
                gp[a] += 1
                mins[a] += line[1]
    return {a: mins[a] / gp[a] * min(1.0, gp[a] / FULL_GP) for a in gp}


def _strength(alloc: dict[str, float], leftover: float, ratings: dict[str, float]) -> float:
    s = sum(m / 48.0 * ratings.get(a, REPLACEMENT) for a, m in alloc.items())
    return s + leftover / 48.0 * REPLACEMENT


NAN_TEAM = {"full": math.nan, "available": math.nan, "missing": math.nan, "n_out": math.nan}


def team_impact(
    hist: list[dict[str, Line]],
    ratings: dict[str, float],
    out: set[str] | None = None,
) -> dict[str, Any]:
    """Full-strength and available strength (points per 48) and missing impact for one team.
    `out=None` uses the proxy (rotation players who did not play the previous game in `hist`);
    otherwise players in `out` (ids outside the rotation are ignored: their absence is already
    in the team's recent games)."""
    if not hist:
        return dict(NAN_TEAM, players=[])
    w = rotation_weights(hist)
    if not w:
        return dict(NAN_TEAM, players=[])
    if out is None:
        last = hist[-1]
        out_set = {a for a in w if not (a in last and last[a][0])}
    else:
        out_set = {a for a in w if a in out}
    full_alloc, full_left = allocate(w)
    av_alloc, av_left = allocate({a: v for a, v in w.items() if a not in out_set})
    full = _strength(full_alloc, full_left, ratings)
    avail = _strength(av_alloc, av_left, ratings)
    players = [
        {
            "athlete_id": a,
            "rating": ratings.get(a, REPLACEMENT),
            "exp_minutes": full_alloc.get(a, 0.0),
            "avail_minutes": av_alloc.get(a, 0.0),
            "out": a in out_set,
        }
        for a in sorted(w, key=lambda a: -full_alloc.get(a, 0.0))
    ]
    return {
        "full": full,
        "available": avail,
        "missing": full - avail,
        "n_out": float(len(out_set)),
        "players": players,
    }


class ImpactEngine:
    """Team impacts for any game as of any time, from one Data load and one rating method."""

    def __init__(self, data: Data, method: str = CHOSEN_METHOD):
        self.data = data
        self.ratings = Ratings(data, method)

    def history(self, team: str, season: int, as_of: datetime) -> list[dict[str, Line]]:
        """The team's last ROTATION_WINDOW box scores this season that finished by as_of."""
        idx = self.data.team_idx.get((team, season), [])
        cut = (as_of - FINISH_LAG).timestamp()
        k = bisect.bisect_right(self.data.team_starts.get((team, season), []), cut)
        sel = [i for i in idx[:k] if self.data.games[i].start + FINISH_LAG <= as_of]
        return [self.data.box[(self.data.games[i].game_id, team)] for i in sel][-ROTATION_WINDOW:]

    def game(
        self,
        game_id: str,
        out_players: set[str] | None = None,
        as_of: datetime | None = None,
        oracle: bool = False,
    ) -> dict[str, Any]:
        """{'home': team_impact, 'away': team_impact, 'as_of', ...} for one game.
        `as_of` defaults to the tip (later values are clamped to the tip). `oracle=True` uses
        who actually played this game (LEAKED: ceiling only)."""
        g = self.data.by_id[game_id]
        t = g.start if as_of is None else min(as_of, g.start)
        ratings = self.ratings.as_of(t)
        out = {}
        for side, team in (("home", g.home), ("away", g.away)):
            hist = self.history(team, g.season, t)
            if oracle:
                own = self.data.box.get((game_id, team))
                if not own:
                    out[side] = dict(NAN_TEAM, players=[])
                    continue
                o = {a for a in rotation_weights(hist) if not (a in own and own[a][0])}
            else:
                o = out_players
            out[side] = team_impact(hist, ratings, o)
        return {
            "game_id": game_id,
            "as_of": t,
            "home_team_id": g.home,
            "away_team_id": g.away,
        } | out


def missing_impact(
    con: duckdb.DuckDBPyConnection,
    game_id: str,
    out_players: set[str] | list[str] | None = None,
    as_of: datetime | None = None,
    method: str = CHOSEN_METHOD,
    league: str = "nba",
) -> dict[str, Any]:
    """Injury impact in points for one game, using only data finished before `as_of` (default
    the tip). `out_players` = athlete ids listed OUT (e.g. from `pregame_injuries`); None uses
    the proxy (rotation players who missed the team's previous game). Per side: full-strength
    and available strength (points per 48 of margin), `missing` = full - available, and the
    rotation with ratings and expected / redistributed minutes. Loads the whole league box
    history: for many games build one `ImpactEngine` instead."""
    eng = ImpactEngine(load_data(con, league), method)
    return eng.game(game_id, None if out_players is None else set(out_players), as_of)


def snapshot_out(con: duckdb.DuckDBPyConnection, league: str = "nba") -> dict[str, set[str]]:
    """game_id -> athletes listed Out in the latest pre-tip snapshot (both teams), only for
    games where both teams have a pre-tip capture (players.pregame_out)."""
    by_team = pregame_out(con, league)
    sides: dict[str, list[set[str]]] = defaultdict(list)
    for (g, _), ids in by_team.items():
        sides[g].append(ids)
    return {g: set().union(*v) for g, v in sides.items() if len(v) >= 2}


def slate_starts(data: Data) -> dict[date, datetime]:
    """Slate date -> earliest tip that evening (the as-of time for every game in it)."""
    out: dict[date, datetime] = {}
    for g in data.games:
        d = slate_date(g.start)
        out[d] = min(out.get(d, g.start), g.start)
    return out


def impact_features(
    data: Data,
    method: str = CHOSEN_METHOD,
    oracle: bool = False,
    game_ids: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    """game_id -> IMPACT_FEATURES + FULL_FEATURE (+ ORACLE_FEATURES) for every game (or only
    `game_ids`). Ratings and rotations are as of the game's slate start (earliest tip of its
    evening), so games on the same evening never see each other. `oracle=True` adds the LEAKED
    ceiling columns (evaluation only)."""
    eng = ImpactEngine(data, method)
    slate_start = slate_starts(data)
    games = data.games if game_ids is None else [data.by_id[g] for g in game_ids]
    out = {}
    for g in games:
        t = slate_start[slate_date(g.start)]
        p = eng.game(g.game_id, as_of=t)
        f = {
            "imp_avail_diff": p["home"]["available"] - p["away"]["available"],
            "imp_missing_diff": p["home"]["missing"] - p["away"]["missing"],
            FULL_FEATURE: p["home"]["full"] - p["away"]["full"],
        }
        if oracle:
            o = eng.game(g.game_id, as_of=t, oracle=True)
            f["orc_avail_diff"] = o["home"]["available"] - o["away"]["available"]
            f["orc_missing_diff"] = o["home"]["missing"] - o["away"]["missing"]
        out[g.game_id] = {k: float(v) for k, v in f.items()}
    return out


def with_impact(
    rows: list[dict[str, Any]], feats: dict[str, dict[str, float]], oracle: bool = False
) -> list[dict[str, Any]]:
    """Copies of build_features rows with the impact columns added (NaN when unknown). The
    LEAKED oracle columns are added only with `oracle=True` (evaluation only)."""
    names = IMPACT_FEATURES + [FULL_FEATURE] + (ORACLE_FEATURES if oracle else [])
    out = []
    for r in rows:
        f = feats.get(r["game_id"], {})
        out.append({**r, "features": {**r["features"], **{n: f.get(n, math.nan) for n in names}}})
    return out


def main(argv: list[str] | None = None) -> int:
    from deepsports.analysis.player_impact_eval import main as eval_main

    return eval_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
