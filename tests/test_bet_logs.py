"""Bet-log integrity: every bets CSV must parse and carry the core grading columns.

Bet logs are append-only history (AGENTS.md non-negotiable #3). These tests check
well-formedness only — they never rewrite or normalize anything.
"""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_GLOB = "logs/*/betting/**/*_bets.csv"

CORE_COLUMNS = {"game_id", "date", "result", "timestamp"}


def bet_log_files():
    files = sorted(ROOT.glob(LOG_GLOB))
    assert files, f"no bet logs matched {LOG_GLOB} — did logs/ move?"
    return files


def test_all_bet_logs_parse_with_core_columns():
    for path in bet_log_files():
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            header = set(reader.fieldnames or [])
            rows = list(reader)

        missing = CORE_COLUMNS - header
        assert not missing, f"{path}: missing core columns {missing}"

        for i, row in enumerate(rows, start=2):
            if row.get("result", "").strip():
                assert row["result"] in ("W", "L", "P", "push", "void"), (
                    f"{path}:{i} has unexpected result {row['result']!r}"
                )


def test_bet_logs_have_no_duplicate_game_side_rows():
    """Same game_id + type + side should appear at most once per log."""
    for path in bet_log_files():
        seen = set()
        with open(path, newline="", encoding="utf-8") as fh:
            for i, row in enumerate(csv.DictReader(fh), start=2):
                key = (row.get("game_id"), row.get("type"), row.get("bet_side") or row.get("bet_team"))
                if all(key):
                    assert key not in seen, f"{path}:{i} duplicate bet {key}"
                    seen.add(key)
