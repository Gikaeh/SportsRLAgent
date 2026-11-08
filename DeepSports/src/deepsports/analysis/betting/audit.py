"""Line-move audit for graded bets (the edge study's "protocol 10"). Pure: data in, data out.

1. Drop and report: per (league, season, market) take the median |open - close| move over games
   with both lines; flag a (game, market) whose move is more than `multiplier` (default 3)
   times that median (likely a data error), and drop bets on it.
2. List the `top_n` biggest-edge winning bets of the kept set with their raw odds rows, so the
   best-looking wins can be eyeballed against the source data.

Edge of a winning bet: spread home margin + line, away line - margin; over total - line, under
line - total; moneyline the upset size (1 - de-vigged closing probability of the side) x 100.

Inputs: graded rows (`grading.grade(...).bets`), game rows with league and season_year,
`loaders.load_lines` rows, and optionally `loaders.load_odds_raw` rows.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from deepsports.analysis.metrics import devig_probability

MOVE_MARKETS = ("spread", "total", "ml")
# bet market -> audited move market
_MOVE_KEY = {"spread": "spread", "total": "total", "moneyline": "ml"}


def _move_for(line: Mapping[str, Any], market: str) -> float | None:
    """|open - close| for one game in one market (moneyline: de-vigged probability points)."""
    if market == "ml":
        p_open = devig_probability(line.get("open_home_ml"), line.get("open_away_ml"))
        p_close = devig_probability(line.get("close_home_ml"), line.get("close_away_ml"))
        if p_open is None or p_close is None:
            return None
        return abs(p_close - p_open) * 100.0
    keys = {
        "spread": ("open_spread_home", "close_spread_home"),
        "total": ("open_total", "close_total"),
    }
    if market not in keys:
        raise ValueError(f"unknown market {market!r}")
    o, c = (line.get(k) for k in keys[market])
    return abs(c - o) if o is not None and c is not None else None


def move_medians(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per (league, season_year, market): the median |open - close| move and the game count."""
    buckets: dict[tuple[str, int, str], list[float]] = {}
    for r in lines:
        league, season = r.get("league"), r.get("season_year")
        if league is None or season is None:
            continue
        for market in MOVE_MARKETS:
            move = _move_for(r, market)
            if move is not None:
                buckets.setdefault((league, int(season), market), []).append(move)
    return [
        {
            "league": league,
            "season_year": season,
            "market": market,
            "n_pairs": len(moves),
            "median_abs_move": statistics.median(moves),
        }
        for (league, season, market), moves in sorted(buckets.items())
    ]


def flag_moves(
    lines: Sequence[Mapping[str, Any]],
    multiplier: float = 3.0,
    medians: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """(game, market) pairs whose |open - close| move is strictly more than `multiplier` x
    their (league, season, market) median."""
    if multiplier <= 0:
        raise ValueError(f"multiplier must be > 0, got {multiplier!r}")
    med = {
        (m["league"], m["season_year"], m["market"]): m["median_abs_move"]
        for m in (medians if medians is not None else move_medians(lines))
    }
    out = []
    for r in lines:
        league, season = r.get("league"), r.get("season_year")
        if league is None or season is None:
            continue
        for market in MOVE_MARKETS:
            base = med.get((league, int(season), market))
            move = _move_for(r, market)
            if not base or base <= 0 or move is None or move / base <= multiplier:
                continue
            out.append(
                {
                    "game_id": str(r.get("game_id")),
                    "league": league,
                    "season_year": int(season),
                    "market": market,
                    "abs_move": move,
                    "median_abs_move": base,
                    "ratio": move / base,
                }
            )
    return sorted(out, key=lambda d: (d["market"], d["league"], d["season_year"], d["game_id"]))


def bet_edge(bet: Mapping[str, Any], lines_row: Mapping[str, Any] | None) -> float | None:
    """Points (moneyline: probability points) by which a winning bet cleared."""
    market, side = bet["market"], bet["side"]
    if market == "spread":
        return bet["margin"] + bet["line"] if side == "home" else bet["line"] - bet["margin"]
    if market == "total":
        return bet["total"] - bet["line"] if side == "over" else bet["line"] - bet["total"]
    if market == "moneyline":
        if lines_row is None:
            return None
        p = devig_probability(lines_row.get("close_home_ml"), lines_row.get("close_away_ml"))
        if p is None:
            return None
        return (1.0 - (p if side == "home" else 1.0 - p)) * 100.0
    raise ValueError(f"unknown market {market!r}")


@dataclass
class AuditResult:
    dropped_count: int = 0
    dropped_bets: list[dict[str, Any]] = field(default_factory=list)
    flagged_games: list[dict[str, Any]] = field(default_factory=list)
    medians: list[dict[str, Any]] = field(default_factory=list)
    top_bets: list[dict[str, Any]] = field(default_factory=list)

    def report(self) -> str:
        out = [
            f"dropped {self.dropped_count} bet(s) on {len(self.flagged_games)} "
            "flagged (game, market) pair(s)",
            "move medians (|open-close|):",
        ]
        out += [
            f"  {m['league']} {m['season_year']} {m['market']}: "
            f"median {m['median_abs_move']:.3f} over {m['n_pairs']} games"
            for m in self.medians
        ]
        out.append(f"top {len(self.top_bets)} biggest-edge winning bets (kept set):")
        out += [
            f"  {b.get('game_id')} {b.get('league')} {b.get('market')} {b.get('side')} "
            f"line {b.get('line')} edge {b.get('edge')}"
            for b in self.top_bets
        ]
        return "\n".join(out)


def audit(
    bets: Sequence[Mapping[str, Any]],
    games: Sequence[Mapping[str, Any]],
    lines: Sequence[Mapping[str, Any]],
    odds_raw: Sequence[Mapping[str, Any]] | None = None,
    *,
    multiplier: float = 3.0,
    top_n: int = 20,
) -> AuditResult:
    """Drop bets on flagged (game, market) moves and list the biggest-edge kept winners.
    `bets` must be graded rows (`grading.grade(...).bets`)."""
    for i, b in enumerate(bets):
        for key in ("game_id", "market", "grade"):
            if b.get(key) is None:
                raise ValueError(
                    f"audit: bets[{i}] is missing {key!r}; pass graded rows (grade(...).bets)"
                )
    games_by_id = {str(g["game_id"]): g for g in games}
    lines_by_id = {str(r["game_id"]): r for r in lines}
    medians = move_medians(lines)
    flagged = flag_moves(lines, multiplier=multiplier, medians=medians)
    flag_by_key = {(f["game_id"], f["market"]): f for f in flagged}

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for bet in bets:
        game = games_by_id.get(str(bet["game_id"])) or {}
        row = dict(bet)
        row["league"] = bet.get("league") if bet.get("league") is not None else game.get("league")
        row["season_year"] = game.get("season_year")
        flag = flag_by_key.get((str(bet["game_id"]), _MOVE_KEY.get(bet["market"], bet["market"])))
        if flag is None:
            kept.append(row)
            continue
        row.update(
            {
                "flag_abs_move": flag["abs_move"],
                "flag_median": flag["median_abs_move"],
                "flag_ratio": flag["ratio"],
            }
        )
        dropped.append(row)

    winners = [b for b in kept if b.get("grade") == "win"]
    for b in winners:
        b["edge"] = bet_edge(b, lines_by_id.get(str(b["game_id"])))
    winners.sort(key=lambda b: (b["edge"] is None, -(b["edge"] or 0.0)))
    raw_by_game: dict[str, list[dict[str, Any]]] = {}
    for r in odds_raw or []:
        raw_by_game.setdefault(str(r["game_id"]), []).append(dict(r))
    top = [{**b, "raw_odds": raw_by_game.get(str(b["game_id"]), [])} for b in winners[:top_n]]
    return AuditResult(
        dropped_count=len(dropped),
        dropped_bets=dropped,
        flagged_games=flagged,
        medians=medians,
        top_bets=top,
    )
