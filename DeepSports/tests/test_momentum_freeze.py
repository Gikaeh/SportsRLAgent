"""Momentum forward-test freeze: slot/day naming, the DS prediction query against a temp
warehouse, the byte copy of the ManualBets export, write-once and the non-fatal paths."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from deepsports import config
from deepsports import momentum_freeze as mf
from deepsports.store import Store

NOW = datetime(2026, 11, 24, 3, 2, 30, tzinfo=UTC)  # 19:02 PST on Nov 23 -> D = Nov 24


@pytest.fixture
def warehouse(tmp_path):
    db = Store(tmp_path / "w.duckdb")
    games = [
        # gid, league, start (UTC), state
        ("g1", "ncaab", "2026-11-24 17:00:00+00", "pre"),  # D, ET and PT
        ("g2", "ncaab", "2026-11-25 04:30:00+00", "pre"),  # 23:30 ET Nov 24 = D
        ("g3", "ncaab", "2026-11-25 18:00:00+00", "pre"),  # D+1: excluded
        ("g4", "nba", "2026-11-24 23:00:00+00", "pre"),  # NBA: excluded
        ("g5", "ncaab", "2026-11-24 20:00:00+00", "pre"),  # D, no predictions
    ]
    for gid, lg, start, state in games:
        db.con.execute(
            "INSERT INTO games (game_id, league, season_year, season_type, start_time_utc,"
            " status, state, completed, home_team_id, away_team_id, updated_at)"
            " VALUES (?, ?, 2027, 2, ?, 'STATUS_SCHEDULED', ?, false, 'h', 'a', now())",
            [gid, lg, start, state],
        )
    preds = [
        ("g1", "v1", "ncaab-v1", 141.5, "2026-11-23 22:00:00+00"),
        ("g1", "v1", "ncaab-v1-early", 143.0, "2026-11-23 22:00:00+00"),
        ("g1", "v1", "ncaab-v1.1alt", 142.2, "2026-11-23 22:00:00+00"),
        ("g1", "v1", "v1.1", 150.0, "2026-11-23 22:00:00+00"),  # other version: excluded
        ("g2", "v1", "ncaab-v1-early", 155.5, "2026-11-23 16:00:00+00"),
        ("g3", "v1", "ncaab-v1", 130.0, "2026-11-23 22:00:00+00"),
    ]
    for gid, model, ver, total, created in preds:
        db.con.execute(
            "INSERT INTO predictions (game_id, model, model_version, created_at, pred_total)"
            " VALUES (?, ?, ?, ?, ?)",
            [gid, model, ver, created, total],
        )
    yield db
    db.close()


def test_slot_and_day():
    assert mf.slot_hhmm(NOW) == "1900"
    assert mf.slot_hhmm(datetime(2026, 11, 24, 3, 31, tzinfo=UTC)) == "1930"
    assert mf.slot_hhmm(datetime(2026, 11, 24, 2, 45, tzinfo=UTC)) == "1830"
    assert mf.game_day(NOW) == date(2026, 11, 24)
    p = mf.freeze_dir(date(2026, 11, 24), "1900", Path("/r"))
    assert p == Path("/r/momentum-forward/frozen/2026-11-24/1900")


def test_prediction_rows(warehouse):
    games = mf.prediction_rows(warehouse.con, date(2026, 11, 24))
    assert [g["game_id"] for g in games] == ["g1", "g5", "g2"]
    g1 = games[0]
    assert {p["model_version"]: p["pred_total"] for p in g1["predictions"]} == {
        "ncaab-v1": 141.5,
        "ncaab-v1-early": 143.0,
        "ncaab-v1.1alt": 142.2,
    }
    assert g1["predictions"][0]["created_at"] == "2026-11-23T22:00:00.000000Z"
    assert games[1]["predictions"] == []


def _mb(tmp_path) -> Path:
    src = tmp_path / "manualbets-export.json"
    src.write_text(json.dumps({"created_at": "2026-11-23T14:05:00-08:00", "ncaab": {"games": []}}))
    return src


def test_run_writes_once(tmp_path, warehouse, monkeypatch):
    rep = tmp_path / "reports"
    src = _mb(tmp_path)
    opened = []

    def opener():
        opened.append(1)
        return warehouse

    monkeypatch.setattr(warehouse, "close", lambda: None)
    line = mf.run(NOW, reports_dir=rep, opener=opener, mb_src=src)
    assert line == (
        "momentum freeze D=2026-11-24 slot 1900: ds 3 games 4 rows; "
        "mb copied (created_at 2026-11-23T14:05:00-08:00)"
    )
    out = rep / "momentum-forward" / "frozen" / "2026-11-24" / "1900"
    body = json.loads((out / "ds_predictions.json").read_text())
    assert body["game_day"] == "2026-11-24" and body["frozen_at"].startswith("2026-11-24T03:02:30")
    assert (out / "manualbets-export.json").read_bytes() == src.read_bytes()
    meta = json.loads((out / "manualbets-export.meta.json").read_text())
    assert meta["size"] == len(src.read_bytes()) and meta["mtime"] and len(meta["sha256"]) == 64
    # again, with a changed export: nothing is overwritten and the warehouse isn't opened
    src.write_text("{}")
    line = mf.run(NOW, reports_dir=rep, opener=opener, mb_src=src)
    assert "ds already frozen" in line and "mb already frozen" in line and len(opened) == 1
    assert json.loads((out / "manualbets-export.json").read_text())["created_at"]
    assert not list(out.glob("*.tmp"))


def test_busy_and_missing_export_are_non_fatal(tmp_path):
    line = mf.run(NOW, reports_dir=tmp_path, opener=lambda: None, mb_src=tmp_path / "nope.json")
    assert "ds FAILED: warehouse busy" in line and "mb FAILED: FileNotFoundError" in line
    assert line.count("\n") == 0
    assert not (tmp_path / "momentum-forward" / "frozen" / "2026-11-24" / "1900").exists()


def test_open_read_only_retries_once(monkeypatch):
    import duckdb

    from deepsports import store

    calls, slept = [], []

    def busy(*a, **k):
        calls.append(k)
        raise duckdb.IOException('Could not set lock on file "w.duckdb": Conflicting lock')

    monkeypatch.setattr(store, "Store", busy)
    assert mf.open_read_only(1.0, 5.0, sleep=slept.append) is None
    assert len(calls) == 2 and slept == [5.0] and all(k["read_only"] for k in calls)


def test_write_once(tmp_path):
    f = tmp_path / "a" / "x.json"
    assert mf.write_once(f, b"1") is True
    assert mf.write_once(f, b"2") is False and f.read_bytes() == b"1"


def test_main_data_dir_unavailable(monkeypatch, capsys):
    def gone():
        raise config.DataDirUnavailable("drive not mounted")

    monkeypatch.setattr(config, "require_data_dir", gone)
    assert mf.main([]) == 0
    assert capsys.readouterr().out.startswith("momentum freeze: skipped, data dir unavailable")
