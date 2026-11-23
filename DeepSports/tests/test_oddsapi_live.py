"""The Odds API scheduled live capture: slot naming, the parser helper (the REAL live response
from 2026-11-19, trimmed to 2 events, totals only; spreads sides from the SYNTHETIC historical
fixture), and the `live` command's guards against a mocked API (never the network)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from deepsports import config, oddsapi_cli
from deepsports.http import PoliteClient
from deepsports.sources import oddsapi_history as oah
from deepsports.sources import oddsapi_live as olv

FIX = Path(__file__).parent / "fixtures"
LIVE = FIX / "oddsapi_live_ncaab_totals_us_20261119.json"  # real, trimmed to 2 events
HIST = FIX / "oddsapi_historical_ncaab_synthetic.json"  # SYNTHETIC: documented shape
KEY = "k3y-0123456789abcdef"
NOW = datetime(2026, 11, 23, 20, 7, 12, tzinfo=UTC)  # 12:07 PT


def test_slot_and_path(tmp_path):
    assert oah.live_slot(NOW) == datetime(2026, 11, 23, 20, 0, tzinfo=UTC)
    assert oah.live_slot(datetime(2026, 11, 23, 20, 59, 59, tzinfo=UTC)) == datetime(
        2026, 11, 23, 20, 30, tzinfo=UTC
    )
    p = oah.live_path("basketball_nba", oah.live_slot(NOW), tmp_path)
    assert p == tmp_path / "oddsapi" / "live" / "basketball_nba" / "20261123T200000Z.json.gz"
    assert olv.stamp_ts(p.name) == datetime(2026, 11, 23, 20, 0, tzinfo=UTC)
    assert olv.stamp_ts("ledger.jsonl") is None


def test_live_cost_ten_books_one_region():
    assert oah.live_cost(["totals", "spreads"], ["us"], list(oah.LIVE_BOOKMAKERS)) == 2
    assert oah.live_cost(["totals"], ["us", "eu"]) == 2


def test_live_rows_real_bare_list_and_envelope():
    data = json.loads(LIVE.read_text())
    snap = datetime(2026, 11, 19, 21, 24, 39, tzinfo=UTC)
    rows = olv.live_rows(data, snap)
    assert rows and all(set(r) == set(olv.LINE_COLUMNS) for r in rows)
    assert {r["side"] for r in rows} == {"over", "under"}
    fd = [r for r in rows if r["book"] == "fanduel" and r["home_team"].startswith("Notre Dame")]
    assert {(r["side"], r["point"], r["price"]) for r in fd} == {
        ("over", 151.5, -110),
        ("under", 151.5, -110),
    }
    assert fd[0]["last_update"] == datetime(2026, 11, 19, 21, 24, 15, tzinfo=UTC)
    assert fd[0]["event_id"] == "57ce51731aa0e3325c489d30a2b2e7ed"
    env = oah.live_envelope(
        data, snap, "basketball_ncaab", ["totals"], ["us"], None, oah.Credits(9, 1, 1)
    )
    assert olv.live_rows(env, None) == rows  # envelope timestamp == snap


def test_live_rows_spread_sides_synthetic():
    rows = olv.live_rows(json.loads(HIST.read_text()))
    sp = {(r["outcome"], r["side"]) for r in rows if r["market"] == "spreads"}
    assert sp == {("Nevada Wolf Pack", "away"), ("San Diego St Aztecs", "home")} or sp == {
        ("Nevada Wolf Pack", "home"),
        ("San Diego St Aztecs", "away"),
    }
    for r in rows:
        if r["market"] == "spreads":
            team = r["home_team"] if r["side"] == "home" else r["away_team"]
            assert r["outcome"] == team


def test_read_live_file_old_layout_uses_name_stamp(tmp_path):
    f = tmp_path / "20261119T212439Z.json.gz"
    with gzip.open(f, "wt") as fh:
        json.dump(json.loads(LIVE.read_text()), fh)
    rows = olv.read_live_file(f)
    assert {r["snapshot_ts"] for r in rows} == {datetime(2026, 11, 19, 21, 24, 39, tzinfo=UTC)}


# ---------------------------------------------------------------- the live command


def _client(handler) -> PoliteClient:
    return PoliteClient(
        raw_dir=Path("/nonexistent"),
        min_interval=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )


def _api(state: dict):
    def handler(req: httpx.Request) -> httpx.Response:
        state.setdefault("seen", []).append((req.url.path, dict(req.url.params)))
        if state.get("status"):
            return httpx.Response(state["status"], json={"message": f"bad key {KEY}"})
        hdr = {"x-requests-used": "0"}
        if req.url.path == "/v4/sports":
            hdr |= {"x-requests-remaining": str(state["remaining"]), "x-requests-last": "0"}
            return httpx.Response(200, json=[], headers=hdr)
        state["remaining"] -= 2
        hdr |= {"x-requests-remaining": str(state["remaining"]), "x-requests-last": "2"}
        return httpx.Response(200, json=json.loads(LIVE.read_text()), headers=hdr)

    return handler


def _setup(monkeypatch, tmp_path, state: dict) -> None:
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(oddsapi_cli, "PoliteClient", lambda: _client(_api(state)))
    monkeypatch.setattr(oah, "read_key", lambda: KEY)


def _args(*extra: str):
    return oddsapi_cli.build_parser().parse_args(["live", *extra])


def test_live_captures_both_leagues_once_per_slot(monkeypatch, tmp_path, capsys):
    state = {"remaining": 41000}
    _setup(monkeypatch, tmp_path, state)
    assert oddsapi_cli._cmd_live(_args(), NOW) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "spent 4, remaining 40996" in out and KEY not in out
    odds_calls = [p for path, p in state["seen"] if path.endswith("/odds")]
    assert len(odds_calls) == 2
    assert odds_calls[0]["bookmakers"].split(",") == list(oah.LIVE_BOOKMAKERS)
    assert odds_calls[0]["markets"] == "totals,spreads" and "regions" not in odds_calls[0]
    # next-day games must stay in: no commence-time filter on the request
    assert not any(k.startswith("commenceTime") for p in odds_calls for k in p)
    for sport in ("basketball_ncaab", "basketball_nba"):
        f = tmp_path / "oddsapi" / "live" / sport / "20261123T200000Z.json.gz"
        env = oah.read_cached(f)
        assert env["sport"] == sport and len(env["data"]) == 2
        req = datetime.fromisoformat(env["snapshot_ts"].replace("Z", "+00:00"))
        assert env["timestamp"] == env["snapshot_ts"] and req.tzinfo is not None
        assert olv.read_live_file(f)
    ledger = oah.read_ledger(tmp_path, oah.LIVE_SUBDIR)
    assert [e["remaining"] for e in ledger] == [40998, 40996]
    assert all(e["slot"] == "2026-11-23T20:00:00Z" and e["last"] == 2 for e in ledger)
    assert all(e["snapshot_ts"] == e["fetched_at"] for e in ledger)
    assert KEY not in (tmp_path / "oddsapi" / "live" / "ledger.jsonl").read_text()
    # same slot again: nothing fetched, nothing spent
    n = len(state["seen"])
    assert oddsapi_cli._cmd_live(_args(), NOW.replace(minute=29)) == 0
    assert "already saved" in capsys.readouterr().out and len(state["seen"]) == n


def test_live_reserve_skips(monkeypatch, tmp_path, capsys):
    state = {"remaining": 2003}
    _setup(monkeypatch, tmp_path, state)
    assert oddsapi_cli._cmd_live(_args("--league", "ncaab", "--league", "nba"), NOW) == 0
    out = capsys.readouterr().out
    assert "ncaab 2 events" in out and "nba skipped (reserve 2000, 2001 left)" in out
    assert not (tmp_path / "oddsapi" / "live" / "basketball_nba").exists()


def test_live_until_and_missing_key_and_rejected_key(monkeypatch, tmp_path, capsys):
    state = {"remaining": 41000}
    _setup(monkeypatch, tmp_path, state)
    late = datetime(2026, 12, 25, 18, 0, tzinfo=UTC)
    assert oddsapi_cli._cmd_live(_args(), late) == 0
    assert "past --until 2026-12-24" in capsys.readouterr().out and "seen" not in state
    # 2026-12-24 21:30 PT is still inside (it is 05:30Z on the 25th)
    assert oddsapi_cli._cmd_live(_args(), datetime(2026, 12, 25, 5, 30, tzinfo=UTC)) == 0
    assert "past --until" not in capsys.readouterr().out

    def no_key():
        raise oah.OddsApiError("no Odds API key: set ODDS_API_KEY or write it to /x (mode 600)")

    monkeypatch.setattr(oah, "read_key", no_key)
    assert oddsapi_cli._cmd_live(_args("--force"), NOW) == 0
    assert "skipped, no Odds API key" in capsys.readouterr().out

    monkeypatch.setattr(oah, "read_key", lambda: KEY)
    state["status"] = 401
    assert oddsapi_cli._cmd_live(_args("--force"), NOW) == 0
    out = capsys.readouterr().out
    assert "key rejected (HTTP 401" in out and KEY not in out and out.count("\n") == 1


def test_live_regions_instead_of_books(monkeypatch, tmp_path, capsys):
    state = {"remaining": 41000}
    _setup(monkeypatch, tmp_path, state)
    args = _args("--league", "nba", "--markets", "totals", "--regions", "us,eu")
    assert oddsapi_cli._cmd_live(args, NOW) == 0
    params = [p for path, p in state["seen"] if path.endswith("/odds")][0]
    assert params["regions"] == "us,eu" and "bookmakers" not in params


def test_live_data_dir_unavailable_is_one_line_exit_0(monkeypatch, capsys):
    def gone():
        raise config.DataDirUnavailable("drive not mounted")

    monkeypatch.setattr(config, "require_data_dir", gone)
    assert oddsapi_cli.main(["live"]) == 0
    assert capsys.readouterr().out.startswith("oddsapi live: skipped, data dir unavailable")


def test_live_until_default_and_parse():
    assert _args().until == date(2026, 12, 24) and _args().reserve == 2000
    assert _args("--until", "2026-12-20").until == date(2026, 12, 20)
