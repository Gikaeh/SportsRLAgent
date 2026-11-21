#!/usr/bin/env python3
"""Cash-out check for the owner's open bets (watch-only, read-only).

For every open total or spread bet on a live game, estimates the chance the bet still wins from the
live score and clock, and the fair cash-out value (P(win) x what the ticket pays, stake included).
Take a book's cash-out offer only when it beats the fair value; cash-outs carry their own margin, so
most offers will be below it. Only after halftime by default (--all for every live game).

Reads open bet labels and live scores from the read API (GET /api/bets, default localhost:8787)
and stakes from ../logs/*/betting/*.csv on this Mac. Never opens DuckDB, never places or cashes
out a bet.

Model (heuristic, not backtested): remaining points ~ Normal(mean, sd).
  mean = remaining_min * (w * live_rate + (1 - w) * line_rate), w = elapsed / (2 * regulation)
         (live pace gets at most half weight; the pregame line carries the rest)
  sd   = 16 * sqrt(remaining / regulation) for college totals, 18 for NBA; margins 11 / 12.
Ignores late fouling (adds points in close games) and overtime.

    uv run python tools/cashout.py            # second-half (NBA: 3rd quarter on) open bets
    uv run python tools/cashout.py --all      # any live game
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import urllib.request
from pathlib import Path

LOGS = Path(__file__).resolve().parents[2] / "logs"
LEAGUE = {
    # periods, period minutes, total sd, margin sd (full game)
    "ncaab": (2, 20.0, 16.0, 11.0),
    "nba": (4, 12.0, 18.0, 12.0),
}


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def clock_minutes(clock: str | None) -> float:
    if not clock:
        return 0.0
    if ":" in clock:
        m, s = clock.split(":")
        return int(m) + float(s) / 60
    return float(clock) / 60


def open_tickets() -> dict[tuple[str, str], tuple[float, float]]:
    """(game_id, label) -> (stake, payout incl. stake) for bets with no result or settle row yet."""
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for path in LOGS.glob("*/betting/*.csv"):
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                gid, bet, line = r.get("game_id", ""), r.get("bet", ""), r.get("line", "")
                if not gid or not bet:
                    continue
                label = label_of(r.get("market", ""), bet, line, r.get("matchup", ""))
                key = (gid, label)
                if (r.get("result") or "").strip():
                    out.pop(key, None)
                    continue
                try:
                    stake = float(r["bet_amount"])
                    payout = stake + float(r["potential_profit"])
                except (KeyError, ValueError):
                    continue
                prev = out.get(key, (0.0, 0.0))
                out[key] = (prev[0] + stake, prev[1] + payout)
    return out


def label_of(market: str, bet: str, line: str, matchup: str) -> str:
    num = float(line) if line else 0.0
    txt = f"{num:g}"
    if market == "total":
        return f"{bet.capitalize()} {txt}"
    if market == "spread":
        team = bet.upper()
        if bet in ("home", "away") and " @ " in matchup:
            away, home = matchup.split(" @ ")
            team = home if bet == "home" else away
        return f"{team} {'+' if num > 0 else ''}{txt}"
    return bet


def p_win(card: dict, label: str) -> tuple[float, str] | None:
    lg = LEAGUE.get(card.get("league", "ncaab"))
    if not lg:
        return None
    periods, plen, sd_total, sd_margin = lg
    reg = periods * plen
    period = int(card.get("period") or 0)
    if period > periods:
        return None  # overtime: skip, too few minutes for the model to mean much
    remaining = (periods - period) * plen + clock_minutes(card.get("clock"))
    elapsed = max(reg - remaining, 0.1)
    w = elapsed / (2 * reg)
    home, away = card["home"], card["away"]
    hs, as_ = float(home.get("score") or 0), float(away.get("score") or 0)
    frac = math.sqrt(max(remaining, 0.01) / reg)

    m = re.fullmatch(r"(Over|Under) ([\d.]+)", label)
    if m:
        side, line = m.group(1), float(m.group(2))
        score = hs + as_
        mean = score + remaining * (w * score / elapsed + (1 - w) * line / reg)
        sd = sd_total * frac
        p_over = 1 - norm_cdf((line - mean) / sd)
        return (p_over if side == "Over" else 1 - p_over), f"proj {mean:.0f} vs {line:g}"
    m = re.fullmatch(r"(\S+) ([+-]?[\d.]+)", label)
    if m:
        team, spread = m.group(1), float(m.group(2))
        if team == home.get("abbr"):
            lead = hs - as_
        elif team == away.get("abbr"):
            lead = as_ - hs
        else:
            return None
        # pregame expectation for the remaining margin taken as the spread's share of the time left
        mean = lead + (-spread) * remaining / reg
        sd = sd_margin * frac
        return 1 - norm_cdf((-spread - mean) / sd), f"{team} leads by {lead:+.0f}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default="http://localhost:8787")
    ap.add_argument("--all", action="store_true", help="every live game, not only the second half")
    args = ap.parse_args()
    with urllib.request.urlopen(f"{args.api}/api/bets", timeout=15) as resp:
        games = json.load(resp)["games"]
    tickets = open_tickets()
    shown = 0
    for g in games:
        if g.get("state") != "in":
            continue
        periods = LEAGUE.get(g.get("league", ""), (2,))[0]
        if not args.all and int(g.get("period") or 0) <= periods // 2:
            continue
        a, h = g["away"], g["home"]
        head = f"{a['abbr']} {a.get('score')} @ {h['abbr']} {h.get('score')} {g.get('status_text')}"
        for label in g.get("bets") or []:
            res = p_win(g, label)
            stake, payout = tickets.get((g["id"], label), (0.0, 0.0))
            if res is None:
                print(f"{head} | {label}: no estimate")
                continue
            p, why = res
            fair = (
                f"fair cash-out ${p * payout:.2f} of ${payout:.2f}"
                if payout
                else "already settled in the logs (cashed out?)"
            )
            verdict = "take an offer above fair" if payout else ""
            print(f"{head} | {label}: P(win) {p:.0%} ({why}); {fair} {verdict}".rstrip())
            shown += 1
    if not shown:
        print("no open bets in the second half of a live game")


if __name__ == "__main__":
    main()
