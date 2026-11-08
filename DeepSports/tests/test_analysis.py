import math
from datetime import UTC, datetime, timedelta

import pytest

from deepsports.analysis import (
    american_to_decimal,
    brier,
    devig_probability,
    elo_ratings,
    evaluate_elo,
    home_court,
    log_loss,
    market_accuracy,
    report,
    win_probability,
)
from deepsports.store import Store

T0 = datetime(2025, 10, 21, 23, 0, tzinfo=UTC)
TEAMS = ["1", "2", "3", "4"]


def make_store(path=":memory:") -> Store:
    s = Store(path)
    s.upsert_teams(
        {"team_id": t, "league": "nba", "abbreviation": f"T{t}", "display_name": f"Team {t}"}
        for t in TEAMS
    )
    return s


def game(gid, day, home, away, hs, as_, season=2026, stype=2, neutral=False, status="STATUS_FINAL"):
    final = status == "STATUS_FINAL"
    return {
        "game_id": gid,
        "league": "nba",
        "season_year": season,
        "season_type": stype,
        "start_time_utc": T0 + timedelta(days=day),
        "status": status,
        "state": "post",
        "completed": final,
        "home_team_id": home,
        "away_team_id": away,
        "home_score": hs if final else None,
        "away_score": as_ if final else None,
        "neutral_site": neutral,
    }


def odds(gid, source="closing", spread=None, total=None, hml=None, aml=None, day=0):
    return {
        "game_id": gid,
        "source": source,
        "captured_at": T0 + timedelta(days=day),
        "provider": "test",
        "details": None,
        "spread_home": spread,
        "over_under": total,
        "home_moneyline": hml,
        "away_moneyline": aml,
    }


def round_robin(season, start_day, n_rounds, home_wins_by=5):
    """Every ordered pair plays; the home team always wins by `home_wins_by`."""
    games, day = [], start_day
    for r in range(n_rounds):
        for h in TEAMS:
            for a in TEAMS:
                if h != a:
                    games.append(
                        game(
                            f"{season}-{r}-{h}-{a}",
                            day,
                            h,
                            a,
                            105 + home_wins_by,
                            105,
                            season=season,
                        )
                    )
                    day += 1
    return games


# ---------- metrics ----------


def test_american_to_decimal():
    assert american_to_decimal(150) == 2.5
    assert american_to_decimal(100) == 2.0
    assert american_to_decimal(-200) == 1.5
    assert american_to_decimal(None) is None and american_to_decimal(0) is None


@pytest.mark.parametrize("h,a", [(-110, -110), (-130, 110), (-450, 350), (100, 100), (250, -300)])
def test_devig_sums_to_one(h, a):
    assert devig_probability(h, a) + devig_probability(a, h) == pytest.approx(1.0)


def test_devig_values():
    assert devig_probability(-110, -110) == pytest.approx(0.5)
    p = devig_probability(-200, 170)
    assert 0.6 < p < 2 / 3  # raw implied 0.667 shrinks once the vig is removed
    assert devig_probability(None, 100) is None


def test_scoring_rules():
    ys = [1, 0, 1, 1]
    assert brier([1.0, 0.0, 1.0, 1.0], ys) == 0
    assert log_loss([1.0, 0.0, 1.0, 1.0], ys) == pytest.approx(0, abs=1e-12)
    assert brier([0.5] * 4, ys) == 0.25
    assert log_loss([0.5] * 4, ys) == pytest.approx(math.log(2))
    assert brier([], []) is None and log_loss([], []) is None


# ---------- home court ----------


def test_home_court_home_always_wins_by_5():
    s = make_store()
    s.upsert_games(round_robin(2026, 0, 2))
    s.upsert_games(
        [
            game("neutral", 100, "1", "2", 90, 120, neutral=True),  # excluded
            game("pre", 101, "1", "2", 90, 120, stype=1),  # preseason, excluded
            game("post", 102, "1", "2", 90, 120, stype=3),  # playoffs, excluded
            game("ppd", 103, "1", "2", 0, 0, status="STATUS_POSTPONED"),  # excluded
        ]
    )
    (row,) = home_court(s.con)
    assert row == {"season": 2026, "n": 24, "home_win_pct": 1.0, "avg_home_margin": 5.0}
    assert home_court(s.con, seasons=[2025]) == []


# ---------- market accuracy ----------


def test_market_accuracy_closing():
    s = make_store()
    s.upsert_games(
        [
            game("a", 0, "1", "2", 110, 100),  # home +10
            game("b", 1, "3", "4", 104, 100),  # home +4
            game("c", 2, "1", "3", 100, 103),  # home -3
            game("d", 3, "2", "4", 100, 120),  # home -20, pick'em
            game("e", 4, "4", "1", 100, 101),  # bad total, no spread
        ]
    )
    s.add_odds(
        [
            odds("a", spread=-6.5, total=200),  # home fav wins, covers; total err 10
            odds("b", spread=2.0, total=210),  # away fav loses; home covers; err 6
            odds("c", spread=3.0, total=203),  # away fav wins by 3: push; err 0
            odds("d", spread=0.0, total=None),  # pick'em, away covers
            odds("e", spread=None, total=1.91),  # decimal price mis-parsed as total
        ]
    )
    (r,) = market_accuracy(s.con)["closing"]
    assert r["n_spread"] == 4 and r["n_favorite"] == 3
    assert r["favorite_win_pct"] == pytest.approx(2 / 3)
    assert (r["home_covers"], r["away_covers"], r["pushes"]) == (2, 1, 1)
    assert r["home_cover_pct"] == pytest.approx(2 / 3)
    # |10-6.5| + |4+2| + |-3+3| + |-20+0| = 3.5 + 6 + 0 + 20
    assert r["spread_mae"] == pytest.approx(29.5 / 4)
    assert r["n_total"] == 3 and r["total_mae"] == pytest.approx(16 / 3)
    assert r["n_total_rejected"] == 1


def test_market_accuracy_movement():
    s = make_store()
    s.upsert_games([game("a", 0, "1", "2", 110, 100), game("b", 1, "3", "4", 100, 100 + 2)])
    s.add_odds(
        [
            odds("a", "opening", spread=-4.0, total=215),
            odds("a", "closing", spread=-7.0, total=212),  # closing closer on both
            odds("b", "opening", spread=-1.0, total=200),
            odds("b", "closing", spread=1.0, total=204),  # margin -2: open err 3, close err 1
        ]
    )
    (m,) = market_accuracy(s.con)["movement"]
    assert m["n_spread"] == 2
    assert m["spread_mean_abs_move"] == pytest.approx(2.5)
    assert m["open_spread_mae"] == pytest.approx((6 + 3) / 2)
    assert m["close_spread_mae"] == pytest.approx((3 + 1) / 2)
    assert m["close_spread_better_pct"] == 1.0
    assert m["total_mean_abs_move"] == pytest.approx(3.5)
    assert m["open_total_mae"] == pytest.approx((5 + 2) / 2)
    assert m["close_total_mae"] == pytest.approx((2 + 2) / 2)


# ---------- Elo ----------


def test_elo_no_games_is_1500():
    s = make_store()
    res = elo_ratings(s.con)
    assert res.games == [] and res.ratings == {t: 1500.0 for t in TEAMS}


def test_elo_first_game_and_zero_sum():
    s = make_store()
    s.upsert_games(round_robin(2026, 0, 2))
    res = elo_ratings(s.con)
    first = res.games[0]
    assert first["home_elo_pre"] == first["away_elo_pre"] == 1500
    assert first["p_home"] == pytest.approx(win_probability(1500, 1500, 100))
    assert first["p_home"] == pytest.approx(1 / (1 + 10 ** (-0.25)))
    assert sum(res.ratings.values()) == pytest.approx(1500 * len(TEAMS))


def test_elo_neutral_site_has_no_home_advantage():
    s = make_store()
    s.upsert_games([game("n", 0, "1", "2", 100, 90, neutral=True)])
    assert elo_ratings(s.con).games[0]["p_home"] == pytest.approx(0.5)


def test_elo_pregame_ratings_ignore_own_result():
    games = round_robin(2026, 0, 2)
    target = 7
    s1, s2 = make_store(), make_store()
    s1.upsert_games(games)
    flipped = [dict(g) for g in games]
    g = flipped[target]
    g["home_score"], g["away_score"] = g["away_score"] - 30, g["home_score"]
    s2.upsert_games(flipped)
    a, b = elo_ratings(s1.con).games, elo_ratings(s2.con).games
    keys = ("home_elo_pre", "away_elo_pre", "p_home")
    for i in range(target + 1):  # the flipped game's own pre-game row is unchanged
        assert [a[i][k] for k in keys] == [b[i][k] for k in keys]
    assert any(a[i]["p_home"] != b[i]["p_home"] for i in range(target + 1, len(a)))


def test_elo_carry_over_between_seasons():
    s = make_store()
    s.upsert_games([game("x", 0, "1", "2", 120, 90, season=2025)])
    s.upsert_games([game("y", 300, "1", "2", 100, 99, season=2026)])
    res = elo_ratings(s.con, carry_over=0.75)
    r1 = elo_ratings(s.con, carry_over=1.0).games[1]["home_elo_pre"]
    assert r1 > 1500
    assert res.games[1]["home_elo_pre"] == pytest.approx(0.75 * r1 + 0.25 * 1500)


def test_elo_mov_bigger_wins_move_more():
    s1, s2 = make_store(), make_store()
    s1.upsert_games([game("x", 0, "1", "2", 101, 100), game("z", 1, "1", "3", 100, 100 - 1)])
    s2.upsert_games([game("x", 0, "1", "2", 130, 100), game("z", 1, "1", "3", 100, 100 - 1)])
    assert (
        elo_ratings(s2.con).games[1]["home_elo_pre"] > elo_ratings(s1.con).games[1]["home_elo_pre"]
    )


# ---------- evaluation ----------


def test_evaluate_elo_baselines_and_market():
    s = make_store()
    s.upsert_games(round_robin(2025, 0, 1))
    s.upsert_games(round_robin(2026, 300, 1))
    # closing moneylines for two 2026 games; one with a missing side (excluded)
    gids = [g["game_id"] for g in round_robin(2026, 300, 1)]
    s.add_odds(
        [
            odds(gids[0], hml=-200, aml=170),
            odds(gids[1], hml=-150, aml=130),
            odds(gids[2], hml=-150, aml=None),
        ]
    )
    ev = evaluate_elo(s.con)
    first, second = ev["per_season"]
    assert first["home_base_rate"] is None and first["all"]["n"] == 0
    assert second["home_base_rate"] == 1.0  # home always won in 2025
    assert second["all"]["n"] == 12
    assert second["all"]["coin_flip"]["brier"] == 0.25
    assert second["all"]["home_always"]["brier"] == pytest.approx(0)  # perfect predictor
    assert second["market"]["n"] == 2
    assert ev["overall"]["seasons"] == [2026] and ev["overall"]["market"]["n"] == 2
    p0 = devig_probability(-200, 170)
    p1 = devig_probability(-150, 130)
    assert second["market"]["market"]["brier"] == pytest.approx(((1 - p0) ** 2 + (1 - p1) ** 2) / 2)


# ---------- report ----------


def test_report_main_writes_markdown(tmp_path):
    db = tmp_path / "w.duckdb"
    s = make_store(db)
    s.upsert_games(round_robin(2025, 0, 1) + round_robin(2026, 300, 1))
    s.add_odds([odds("2026-0-1-2", spread=-5, total=210, hml=-200, aml=170)])
    s.close()
    out = tmp_path / "r.md"
    assert report.main(["--db", str(db), "--out", str(out)]) == 0
    text = out.read_text()
    assert "## Home court" in text and "| 2026 |" in text and "T1" in text
    assert report.main(["--db", str(tmp_path / "missing.duckdb")]) == 1
