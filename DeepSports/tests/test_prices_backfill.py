"""Offline price backfill (`deepsports prices-backfill`): fill NULL spread/total prices on
historical opening/closing rows from the cached response each row was parsed from."""

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from deepsports import cli, pipeline
from deepsports.parse_espn import (
    PRICE_COLS,
    match_cached_prices,
    parse_core_odds,
    parse_pickcenter,
    parse_time,
    price_origin,
)
from deepsports.store import Store

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def prices(row: dict) -> tuple:
    return tuple(row[k] for k in PRICE_COLS)


def unpriced(row: dict) -> dict:
    return {**row, **dict.fromkeys(PRICE_COLS)}


# 2021-22 NBA game: the summary's pickcenter (consensus) and the core API's chosen book
# (DraftKings) quote the same -1.5 / 234 line at different prices, so each stored row must
# take its prices from the response it was built from.
NBA_SUMMARY = load("espn_nba_summary_pickcenter_401358773.json")
NBA_CORE = load("espn_nba_core_odds_401358773.json")
NBA_START = parse_time(NBA_SUMMARY["header"]["competitions"][0]["date"])
FETCHED = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


# ---------- pure parts ----------


def test_price_origin():
    start = NBA_START
    assert price_origin("opening", start, start) == "core"
    assert price_origin("closing", start, start) == "core"
    assert price_origin("closing", start + timedelta(days=900), start) == "summary"
    assert price_origin("pregame", start, start) is None


def test_summary_and_core_disagree_on_price_at_the_same_line():
    (summary,) = parse_pickcenter(NBA_SUMMARY, FETCHED)
    (core,) = parse_core_odds(NBA_CORE, "401358773", NBA_START)  # flat legacy: closing only
    assert core["source"] == "closing"
    assert (summary["spread_home"], summary["over_under"]) == (-1.5, 234.0)
    assert (core["spread_home"], core["over_under"]) == (-1.5, 234.0)
    assert prices(summary) == (-112, -108, -110, -110)
    assert prices(core) == (-115, -105, -110, -110)
    assert (summary["provider"], core["provider"]) == ("consensus", "DraftKings")


def test_match_fills_from_its_own_origin_only():
    (summary,) = parse_pickcenter(NBA_SUMMARY, FETCHED)
    stored = unpriced(summary)
    status, fill = match_cached_prices(stored, [summary])
    assert status == "fill" and prices({**stored, **fill}) == (-112, -108, -110, -110)
    # the core API's closing row is a different book: never used for a summary-built row
    core = parse_core_odds(NBA_CORE, "401358773", NBA_START)
    assert match_cached_prices(stored, core) == ("mismatch", {})


def test_match_never_overwrites_and_skips_changed_lines():
    (summary,) = parse_pickcenter(NBA_SUMMARY, FETCHED)
    partial = {**unpriced(summary), "over_price": -999}
    status, fill = match_cached_prices(partial, [summary])
    assert status == "fill" and "over_price" not in fill and fill["under_price"] == -110
    assert match_cached_prices(summary, [summary]) == ("no_prices", {})
    moved = {**unpriced(summary), "spread_home": -2.5}
    assert match_cached_prices(moved, [summary]) == ("mismatch", {})
    assert match_cached_prices({**unpriced(summary), "source": "opening"}, [summary]) == (
        "missing",
        {},
    )


# ---------- job + store ----------


def write_cache(raw_dir: Path, key: str, data: dict) -> None:
    path = raw_dir / f"{key}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)


def game(game_id: str, league: str, start: datetime) -> dict:
    return {
        "game_id": game_id,
        "league": league,
        "season_year": 2025,
        "season_type": 2,
        "start_time_utc": start,
        "status": "STATUS_FINAL",
        "state": "post",
        "completed": True,
        "home_team_id": "1",
        "away_team_id": "2",
        "updated_at": FETCHED,
    }


@pytest.fixture
def warehouse(tmp_path):
    """A warehouse whose historical odds rows have NULL prices, plus their real raw cache."""
    raw = tmp_path / "raw"
    path = tmp_path / "w.duckdb"
    write_cache(raw, "espn/nba/summary/401358773", NBA_SUMMARY)
    write_cache(raw, "espn/nba/core_odds/401358773", NBA_CORE)
    core25 = load("espn_core_odds_401705426.json")
    start25 = datetime(2025, 1, 2, 0, 30, tzinfo=UTC)
    write_cache(raw, "espn/nba/core_odds/401705426", core25)
    college = load("espn_ncaab_core_odds_401829317.json")
    start_c = datetime(2026, 1, 31, 3, 0, tzinfo=UTC)
    write_cache(raw, "espn/ncaab/core_odds/401829317", college)

    rows = [unpriced(r) for r in parse_pickcenter(NBA_SUMMARY, FETCHED)]  # closing (summary)
    rows += [unpriced(r) for r in parse_core_odds(core25, "401705426", start25)]  # open + close
    c_rows = [unpriced(r) for r in parse_core_odds(college, "401829317", start_c)]
    # this college opening line was edited after the fact: must be skipped, not priced
    c_rows = [{**r, "over_under": 999.5} if r["source"] == "opening" else r for r in c_rows]
    db = Store(path)
    db.upsert_games(
        [
            game("401358773", "nba", NBA_START),
            game("401705426", "nba", start25),
            game("401829317", "ncaab", start_c),
        ]
    )
    db.add_odds(rows + c_rows)
    db.close()
    return path, raw


def stored_prices(path: Path) -> dict:
    s = Store(path, read_only=True)
    out = {
        (g, src): tuple(p)
        for g, src, *p in s.con.execute(
            f"SELECT game_id, source, {', '.join(PRICE_COLS)} FROM odds_snapshots"
        ).fetchall()
    }
    s.close()
    return out


def test_backfill_job_fills_matches_and_is_idempotent(warehouse):
    path, raw = warehouse
    db = Store(path)
    try:
        todo = db.odds_missing_prices("nba")
        assert len(todo) == 3
        fills, counts, notes = pipeline.plan_price_backfill(todo, raw, "nba")
        assert counts == {"fill": 3} and not notes
        assert db.fill_odds_prices(fills) == 3
        assert db.fill_odds_prices(fills) == 0  # re-run: nothing left to fill
        assert db.odds_missing_prices("nba") == []

        todo = db.odds_missing_prices("ncaab")
        fills, counts, notes = pipeline.plan_price_backfill(todo, raw, "ncaab")
        assert counts == {"fill": 1, "mismatch": 1} and "999.5" in notes[0]
        assert db.fill_odds_prices(fills) == 1
    finally:
        db.close()
    got = stored_prices(path)
    assert got[("401358773", "closing")] == (-112, -108, -110, -110)  # summary, not core
    assert got[("401705426", "opening")] == (100, -120, -115, -105)
    assert got[("401705426", "closing")] == (-115, -105, -115, -105)
    assert got[("401829317", "opening")] == (None,) * 4  # mismatch left alone
    assert None not in got[("401829317", "closing")]


def test_fill_rechecks_line_and_keeps_existing_prices(warehouse):
    path, raw = warehouse
    db = Store(path)
    try:
        fills, _, _ = pipeline.plan_price_backfill(db.odds_missing_prices("nba"), raw, "nba")
        # between planning and writing, one line changes and one price is set by someone else
        db.con.execute(
            "UPDATE odds_snapshots SET spread_home = -9 WHERE game_id = '401705426' "
            "AND source = 'opening'"
        )
        db.con.execute("UPDATE odds_snapshots SET over_price = -130 WHERE game_id = '401358773'")
        assert db.fill_odds_prices(fills) == 2
    finally:
        db.close()
    got = stored_prices(path)
    assert got[("401705426", "opening")] == (None,) * 4
    assert got[("401358773", "closing")] == (-112, -108, -130, -110)


def test_missing_cache_is_counted(warehouse, tmp_path):
    path, _ = warehouse
    s = Store(path, read_only=True)
    todo = s.odds_missing_prices("nba")
    s.close()
    fills, counts, _ = pipeline.plan_price_backfill(todo, tmp_path / "empty", "nba")
    assert fills == [] and counts == {"no_cache": 3}


def test_cli_dry_run_then_write(warehouse, monkeypatch, capsys):
    path, raw = warehouse
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli.config, "DB_PATH", path)
    monkeypatch.setattr(cli.config, "RAW_DIR", raw)
    before = stored_prices(path)
    assert cli.main(["prices-backfill", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "(dry run)" in out and "nba: rows=3 fill=3" in out and "ncaab: rows=2" in out
    assert "rows_updated=0" in out and stored_prices(path) == before
    assert cli.main(["prices-backfill"]) == 0
    assert "matched_with_prices=4 rows_updated=4" in capsys.readouterr().out
    assert cli.main(["prices-backfill", "--league", "nba"]) == 0
    assert "nba: rows=0 " in capsys.readouterr().out + " "
    s = Store(path, read_only=True)
    runs = s.con.execute("SELECT command, network_requests FROM ingest_runs").fetchall()
    s.close()
    assert runs == [("prices-backfill nba,ncaab", 0), ("prices-backfill nba", 0)]
