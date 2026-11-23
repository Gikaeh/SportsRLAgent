"""Shared fixture for the et-v1 / et-v1-alt CLI tests: a tiny warehouse file, a night-before WH
feed and a ManualBets export with five games built so the two rules agree on some and differ on
others (see GAMES). Used by tests/test_early_totals_alt.py, including the et-v1 golden test."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

NOW = datetime(2026, 11, 23, 5, 0, tzinfo=UTC)  # 21:00 PT on Nov 22
TIP = datetime(2026, 11, 23, 20, 0, tzinfo=UTC)
GAME_DATE = "2026-11-23"
LINE = 140.0
MADE = NOW - timedelta(hours=7)

# game_id -> (ncaab-v1 total, ncaab-v1-early total, ncaab-v1.1alt total, MB total, venue elev m)
# vs a 140 line:
# 1: both rules bet over (alt 151 vs v1 150).
# 2: alt-only over (v1 avg edge 3, alt 5.5).
# 3: v1-only over (v1 avg 6, alt 2.5).
# 4: only an early prediction: both rules use it, both bet.
# 5: ncaab-v1 but no alt row (predict failed): alt falls back to v1, both bet.
GAMES = {
    "1": (150.0, None, 151.0, 146.0, 2184.0),
    "2": (141.0, None, 146.0, 145.0, 1600.0),
    "3": (148.0, None, 141.0, 144.0, 100.0),
    "4": (None, 150.0, None, 146.0, 300.0),
    "5": (150.0, None, None, 146.0, 50.0),
}


def warehouse(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE teams (league VARCHAR, team_id VARCHAR, abbreviation VARCHAR, listed BOOLEAN)"
    )
    con.execute(
        "CREATE TABLE games (game_id VARCHAR, league VARCHAR, state VARCHAR, season_year INT,"
        " season_type INT, start_time_utc TIMESTAMPTZ, home_team_id VARCHAR, away_team_id VARCHAR,"
        " home_score INT, away_score INT, completed BOOLEAN, status VARCHAR, venue_id VARCHAR)"
    )
    con.execute("CREATE TABLE venues (venue_id VARCHAR, elevation_m DOUBLE)")
    con.execute(
        "CREATE TABLE predictions (game_id VARCHAR, model VARCHAR, model_version VARCHAR,"
        " created_at TIMESTAMPTZ, p_home_win DOUBLE, pred_home_margin DOUBLE, pred_total DOUBLE)"
    )
    con.execute(
        "CREATE TABLE odds_snapshots (game_id VARCHAR, source VARCHAR, captured_at TIMESTAMPTZ,"
        " provider VARCHAR, details VARCHAR, spread_home DOUBLE, over_under DOUBLE,"
        " home_moneyline INT, away_moneyline INT)"
    )
    for gid, (v1, early, alt, _mb, elev) in GAMES.items():
        con.execute(
            "INSERT INTO teams VALUES ('ncaab', ?, ?, true), ('ncaab', ?, ?, true)",
            [f"h{gid}", f"H{gid}", f"a{gid}", f"A{gid}"],
        )
        con.execute(
            "INSERT INTO games VALUES (?, 'ncaab', 'pre', 2027, 2, ?, ?, ?, NULL, NULL, false,"
            " 'pre', ?)",
            [gid, TIP + timedelta(minutes=int(gid)), f"h{gid}", f"a{gid}", f"v{gid}"],
        )
        con.execute("INSERT INTO venues VALUES (?, ?)", [f"v{gid}", elev])
        for version, total in (("ncaab-v1", v1), ("ncaab-v1-early", early),
                               ("ncaab-v1.1alt", alt)):  # fmt: skip
            if total is not None:
                con.execute(
                    "INSERT INTO predictions VALUES (?, 'v1', ?, ?, 0.5, 0, ?)",
                    [gid, version, MADE, total],
                )
    # made after the log time: never used
    con.execute(
        "INSERT INTO predictions VALUES ('2', 'v1', 'ncaab-v1.1alt', ?, 0.5, 0, 100.0)",
        [NOW + timedelta(hours=1)],
    )
    con.close()


def early_lines() -> dict:
    lines = []
    for gid in GAMES:
        for side in ("over", "under"):
            lines.append({"game_id": gid, "league": "ncaab", "away": f"A{gid}", "home": f"H{gid}",
                          "market": "total", "side": side, "line": LINE, "price": -110,
                          "rotation": None})  # fmt: skip
    return {"date": GAME_DATE, "grabbed_at": "2026-11-22T21:00:00-08:00", "book": "williamhill",
            "lines": lines}  # fmt: skip


def manualbets() -> dict:
    return {"created_at": MADE.isoformat(),
            "ncaab": {"games": [{"game_id": g, "model": {"total": v[3]}, "gated": True}
                                for g, v in GAMES.items()]}}  # fmt: skip


def setup(tmp_path: Path, monkeypatch, cli) -> tuple[Path, Path]:
    """Point the early-totals CLI at the fixture; returns (warehouse path, ManualBets file)."""
    db = tmp_path / "w.duckdb"
    warehouse(db)
    books = tmp_path / "books"
    (books / "williamhill" / "early").mkdir(parents=True)
    (books / "williamhill" / "early" / f"{GAME_DATE}.json").write_text(json.dumps(early_lines()))
    mbf = tmp_path / "mb.json"
    mbf.write_text(json.dumps(manualbets()))
    monkeypatch.setattr(cli.config, "DB_PATH", db)
    monkeypatch.setattr(cli.config, "BOOKS_DIR", books)
    monkeypatch.setattr(cli.config, "WH_LINES_DIR", tmp_path / "wh" / "lines")
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(cli, "datetime", Clock)
    return db, mbf
