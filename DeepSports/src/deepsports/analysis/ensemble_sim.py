"""Historical backtest of the ensemble-betting tool: point-in-time slates and baseline bets.

For each chosen NBA game day (US/Eastern) the decision time `now` is one hour before that day's
first tip. The slate holds that day's games, built by `ensemble_bets.load_historical_slate`
with only what was known at `now`, final pre-tip (closing) lines, and v1.1 numbers fit
walk-forward on games that finished before `now`. Bettors get the one-pick brief
(ctx-v1-sim1): exactly one pick, stake 1.

Outputs (never under the live runs dir that `ensemble-bets grade` scans):
  <out>/<YYYY-MM-DD>/slate.json + context-a01.md ... context-aNN.md
  <out>/baselines.json: the bet each simple strategy makes per day (see BASELINES).

Grading (later, not here): every bet is 1 unit at the slate's line/price (`grade_pick`); the
ensemble bet of a day is the plurality pick across agents (`plurality_pick`). When tallying a
sim day, validate picks with now = the slate's `created_at` (not the wall clock, which is after
every tip and would drop every pick).

    uv run python -m deepsports.analysis.ensemble_sim --db <copy.duckdb> --out <dir>
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from deepsports import config
from deepsports.analysis import ensemble_bets as eb

EASTERN = ZoneInfo("America/New_York")
DEFAULT_OUT = config.REPORTS_DIR / "ensemble-bets-sim"
DECISION_LEAD = timedelta(hours=1)
MODEL_VERSION = "v1.1"
BASELINE_SEED = 42
BASELINES = {
    "model_edge": "v1.1's largest |model - line| on spread or total, side toward the model",
    "home_ml_favorite": "moneyline on the biggest home favorite (lowest home price)",
    "spread_underdog": "the biggest spread underdog, taking the points",
    "over_highest_total": "the over on the day's highest total",
    "random": f"a random offered market/side, random.Random({BASELINE_SEED}) drawn in date order",
}
GRADING_RULE = (
    "Each bet is 1 unit at the slate's line and price (ensemble_bets.grade_pick). The ensemble "
    "bet of a day is the plurality pick across the agents (ties: higher sum of confidence, then "
    "the lower game_id); agents' picks are validated with now = the slate's created_at."
)


# ---------- choosing days (pure) ----------


def choose_days(
    counts: Mapping[date, int], start: date, end: date, n: int = 10, min_games: int = 4
) -> list[date]:
    """`n` eligible days (>= `min_games` lined games) in [start, end], as evenly spaced as
    possible: the subset closest (sum of |day - target|) to n evenly spaced targets from start
    to end; ties go to the earlier subset. Fewer than n eligible days returns them all."""
    eligible = sorted(d for d, k in counts.items() if start <= d <= end and k >= min_games)
    if len(eligible) <= n:
        return eligible
    span = (end - start).days
    targets = [i * span / (n - 1) for i in range(n)] if n > 1 else [span / 2]
    off = [(d - start).days for d in eligible]
    m, inf = len(eligible), float("inf")
    # f[i][j]: least cost of assigning targets i.. to an increasing subset of eligible[j:]
    f = [[inf] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        f[n][j] = 0.0
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            f[i][j] = min(f[i][j + 1], abs(off[j] - targets[i]) + f[i + 1][j + 1])
    out, j = [], 0
    for i in range(n):  # walk forward, taking a day whenever it is optimal (earliest subset)
        while abs(off[j] - targets[i]) + f[i + 1][j + 1] > f[i][j] + 1e-9:
            j += 1
        out.append(eligible[j])
        j += 1
    return out


def eastern_day(t: datetime) -> date:
    return t.astimezone(EASTERN).date()


def day_window(first_tip: datetime, day: date) -> tuple[datetime, datetime]:
    """(now, until): decision time one hour before the first tip, and the end of the Eastern
    day (games tipping after midnight Eastern belong to the next day)."""
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), EASTERN)
    return first_tip - DECISION_LEAD, end.astimezone(UTC)


# ---------- model numbers as of `now` ----------


def asof_predictions(
    rows: Sequence[Mapping[str, Any]],
    now: datetime,
    game_ids: Sequence[str],
    model_version: str = MODEL_VERSION,
    burn_in_seasons: int = 1,
) -> tuple[dict[str, dict[str, Any]], int]:
    """Fit `model_version` on games that finished before `now` (start + FINISH_LAG <= now) and
    predict `game_ids`. `rows` come from features.build_features, whose features for a game use
    only games finished before its tip. Returns (game_id -> prediction, training games)."""
    from deepsports.analysis.features import FINISH_LAG
    from deepsports.analysis.model import make_model, training_rows

    train = [
        r
        for r in training_rows(list(rows), burn_in_seasons)
        if r["start_time_utc"] + FINISH_LAG <= now
    ]
    want = set(game_ids)
    test = [r for r in rows if r["game_id"] in want]
    if not train or not test:
        return {}, len(train)
    model = make_model(model_version).fit(train)
    out = {}
    for r, p in zip(test, model.predict(test), strict=True):
        out[r["game_id"]] = {
            "model_version": model_version,
            "p_home_win": p["p_home_win"],
            "pred_home_margin": p["pred_home_margin"],
            "pred_total": p["pred_total"],
        }
    return out, len(train)


# ---------- baselines and the ensemble pick (pure) ----------


def _bet(game: Mapping[str, Any], market: str, side: str, why: str) -> dict[str, Any]:
    lp = eb.priced(game, market, side)
    assert lp is not None, (game["game_id"], market, side)
    return {
        "game_id": game["game_id"],
        "league": game["league"],
        "market": market,
        "side": side,
        "line": lp[0],
        "price": lp[1],
        "stake": 1,
        "label": eb.label(game, market, side, lp[0]),
        "reason": why,
    }


def offered(games: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """Every (game_id, market, side) on the slate, in a fixed order."""
    return [
        (g["game_id"], m, s)
        for g in sorted(games, key=lambda g: g["game_id"])
        for m in eb.MARKETS
        if m in g["markets"]
        for s in eb.SIDES[m]
    ]


def baseline_bets(
    games: Sequence[Mapping[str, Any]], rng: random.Random, ml_fallback: bool = False
) -> dict[str, Any]:
    """The bet each strategy in BASELINES makes on this slate (None if it has no candidate).
    Ties go to the lower game_id. `rng` is consumed exactly once per call. `ml_fallback`
    (college, where many moneylines are off the board): with no home favorite priced on the
    moneyline, bet the biggest favorite of either side that has one."""
    gs = sorted(games, key=lambda g: g["game_id"])
    out: dict[str, Any] = {}
    # 1. model edge on spread or total
    best = None
    for g in gs:
        md, m = g.get("model"), g["markets"]
        if not md:
            continue
        if "spread" in m and md["home_margin"] is not None:
            implied = -m["spread"]["home_line"]  # line's home margin
            edge = md["home_margin"] - implied
            cand = (abs(edge), g, "spread", "home" if edge > 0 else "away", edge)
            if edge != 0 and (best is None or cand[0] > best[0]):
                best = cand
        if "total" in m and md["total"] is not None:
            edge = md["total"] - m["total"]["line"]
            cand = (abs(edge), g, "total", "over" if edge > 0 else "under", edge)
            if edge != 0 and (best is None or cand[0] > best[0]):
                best = cand
    out["model_edge"] = (
        None
        if best is None
        else {
            **_bet(best[1], best[2], best[3], f"model {best[4]:+.1f} pts vs the line"),
            "edge_points": round(best[0], 2),
        }
    )
    # 2. biggest home favorite on the moneyline
    favs = [
        g
        for g in gs
        if "moneyline" in g["markets"]
        and g["markets"]["moneyline"]["home_price"] < g["markets"]["moneyline"]["away_price"]
    ]
    fav = min(favs, key=lambda g: g["markets"]["moneyline"]["home_price"], default=None)
    out["home_ml_favorite"] = (
        None if fav is None else _bet(fav, "moneyline", "home", "biggest home favorite")
    )
    if fav is None and ml_fallback:
        mls = [
            (min(ml["home_price"], ml["away_price"]), g)
            for g in gs
            if (ml := g["markets"].get("moneyline"))
        ]
        if mls:
            price, g = min(mls, key=lambda x: x[0])
            ml = g["markets"]["moneyline"]
            side = "home" if ml["home_price"] == price else "away"
            out["home_ml_favorite"] = {
                **_bet(g, "moneyline", side, "no home favorite on the moneyline: biggest favorite"),
                "fallback": True,
            }
    # 3. biggest spread underdog
    spr = [g for g in gs if "spread" in g["markets"] and g["markets"]["spread"]["home_line"] != 0]
    dog = max(spr, key=lambda g: abs(g["markets"]["spread"]["home_line"]), default=None)
    out["spread_underdog"] = (
        None
        if dog is None
        else _bet(
            dog,
            "spread",
            "home" if dog["markets"]["spread"]["home_line"] > 0 else "away",
            "biggest spread underdog",
        )
    )
    # 4. over on the highest total
    tots = [g for g in gs if "total" in g["markets"]]
    hi = max(tots, key=lambda g: g["markets"]["total"]["line"], default=None)
    out["over_highest_total"] = None if hi is None else _bet(hi, "total", "over", "highest total")
    # 5. random offered market/side
    opts = offered(gs)
    by_id = {g["game_id"]: g for g in gs}
    pick = opts[rng.randrange(len(opts))] if opts else None
    out["random"] = None if pick is None else _bet(by_id[pick[0]], pick[1], pick[2], "random")
    return out


def plurality_pick(
    picks_by_agent: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any] | None:
    """The ensemble bet of a one-pick day: the (game, market, side) most agents chose; ties by
    the higher sum of confidence, then the lower game_id (then market, side). None if no picks."""
    votes: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for picks in picks_by_agent.values():
        for p in picks:
            votes[(p["game_id"], p["market"], p["side"])].append(p)
    if not votes:
        return None
    key = min(
        votes,
        key=lambda k: (
            -len(votes[k]),
            -sum(p.get("confidence") or 0.0 for p in votes[k]),
            k,
        ),
    )
    p0 = votes[key][0]
    return {
        "game_id": key[0],
        "market": key[1],
        "side": key[2],
        "line": p0["line"],
        "price": p0["price"],
        "stake": 1,
        "votes": len(votes[key]),
        "n_agents": len(picks_by_agent),
    }


# ---------- building the sim (DuckDB, read-only) ----------


def lined_day_counts(
    con: duckdb.DuckDBPyConnection, start: date, end: date, league: str = "nba"
) -> dict[date, tuple[int, datetime]]:
    """Eastern day -> (regular-season games with a closing spread and total, first tip)."""
    rows = con.execute(
        """SELECT g.start_time_utc,
                  EXISTS (SELECT 1 FROM odds_snapshots o WHERE o.game_id = g.game_id
                          AND o.source = 'closing' AND o.spread_home IS NOT NULL
                          AND o.over_under IS NOT NULL) AS lined
           FROM games g WHERE g.league = ? AND g.season_type = 2
             AND g.start_time_utc >= ? AND g.start_time_utc < ?""",
        [
            league,
            datetime.combine(start, datetime.min.time(), EASTERN),
            datetime.combine(end + timedelta(days=1), datetime.min.time(), EASTERN),
        ],
    ).fetchall()
    out: dict[date, list[Any]] = {}
    for tip, lined in rows:
        d = eastern_day(tip)
        slot = out.setdefault(d, [0, tip])
        slot[0] += int(bool(lined))
        slot[1] = min(slot[1], tip)
    return {d: (k, t) for d, (k, t) in out.items()}


def build_sim(
    con: duckdb.DuckDBPyConnection,
    out: Path,
    start: date,
    end: date,
    n_days: int = 10,
    n_agents: int = 5,
) -> dict[str, Any]:
    from deepsports.analysis.features import build_features
    from deepsports.analysis.model import uses_players

    if out.resolve() == eb.RUNS_DIR.resolve():
        raise ValueError("sim output must not be the live runs dir")
    counts = lined_day_counts(con, start, end)
    days = choose_days({d: k for d, (k, _) in counts.items()}, start, end, n_days)
    rows = build_features(con, include_players=uses_players(MODEL_VERSION))
    rng = random.Random(BASELINE_SEED)
    summary: dict[str, Any] = {"days": [], "contexts": []}
    baselines: dict[str, Any] = {
        "strategies": BASELINES,
        "grading_rule": GRADING_RULE,
        "context_version": eb.SIM_CONTEXT_VERSION,
        "days": {},
    }
    for d in days:
        now, until = day_window(counts[d][1], d)
        ids = [g["game_id"] for g in eb.load_historical_games(con, "nba", now, until)]
        preds, n_train = asof_predictions(rows, now, ids)
        source = f"walk-forward {MODEL_VERSION} fit on {n_train} games finished before now"
        slate = eb.load_historical_slate(
            con, now, until, "nba", predictions=preds, model_source=source
        )
        run = out / d.isoformat()
        run.mkdir(parents=True, exist_ok=True)
        paths = eb.write_context(
            run, slate, n_agents, seed=int(d.strftime("%Y%m%d")), one_pick=True
        )
        bets = baseline_bets(slate["games"], rng)
        baselines["days"][d.isoformat()] = {"now": slate["created_at"], "bets": bets}
        summary["days"].append(
            {
                "day": d.isoformat(),
                "now": slate["created_at"],
                "games": len(slate["games"]),
                "unlined": slate["unlined_games"],
                "with_model": sum(g["model"] is not None for g in slate["games"]),
                "model_source": source,
                "injuries_captured_at": slate["injuries_captured_at"],
            }
        )
        summary["contexts"] += [str(p) for p in paths]
    (out / "baselines.json").write_text(json.dumps(baselines, indent=1))
    return summary


# ---------- college (NCAAB) sim: sampled, anonymized slates ----------
#
# College seasons in the warehouse predate the bettor models' training cutoff, so results could
# be remembered. Every slate is anonymized (anonymize_slate): per-day shuffled team labels,
# per-day game ids (G01...), no venue / TV, dates without a year. The real ids and names go to
# key.json beside slate.json; bettors read only their context file.

NCAAB_OUT = config.REPORTS_DIR / "ensemble-bets-sim-ncaab"
ANON_CONTEXT_VERSION = "ctx-v1-sim1-anon"
ANON_NOTE = "Team names and the season are hidden; judge only from the numbers given."
NCAAB_MAX_GAMES = 25
NCAAB_MIN_GAMES = 8
LABEL_LETTERS = "ABCDEFGHIJKLMNOPRSTUVWXYZ"  # no Q: labels are Q + two letters


def college_day_games(
    con: duckdb.DuckDBPyConnection, start: date, end: date
) -> dict[date, dict[str, datetime]]:
    """Eastern day -> {game_id: tip} of regular-season D1-vs-D1 games with a closing spread
    and total."""
    rows = con.execute(
        """SELECT g.game_id, g.start_time_utc FROM games g
           JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
           JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
           WHERE g.league = 'ncaab' AND g.season_type = 2
             AND coalesce(h.listed, TRUE) AND coalesce(a.listed, TRUE)
             AND g.start_time_utc >= ? AND g.start_time_utc < ?
             AND EXISTS (SELECT 1 FROM odds_snapshots o WHERE o.game_id = g.game_id
                         AND o.source = 'closing' AND o.spread_home IS NOT NULL
                         AND o.over_under IS NOT NULL)
           ORDER BY g.game_id""",
        [
            datetime.combine(start, datetime.min.time(), EASTERN),
            datetime.combine(end + timedelta(days=1), datetime.min.time(), EASTERN),
        ],
    ).fetchall()
    out: dict[date, dict[str, datetime]] = defaultdict(dict)
    for gid, tip in rows:
        out[eastern_day(tip)][gid] = tip
    return dict(out)


def sample_games(ids: Sequence[str], k: int, rng: random.Random) -> list[str]:
    ids = sorted(ids)
    return ids if len(ids) <= k else sorted(rng.sample(ids, k))


def _fit_targets(
    done: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    choice: Mapping[str, Mapping[str, Any]],
    ok,
) -> list[dict[str, float]]:
    """Fit each target's model (feature set + training filter from `choice`) and predict
    `test`, as ncaab._version_predictions does. Returns one dict per test row."""
    from deepsports.analysis.ncaab import make_model

    keys = {"win": "p_home_win", "margin": "pred_home_margin", "total": "pred_total"}
    out: list[dict[str, float]] = [{} for _ in test]
    if not test:
        return out
    fitted: dict[tuple, list[dict[str, float]]] = {}
    for tgt, c in choice.items():
        fk = (c["feature_set"], int(c["min_games"]), c.get("mode"))
        if fk not in fitted:
            train = [r for r in done if ok(r, c)]
            fitted[fk] = make_model(c["feature_set"]).fit(train).predict(list(test))
        for o, pr in zip(out, fitted[fk], strict=True):
            o[keys[tgt]] = float(pr[keys[tgt]])
    return out


def college_asof_predictions(
    v1_rows: Sequence[Mapping[str, Any]],
    prior_rows: Sequence[Mapping[str, Any]],
    now: datetime,
    game_ids: Sequence[str],
    v1cfg: Mapping[str, Any],
    pcfg: Mapping[str, Any],
    finish_lag: timedelta | None = None,
    all_prior: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """The college display model as of `now`: `ncaab-v1` when both teams have >= 5 games
    (rt_n), else the prior model's early prediction (`ncaab-v1-early`, >= 1 game), else none.
    Both fit on completed D1-vs-D1 games of all seasons that finished before `now`
    (start + finish_lag <= now), exactly like the live sync but with a cutoff. `v1_rows` /
    `prior_rows` come from ncaab.live_rows / ncaab_prior.live_rows. `all_prior` also returns
    the prior model's numbers for every game under key 'prior' (for checks).
    Returns (game_id -> prediction, counts per source)."""
    from deepsports.analysis import ncaab, ncaab_prior
    from deepsports.analysis.features import FINISH_LAG

    lag = FINISH_LAG if finish_lag is None else finish_lag
    want = set(game_ids)

    def split(rows):
        done = [
            r for r in rows if r["state"] == "post" and r["d1"] and r["start_time_utc"] + lag <= now
        ]
        return done, {r["game_id"]: r for r in rows if r["game_id"] in want}

    v1_done, v1_test = split(v1_rows)
    pr_done, pr_test = split(prior_rows)
    use_v1 = [
        g for g in sorted(want) if g in v1_test and v1_test[g]["rt_n"] >= ncaab.MIN_GAMES_TO_PREDICT
    ]
    use_pr = [
        g
        for g in sorted(want)
        if g not in use_v1 and g in pr_test and pr_test[g]["rt_n"] >= ncaab.EARLY_MIN_GAMES
    ]
    v1p = _fit_targets(
        v1_done,
        [v1_test[g] for g in use_v1],
        v1cfg["choice"],
        lambda r, c: r["rt_n"] >= int(c["min_games"]),
    )
    pr_ids = sorted(g for g in want if g in pr_test) if all_prior else use_pr
    prp = _fit_targets(
        pr_done,
        [pr_test[g] for g in pr_ids],
        pcfg["choice"],
        lambda r, c: ncaab_prior.train_ok(r, int(c["min_games"]), c["mode"]),
    )
    prior_by = dict(zip(pr_ids, prp, strict=True))
    out: dict[str, dict[str, Any]] = {}
    for g, p in zip(use_v1, v1p, strict=True):
        out[g] = {"model_version": ncaab.MODEL_VERSION, **p}
    for g in use_pr:
        out[g] = {"model_version": ncaab.EARLY_VERSION, **prior_by[g]}
    if all_prior:
        for g, p in prior_by.items():
            out.setdefault(g, {"model_version": None})["prior"] = p
    counts = {
        ncaab.MODEL_VERSION: len(use_v1),
        ncaab.EARLY_VERSION: len(use_pr),
        "none": len(want) - len(use_v1) - len(use_pr),
        "train_v1": len(v1_done),
        "train_prior": len(pr_done),
    }
    return out, counts


def anon_labels(n: int, rng: random.Random, forbidden: set[str]) -> list[str]:
    """n distinct 3-letter labels 'Q' + two letters, none equal to a real abbreviation."""
    pool = [f"Q{a}{b}" for a in LABEL_LETTERS for b in LABEL_LETTERS if f"Q{a}{b}" not in forbidden]
    return rng.sample(pool, n)


def anonymize_slate(
    slate: Mapping[str, Any], rng: random.Random, forbidden: set[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(anonymized slate, key). Teams get per-slate shuffled labels ('Team QXY' / 'QXY'), games
    get ids G01... in tip order, venue and TV are dropped, the brief shows no year. The key maps
    each label and game id back to the real ones (kept out of the bettors' files)."""
    games = sorted(slate["games"], key=lambda g: (g["tip_utc"], g["game_id"]))
    teams = sorted({g[s]["abbr"] for g in games for s in ("home", "away")})
    labels = dict(zip(teams, anon_labels(len(teams), rng, forbidden), strict=True))
    key: dict[str, Any] = {"games": {}, "teams": {}}
    out_games = []
    for i, g in enumerate(games, 1):
        gid = f"G{i:02d}"
        key["games"][gid] = {
            "game_id": g["game_id"],
            "home": g["home"]["name"],
            "away": g["away"]["name"],
            "venue": g["venue"],
        }
        x = {**g, "game_id": gid, "real_game_id": g["game_id"], "venue": None, "tv": None}
        for side in ("home", "away"):
            lab = labels[g[side]["abbr"]]
            key["teams"][lab] = g[side]["name"]
            x[side] = {**g[side], "abbr": lab, "name": f"Team {lab}"}
        tip = datetime.fromisoformat(g["tip_utc"]).astimezone(config.LOCAL_TZ)
        x["tip_local"] = tip.strftime("%a %b %-d %-I:%M %p %Z")  # no year
        out_games.append(x)
    now = datetime.fromisoformat(slate["created_at"])
    anon = {
        **slate,
        "context_version": ANON_CONTEXT_VERSION,
        "anonymized": True,
        "created_label": now.astimezone(config.LOCAL_TZ).strftime("%a %b %-d %-I:%M %p %Z"),
        "brief_notes": [  # capture timestamps carry the year: drop them
            ANON_NOTE,
            *(
                re.sub(r" ?\(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\)", "", n)
                for n in slate.get("brief_notes", [])
            ),
        ],
        "games": out_games,
    }
    return anon, key


def leak_terms(con: duckdb.DuckDBPyConnection, league: str = "ncaab") -> list[str]:
    """Every real team abbreviation, display name, location and nickname of the league, every
    venue name, plus the season's years: strings an anonymized context must not contain."""
    terms = {"2025", "2026", "2024", "2027"}
    for row in con.execute(
        """SELECT abbreviation, display_name, location, name FROM teams WHERE league = ?""",
        [league],
    ).fetchall():
        terms.update(t for t in row if t)
    terms.update(
        v
        for (v,) in con.execute(
            "SELECT DISTINCT venue FROM games WHERE league = ? AND venue IS NOT NULL", [league]
        ).fetchall()
    )
    return sorted(terms)


def find_leaks(text: str, terms: Sequence[str]) -> list[str]:
    """Terms that occur in `text` as whole words (case-sensitive)."""
    import re

    return [t for t in terms if re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", text)]


def build_sim_ncaab(
    con: duckdb.DuckDBPyConnection,
    out: Path,
    start: date,
    end: date,
    n_days: int = 10,
    n_agents: int = 5,
    max_games: int = NCAAB_MAX_GAMES,
    min_games: int = NCAAB_MIN_GAMES,
) -> dict[str, Any]:
    from deepsports.analysis import ncaab, ncaab_prior

    if out.resolve() == eb.RUNS_DIR.resolve():
        raise ValueError("sim output must not be the live runs dir")
    by_day = college_day_games(con, start, end)
    days = choose_days({d: len(v) for d, v in by_day.items()}, start, end, n_days, min_games)
    v1cfg = ncaab.load_config()
    pcfg = ncaab_prior.load_config()
    v1_rows = ncaab.live_rows(con, v1cfg)
    prior_rows = ncaab_prior.live_rows(con, pcfg, v1cfg)
    forbidden = {a.upper() for (a,) in con.execute("SELECT abbreviation FROM teams").fetchall()}
    terms = leak_terms(con)
    rng = random.Random(BASELINE_SEED)
    summary: dict[str, Any] = {"days": [], "contexts": [], "leaks": {}}
    baselines: dict[str, Any] = {
        "strategies": {
            **BASELINES,
            "home_ml_favorite": BASELINES["home_ml_favorite"]
            + "; if no home favorite has a moneyline, the biggest favorite of either side",
        },
        "grading_rule": GRADING_RULE
        + " Game ids are per-day labels (G01...): map them to real ids with key.json.",
        "context_version": ANON_CONTEXT_VERSION,
        "days": {},
    }
    for d in days:
        seed = int(d.strftime("%Y%m%d"))
        kept = sample_games(by_day[d], max_games, random.Random(seed))
        now, until = day_window(min(by_day[d][g] for g in kept), d)
        preds, counts = college_asof_predictions(v1_rows, prior_rows, now, kept, v1cfg, pcfg)
        source = (
            f"walk-forward as of now: ncaab-v1 fit on {counts['train_v1']} / prior model on "
            f"{counts['train_prior']} D1 games finished before now"
        )
        slate = eb.load_historical_slate(
            con, now, until, "ncaab", predictions=preds, model_source=source, game_ids=kept
        )
        anon, key = anonymize_slate(slate, random.Random(seed + 1), forbidden)
        run = out / d.isoformat()
        run.mkdir(parents=True, exist_ok=True)
        paths = eb.write_context(run, anon, n_agents, seed=seed, one_pick=True)
        (run / "key.json").write_text(json.dumps(key, indent=1))
        leaks = {p.name: find_leaks(p.read_text(), terms) for p in paths}
        summary["leaks"][d.isoformat()] = {k: v for k, v in leaks.items() if v}
        bets = baseline_bets(anon["games"], rng, ml_fallback=True)
        for b in bets.values():
            if b:
                b["real_game_id"] = key["games"][b["game_id"]]["game_id"]
        baselines["days"][d.isoformat()] = {"now": anon["created_at"], "bets": bets}
        summary["days"].append(
            {
                "day": d.isoformat(),
                "now": anon["created_at"],
                "eligible": len(by_day[d]),
                "games": len(anon["games"]),
                "unlined": anon["unlined_games"],
                "model_counts": {k: v for k, v in counts.items() if not k.startswith("train")},
                "model_source": source,
            }
        )
        summary["contexts"] += [str(p) for p in paths]
    (out / "baselines.json").write_text(json.dumps(baselines, indent=1))
    return summary


# ---------- matched context test: ctx-v1 vs ctx-v2 on the same college days ----------

CTX_TEST_OUT = config.REPORTS_DIR / "ensemble-ctx-test"
# The 10 days of the first college sim (reports/ensemble-bets-sim-ncaab): never reused.
SIM1_NCAAB_DAYS = tuple(
    date.fromisoformat(d)
    for d in ("2025-11-15", "2025-11-27", "2025-12-09", "2025-12-20", "2026-01-01",
              "2026-01-12", "2026-01-24", "2026-02-05", "2026-02-16", "2026-02-28")
)  # fmt: skip
CTX_ARMS = {"v1": "ctx-v1-sim1-anon", "v2": "ctx-v2-sim1-anon"}
MIN_GAP_DAYS = 2


def far_from(days: Sequence[date], used: Sequence[date], gap: int = MIN_GAP_DAYS) -> list[date]:
    """`days` that are at least `gap` days from every day in `used`."""
    return [d for d in days if all(abs((d - u).days) >= gap for u in used)]


def ctx_test_plan(days: Sequence[date], n_agents: int, sizes: Mapping[str, float]) -> str:
    """The pre-declared comparison (written before any bettor runs or grading)."""
    sd = 0.95  # per-pick profit SD of a 1-unit bet near -110 (wins +0.91, losses -1)
    n = len(days) * n_agents
    se = math.sqrt(2) * sd / math.sqrt(n)
    mde = 2.8 * se  # 80% power, two-sided alpha 0.05
    se_day = math.sqrt(2) * sd / math.sqrt(len(days))
    se200 = math.sqrt(2) * sd / math.sqrt(200)
    dw = mde / 1.909  # profit per pick at -110 = 1.909 * win rate - 1
    return f"""# Matched context test: ctx-v1 vs ctx-v2 (college 2025-26, anonymized)

Written {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, before any bettor run or grading. Nothing below may
change after picks exist.

## Design
- {len(days)} new college game days (US/Eastern), each at least {MIN_GAP_DAYS} days from
  the 10 days of the first college sim: {", ".join(d.isoformat() for d in days)}.
- Per day: the same sampled games (<= {NCAAB_MAX_GAMES}, D1 vs D1, closing spread and
  total), the same anonymized labels and G-ids, the same decision time `now`, the same
  lines, prices and model numbers in both arms. The only difference is the ctx-v2 blocks
  (last season, ratings now, pace/efficiency, base rates). Line timing is absent (no
  pregame snapshots on past days) and college has no injury data, so those two v2 blocks
  don't appear.
- {n_agents} agents per arm per day, one-pick brief (exactly one pick, stake 1). Agent aNN
  gets the same game order in both arms (same shuffle seed). Bettors in the two arms are
  separate launches; no agent sees both arms.
- Files: `<day>/v1/context-aNN.md`, `<day>/v2/context-aNN.md`; `<day>/slate.json` (anonymized,
  with the v2 blocks; v1 renders without them) and `<day>/key.json` (G-id -> real game id).
- Context size (chars/4 ~ tokens, mean per file): v1 {sizes["v1"]:.0f}, v2 {sizes["v2"]:.0f}
  (ratio {sizes["v2"] / sizes["v1"]:.2f}).

## Grading rule
Each pick is 1 unit at the slate's line and price (`ensemble_bets.grade_pick`), validated
against the day's `slate.json` with now = its `created_at`. Game ids map to real ids via
`key.json`. An invalid or missing reply counts as no pick (reported, not imputed).

## Primary
Units won and record of all {n} agent picks per arm (v1 vs v2), at the slate's prices.

## Secondary
- The plurality pick per day and arm (`ensemble_sim.plurality_pick`: most votes, then sum of
  confidence, then lower game id): record and units over the {len(days)} days.
- Agreement: per day, the share of agents on the plurality pick, and the number of distinct
  picks; compared between arms.

## Paired analysis
Same days in both arms. Statistic: mean profit per pick (v2) - mean profit per pick (v1).
95% CI by a day-clustered bootstrap: resample the {len(days)} days with replacement (10,000 draws,
seed 0), keep every pick of a drawn day in both arms, and recompute the difference.

## Verdict rule
v2 replaces v1 in the live vote only if (a) the CI on the per-pick difference excludes 0 in
v2's favor, or (b) after the live record reaches >= 200 graded picks per version, v2 is not
worse than v1 (its per-pick profit >= v1's). Otherwise v1 stays.

## Power (say it plainly)
{n} vs {n} picks is underpowered. With a per-pick SD of ~{sd} units, the SE of the
difference is ~{se:.2f} units per pick if picks were independent, so the minimum detectable
effect (80% power, 5% two-sided) is ~{mde:.2f} units per pick: about a {dw:.0%} difference
in win rate at -110. Agents on the same day often take the same bet, so the effective sample
is closer to {len(days)} days per arm (SE ~{se_day:.2f}, MDE ~{2.8 * se_day:.2f} units per pick).
Real context effects are likely a few percent, far below this, so this test can only catch
a large difference or a broken context. At 200 picks per arm the
MDE falls to ~{2.8 * se200:.2f} units per pick.
"""


def read_ctx_test_arm(day_dir: Path, arm: str) -> tuple[dict, dict[str, list[dict]], dict]:
    """(slate, valid picks per agent, problems per agent) for one arm of a ctx-test day: the
    arm's picks-aNN.json validated against the day-level slate at its decision time."""
    slate = json.loads((day_dir / "slate.json").read_text())
    now = datetime.fromisoformat(slate["created_at"])
    picks: dict[str, list[dict]] = {}
    problems: dict[str, list[str]] = {}
    for ctx in sorted((day_dir / arm).glob("context-*.md")):
        name = ctx.stem.removeprefix("context-")
        try:
            reply = eb.parse_reply((day_dir / arm / f"picks-{name}.json").read_text())
        except (OSError, ValueError) as e:
            picks[name], problems[name] = [], [f"no usable picks file: {e}"]
            continue
        picks[name], problems[name] = eb.validate_picks(reply, slate, now=now)
    return slate, picks, problems


def build_ctx_test(
    con: duckdb.DuckDBPyConnection,
    out: Path,
    start: date,
    end: date,
    used: Sequence[date] = SIM1_NCAAB_DAYS,
    n_days: int = 10,
    n_agents: int = 5,
    max_games: int = NCAAB_MAX_GAMES,
    min_games: int = NCAAB_MIN_GAMES,
) -> dict[str, Any]:
    from deepsports.analysis import ncaab, ncaab_prior
    from deepsports.analysis.ensemble_context_v2 import strip_v2

    if out.resolve() == eb.RUNS_DIR.resolve():
        raise ValueError("test output must not be the live runs dir")
    by_day = college_day_games(con, start, end)
    allowed = set(far_from(sorted(by_day), used))
    counts = {d: len(v) for d, v in by_day.items() if d in allowed}
    days = choose_days(counts, start, end, n_days, min_games)
    v1cfg, pcfg = ncaab.load_config(), ncaab_prior.load_config()
    v1_rows = ncaab.live_rows(con, v1cfg)
    prior_rows = ncaab_prior.live_rows(con, pcfg, v1cfg)
    forbidden = {a.upper() for (a,) in con.execute("SELECT abbreviation FROM teams").fetchall()}
    terms = leak_terms(con)
    summary: dict[str, Any] = {"days": [], "contexts": {"v1": [], "v2": []}, "leaks": {}}
    chars: dict[str, list[int]] = {"v1": [], "v2": []}
    for d in days:
        seed = int(d.strftime("%Y%m%d"))
        kept = sample_games(by_day[d], max_games, random.Random(seed))
        now, until = day_window(min(by_day[d][g] for g in kept), d)
        preds, mc = college_asof_predictions(v1_rows, prior_rows, now, kept, v1cfg, pcfg)
        source = (
            f"walk-forward as of now: ncaab-v1 fit on {mc['train_v1']} / prior model on "
            f"{mc['train_prior']} D1 games finished before now"
        )
        slate = eb.load_historical_slate(
            con, now, until, "ncaab", predictions=preds, model_source=source, game_ids=kept,
            context="v2",
        )  # fmt: skip
        anon, key = anonymize_slate(slate, random.Random(seed + 1), forbidden)
        arms = {
            "v1": {**strip_v2(anon), "context_version": CTX_ARMS["v1"]},
            "v2": {**anon, "context_version": CTX_ARMS["v2"]},
        }
        day_dir = out / d.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / "slate.json").write_text(
            json.dumps({**anon, "context_versions": CTX_ARMS}, indent=1, default=str)
        )
        (day_dir / "key.json").write_text(json.dumps(key, indent=1))
        leaks = {}
        for arm, s_arm in arms.items():
            (day_dir / arm).mkdir(exist_ok=True)
            for i, name in enumerate(eb.agent_names(n_agents)):
                p = day_dir / arm / f"context-{name}.md"
                text = eb.render_context(s_arm, seed=seed * 1000 + i, one_pick=True)
                p.write_text(text)
                chars[arm].append(len(text))
                summary["contexts"][arm].append(str(p))
                hit = find_leaks(text, terms)
                if hit:
                    leaks[f"{arm}/{p.name}"] = hit
        summary["leaks"][d.isoformat()] = leaks
        summary["days"].append(
            {
                "day": d.isoformat(),
                "now": anon["created_at"],
                "eligible": len(by_day[d]),
                "games": len(anon["games"]),
                "model_counts": {k: v for k, v in mc.items() if not k.startswith("train")},
                "base_rate_seasons": anon["base_rates"]["ncaab"]["seasons"],
            }
        )
    sizes = {a: sum(v) / len(v) / 4 for a, v in chars.items() if v}
    summary["tokens_per_file"] = sizes
    if sizes:
        (out / "PLAN.md").write_text(ctx_test_plan(days, n_agents, sizes))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=config.DB_PATH, help="warehouse (a copy is best)")
    ap.add_argument("--league", choices=["nba", "ncaab"], default="nba")
    ap.add_argument("--ctx-test", action="store_true", help="college ctx-v1 vs ctx-v2 matched test")
    ap.add_argument("--out", type=Path, help="default: reports/ensemble-bets-sim[-ncaab]")
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--agents", type=int, default=5)
    a = ap.parse_args(argv)
    college = a.league == "ncaab" or a.ctx_test  # college slates: sampled and anonymized
    start = a.start or (date(2025, 11, 15) if college else date(2026, 10, 23))
    end = a.end or (date(2026, 2, 28) if college else date(2026, 11, 5))
    out = a.out or (CTX_TEST_OUT if a.ctx_test else NCAAB_OUT if college else DEFAULT_OUT)
    con = duckdb.connect(str(a.db), read_only=True)
    try:
        build = build_ctx_test if a.ctx_test else build_sim_ncaab if college else build_sim
        s = build(con, out, start, end, n_days=a.days, n_agents=a.agents)
    finally:
        con.close()
    json.dump(s, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
