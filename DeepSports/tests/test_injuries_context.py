"""Injury snapshots, schedule context (team_game_context), and the predictions table."""

import copy
import gzip
import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from deepsports import pipeline
from deepsports.http import PoliteClient
from deepsports.parse_espn import parse_injuries, parse_scoreboard, parse_summary, parse_teams
from deepsports.sources.espn_nba import EspnNba
from deepsports.store import Store
from deepsports.venues import VENUE_CITIES

FIX = Path(__file__).parent / "fixtures"
PREGAME = "espn_summary_pregame_injuries.json"  # MIL @ BOS 2026-11-05, fetched 2026-11-03
OLD = "espn_summary_2021_injuries_fetched_later.json"  # BOS @ NY 2021-10-20, fetched 2026-11-04
TIP = datetime(2026, 11, 5, 0, 30, tzinfo=UTC)


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


@pytest.fixture
def db():
    store = Store(":memory:")
    store.upsert_teams(parse_teams(load("espn_teams.json")))
    yield store
    store.close()


def make_client(tmp_path, handler):
    return PoliteClient(
        raw_dir=tmp_path,
        min_interval=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )


# ---------- parser ----------


def test_parse_injuries_pregame_snapshot():
    captured = TIP - timedelta(hours=27)
    reports, captures = parse_injuries(load(PREGAME), captured)
    assert {(c["team_id"], c["n_listed"]) for c in captures} == {("2", 3), ("15", 0)}
    assert all(r["captured_before_tip"] for r in (*reports, *captures))
    carter = next(r for r in reports if r["athlete_name"] == "Devin Carter")
    assert carter["team_id"] == "2" and carter["athlete_id"] == "4433188"
    assert (carter["status"], carter["injury_type"]) == ("Out", "Illness")
    assert carter["return_date"].isoformat() == "2026-11-08"
    assert carter["reported_at"] == datetime(2026, 10, 18, 14, 49, tzinfo=UTC)
    tatum = next(r for r in reports if r["athlete_name"] == "Jayson Tatum")
    assert (tatum["status"], tatum["injury_type"]) == ("Day-To-Day", "Rest")


def test_parse_injuries_after_tip_is_flagged():
    reports, captures = parse_injuries(load(PREGAME), TIP + timedelta(minutes=1))
    assert not any(r["captured_before_tip"] for r in (*reports, *captures))
    # an explicit start time overrides the header's
    _, captures = parse_injuries(load(PREGAME), TIP, start_time=TIP + timedelta(hours=1))
    assert captures[0]["captured_before_tip"]


def test_completed_summary_injuries_are_fetch_time_not_game_time():
    """The evidence behind captured_before_tip: a 2021 game fetched in 2026 lists BOS's
    November 2026 injury report, including a player who was in college in 2021, and players
    marked injured who actually played in that game."""
    raw = load(OLD)
    start = datetime(2021, 10, 20, 23, 30, tzinfo=UTC)
    reports, _ = parse_injuries(raw, datetime(2026, 11, 4, 1, 7, tzinfo=UTC))
    assert reports and all(r["reported_at"] > start + timedelta(days=365) for r in reports)
    assert {r["athlete_name"] for r in reports} == {r["athlete_name"] for r in parse_injuries(
        load(PREGAME), TIP)[0]}  # fmt: skip  # same list as the 2026 upcoming game
    _, players, _ = parse_summary(raw)
    played = {p["athlete_id"] for p in players if not p["did_not_play"]}
    assert "4065648" in played  # Jayson Tatum: listed Day-To-Day, played in the game


# ---------- store ----------


def test_add_injuries_is_idempotent_and_replaces_stale_rows(db):
    captured = TIP - timedelta(hours=5)
    reports, captures = parse_injuries(load(PREGAME), captured)
    db.add_injuries(reports, captures)
    db.add_injuries(reports, captures)
    assert db.counts()["injury_reports"] == 3
    # same capture re-parsed with one player gone: that player's row disappears
    db.add_injuries([r for r in reports if r["athlete_name"] != "Devin Carter"], captures)
    assert db.counts()["injury_reports"] == 2
    assert db.con.execute("SELECT count(*) FROM injury_captures").fetchone()[0] == 2


def test_collect_injury_snapshots_stores_pretip_snapshots(tmp_path, db):
    games, _ = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    db.upsert_games([g for g in games if g["game_id"] == "401909924"])
    calls = []

    def handler(request):
        calls.append(request.url.params["event"])
        return httpx.Response(200, json=load(PREGAME))

    src = EspnNba(make_client(tmp_path, handler))
    t1, t2 = TIP - timedelta(hours=30), TIP - timedelta(hours=2)
    s1 = pipeline.collect_injury_snapshots(src, db, days_ahead=2, now=t1)
    s2 = pipeline.collect_injury_snapshots(src, db, days_ahead=2, now=t2)
    assert calls == ["401909924", "401909924"] and s1.injuries == s2.injuries == 3
    assert not s1.errors and not s2.errors
    # each snapshot is kept in the raw zone under its own timestamp
    snaps = sorted((tmp_path / "espn/nba/summary_pregame/401909924").glob("*.json.gz"))
    assert [p.name for p in snaps] == ["20261103T183000Z.json.gz", "20261104T223000Z.json.gz"]
    assert (
        db.con.execute("SELECT count(DISTINCT captured_at) FROM injury_reports").fetchone()[0] == 2
    )
    latest = db.con.execute("SELECT DISTINCT captured_at FROM pregame_injuries").fetchall()
    assert latest == [(t2,)]
    # outside the window: no fetch
    pipeline.collect_injury_snapshots(src, db, days_ahead=1, now=TIP - timedelta(days=3))
    assert len(calls) == 2


def test_collect_injury_snapshots_skips_game_that_tipped(tmp_path, db):
    games, _ = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    db.upsert_games([g for g in games if g["game_id"] == "401909924"])
    moved = load(PREGAME)
    moved["header"]["competitions"][0]["date"] = "2026-11-03T00:00Z"  # moved earlier
    src = EspnNba(make_client(tmp_path, lambda r: httpx.Response(200, json=moved)))
    stats = pipeline.collect_injury_snapshots(src, db, now=TIP - timedelta(hours=3))
    assert stats.injuries == 0 and db.counts()["injury_reports"] == 0


def _write_gz(path: Path, data: dict, mtime: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    if mtime:
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))


def test_backfill_injuries_from_raw(tmp_path, db):
    summary = tmp_path / "espn/nba/summary"
    fetched = datetime(2026, 11, 4, 1, 7, 41, tzinfo=UTC)
    _write_gz(summary / "401358775.json.gz", load(OLD), fetched)
    (summary / "._401358775.json.gz").write_bytes(b"\x00\x05AppleDouble")
    _write_gz(summary / "401909924.json.gz", load(PREGAME))  # not completed: skipped
    snap_at = datetime(2026, 11, 4, 22, 30, tzinfo=UTC)
    _write_gz(tmp_path / "espn/nba/summary_pregame/401909924/20261104T223000Z.json.gz",
              load(PREGAME))  # fmt: skip
    stats = pipeline.backfill_injuries_from_raw(db, tmp_path)
    assert not stats.errors and stats.injuries == 6
    rows = db.con.execute(
        "SELECT game_id, captured_at, bool_and(captured_before_tip), count(*) "
        "FROM injury_reports GROUP BY ALL ORDER BY 1"
    ).fetchall()
    assert rows == [("401358775", fetched, False, 3), ("401909924", snap_at, True, 3)]
    pipeline.backfill_injuries_from_raw(db, tmp_path)  # idempotent
    assert db.counts()["injury_reports"] == 6


# ---------- schedule context ----------

A, B, C = "1", "2", "3"  # ATL, BOS, BKN in the teams fixture


def _game(gid, day, home, away, city, season_type=2, state="post", status="STATUS_FINAL",
          season=2027):  # fmt: skip
    return {
        "game_id": gid,
        "league": "nba",
        "season_year": season,
        "season_type": season_type,
        # 23:30Z is 18:30/19:30 US/Eastern on the same date
        "start_time_utc": datetime(2026, 11 if season == 2027 else 4, day, 23, 30, tzinfo=UTC),
        "status": status,
        "state": state,
        "completed": state == "post" and status == "STATUS_FINAL",
        "home_team_id": home,
        "away_team_id": away,
        "home_score": None,
        "away_score": None,
        "venue": None,
        "venue_city": city,
        "neutral_site": False,
        "attendance": None,
        "broadcasts": None,
    }


def _km(c1: str, c2: str) -> float:
    (la1, lo1), (la2, lo2) = VENUE_CITIES[c1], VENUE_CITIES[c2]
    p1, p2, dp, dl = map(math.radians, (la1, la2, la2 - la1, lo2 - lo1))
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


SCHEDULE = [
    _game("p0", 10, A, B, "Boston", season=2026),  # last season: must not carry over
    _game("g1", 1, B, A, "Boston"),
    _game("g2", 2, C, A, "New York"),
    _game("pre", 3, A, C, "Los Angeles", season_type=1),  # preseason: ignored
    _game("g3", 5, A, B, "Los Angeles"),
    _game("ppd", 12, A, C, "Los Angeles", status="STATUS_POSTPONED"),  # ignored
    _game("g4", 20, B, A, "Boston"),
    _game("g5", 21, C, A, "Atlantis"),  # unknown city: no travel
    _game("g6", 23, A, B, "Los Angeles", state="pre", status="STATUS_SCHEDULED"),
]


def _context(db, team=A):
    cur = db.con.execute(
        "SELECT * FROM team_game_context WHERE team_id = ? ORDER BY start_time_utc", [team]
    )
    cols = [d[0] for d in cur.description]
    return {r[0]: dict(zip(cols, r, strict=True)) for r in cur.fetchall()}


def test_team_game_context_synthetic_schedule(db):
    db.upsert_games(SCHEDULE)
    ctx = _context(db)
    assert list(ctx) == ["p0", "g1", "g2", "g3", "g4", "g5", "g6"]
    want = {  # rest, b2b, games_last_7, road_trip, home
        "g1": (None, False, 0, 1, False),
        "g2": (1, True, 1, 2, False),
        "g3": (3, False, 2, 0, True),
        "g4": (7, False, 0, 1, False),  # 15 days, capped at 7
        "g5": (1, True, 1, 2, False),
        "g6": (2, False, 2, 0, True),
    }
    for gid, (rest, b2b, last7, trip, home) in want.items():
        r = ctx[gid]
        got = (r["rest_days"], r["back_to_back"], r["games_last_7_days"],
               r["road_trip_length"], r["is_home"])  # fmt: skip
        assert got == (rest, b2b, last7, trip, home), gid
    assert ctx["g1"]["opponent_id"] == B and ctx["g1"]["travel_km"] is None
    assert ctx["g2"]["travel_km"] == pytest.approx(_km("Boston", "New York"), abs=0.1)
    assert ctx["g3"]["travel_km"] == pytest.approx(_km("New York", "Los Angeles"), abs=0.1)
    assert ctx["g4"]["travel_km"] == pytest.approx(_km("Los Angeles", "Boston"), abs=0.1)
    assert ctx["g5"]["travel_km"] is None and ctx["g6"]["travel_km"] is None
    # the opponent's side of g1: home, first game of its season
    b = _context(db, B)["g1"]
    assert (b["is_home"], b["rest_days"], b["road_trip_length"], b["travel_km"]) == (
        True, None, 0, None)  # fmt: skip


def test_team_game_context_uses_only_earlier_games(db):
    """Adding later games must not change any earlier row (no look-ahead)."""
    db.upsert_games(SCHEDULE[:5])
    before = _context(db)
    db.upsert_games(SCHEDULE[5:])
    after = _context(db)
    assert all(after[g] == before[g] for g in before)


def test_team_game_context_skips_unknown_teams(db):
    db.upsert_games([_game("asg", 15, "999", "998", "San Francisco")])
    assert db.con.execute("SELECT count(*) FROM team_game_context").fetchone()[0] == 0


# ---------- predictions ----------


def _pred(gid, version, created, p):
    return {
        "game_id": gid,
        "model": "elo",
        "model_version": version,
        "created_at": created,
        "p_home_win": p,
        "pred_home_margin": 3.5,
        "pred_total": 221.0,
        "features_json": {"elo_diff": 42.0},
    }


def test_predictions_upsert_and_latest(db):
    t = datetime(2026, 11, 3, tzinfo=UTC)
    db.add_predictions([_pred("g1", "v1", t, 0.6), _pred("g2", "v1", t, 0.4)])
    db.add_predictions([_pred("g1", "v1", t, 0.65)])  # same key: replaced
    assert db.counts()["predictions"] == 2
    db.add_predictions([_pred("g1", "v2", t + timedelta(hours=1), 0.7)])
    latest = db.latest_predictions(["g1", "g2", "nope"])
    assert [(r["game_id"], r["model_version"], r["p_home_win"]) for r in latest] == [
        ("g1", "v2", 0.7),
        ("g2", "v1", 0.4),
    ]
    assert json.loads(latest[0]["features_json"]) == {"elo_diff": 42.0}
    hidden = db.latest_predictions(["g1", "g2"], exclude_versions=["v2"])
    assert [(r["game_id"], r["model_version"]) for r in hidden] == [("g1", "v1"), ("g2", "v1")]
    assert db.latest_predictions([]) == []
    row = _pred("g3", "v1", None, 0.5)
    row["features_json"] = '{"x": 1}'
    db.add_predictions([row])
    assert db.latest_predictions(["g3"])[0]["created_at"] is not None
    with pytest.raises(ValueError, match="unknown"):
        db.add_predictions([{**row, "home_win_prob": 0.5}])


# ---------- compatibility with a warehouse created by older code ----------


def test_read_only_commands_work_before_migration(tmp_path):
    """`status`/`check` open read-only and never apply SCHEMA, so the new tables can be
    missing from the live warehouse until the next writer runs."""
    from deepsports.quality import run_checks

    path = tmp_path / "old.duckdb"
    old = Store(path)
    for view in ("team_game_context", "pregame_injuries"):
        old.con.execute(f"DROP VIEW {view}")
    for table in ("injury_reports", "injury_captures", "predictions", "venue_cities"):
        old.con.execute(f"DROP TABLE {table}")
    old.close()
    ro = Store(path, read_only=True)
    assert "injury_reports" not in ro.counts()
    names = [c.name for c in run_checks(ro)]
    assert "injury coverage" in names
    ro.close()
    Store(path).close()  # the next writer migrates additively
    ro = Store(path, read_only=True)
    assert ro.counts()["predictions"] == 0
    ro.close()


def test_injury_coverage_counts_gaps_only_after_snapshots_began(db):
    from deepsports.quality import injury_coverage

    games, _ = parse_scoreboard(load("espn_scoreboard_final.json"))
    db.upsert_games(games)  # 15 final games on 2026-11-02/03
    (check,) = injury_coverage(db)
    assert check.failures == 0 and check.detail.startswith("0/15")
    raw = copy.deepcopy(load(PREGAME))
    raw["header"]["id"] = games[0]["game_id"]
    reports, captures = parse_injuries(raw, datetime(2026, 11, 1, tzinfo=UTC), games[0][
        "start_time_utc"])  # fmt: skip
    db.add_injuries(reports, captures)
    (check,) = injury_coverage(db)
    assert check.detail.startswith("1/15") and check.failures == 14 and not check.hard
