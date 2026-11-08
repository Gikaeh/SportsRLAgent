"""League-scoped keys (migration from the legacy schema), college basketball parsing and
collection, the bulk writer, and the per-league CLI/config."""

import json
import math
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import httpx
import pytest
from legacy_schema_v1 import LEGACY_SCHEMA_V1

from deepsports import cli, pipeline
from deepsports.api import warehouse
from deepsports.http import PoliteClient
from deepsports.parse_espn import (
    choose_book,
    parse_core_odds,
    parse_injuries,
    parse_scoreboard,
    parse_scoreboard_teams,
    parse_summary,
    parse_teams,
)
from deepsports.quality import run_checks
from deepsports.sources.espn import EspnBasketball, get_league
from deepsports.sources.espn_nba import EspnNba
from deepsports.store import LEAGUE_SCOPED, Store, expected_shapes
from deepsports.venues import VENUE_CITIES

FIX = Path(__file__).parent / "fixtures"
NEV = "2440"
NBA_GAMES = 29  # 15 final + 14 upcoming in the NBA scoreboard fixtures
NCAA_FINAL = "espn_ncaab_scoreboard_20260207_final.json"  # full Saturday slate, all final
NCAA_LIVE = "espn_ncaab_scoreboard_20261103_live.json"  # opening week: pre/in/final, odds
NCAA_UPCOMING = "espn_ncaab_scoreboard_20261108_upcoming.json"  # SMC vs NEV at Stateline
NCAA_SUMMARY = "espn_ncaab_summary_final_nev_unlv.json"  # UNLV @ NEV 2026-01-31, 89-76
NCAA_PREGAME = "espn_ncaab_summary_pregame_nev_smc.json"  # 401911453, fetched pre-tip
NCAA_CORE_ODDS = "espn_ncaab_core_odds_401829317.json"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def make_client(tmp_path, handler):
    return PoliteClient(
        raw_dir=tmp_path,
        min_interval=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )


# ---------- migration from the legacy (team_id-keyed) schema ----------


def _legacy_insert(con, table: str, rows: list[dict]) -> None:
    cols = [c[0] for c in con.execute(f"DESCRIBE {table}").fetchall()]
    now = datetime.now(UTC)
    rows = [{**r, "updated_at": now} for r in rows]
    con.executemany(
        f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' for _ in cols)})",
        [[r.get(c) for c in cols] for r in rows],
    )


def build_legacy_db(path: Path) -> None:
    """A warehouse as the previous code wrote it, filled from real NBA fixtures."""
    con = duckdb.connect(str(path))
    con.execute(LEGACY_SCHEMA_V1)
    _legacy_insert(con, "teams", parse_teams(load("espn_teams.json")))
    final, _ = parse_scoreboard(load("espn_scoreboard_final.json"))
    upcoming, pre_odds = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    _legacy_insert(con, "games", final + upcoming)
    teams, players, closing = parse_summary(load("espn_summary_final.json"))
    _legacy_insert(con, "team_game_stats", teams)
    _legacy_insert(con, "player_game_stats", players)
    _legacy_insert(con, "odds_snapshots", pre_odds + closing)
    tip = datetime(2026, 11, 5, 0, 30, tzinfo=UTC)
    reports, captures = parse_injuries(
        load("espn_summary_pregame_injuries.json"), tip - timedelta(1)
    )
    _legacy_insert(con, "injury_captures", captures)
    _legacy_insert(con, "injury_reports", reports)
    con.execute(
        "INSERT INTO predictions VALUES ('401909924', 'elo', 'v1', now(), 0.6, 3.0, 220.0, '{}')"
    )
    con.execute("INSERT INTO ingest_runs (started_at, command) VALUES (now(), 'update')")
    con.executemany(
        "INSERT INTO venue_cities VALUES (?, ?, ?)",
        [[c, lat, lon] for c, (lat, lon) in VENUE_CITIES.items()],
    )
    con.close()


ALL_TABLES = (
    "teams",
    "games",
    "team_game_stats",
    "player_game_stats",
    "odds_snapshots",
    "injury_captures",
    "injury_reports",
    "predictions",
    "ingest_runs",
    "venue_cities",
)
CONTEXT_COLS = (
    "game_id, team_id, opponent_id, is_home, start_time_utc, season_year, season_type, "
    "rest_days, back_to_back, games_last_7_days, road_trip_length, travel_km"
)


def snapshot(con) -> dict:
    out = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ALL_TABLES}
    out["context"] = con.execute(
        f"SELECT {CONTEXT_COLS} FROM team_game_context ORDER BY game_id, team_id"
    ).fetchall()
    out["pregame_injuries"] = con.execute(
        "SELECT game_id, athlete_id FROM pregame_injuries ORDER BY 1, 2"
    ).fetchall()
    out["points"] = con.execute(
        "SELECT game_id, team_id, sum(pts) FROM player_game_stats GROUP BY ALL ORDER BY 1, 2"
    ).fetchall()
    return out


@pytest.fixture
def legacy_path(tmp_path):
    path = tmp_path / "legacy.duckdb"
    build_legacy_db(path)
    return path


# The v1 warehouse also predates the odds price columns (2026-11-06).
MIGRATED = (*LEAGUE_SCOPED, "odds_snapshots")


def test_read_only_commands_work_on_unmigrated_warehouse(legacy_path):
    """`status`, `check` and `upcoming` (read-only, new code) must work on the live warehouse
    before any writer has migrated it."""
    ro = Store(legacy_path, read_only=True)
    assert sorted(ro.stale_tables()) == sorted(MIGRATED)
    assert ro.counts()["games"] == NBA_GAMES
    checks = {c.name: c for c in run_checks(ro)}
    assert checks["player points sum to team score"].failures == 0
    rows = ro.upcoming_games(datetime(2026, 11, 4, tzinfo=UTC), datetime(2026, 11, 6, tzinfo=UTC))
    assert rows and all(r["league"] == "nba" for r in rows)
    ro.close()


def test_migration_keeps_every_row_and_is_idempotent(legacy_path):
    con = duckdb.connect(str(legacy_path))
    before = snapshot(con)
    con.close()

    db = Store(legacy_path)  # the first writer migrates
    assert set(db.migration_report) == set(MIGRATED)
    assert all(b == a for b, a in db.migration_report.values())
    assert db.migration_report["player_game_stats"][0] == before["player_game_stats"] > 0
    after = snapshot(db.con)
    assert after == before
    assert db.stale_tables() == []
    shapes = expected_shapes()
    assert shapes["teams"][1] == ("league", "team_id")
    for t in ("team_game_stats", "player_game_stats", "injury_captures", "injury_reports"):
        assert db.con.execute(f"SELECT DISTINCT league FROM {t}").fetchall() == [("nba",)]
    assert db.con.execute("SELECT bool_and(listed) FROM teams").fetchone()[0]
    # second run: a no-op
    assert db.migrate() == {}
    db.close()
    db = Store(legacy_path)
    assert db.migration_report == {}
    assert snapshot(db.con) == before
    # writes still work after the rebuild (primary keys enforced)
    teams, players, _ = parse_summary(load("espn_summary_final.json"), league="nba")
    db.upsert_team_stats(teams)
    db.upsert_player_stats(players)
    assert snapshot(db.con)["player_game_stats"] == before["player_game_stats"]
    db.close()


def test_api_read_paths_work_after_migration(legacy_path):
    Store(legacy_path).close()
    with warehouse.connect(legacy_path) as con:
        table = warehouse.standings(con, {"OKC"})
        teams = [t["abbr"] for c in table["conferences"] for t in c["teams"]]
        assert "OKC" in teams and "CLE" in teams
        page = warehouse.team_page(con, "OKC", {"OKC"})
        assert page["team"]["id"] == "25" and page["recent"]


def test_colliding_team_ids_stay_separate(legacy_path):
    db = Store(legacy_path)
    db.upsert_teams(parse_teams(load("espn_ncaab_teams.json"), "ncaab"))
    names = dict(
        db.con.execute("SELECT league, display_name FROM teams WHERE team_id = '5'").fetchall()
    )
    assert names == {"nba": "Cleveland Cavaliers", "ncaab": "UAB Blazers"}
    games, _ = parse_scoreboard(load(NCAA_FINAL), league="ncaab")
    db.upsert_games(games)
    # NBA context rows are unchanged by college games involving team ids 5/25
    nba_ctx = db.con.execute(
        "SELECT count(*) FROM team_game_context WHERE league = 'nba'"
    ).fetchone()[0]
    assert nba_ctx == 2 * NBA_GAMES
    d1 = {t["team_id"] for t in parse_teams(load("espn_ncaab_teams.json"), "ncaab")}
    both_d1 = [g for g in games if {g["home_team_id"], g["away_team_id"]} <= d1]
    assert len(both_d1) == 152  # 3 games against non-D1 schools (not in `teams` here)
    assert db.con.execute(
        "SELECT count(*) FROM team_game_context WHERE league = 'ncaab'"
    ).fetchone()[0] == 2 * len(both_d1)
    up = db.upcoming_games(datetime(2026, 11, 4, tzinfo=UTC), datetime(2026, 11, 6, tzinfo=UTC))
    assert {r["league"] for r in up} == {"nba"}
    assert db.counts()["teams"] == 30 + 362
    db.close()


# ---------- college parsing ----------


def test_event_ids_are_unique_across_leagues():
    nba = {e["id"] for f in ("espn_scoreboard_final.json", "espn_scoreboard_upcoming.json")
           for e in load(f)["events"]}  # fmt: skip
    ncaa = {e["id"] for f in (NCAA_FINAL, NCAA_LIVE, NCAA_UPCOMING) for e in load(f)["events"]}
    assert nba and ncaa and not nba & ncaa


def test_parse_ncaab_teams():
    rows = parse_teams(load("espn_ncaab_teams.json"), "ncaab")
    assert len(rows) == 362  # all of D1
    nev = next(r for r in rows if r["team_id"] == NEV)
    assert (nev["abbreviation"], nev["display_name"]) == ("NEV", "Nevada Wolf Pack")
    assert nev["league"] == "ncaab" and nev["listed"]
    assert len({r["abbreviation"] for r in rows}) == 362  # unique within the league


def test_parse_ncaab_scoreboard_final_day():
    games, odds = parse_scoreboard(load(NCAA_FINAL), league="ncaab")
    assert len(games) == 155 and odds == []
    assert all(g["league"] == "ncaab" and g["completed"] for g in games)
    assert all(g["home_score"] is not None and g["season_year"] == 2026 for g in games)


def test_parse_ncaab_scoreboard_live_day_and_non_d1_opponents():
    raw = load(NCAA_LIVE)
    games, odds = parse_scoreboard(raw, league="ncaab")
    assert {g["state"] for g in games} == {"pre", "in", "post"}
    assert odds and all(o["provider"] == "Draft Kings" for o in odds)
    unlv = next(o for o in odds if o["details"].startswith("UNLV"))
    assert unlv["spread_home"] == -20.5 and unlv["home_moneyline"] == -5000
    d1 = {r["team_id"] for r in parse_teams(load("espn_ncaab_teams.json"), "ncaab")}
    seen = parse_scoreboard_teams(raw, "ncaab")
    non_d1 = [t for t in seen if t["team_id"] not in d1]
    assert len(non_d1) == 10 and not any(t["listed"] for t in seen)
    assert "Lincoln (MO) Blue Tigers" in {t["display_name"] for t in non_d1}


def test_parse_ncaab_neutral_site():
    games, _ = parse_scoreboard(load(NCAA_UPCOMING), league="ncaab")
    g = next(g for g in games if g["game_id"] == "401911453")
    assert g["neutral_site"] and g["venue_city"] == "Stateline"
    assert g["home_team_id"] == NEV and g["state"] == "pre"


def test_parse_ncaab_summary_two_halves_box_score():
    raw = load(NCAA_SUMMARY)
    comps = raw["header"]["competitions"][0]["competitors"]
    assert all(len(c["linescores"]) == 2 for c in comps)  # halves, not quarters
    teams, players, odds = parse_summary(raw, league="ncaab")
    assert len(teams) == 2 and all(r["league"] == "ncaab" for r in teams + players)
    for t in teams:
        assert t["fga"] >= t["fgm"] > 0 and t["reb"] == t["oreb"] + t["dreb"]
    pts = {}
    for p in players:
        pts[p["team_id"]] = pts.get(p["team_id"], 0) + (p["pts"] or 0)
    assert pts == {NEV: 89, "2439": 76}
    assert odds[0]["provider"] == "Draft Kings" and odds[0]["details"] == "NEV -7.5"
    assert odds[0]["spread_home"] == -7.5 and odds[0]["home_moneyline"] == -375
    # without a league the rows match the API's live box score shape (no league key)
    t2, p2, _ = parse_summary(raw)
    assert "league" not in t2[0] and "league" not in p2[0]


def test_ncaab_summaries_have_no_injury_report():
    for name in (NCAA_PREGAME, NCAA_SUMMARY):
        raw = load(name)
        assert "injuries" not in raw
        assert parse_injuries(raw, datetime(2026, 11, 3, tzinfo=UTC), league="ncaab") == ([], [])


def test_ncaab_core_odds_draft_kings():
    raw = load(NCAA_CORE_ODDS)
    assert choose_book(raw["items"])["provider"]["name"] == "Draft Kings"
    start = datetime(2026, 1, 31, 3, tzinfo=UTC)
    by = {r["source"]: r for r in parse_core_odds(raw, "401829317", start)}
    assert by["opening"]["spread_home"] == -7.5 and by["opening"]["over_under"] == 148.5
    assert by["closing"]["spread_home"] == -7.5 and by["closing"]["over_under"] == 147.5


# ---------- source + pipeline ----------


def fixture_router(calls: list):
    def handler(request: httpx.Request):
        calls.append(request)
        path = request.url.path
        if path.endswith("/teams"):
            return httpx.Response(200, json=load("espn_ncaab_teams.json"))
        if path.endswith("/scoreboard"):
            if request.url.params["dates"] == "20261108":
                return httpx.Response(200, json=load(NCAA_UPCOMING))
            return httpx.Response(200, json={"events": []})
        if path.endswith("/summary"):
            return httpx.Response(200, json=load(NCAA_PREGAME))
        return httpx.Response(404)

    return handler


def test_league_lookup_and_nba_alias():
    assert get_league("mens-college-basketball").code == "ncaab"
    with pytest.raises(ValueError):
        get_league("nfl")
    src = EspnNba(PoliteClient(raw_dir=Path("/nonexistent")))
    assert isinstance(src, EspnBasketball) and src.league == "nba"
    assert src.base.endswith("/basketball/nba")


def test_ncaab_requests_and_cache_keys(tmp_path):
    calls = []
    src = EspnBasketball(make_client(tmp_path, fixture_router(calls)), "ncaab")
    src.teams()
    src.scoreboard(date(2026, 11, 8))
    assert calls[0].url.params["limit"] == "1000"
    sb = calls[1].url
    assert "/mens-college-basketball/scoreboard" in sb.path
    assert (sb.params["groups"], sb.params["limit"], sb.params["dates"]) == (
        "50",
        "1000",
        "20261108",
    )
    assert (tmp_path / "espn/ncaab/teams.json.gz").exists()
    assert (tmp_path / "espn/ncaab/scoreboard/20261108.json.gz").exists()


def test_ncaab_schedule_upcoming_and_followed_injury_snapshots(tmp_path):
    calls = []
    src = EspnBasketball(make_client(tmp_path, fixture_router(calls)), "ncaab")
    db = Store(":memory:")
    db.upsert_teams(parse_teams(load("espn_teams.json")))  # NBA teams too: ids collide
    pipeline.collect_teams(src, db)
    stats = pipeline.collect_schedule(src, db, date(2026, 11, 8), date(2026, 11, 8))
    assert stats.games == 35 and not stats.errors
    assert db.team_count("ncaab") >= 362 and db.team_count("nba") == 30
    # every college game is displayable, including ones against non-D1 schools
    start = datetime(2026, 11, 8, 5, tzinfo=UTC)
    rows = db.upcoming_games(start, start + timedelta(days=1), league="ncaab")
    assert len(rows) == 35
    nev = db.upcoming_games(start, start + timedelta(days=1), ["NEV"], league="ncaab")
    assert [(r["away_abbr"], r["home_abbr"]) for r in nev] == [("SMC", "NEV")]
    assert db.upcoming_games(start, start + timedelta(days=1), ["NEV"]) == []  # nba default
    # followed-only injury snapshots: one summary request, for Nevada's game
    n = len(calls)
    snap = pipeline.collect_injury_snapshots(src, db, now=start, teams=["NEV"])
    assert len(calls) == n + 1 and calls[-1].url.params["event"] == "401911453"
    assert snap.injuries == 0 and not snap.errors  # ESPN lists no college injuries
    assert list((tmp_path / "espn/ncaab/summary_pregame/401911453").glob("*.json.gz"))
    db.close()


def test_upcoming_calendar_keys_and_titles(monkeypatch):
    db = Store(":memory:")
    db.upsert_teams(parse_teams(load("espn_ncaab_teams.json"), "ncaab"))
    raw = load(NCAA_UPCOMING)
    db.add_discovered_teams(parse_scoreboard_teams(raw, "ncaab"))
    games, _ = parse_scoreboard(raw, league="ncaab")
    db.upsert_games(games)
    fake_now = datetime(2026, 11, 8, 5, tzinfo=UTC)

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    monkeypatch.setattr(pipeline, "datetime", FakeDatetime)
    rows = pipeline.upcoming(db, 2, ["NEV"], "ncaab")
    assert len(rows) == 1
    r = rows[0]
    assert r["league"] == "ncaab" and r["calendar_key"] == "deepsports:ncaab:401911453"
    assert r["title"] == "🏀🎓 SMC vs NEV"  # neutral site: "vs"
    db.close()


def test_update_wires_injury_snapshots(monkeypatch, tmp_path):
    calls = []
    seen = {}

    def spy(src, db, days_ahead=2, now=None, teams=None):
        seen.update(league=src.league, days_ahead=days_ahead, teams=teams)
        return pipeline.RunStats(injuries=3)

    monkeypatch.setattr(pipeline, "collect_injury_snapshots", spy)
    monkeypatch.setattr(pipeline, "league_today", lambda: date(2026, 11, 8))
    src = EspnBasketball(make_client(tmp_path, fixture_router(calls)), "ncaab")
    db = Store(":memory:")
    stats = pipeline.update(src, db, 0, 0, injury_teams=["NEV"])
    assert seen == {"league": "ncaab", "days_ahead": 2, "teams": ["NEV"]}
    assert stats.injuries == 3 and stats.games == 35
    seen.clear()
    pipeline.update(src, db, 0, 0, injuries=False)
    assert seen == {}
    db.close()


def test_season_dates_per_league():
    assert pipeline.season_dates("2025-26") == (date(2025, 10, 1), date(2026, 6, 30))
    assert pipeline.season_dates("2025-26", "ncaab") == (date(2025, 11, 1), date(2026, 4, 15))


# ---------- CLI + config ----------


def test_followed_teams_per_league_and_backward_compatible():
    assert cli.followed_teams({"teams": ["gs", "LAL"]}) == ["GS", "LAL"]
    assert cli.followed_teams({"teams": ["GS"]}, "ncaab") == []
    cfg = {"teams": ["GS"], "nba": {"teams": ["BOS"]}, "ncaab": {"teams": ["nev"]}}
    assert cli.followed_teams(cfg) == ["BOS"]
    assert cli.followed_teams(cfg, "ncaab") == ["NEV"]


def test_cli_parses_league_options():
    p = cli.build_parser()
    assert p.parse_args(["update"]).league == "nba"
    assert p.parse_args(["backfill", "--season", "2025-26", "--league", "ncaab"]).league == "ncaab"
    assert p.parse_args(["upcoming", "--league", "all"]).league == "all"
    assert p.parse_args(["injuries-backfill"]).command == "injuries-backfill"
    with pytest.raises(SystemExit):
        p.parse_args(["update", "--league", "all"])


def test_cli_migrate_and_upcoming_all(monkeypatch, legacy_path, capsys):
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli, "Store", lambda read_only=False: Store(legacy_path, read_only))
    assert cli.main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "migrated teams" in out and "rows 30 -> 30" in out
    assert cli.main(["migrate"]) == 0
    assert "nothing to migrate" in capsys.readouterr().out
    db = Store(legacy_path)
    db.upsert_teams(parse_teams(load("espn_ncaab_teams.json"), "ncaab"))
    db.close()
    monkeypatch.setattr(
        cli, "load_calendar_config", lambda: {"teams": ["LAL"], "ncaab": {"teams": ["NEV"]}}
    )
    assert cli.main(["upcoming", "--league", "all", "--json", "--days", "3"]) == 0
    json.loads(capsys.readouterr().out)  # valid JSON (dates relative to now: may be empty)


# ---------- bulk writer ----------


def test_bulk_write_types_duplicates_and_ignore_mode():
    db = Store(":memory:")
    when = datetime(2026, 11, 3, 3, 0, tzinfo=UTC)
    rows = [
        {"game_id": "g", "model": "m", "model_version": "1", "created_at": when,
         "p_home_win": float("nan"), "pred_home_margin": None, "pred_total": 1.5,
         "features_json": 'it\'s "quoted"\n🏀'},
        {"game_id": "g", "model": "m", "model_version": "1", "created_at": when,
         "p_home_win": 0.25, "pred_home_margin": -2.0, "pred_total": None,
         "features_json": None},
    ]  # fmt: skip
    assert db.add_predictions(rows[:1]) == 1
    got = db.latest_predictions(["g"])[0]
    assert math.isnan(got["p_home_win"]) and got["created_at"] == when
    assert got["features_json"] == 'it\'s "quoted"\n🏀' and got["pred_home_margin"] is None
    db.add_predictions(rows)  # same key twice in one batch: the last row wins
    got = db.latest_predictions(["g"])[0]
    assert (got["p_home_win"], got["pred_total"]) == (0.25, None)
    db.upsert_teams(parse_teams(load("espn_ncaab_teams.json"), "ncaab"))
    seen = parse_scoreboard_teams(load(NCAA_LIVE), "ncaab")
    added = db.add_discovered_teams(seen)
    assert added == len(seen)
    assert db.con.execute("SELECT count(*) FROM teams WHERE NOT listed").fetchone()[0] == 10
    assert db.con.execute(
        "SELECT listed FROM teams WHERE league = 'ncaab' AND team_id = '258'"
    ).fetchone() == (True,)  # Virginia stays listed
    db.close()


def test_bulk_write_is_fast():
    db = Store(":memory:")
    db.upsert_games(parse_scoreboard(load(NCAA_FINAL), league="ncaab")[0])
    teams, players, _ = parse_summary(load(NCAA_SUMMARY), league="ncaab")
    rows = [
        {**p, "game_id": f"g{i}", "athlete_id": f"{p['athlete_id']}-{i}"}
        for i in range(800)
        for p in players
    ]  # ~23k rows x 29 columns
    t = time.perf_counter()
    db.upsert_player_stats(rows)
    elapsed = time.perf_counter() - t
    assert db.counts()["player_game_stats"] == len(rows)
    assert elapsed < 5, elapsed  # was ~70 s with executemany
    db.close()


def test_context_counts_non_d1_games_but_only_emits_listed_teams():
    db = Store(":memory:")
    db.upsert_teams(parse_teams(load("espn_ncaab_teams.json"), "ncaab"))
    raw = load(NCAA_LIVE)
    db.add_discovered_teams(parse_scoreboard_teams(raw, "ncaab"))
    games, _ = parse_scoreboard(raw, league="ncaab")
    db.upsert_games(games)
    rows = db.con.execute("SELECT team_id FROM team_game_context").fetchall()
    assert len(rows) == 2 * len(games) - 10  # the 10 non-D1 sides get no rows
    db.close()
