"""Spread/total prices in odds_snapshots (all odds paths), price-only line moves, the
price-column migration, and the light `deepsports odds-snapshot` command."""

import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import httpx
import pytest

from deepsports import cli, pipeline
from deepsports.http import PoliteClient
from deepsports.parse_espn import (
    parse_core_odds,
    parse_price,
    parse_scoreboard,
    parse_summary,
)
from deepsports.sources.espn import EspnBasketball
from deepsports.store import Store

FIX = Path(__file__).parent / "fixtures"
START = datetime(2025, 1, 1, tzinfo=UTC)
PRICES = ("spread_home_price", "spread_away_price", "over_price", "under_price")


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def prices(row: dict) -> tuple:
    return tuple(row[k] for k in PRICES)


# ---------- parsers ----------


@pytest.mark.parametrize(
    "raw, expected",
    [("-111", -111), (-105.0, -105), ("+100", 100), ("EVEN", 100), (1.91, None), (None, None)],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_scoreboard_pregame_prices():
    _, odds = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    by = {o["game_id"]: o for o in odds}
    # DET -2.5 (-111) / PHI +2.5 (-109); o217.5 -107 / u217.5 -113 (the `close` = current block)
    assert prices(by["401909922"]) == (-111, -109, -107, -113)
    assert all(None not in prices(o) for o in odds)


def test_summary_closing_prices_nba_and_college():
    _, _, nba = parse_summary(load("espn_summary_final.json"))
    assert prices(nba[0]) == (-105, -115, -110, -110)
    _, _, college = parse_summary(load("espn_ncaab_summary_final_nev_unlv.json"))
    assert prices(college[0]) == (-115, -105, -108, -112)


def test_core_odds_open_and_close_prices():
    by = {
        r["source"]: r for r in parse_core_odds(load("espn_core_odds_401705426.json"), "x", START)
    }
    assert prices(by["opening"]) == (100, -120, -115, -105)
    assert prices(by["closing"]) == (-115, -105, -115, -105)
    # the same college game from the core API and the summary agree on the closing prices
    core = parse_core_odds(load("espn_ncaab_core_odds_401829317.json"), "401829317", START)
    closing = next(r for r in core if r["source"] == "closing")
    _, _, summary = parse_summary(load("espn_ncaab_summary_final_nev_unlv.json"))
    assert prices(closing) == prices(summary[0])


def test_core_odds_flat_legacy_prices():
    (row,) = parse_core_odds(load("espn_core_odds_401360500.json"), "401360500", START)
    assert prices(row) == (-115, -105, -115, -105)


# ---------- store ----------


@pytest.fixture
def db():
    store = Store(":memory:")
    yield store
    store.close()


def test_price_only_move_writes_a_new_pregame_row(db):
    _, odds = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    first = db.add_odds(odds)
    o = odds[0]
    later = o["captured_at"] + timedelta(minutes=30)
    assert db.add_odds([{**o, "captured_at": later}]) == 0  # nothing moved
    juiced = {**o, "captured_at": later + timedelta(minutes=30), "spread_home_price": -120}
    assert db.add_odds([juiced]) == 1  # same line, new juice
    assert db.counts()["odds_snapshots"] == first + 1
    stored = db.con.execute(
        "SELECT spread_home_price FROM odds_snapshots WHERE game_id = ? ORDER BY captured_at",
        [o["game_id"]],
    ).fetchall()
    assert stored == [(-111,), (-120,)]


def test_add_odds_accepts_rows_without_price_keys(db):
    row = {
        "game_id": "g1",
        "source": "pregame",
        "captured_at": START,
        "provider": "X",
        "details": "AAA -1",
        "spread_home": -1.0,
        "over_under": 200.0,
        "home_moneyline": -120,
        "away_moneyline": 100,
    }
    assert db.add_odds([row]) == 1
    assert db.con.execute("SELECT over_price FROM odds_snapshots").fetchone() == (None,)


PRE_PRICE_ODDS = """
CREATE TABLE odds_snapshots (
    game_id VARCHAR NOT NULL, source VARCHAR NOT NULL, captured_at TIMESTAMPTZ NOT NULL,
    provider VARCHAR, details VARCHAR, spread_home DOUBLE, over_under DOUBLE,
    home_moneyline INTEGER, away_moneyline INTEGER,
    PRIMARY KEY (game_id, source, captured_at)
)"""


def test_migration_adds_nullable_price_columns(tmp_path):
    path = tmp_path / "w.duckdb"
    con = duckdb.connect(str(path))
    con.execute(PRE_PRICE_ODDS)
    con.execute(
        "INSERT INTO odds_snapshots VALUES ('g1', 'closing', '2026-01-01 00:00:00+00', 'DK', "
        "'AAA -3', -3, 210, -150, 130), ('g1', 'pregame', '2025-12-31 12:00:00+00', 'DK', "
        "'AAA -2', -2, 211, -140, 120)"
    )
    con.close()

    s = Store(path)
    assert s.migration_report == {"odds_snapshots": (2, 2)}
    rows = s.con.execute(
        "SELECT source, spread_home, spread_home_price, over_price FROM odds_snapshots ORDER BY 1"
    ).fetchall()
    assert rows == [("closing", -3.0, None, None), ("pregame", -2.0, None, None)]
    # an unchanged line on a NULL-price row now carries prices: stored once, then deduped
    new = {
        "game_id": "g1",
        "source": "pregame",
        "captured_at": datetime(2026, 1, 1, tzinfo=UTC) - timedelta(hours=1),
        "provider": "DK",
        "spread_home": -2.0,
        "over_under": 211.0,
        "home_moneyline": -140,
        "away_moneyline": 120,
        "spread_home_price": -110,
        "spread_away_price": -110,
        "over_price": -110,
        "under_price": -110,
    }
    assert s.add_odds([new]) == 1
    assert s.add_odds([{**new, "captured_at": new["captured_at"] + timedelta(minutes=5)}]) == 0
    s.close()

    again = Store(path)
    assert again.migration_report == {}  # idempotent
    again.close()


# ---------- odds-snapshot job ----------


def make_client(tmp_path, handler):
    return PoliteClient(
        raw_dir=tmp_path,
        min_interval=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )


def test_fetch_pregame_odds_always_refetches_today_and_tomorrow(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.params["dates"])
        return httpx.Response(200, json=load("espn_scoreboard_upcoming.json"))

    src = EspnBasketball(make_client(tmp_path, handler), "nba")
    for _ in range(2):  # an upcoming day is never served from cache
        rows, stats = pipeline.fetch_pregame_odds(src, today=date(2026, 11, 4))
    assert calls == ["20261104", "20261105"] * 2
    assert not stats.errors and len(rows) == 22  # 11 games with odds per scoreboard
    assert all(r["source"] == "pregame" and r["spread_home_price"] for r in rows)
    assert (tmp_path / "espn/nba/scoreboard/20261105.json.gz").exists()


def _patch_cli(monkeypatch, tmp_path, handler) -> Path:
    path = tmp_path / "w.duckdb"
    Store(path).close()
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli.config, "DB_PATH", path)
    monkeypatch.setattr(cli, "PoliteClient", lambda: make_client(tmp_path / "raw", handler))
    return path


def test_cli_odds_snapshot_writes_pregame_rows_only(tmp_path, monkeypatch, capsys):
    def handler(request):
        name = "espn_scoreboard_upcoming.json"
        if "mens-college" in str(request.url):
            name = "espn_ncaab_scoreboard_20261108_upcoming.json"  # no odds posted yet
        return httpx.Response(200, json=load(name))

    path = _patch_cli(monkeypatch, tmp_path, handler)
    assert cli.main(["odds-snapshot"]) == 0
    out = capsys.readouterr().out
    assert "games_with_odds=22 with_prices=22 new_rows=11 requests=4" in out
    assert cli.main(["odds-snapshot"]) == 0  # nothing moved: no new rows
    assert "new_rows=0" in capsys.readouterr().out
    s = Store(path, read_only=True)
    assert s.con.execute("SELECT DISTINCT source FROM odds_snapshots").fetchall() == [("pregame",)]
    assert s.counts()["odds_snapshots"] == 11 and s.counts()["games"] == 0
    runs = s.con.execute("SELECT command, network_requests FROM ingest_runs").fetchall()
    assert runs == [("odds-snapshot nba,ncaab", 4)] * 2
    s.close()


def test_cli_odds_snapshot_skips_quietly_when_writer_lock_is_held(tmp_path, monkeypatch, capsys):
    def handler(request):
        raise AssertionError("must not fetch while another writer runs")

    path = _patch_cli(monkeypatch, tmp_path, handler)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import duckdb, sys, time; c = duckdb.connect(sys.argv[1]); "
            "print('ready', flush=True); time.sleep(60)",
            str(path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        assert cli.main(["odds-snapshot"]) == 0
    finally:
        holder.kill()
        holder.wait()
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "skipped, warehouse busy" in out[0]
