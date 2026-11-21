"""Open (ungraded) owner bets, read from the SportsRLAgent bet logs, so the apps can tag the game.

The logs are `logs/**/*_bets.csv` and `logs/college_basketball/betting/bets.csv` one level above
this project. They are read-only here (the owner's bet logs are append-only history). Only a short
label is exposed ("TOR -2.5", "Over 216.5"), never the stake. Game ids are ESPN's, which is what
the owner's rows use; older rows with NBA-API ids simply never match a card.
"""

import csv
import os
from pathlib import Path

from deepsports import config

NBA_LOGS = ("h2h_bets.csv", "spread_bets.csv", "total_bets.csv")


def logs_dir() -> Path:
    return Path(os.environ.get("DEEPSPORTS_BET_LOGS", config.ROOT.parent / "logs"))


def _signed(x: str) -> str:
    n = float(x)
    text = f"{n:+g}"
    return text


def _label(row: dict[str, str], kind: str) -> str | None:
    """One short label for an open bet row, or None if the row can't be read."""
    try:
        if kind == "college":
            market, team = row["market"], row["bet"]
            suffix = " 1H" if market.endswith("_1h") else ""
            base = market.removesuffix("_1h")
            if base == "total":
                return f"{team.capitalize()} {float(row['line']):g}{suffix}"
            if base == "h2h":
                return f"{team} ML{suffix}"
            return f"{team}{suffix} {_signed(row['line'])}"
        bet_type = row["type"]
        if bet_type == "total":
            return f"{row['bet_side'].capitalize()} {float(row['total_line']):g}"
        if bet_type == "h2h":
            return f"{row['bet_team']} ML"
        line = row["home_spread"] if row["bet_side"] == "home" else row["away_spread"]
        return f"{row['bet_team']} {_signed(line)}"
    except (KeyError, ValueError, AttributeError):
        return None


def open_bets(directory: Path | None = None) -> dict[str, list[str]]:
    """{game_id: [labels]} for bet rows with no result and no later settling row.

    Missing files are skipped.
    """
    base = directory or logs_dir()
    files = [(base / "basketball" / "betting" / n, "nba") for n in NBA_LOGS]
    files.append((base / "college_basketball" / "betting" / "bets.csv", "college"))
    found: dict[str, list[str]] = {}
    for path, kind in files:
        try:
            with path.open(newline="") as f:
                rows = list(csv.DictReader(f))
        except OSError:
            continue
        # Logs are append-only, so a bet settled later (e.g. a cashout) keeps its open row and gets
        # a new row with a result. A row with a result closes one earlier open row with the same
        # game, label and book.
        pending: dict[tuple[str, str, str], list[str]] = {}
        for row in rows:
            label = _label(row, kind)
            game_id = (row.get("game_id") or "").strip()
            if not (label and game_id):
                continue
            key = (game_id, label, (row.get("book") or "").strip().lower())
            if (row.get("result") or "").strip():
                if pending.get(key):
                    pending[key].pop()
                continue
            pending.setdefault(key, []).append(label)
        for (game_id, _, _), labels in pending.items():
            if labels:
                found.setdefault(game_id, []).extend(labels)
    return found
