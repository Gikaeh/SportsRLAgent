"""Walk-forward evaluation of Elo win probabilities against simple and market baselines.

Elo is updated online, so every probability is already out-of-sample (made before tip-off).
The home-team baseline uses only *earlier* seasons' home win rate, so it is walk-forward too.
"""

from collections import defaultdict
from typing import Any

import duckdb

from deepsports.analysis.elo import EloResult, elo_ratings
from deepsports.analysis.metrics import brier, devig_probability, log_loss


def closing_market_probs(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """game_id -> vig-free home win probability from the closing moneylines."""
    rows = con.execute(
        """
        SELECT game_id, home_moneyline, away_moneyline FROM odds_snapshots
        WHERE source = 'closing'
        QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) = 1
        """
    ).fetchall()
    out = {}
    for gid, hml, aml in rows:
        p = devig_probability(hml, aml)
        if p is not None:
            out[gid] = p
    return out


def _score(probs: list[float], ys: list[int]) -> dict[str, float | None]:
    return {"brier": brier(probs, ys), "log_loss": log_loss(probs, ys)}


def evaluate_elo(
    con: duckdb.DuckDBPyConnection,
    elo: EloResult | None = None,
    burn_in_seasons: int = 1,
    **elo_kwargs: Any,
) -> dict[str, Any]:
    """Per-season Brier/log loss for Elo vs 50/50, home-team-always, and the closing market.

    Two comparisons, each on a common set of games so the numbers are comparable:
    - `all`: every rated game that has a prior-season home rate (Elo, 50/50, home baseline).
    - `market`: the subset with closing moneylines on both sides (Elo vs market).
    `overall` pools seasons after the first `burn_in_seasons` (Elo starts everyone at 1500).
    """
    elo = elo or elo_ratings(con, **elo_kwargs)
    market = closing_market_probs(con)
    by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for g in elo.games:
        by_season[g["season"]].append(g)

    seasons = sorted(by_season)
    prior_wins = prior_n = 0
    per_season = []
    pooled: dict[str, list] = defaultdict(list)
    for i, s in enumerate(seasons):
        games = by_season[s]
        home_rate = prior_wins / prior_n if prior_n else None
        row: dict[str, Any] = {"season": s, "n_rated": len(games), "home_base_rate": home_rate}
        if home_rate is not None:
            ys = [g["home_win"] for g in games]
            pe = [g["p_home"] for g in games]
            row["all"] = {
                "n": len(games),
                "elo": _score(pe, ys),
                "coin_flip": _score([0.5] * len(ys), ys),
                "home_always": _score([home_rate] * len(ys), ys),
            }
        else:
            row["all"] = {"n": 0}
        mk = [g for g in games if g["game_id"] in market]
        ys_m = [g["home_win"] for g in mk]
        row["market"] = {
            "n": len(mk),
            "elo": _score([g["p_home"] for g in mk], ys_m),
            "market": _score([market[g["game_id"]] for g in mk], ys_m),
        }
        per_season.append(row)
        if i >= burn_in_seasons:
            if home_rate is not None:
                for g in games:
                    pooled["all_y"].append(g["home_win"])
                    pooled["all_elo"].append(g["p_home"])
                    pooled["all_home"].append(home_rate)
            for g in mk:
                pooled["mk_y"].append(g["home_win"])
                pooled["mk_elo"].append(g["p_home"])
                pooled["mk_market"].append(market[g["game_id"]])
        # Only regular-season, non-neutral games feed the home baseline for later seasons.
        reg = [g for g in games if g["season_type"] == 2 and not g["neutral_site"]]
        prior_wins += sum(g["home_win"] for g in reg)
        prior_n += len(reg)

    ay, my = pooled["all_y"], pooled["mk_y"]
    overall = {
        "seasons": seasons[burn_in_seasons:],
        "all": {
            "n": len(ay),
            "elo": _score(pooled["all_elo"], ay),
            "coin_flip": _score([0.5] * len(ay), ay),
            "home_always": _score(pooled["all_home"], ay),
        },
        "market": {
            "n": len(my),
            "elo": _score(pooled["mk_elo"], my),
            "market": _score(pooled["mk_market"], my),
        },
    }
    return {"per_season": per_season, "overall": overall}
