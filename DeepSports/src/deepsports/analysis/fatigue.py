"""Accumulated player load: minutes by a team's top-8 players over the last few days. Pure.

Definition (the DeepSeek edge study's B3 feature, collab/deepseek/lab/b3/features.py and
b3/RESULTS.md; reproduced exactly here):
- top-8 of team T at game G: the (up to) 8 players of T with the most season-to-date minutes
  in games of the same (league, season_year) that tipped strictly before G. Ties go to the
  smaller athlete_id. No prior minutes (season opener) -> the load is undefined (None).
- load = the minutes those players logged in T's games that tipped in
  [t_G - window_hours, t_G - exclude_hours). NULL minutes (DNP) count as 0.

`nba-load-under` (analysis/paper.py) uses window 72 h and exclude 27 h ("3-day load excluding
the final 24 h": 24 h plus a 3 h game length, so nothing that finished within 24 h of tip
counts). B3 found that the sum of both teams' value predicted a lower total than the closing
line in all four NBA dev seasons (exploratory, not pre-registered).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

TOP_N = 8
H = 3600.0


def top8_load(
    games: Iterable[Mapping[str, Any]],
    player_stats: Iterable[Mapping[str, Any]],
    window_hours: float = 72.0,
    exclude_hours: float = 27.0,
    top_n: int = TOP_N,
) -> dict[str, dict[str, float | None]]:
    """{game_id: {"home": load, "away": load}} for every game in `games`.

    games: game_id, league, season_year, start_epoch (seconds), home_team_id, away_team_id;
        include every game of the season that can be history (finished games) or a target.
    player_stats: game_id, team_id, athlete_id, minutes (None = DNP). Stats of games not in
        `games` are ignored; a game without stats adds nothing to anyone's history.
    History comes only from games with a strictly earlier tip, so a scheduled game can be
    passed alongside the finished ones.
    """
    if not 0 <= exclude_hours <= window_hours:
        raise ValueError("need 0 <= exclude_hours <= window_hours")
    stats: dict[tuple[str, str], dict[str, float]] = {}
    for s in player_stats:
        mins = s.get("minutes")
        stats.setdefault((str(s["game_id"]), str(s["team_id"])), {})[str(s["athlete_id"])] = (
            float(mins) if mins else 0.0
        )
    groups: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for g in games:
        groups[(g["league"], int(g["season_year"]))].append(g)

    out: dict[str, dict[str, float | None]] = {}
    for gs in groups.values():
        cum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        recent: dict[str, list[tuple[float, dict[str, float]]]] = defaultdict(list)
        for g in sorted(gs, key=lambda g: (float(g["start_epoch"]), str(g["game_id"]))):
            t = float(g["start_epoch"])
            teams = {"home": str(g["home_team_id"]), "away": str(g["away_team_id"])}
            row: dict[str, float | None] = {}
            for side, team in teams.items():
                top = sorted(
                    ((a, m) for a, m in cum[team].items() if m > 0), key=lambda am: (-am[1], am[0])
                )[:top_n]
                ids = {a for a, _ in top}
                if not ids:
                    row[side] = None
                    continue
                row[side] = sum(
                    sum(box.get(a, 0.0) for a in ids)
                    for e, box in recent[team]
                    if t - window_hours * H <= e < t - exclude_hours * H
                )
            out[str(g["game_id"])] = row
            for team in teams.values():  # this game becomes history for later ones
                box = stats.get((str(g["game_id"]), team))
                if box:
                    for a, m in box.items():
                        cum[team][a] += m
                    recent[team].append((t, box))
                    while recent[team] and recent[team][0][0] < t - window_hours * H:
                        recent[team].pop(0)
    return out
