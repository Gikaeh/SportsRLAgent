"""Injury-aware model v1.1i and the light `deepsports pretip` job (docs/DECISIONS.md
2026-11-10): v1.1i gating, the split injury fetch/write, the pretip CLI, the API's display
order, and the calendar export that never shows v1.1i."""

import copy
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient
from test_injuries_context import PREGAME, TIP
from test_injuries_context import make_client as raw_client
from test_model import synth_store
from test_odds_prices import load
from test_players import add_players

from deepsports import cli, config, pipeline
from deepsports.analysis.record import injury_capture_teams, pretip_predictions_versions
from deepsports.api import app as app_module
from deepsports.api import warehouse
from deepsports.parse_espn import parse_scoreboard, parse_teams
from deepsports.sources.espn import EspnBasketball
from deepsports.store import Store

# ---------- helpers ----------


def _pre_game(gid: str, start: datetime, home: str, away: str) -> dict:
    return {
        "game_id": gid,
        "league": "nba",
        "season_year": 2026,
        "season_type": 2,
        "start_time_utc": start,
        "status": "STATUS_SCHEDULED",
        "state": "pre",
        "completed": False,
        "home_team_id": home,
        "away_team_id": away,
        "neutral_site": False,
    }


def _capture(con, gid: str, team: str, at: datetime, out: str | None = None) -> None:
    con.execute("INSERT INTO injury_captures VALUES (?, ?, ?, true, ?, 'nba')",
                [gid, team, at, int(out is not None)])  # fmt: skip
    if out:
        con.execute(
            "INSERT INTO injury_reports (game_id, team_id, athlete_id, status, captured_at, "
            "captured_before_tip, league) VALUES (?, ?, ?, 'Out', ?, true, 'nba')",
            [gid, team, out, at],
        )


def _summary(gid: str, start: datetime, home: str, away: str | None, state: str = "pre") -> dict:
    """The saved pregame summary (BOS home with 3 listed, MIL away with none) re-keyed to a
    synthetic game. `away=None` drops the away team's report (that team falls back)."""
    raw = copy.deepcopy(load(PREGAME))
    raw["header"]["id"] = gid
    comp = raw["header"]["competitions"][0]
    comp["date"] = start.strftime("%Y-%m-%dT%H:%MZ")
    comp["status"]["type"]["state"] = state
    inj = raw["injuries"]
    inj[0]["team"]["id"] = home
    inj[1]["team"]["id"] = away
    if away is None:
        raw["injuries"] = inj[:1]
    return raw


@pytest.fixture(scope="module")
def trained():
    """Synthetic league with player rows; four scheduled games in 2026."""
    s = synth_store(seasons=(2025, 2026), rounds=2)
    add_players(s, p_dnp=0.0)
    last = s.con.execute("SELECT max(start_time_utc) FROM games").fetchone()[0]
    s.upsert_games(
        [_pre_game(f"pre-{i}", last + timedelta(days=1, hours=i), str(i + 1), str(i + 2))
         for i in range(3)]
    )  # fmt: skip
    yield s, last
    s.close()


# ---------- model v1.1i gating ----------


def test_v11i_writes_only_games_with_a_capture_and_falls_back_per_team(trained):
    s, last = trained
    con = s.con
    con.execute("BEGIN")
    try:
        at = last + timedelta(hours=1)
        _capture(con, "pre-0", "1", at, out="1-p0")  # home captured, star Out; away falls back
        _capture(con, "pre-1", "2", at)
        _capture(con, "pre-1", "3", at)  # both captured, nobody out
        now = last + timedelta(hours=2)
        gated: dict = {}
        res = pretip_predictions_versions(con, ["v1.1", "v1.1i"], now=now, days=3, gated=gated)
        v11, v11i = ({r["game_id"]: r for r in res[v][0]} for v in ("v1.1", "v1.1i"))
        assert sorted(v11) == ["pre-0", "pre-1", "pre-2"]
        assert sorted(v11i) == ["pre-0", "pre-1"]  # pre-2 has no capture: no v1.1i row
        assert gated == {"v1.1": {}, "v1.1i": {"no_injury_capture": 1}}
        assert {r["model_version"] for r in v11i.values()} == {"v1.1i"}
        f11 = json.loads(v11["pre-0"]["features_json"])
        f11i = json.loads(v11i["pre-0"]["features_json"])
        # home star listed Out moves the home side; the uncaptured away side uses the box rule
        assert f11i["top6_out_last_diff"] == f11["top6_out_last_diff"] + 1
        assert v11i["pre-0"]["p_home_win"] < v11["pre-0"]["p_home_win"]
        # nobody out and nobody sat last game (p_dnp=0): identical to v1.1
        assert v11i["pre-1"]["features_json"] == v11["pre-1"]["features_json"]
        assert injury_capture_teams(con, ["pre-0", "pre-1", "pre-2"]) == {
            "pre-0": {"1"},
            "pre-1": {"2", "3"},
        }
    finally:
        con.execute("ROLLBACK")


def test_v11i_keeps_the_started_game_guard(trained):
    s, last = trained
    con = s.con
    con.execute("BEGIN")
    try:
        _capture(con, "pre-0", "1", last)
        start0 = con.execute("SELECT start_time_utc FROM games WHERE game_id = 'pre-0'").fetchone()
        rows, started = pretip_predictions_versions(
            con, ["v1.1i"], now=start0[0] + timedelta(minutes=1), days=3
        )["v1.1i"]
        assert rows == [] and started == 1
    finally:
        con.execute("ROLLBACK")


# ---------- split fetch / write ----------


def test_fetch_injury_snapshots_matches_collect(tmp_path):
    games, _ = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    now = TIP - timedelta(hours=3)
    out = {}
    for mode in ("collect", "split"):
        db = Store(":memory:")
        db.upsert_teams(parse_teams(load("espn_teams.json")))
        db.upsert_games([g for g in games if g["game_id"] == "401909924"])
        src = EspnBasketball(
            raw_client(tmp_path / mode, lambda r: httpx.Response(200, json=load(PREGAME)))
        )
        if mode == "collect":
            st = pipeline.collect_injury_snapshots(src, db, days_ahead=2, now=now)
        else:
            reports, captures, st = pipeline.fetch_injury_snapshots(src, ["401909924"], now)
            assert st.injuries == 0 and len(captures) == 2 and len(reports) == 3
            st.injuries = db.add_injuries(reports, captures)
        out[mode] = (
            st.injuries,
            st.errors,
            db.con.execute("SELECT * FROM injury_reports ORDER BY athlete_id").fetchall(),
            db.con.execute("SELECT * FROM injury_captures ORDER BY team_id").fetchall(),
        )
        db.close()
    assert out["collect"] == out["split"] and out["split"][0] == 3


def test_fetch_injury_snapshots_skip_started(tmp_path):
    started = load(PREGAME)
    started["header"]["competitions"][0]["status"]["type"]["state"] = "in"
    src = EspnBasketball(raw_client(tmp_path, lambda r: httpx.Response(200, json=started)))
    now = TIP - timedelta(minutes=5)  # an early tip: before the scheduled time, already live
    _, caps, st = pipeline.fetch_injury_snapshots(src, ["401909924"], now)
    assert len(caps) == 2 and st.skipped_started == 0  # default: same as before the split
    _, caps, st = pipeline.fetch_injury_snapshots(src, ["401909924"], now, skip_started=True)
    assert caps == [] and st.skipped_started == 1


# ---------- deepsports pretip ----------


@pytest.fixture
def pretip_wh(tmp_path, monkeypatch):
    """A file warehouse with a trained history and real-time scheduled games:
    in-1 (+30 min, both teams reported), in-2 (+60 min, away report missing), live (+40 min,
    but its fresh summary says it started), soon (+3 min, inside min-lead), late (+5 h)."""
    path = tmp_path / "w.duckdb"
    s = synth_store(seasons=(2025, 2026), rounds=2, context="view", path=str(path))
    add_players(s, p_dnp=0.0)
    base = datetime.now(UTC).replace(second=0, microsecond=0)
    plan = {
        "in-1": (30, "1", "2"),
        "in-2": (60, "3", "4"),
        "live": (40, "5", "6"),
        "soon": (3, "1", "3"),
        "late": (300, "2", "4"),
    }
    s.upsert_games(
        [_pre_game(g, base + timedelta(minutes=m), h, a) for g, (m, h, a) in plan.items()]
    )
    s.close()
    calls: list[str] = []

    def handler(request):
        gid = request.url.params["event"]
        calls.append(gid)
        m, h, a = plan[gid]
        start = base + timedelta(minutes=m)
        return httpx.Response(
            200,
            json=_summary(
                gid, start, h, None if gid == "in-2" else a, "in" if gid == "live" else "pre"
            ),
        )

    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli.config, "DB_PATH", path)
    monkeypatch.setattr(cli, "PoliteClient", lambda: raw_client(tmp_path / "raw", handler))
    return path, calls


def test_cli_pretip_captures_and_predicts_in_window_games_only(pretip_wh, capsys):
    path, calls = pretip_wh
    assert cli.main(["pretip"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert out[0].startswith(
        "pretip: games=3 captured=2 predicted=2 fallback_teams=1 skipped_started=1"
    )
    assert sorted(calls) == ["in-1", "in-2", "live"]  # soon/late are outside the window
    s = Store(path, read_only=True)
    preds = s.con.execute("SELECT game_id, model_version FROM predictions ORDER BY 1").fetchall()
    caps = s.con.execute("SELECT DISTINCT game_id FROM injury_captures ORDER BY 1").fetchall()
    notes = s.con.execute("SELECT command, notes FROM ingest_runs").fetchall()
    s.close()
    assert preds == [("in-1", "v1.1i"), ("in-2", "v1.1i")]
    assert caps == [("in-1",), ("in-2",)]  # the started game and out-of-window games untouched
    assert notes[0][0] == "pretip v1.1i" and "fallback_teams=1" in notes[0][1]


def test_cli_pretip_no_games_in_window_does_not_fetch(pretip_wh, capsys):
    path, calls = pretip_wh
    assert cli.main(["pretip", "--window-min", "20", "--min-lead", "10"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "no NBA games" in out[0]
    assert calls == []


def test_cli_pretip_skips_quietly_when_writer_lock_is_held(pretip_wh, capsys):
    path, calls = pretip_wh
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
        assert cli.main(["pretip"]) == 0
    finally:
        holder.kill()
        holder.wait()
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "skipped, warehouse busy" in out[0]
    assert calls == []


def test_cli_pretip_access_error_fails_loudly(pretip_wh, capsys, monkeypatch):
    def denied(*a, **k):
        raise duckdb.IOException('IO Error: Cannot open file "w.duckdb": Operation not permitted')

    monkeypatch.setattr(duckdb, "connect", denied)
    assert cli.main(["pretip"]) == 1
    out = capsys.readouterr().out
    assert "FAILED, cannot open the warehouse" in out and "busy" not in out


# ---------- display order (API) and calendar ----------


def _pred(gid: str, version: str, created: datetime, p: float) -> dict:
    return {
        "game_id": gid,
        "model": "v1",
        "model_version": version,
        "created_at": created,
        "p_home_win": p,
        "pred_home_margin": 0.0,
        "pred_total": 220.0,
        "features_json": {},
    }


def test_api_display_order_v11i_then_v11_then_latest(tmp_path, monkeypatch):
    path = tmp_path / "w.duckdb"
    store = Store(path)
    store.upsert_teams(parse_teams(load("espn_teams.json")))
    upcoming, _ = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    store.upsert_games(upcoming)
    ids = sorted(g["game_id"] for g in upcoming)[:3]
    t0 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    store.add_predictions([
        _pred(ids[0], "v1.1", t0 + timedelta(hours=2), 0.6),  # newer v1.1 ...
        _pred(ids[0], "v1.1i", t0 + timedelta(hours=1), 0.4),  # ... but v1.1i wins
        _pred(ids[0], "v1.0", t0 + timedelta(hours=3), 0.5),
        _pred(ids[1], "v1.0", t0 + timedelta(hours=3), 0.5),  # no v1.1i: v1.1
        _pred(ids[1], "v1.1", t0, 0.6),
        _pred(ids[2], "v1.0", t0, 0.5),  # neither: latest
        _pred(ids[2], "v1.1c", t0 + timedelta(hours=1), 0.55),
    ])  # fmt: skip
    store.close()
    with warehouse.connect(path) as con:
        got = warehouse.pre_tip_predictions(
            con, ids, prefer_versions=app_module.DISPLAY_MODEL_VERSIONS["nba"]
        )
        single = warehouse.pre_tip_predictions(con, ids, prefer_versions="v1.0")
        none = warehouse.pre_tip_predictions(con, ids)
    assert [got[i]["model_version"] for i in ids] == ["v1.1i", "v1.1", "v1.1c"]
    assert all(got[i]["created_at"] is not None for i in ids)
    assert [single[i]["model_version"] for i in ids] == ["v1.0", "v1.0", "v1.0"]
    assert [none[i]["model_version"] for i in ids] == ["v1.0", "v1.0", "v1.1c"]
    assert app_module.DISPLAY_MODEL_VERSIONS["ncaab"] == ("ncaab-v1",)

    # the record endpoint keeps defaulting to v1.1; v1.1i by query
    monkeypatch.setattr(app_module, "followed_teams", lambda league="nba": set())
    client = TestClient(app_module.create_app(db_path=path, web_dist=tmp_path / "nodist"))
    assert client.get("/api/predictions/record").json()["model_version"] == "v1.1"
    rec = client.get("/api/predictions/record", params={"model_version": "v1.1i"}).json()
    assert rec["model_version"] == "v1.1i"


def test_calendar_export_never_shows_v11i(tmp_path, monkeypatch, capsys):
    assert "v1.1i" in config.CALENDAR_EXCLUDED_VERSIONS
    assert set(config.HIDDEN_MODEL_VERSIONS) <= set(config.CALENDAR_EXCLUDED_VERSIONS)
    path = tmp_path / "w.duckdb"
    s = synth_store(seasons=(2026,), rounds=1, context="view", path=str(path))
    now = datetime.now(UTC)
    s.upsert_games([_pre_game("cal-1", now + timedelta(hours=5), "1", "2"),
                    _pre_game("cal-2", now + timedelta(hours=6), "3", "4")])  # fmt: skip
    s.add_predictions([
        _pred("cal-1", "v1.1", now - timedelta(hours=2), 0.6),
        _pred("cal-1", "v1.1i", now - timedelta(minutes=5), 0.3),  # written last
        _pred("cal-2", "v1.1i", now - timedelta(minutes=5), 0.3),  # only v1.1i: none shown
    ])  # fmt: skip
    s.close()
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli, "Store", lambda read_only=False: Store(path, read_only))
    assert cli.main(["upcoming", "--all", "--json", "--days", "2"]) == 0
    games = {g["game_id"]: g for g in json.loads(capsys.readouterr().out)}
    assert games["cal-1"]["prediction"]["model_version"] == "v1.1"
    assert games["cal-2"]["prediction"] is None
