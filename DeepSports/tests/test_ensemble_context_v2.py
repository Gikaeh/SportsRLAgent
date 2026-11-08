"""ctx-v2 blocks: every one is point-in-time (invariant to anything after the decision time)."""

import json
import random
from datetime import UTC, datetime, timedelta

import pytest
from test_ensemble_bets import NOW, hist_db  # noqa: F401  (fixture)

from deepsports.analysis import ensemble_bets as eb
from deepsports.analysis import ensemble_context_v2 as v2
from deepsports.analysis import ensemble_sim as sim

TS = NOW - timedelta(days=400)


def _game(con, gid, start, home, away, hs, as_, season=2027, league="nba"):
    con.execute(
        "INSERT INTO games (game_id, league, season_year, season_type, start_time_utc, status,"
        " state, completed, home_team_id, away_team_id, home_score, away_score, venue,"
        " venue_city, neutral_site, broadcasts, updated_at)"
        " VALUES (?, ?, ?, 2, ?, 'STATUS_FINAL', 'post', TRUE, ?, ?, ?, ?, 'Arena',"
        " 'Los Angeles', FALSE, 'TV', ?)",
        [gid, league, season, start, home, away, hs, as_, TS],
    )


def _box(con, gid, tid, fga=85, oreb=10, tov=13, fta=20, league="nba"):
    con.execute(
        "INSERT INTO team_game_stats (game_id, team_id, fga, oreb, tov, fta, updated_at, league)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [gid, tid, fga, oreb, tov, fta, TS, league],
    )


def _closing(con, gid, sp, tot, source="closing", at=None):
    con.execute(
        "INSERT INTO odds_snapshots (game_id, source, captured_at, provider, spread_home,"
        " over_under, home_moneyline, away_moneyline) VALUES (?, ?, ?, 'DK', ?, ?, -150, 130)",
        [gid, source, at or TS, sp, tot],
    )


@pytest.fixture
def v2_db(hist_db):  # noqa: F811
    con = hist_db
    # last season (2026): finals with closing lines (base rates + last-season block)
    for i, (h, a, hs, as_, sp, tot) in enumerate(
        [("1", "2", 110, 100, -4.5, 215.5), ("2", "3", 99, 104, 2.5, 209.5),
         ("3", "1", 120, 118, -1.5, 230.5), ("1", "3", 95, 101, -8.5, 221.5)]
    ):  # fmt: skip
        gid = f"p{i}"
        _game(con, gid, NOW - timedelta(days=200 - i), h, a, hs, as_, season=2026)
        _closing(con, gid, sp, tot)
    # this season: box scores for the finished game, the unfinished one and the target
    for gid, t1, t2 in (("g0", "1", "3"), ("gr", "3", "1"), ("g1", "1", "2")):
        _box(con, gid, t1)
        _box(con, gid, t2, fga=80)
    # a this-season closing line elsewhere (must not enter base rates)
    _closing(con, "g0", -3.5, 220.5)
    # pregame snapshots of the target: two before NOW, one after
    for at, sp in ((NOW - timedelta(hours=6), -3.0), (NOW - timedelta(hours=1), -4.0),
                   (NOW + timedelta(minutes=20), -6.5)):  # fmt: skip
        _closing(con, "g1", sp, 220.5, source="pregame", at=at)
    return con


def _mutate_future(con):
    """Change everything that happened after the decision time (or before it but not finished)."""
    cut = (NOW - timedelta(hours=4)).isoformat()
    late = f"(SELECT game_id FROM games WHERE start_time_utc > TIMESTAMPTZ '{cut}')"
    con.execute(f"UPDATE games SET home_score = home_score + 61 WHERE game_id IN {late}")
    con.execute(f"UPDATE team_game_stats SET fga = fga + 40, tov = 0 WHERE game_id IN {late}")
    con.execute(f"UPDATE player_game_stats SET minutes = 48, pts = 90 WHERE game_id IN {late}")
    con.execute("UPDATE odds_snapshots SET spread_home = 9.5 WHERE game_id = 'g0'")
    con.execute(
        "UPDATE odds_snapshots SET spread_home = -12.5"
        " WHERE source = 'pregame' AND captured_at > ?",
        [NOW],
    )


def _v2_slate(con, timing):
    s = eb.load_historical_slate(con, NOW, NOW + timedelta(hours=12), context="v2")
    if timing:  # the live path's line-timing block on the same games
        raw = eb.load_historical_games(con, "nba", NOW, NOW + timedelta(hours=12))
        inj, _ = eb.load_injuries_as_of(con, "nba", [g["game_id"] for g in raw], NOW)
        v2.attach_v2(con, s, NOW, raw, inj, timing=True)
    return json.loads(json.dumps(s, default=str))


def test_v2_blocks_are_point_in_time(v2_db):
    before = _v2_slate(v2_db, timing=True)
    g = before["games"][0]
    h = g["home"]["v2"]
    # non-trivial: each block has content
    assert h["last_season"]["record"] == "1-2" and h["last_season"]["final_rating"] is not None
    assert h["elo"] is not None and h["pace"] is not None and h["box_gp"] == 1
    assert g["away"]["v2"]["box_gp"] is None  # BOS's only box is the target game itself
    assert h["injury_impact"]["min_share"] == 1.0  # Early Guy: all of LAL's g0 minutes
    assert g["line_timing"]["snapshots"] == 2
    assert g["line_timing"]["biggest"]["to"] == -4.0
    assert g["line_timing"]["last3h_spread"] == -1.0
    br = before["base_rates"]["nba"]
    assert br["seasons"] == [2026] and br["home_ats"]["n"] == 4
    _mutate_future(v2_db)
    assert _v2_slate(v2_db, timing=True) == before


def test_v2_brief_and_v1_equivalence(v2_db):
    v1 = eb.load_historical_slate(v2_db, NOW, NOW + timedelta(hours=12))
    s2 = eb.load_historical_slate(v2_db, NOW, NOW + timedelta(hours=12), context="v2")
    assert s2["context_version"] == "ctx-v2-sim1" and v1["context_version"] == "ctx-v1-sim1"
    t1 = eb.render_context(v1, seed=3, one_pick=True)
    t2 = eb.render_context(s2, seed=3, one_pick=True)
    assert eb.render_context(v2.strip_v2(s2), seed=3, one_pick=True) == t1
    assert "More facts in this context version" in t2 and "More facts" not in t1
    assert "Base rates, NBA" in t2 and "descriptive history, not edges" in t2
    assert "  - more: last season 1-2" in t2 and "injury impact: missing ~100%" in t2
    assert "- line timing:" not in t2  # historical slates have no timing block
    assert len(t2) < 2.5 * len(t1)


def test_base_rates_exclude_the_slate_season(v2_db):
    br = v2.base_rates(v2_db, "nba", 2027)
    assert br["seasons"] == [2026]
    assert br["home_ats"]["k"] == 2 and br["home_ats"]["n"] == 4  # p0, p2 cover; p1, p3 don't
    assert br["favorite_ats"]["3.5-7"] == {**br["favorite_ats"]["3.5-7"], "k": 1, "n": 1}
    assert v2.base_rates(v2_db, "nba", 2026)["home_ats"]["n"] == 0
    text = v2.render_base_rates(br)
    assert "home team covers the spread: 50.0%" in text and "n=4" in text


def test_live_load_slate_v2_flag(v2_db):
    v2_db.execute("UPDATE games SET state = 'pre' WHERE game_id = 'g1'")
    live = eb.load_slate(v2_db, NOW, days=1, leagues=["nba"], context="v2")
    assert live["context_version"] == "ctx-v2"
    assert eb.load_slate(v2_db, NOW, days=1, leagues=["nba"])["context_version"] == "ctx-v1"
    with pytest.raises(ValueError):
        eb.load_slate(v2_db, NOW, days=1, context="v3")


@pytest.fixture
def college_db():
    from deepsports.store import Store

    store = Store(":memory:")
    con = store.con
    for t in "ABCD":
        con.execute(
            "INSERT INTO teams (team_id, league, abbreviation, display_name, listed, updated_at)"
            " VALUES (?, 'ncaab', ?, ?, TRUE, ?)",
            [t, t * 2, f"School {t}", TS],
        )
    base = NOW - timedelta(days=300)
    rng = random.Random(0)
    n = 0
    for season, t0 in ((2025, base), (2026, NOW - timedelta(days=20))):
        for k in range(12):
            h, a = rng.sample("ABCD", 2)
            _game(con, f"c{n}", t0 + timedelta(days=k), h, a, 70 + rng.randint(-15, 15),
                  70 + rng.randint(-15, 15), season=season, league="ncaab")  # fmt: skip
            n += 1
    _game(con, "late", NOW - timedelta(hours=2), "A", "B", 140, 20, season=2026, league="ncaab")
    yield con
    store.close()


def test_college_ratings_point_in_time(college_db):
    cutoff = NOW - timedelta(hours=4)
    net, rank, n_ranked, last = v2.college_ratings(college_db, 2026, cutoff)
    assert n_ranked == 4 and sorted(rank.values()) == [1, 2, 3, 4] and set(last) == set("ABCD")
    college_db.execute("UPDATE games SET home_score = 10 WHERE game_id = 'late'")
    assert v2.college_ratings(college_db, 2026, cutoff) == (net, rank, n_ranked, last)
    # the last season's final rating ignores this season entirely
    college_db.execute("UPDATE games SET home_score = home_score + 30 WHERE season_year = 2026")
    assert v2.college_ratings(college_db, 2026, cutoff)[3] == last


def test_render_team_v2_and_timing():
    t = {
        "v2": {
            "last_season": None,
            "elo": None,
            "rating": 4.25,
            "rank": 12,
            "n_ranked": 360,
            "box_gp": 5,
            "pace": 68.1,
            "ortg": 110.2,
            "drtg": 99.5,
            "injury_impact": None,
        }
    }
    assert v2.render_team_v2(t, "ncaab") == [
        "  - more: last season n/a; rating now +4.25 (#12 of 360 D1); pace 68.1, off 110.2 / "
        "def 99.5 per 100"
    ]  # fmt: skip
    g = {"line_timing": {"first_seen": datetime(2026, 11, 7, 20, tzinfo=UTC).isoformat(),
                         "snapshots": 3, "biggest": None, "last3h_spread": None,
                         "last3h_total": 1.5}}  # fmt: skip
    (line,) = v2.render_timing(g)
    assert "3 snapshots" in line and "last 3 h: total +1.5" in line


def test_anonymized_v2_context_has_no_names(v2_db):
    s = eb.load_historical_slate(v2_db, NOW, NOW + timedelta(hours=12), context="v2")
    anon, _ = sim.anonymize_slate(s, random.Random(3), forbidden={"LAL", "BOS", "NY"})
    text = eb.render_context(anon, seed=0, one_pick=True)
    terms = ["LAL", "BOS", "NY", "Lakers", "Celtics", "Knicks", "Arena", "2026", "2027", "2025"]
    assert sim.find_leaks(text, terms) == []
    assert "  - more: last season" in text and "Base rates, NBA" in text
