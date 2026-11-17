from __future__ import annotations

import json

from deepsports.analysis import model_picks as mp


def game(gid, league, home_line, total, ds, mb, gated=False, best=None):
    g = {
        "game_id": gid,
        "league": league,
        "tip_local": "Fri Nov 13 4:00 PM PST",
        "home": {"abbr": f"H{gid}"},
        "away": {"abbr": f"A{gid}"},
        "markets": {
            "spread": {
                "home_line": home_line, "home_price": -110,
                "away_line": -home_line, "away_price": -105,
            },
            "total": {"line": total, "over_price": -112, "under_price": -108},
        },
        "model": {"home_margin": ds[0], "total": ds[1]},
        "manualbets": {"model": {"home_margin": mb[0], "total": mb[1]}, "gated": gated},
    }  # fmt: skip
    if best:
        g["manualbets"]["best_prices"] = {"spread": best}
    return g


def slate(*games):
    return {
        "created_at": "2026-11-13T22:00:00+00:00",
        "manualbets": {"available": True, "errors": {}},
        "games": list(games),
    }


def test_tiers_and_sides():
    s = slate(
        # spread: home -5; DS home by 10 (+5 home), MB by 9.5 (+4.5) -> strong home
        # total 200: DS 196.5 (-3.5), MB 195 (-5) -> lean under
        game("1", "nba", -5, 200, (10, 196.5), (9.5, 195)),
        # models disagree on spread; total edges 2 and 6 -> nothing
        game("2", "nba", -3, 220, (6, 222), (0, 226)),
    )
    picks = mp.find_picks(s)
    got = {(p["game_id"], p["market"], p["side"], p["tier"]) for p in picks}
    assert got == {("1", "spread", "home", "strong"), ("1", "total", "under", "lean")}
    sp = next(p for p in picks if p["market"] == "spread")
    assert (sp["line"], sp["price"], sp["ds_edge"], sp["mb_edge"]) == (-5, -110, 5.0, 4.5)
    assert picks[0]["tier"] == "strong"


def test_away_side_line_from_bettors_view():
    # home -8: DS home by 2 (-6), MB home by 3 (-5) -> away +8 strong
    p = mp.find_picks(slate(game("1", "ncaab", -8, 150, (2, 150), (3, 150))))[0]
    assert (p["side"], p["line"], p["price"], p["label"]) == ("away", 8, -105, "A1 +8")


def test_top_one_per_game_skips_big_college_dogs_and_caps():
    games = [game("big", "ncaab", -22, 150, (12, 150), (10, 150))]  # away +22, edges 10/12
    games += [game(str(i), "nba", -1, 200, (5 + i, 210 + i), (5 + i, 210 + i)) for i in range(7)]
    picks = mp.find_picks(slate(*games))
    top = mp.top_picks(picks)
    assert len(top) == mp.TOP_N
    assert "big" not in {p["game_id"] for p in top}
    assert len({p["game_id"] for p in top}) == len(top)
    assert [p["min_edge"] for p in top] == sorted((p["min_edge"] for p in top), reverse=True)


def test_render_and_no_manualbets():
    s = slate(game("1", "ncaab", -5, 200, (10, 200), (10, 200), gated=True))
    picks = mp.find_picks(s)
    text = mp.render(s, picks, mp.top_picks(picks))
    assert "Top 1" in text and "H1 -5*" in text and "early-season" in text
    s["manualbets"] = {"available": False}
    assert "no picks" in mp.render(s, [], [])
    assert "No bet today" in mp.render(slate(), [], [])


def test_best_price_only_when_same_line_or_better():
    best = {"home": {"price": -102, "point": -5.0, "book": "x"}}
    s = slate(game("1", "nba", -5, 200, (10, 200), (10, 200), best=best))
    assert mp.find_picks(s)[0]["best"]["book"] == "x"
    best["home"]["point"] = -5.5  # worse line
    assert "best" not in mp.find_picks(s)[0]


def _db(games, closes):
    import duckdb

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE games (game_id VARCHAR, league VARCHAR, season_year INT, season_type INT,"
        " start_time_utc TIMESTAMPTZ, home_score INT, away_score INT, completed BOOLEAN,"
        " status VARCHAR)"
    )
    con.execute(
        "CREATE TABLE odds_snapshots (game_id VARCHAR, source VARCHAR, captured_at TIMESTAMPTZ,"
        " provider VARCHAR, details VARCHAR, spread_home DOUBLE, over_under DOUBLE,"
        " home_moneyline INT, away_moneyline INT)"
    )
    for gid, league, hs, as_ in games:
        con.execute(
            "INSERT INTO games VALUES (?, ?, 2027, 2, '2026-11-14 00:00:00+00', ?, ?, ?, ?)",
            [gid, league, hs, as_, hs is not None, "STATUS_FINAL" if hs is not None else "pre"],
        )
    for gid, when, sp, tot in closes:
        con.execute(
            "INSERT INTO odds_snapshots VALUES (?, 'closing', ?, 'x', '', ?, ?, NULL, NULL)",
            [gid, when, sp, tot],
        )
    return con


def test_pick_clv_bet_side_view():
    close = {"spread_home": -7.0, "over_under": 205.0}
    home = {"league": "nba", "market": "spread", "side": "home", "line": -5}
    away = {"league": "nba", "market": "spread", "side": "away", "line": 5}
    over = {"league": "nba", "market": "total", "side": "over", "line": 200}
    under = {"league": "nba", "market": "total", "side": "under", "line": 200}
    # home -5 taken, closed -7: +2 for home; away +5 vs +7 at the close: -2
    assert mp.pick_clv(home, close) == 2.0 and mp.pick_clv(away, close) == -2.0
    assert mp.pick_clv(over, close) == 5.0 and mp.pick_clv(under, close) == -5.0
    assert mp.pick_clv(home, None) is None
    assert mp.pick_clv(over, {"spread_home": -7.0, "over_under": 999.0}) is None  # not sane


def test_grade_picks_clv_by_league_and_pending():
    s = slate(
        game("1", "nba", -5, 200, (10, 196), (10, 195)),  # home -5 strong, under 200 strong
        game("2", "ncaab", -3, 140, (4, 150), (5, 150)),  # total over 140 strong only
        game("3", "ncaab", -3, 140, (4, 150), (5, 150)),  # not final yet
    )
    con = _db(
        [("1", "nba", 110, 100), ("2", "ncaab", 70, 60), ("3", "ncaab", None, None)],
        [
            ("1", "2026-11-14 00:30:00+00", -6.5, 198.0),
            ("1", "2026-11-13 23:00:00+00", -5.0, 200.0),  # older close row: ignored
        ],
    )
    rec = mp.grade_picks(con, [mp.slate_run(s, run="r1")])
    assert rec["pending_picks"] == 1
    st = rec["strong"]
    # home -5 won by 10 (win), under 200 vs 210 (loss), over 140 vs 130 (loss)
    assert st["record"] == "1-2-0" and st["bets"] == 3
    assert st["clv_n"] == 2 and st["clv_coverage"] == round(2 / 3, 3)
    assert st["clv_mean"] == 1.75  # home +1.5, under +2.0; game 2 has no closing row
    assert rec["by_league"]["nba"]["strong"]["clv_mean"] == 1.75
    assert rec["by_league"]["ncaab"]["strong"]["clv_n"] == 0
    assert rec["per_run"][0]["run"] == "r1" and rec["per_run"][0]["all"]["bets"] == 3


def test_write_and_grade(tmp_path):
    from datetime import UTC, datetime

    s = slate(game("1", "nba", -5, 200, (10, 196), (10, 195)))
    run, _ = mp.write_run(s, datetime(2026, 11, 13, 22, tzinfo=UTC), root=tmp_path)
    saved = json.loads((run / "picks.json").read_text())
    assert saved["rule_version"] == mp.RULE_VERSION and len(saved["top"]) == 1
    con = _db([("1", "nba", 110, 100)], [])
    rec = mp.grade_runs(con, root=tmp_path)
    # home -5 wins by 10 -> win; under 200 with 210 -> loss
    assert rec["strong"]["record"] == "1-1-0" and rec["top"]["bets"] == 1
    assert rec["strong"]["clv_n"] == 0 and rec["per_run"][0]["run"] == run.name


def test_write_run_skips_games_an_earlier_run_posted(tmp_path):
    from datetime import UTC, datetime, timedelta

    s = slate(game("1", "nba", -5, 200, (10, 196), (10, 195)))
    t0 = datetime.fromisoformat(s["created_at"])
    first, _ = mp.write_run(s, t0, root=tmp_path)
    s2 = dict(s, created_at=(t0 + timedelta(hours=18)).isoformat())
    second, text = mp.write_run(s2, t0 + timedelta(hours=18), root=tmp_path)
    saved = json.loads((second / "picks.json").read_text())
    assert saved["picks"] == [] and saved["top"] == []
    assert "1 game already posted in an earlier run left out." in text
    # Two days later the old run no longer counts.
    s3 = dict(s, created_at=(t0 + timedelta(hours=48)).isoformat())
    third, _ = mp.write_run(s3, t0 + timedelta(hours=48), root=tmp_path)
    assert len(json.loads((third / "picks.json").read_text())["top"]) == 1
    assert mp.posted_games(tmp_path, datetime(2000, 1, 1, tzinfo=UTC)) == set()


def test_best_book_line_first_then_price():
    sp = {
        "market": "spread",
        "side": "away",
        "books": {
            "circa": {"line": 7.5, "price": -115},
            "williamhill": {"line": 7.0, "price": -105},
        },
    }
    assert mp.best_book(sp) == {"book": "circa", "line": 7.5, "price": -115}
    over = {
        "market": "total",
        "side": "over",
        "books": {
            "circa": {"line": 141.5, "price": -110},
            "williamhill": {"line": 141.0, "price": -110},
        },
    }
    assert mp.best_book(over)["book"] == "williamhill"
    under = dict(over, side="under")
    assert mp.best_book(under)["book"] == "circa"
    tie = {
        "market": "total",
        "side": "over",
        "books": {
            "circa": {"line": 141.0, "price": -112},
            "williamhill": {"line": 141.0, "price": +100},
        },
    }
    assert mp.best_book(tie)["price"] == 100
    assert mp.best_book({"market": "total", "side": "over"}) is None
    assert mp.best_book({**over, "books": {"circa": {"line": None, "price": -110}}}) is None


def test_grade_picks_at_book_price_beside_draftkings():
    s = slate(
        game("1", "nba", -5, 200, (10, 196), (10, 195)),  # top: home -5 (DK -110)
        game("2", "ncaab", -3, 140, (4, 150), (5, 150)),  # top: over 140, no book quote
    )
    run = mp.slate_run(s, run="r1")
    books = {
        "circa": {
            "lines": [
                {"game_id": "1", "market": "spread", "side": "home", "line": -6.5, "price": +100}
            ]
        },
        "williamhill": {
            "lines": [
                {"game_id": "1", "market": "spread", "side": "home", "line": -4.5, "price": -120}
            ]
        },
    }
    mp.attach_books(run["top"], books)
    con = _db(
        [("1", "nba", 110, 104), ("2", "ncaab", 70, 60)],
        [("1", "2026-11-14 00:30:00+00", -6.0, 198.0)],
    )
    rec = mp.grade_picks(con, [run])
    # DK home -5 wins by 6; WH -4.5 (better line) wins at -120; Circa -6.5 would have lost
    assert rec["top"]["record"] == "1-1-0"  # unchanged DK record (over 140 vs 130 loses)
    assert rec["book_quotes"]["top_picks"] == 2 and rec["book_quotes"]["with_quote"] == 1
    assert rec["book_quotes"]["by_book"] == {"williamhill": 1}
    tb, dk = rec["top_books"], rec["top_books_dk"]
    assert tb["bets"] == dk["bets"] == 1 and tb["record"] == "1-0-0"
    assert tb["units_profit"] == round(100 / 120, 2) and dk["units_profit"] == round(100 / 110, 2)
    assert tb["clv_mean"] == 1.5 and dk["clv_mean"] == 1.0
    assert rec["by_league"]["nba"]["top_books"]["bets"] == 1
    assert rec["per_run"][0]["top_books"]["bets"] == 1


def _books(*rows):
    """{"circa": {"lines": [...]}} from (book, game_id, market, side, line, price) rows."""
    out = {}
    for book, gid, market, side, line, price in rows:
        out.setdefault(book, {"lines": []})["lines"].append(
            {"game_id": gid, "market": market, "side": side, "line": line, "price": price}
        )
    return out


def test_book_line_upgrades_tier_and_records_draftkings():
    # home -3.5 at DK, DS by 7 (+3.5), MB by 10 (+6.5) -> lean; at Circa -3: +4.0 / +7.0 -> strong
    s = slate(game("1", "nba", -3.5, 220, (7, 220), (10, 220)))
    assert mp.find_picks(s)[0]["tier"] == "lean"
    books = _books(
        ("circa", "1", "spread", "home", -3.0, -110),
        ("williamhill", "1", "spread", "home", -3.5, -110),
    )
    p = mp.find_picks(s, books)[0]
    assert (p["tier"], p["line"], p["book"], p["label"]) == ("strong", -3.0, "circa", "H1 -3")
    assert (p["ds_edge"], p["mb_edge"], p["dk_line"], p["dk_price"]) == (4.0, 7.0, -3.5, -110)
    text = mp.render(s, [p], [p])
    assert "H1 -3 (-110 Circa)" in text


def test_book_quote_can_qualify_and_draftkings_wins_ties():
    # total 150 at DK: DS 147.5 (-2.5), MB 146 (-4): no pick; WH under 151 makes DS +3.5 -> lean
    s = slate(game("1", "ncaab", -2, 150, (0, 147.5), (0, 146)))
    assert mp.find_picks(s) == []
    p = mp.find_picks(s, _books(("williamhill", "1", "total", "under", 151, -110)))[0]
    assert (p["side"], p["line"], p["book"], p["tier"]) == ("under", 151.0, "williamhill", "lean")
    # same line and price as DK (spread away +8 at -105) -> stays a DraftKings pick
    s2 = slate(game("2", "ncaab", -8, 150, (2, 150), (3, 150)))
    p2 = mp.find_picks(s2, _books(("circa", "2", "spread", "away", 8, -105)))[0]
    assert "book" not in p2 and p2["line"] == 8
    # worse book line is ignored; better price at the same line is taken
    p3 = mp.find_picks(s2, _books(("circa", "2", "spread", "away", 7.5, +100)))[0]
    assert "book" not in p3
    p4 = mp.find_picks(s2, _books(("circa", "2", "spread", "away", 8, +100)))[0]
    assert (p4["book"], p4["price"]) == ("circa", 100)


def test_repriced_lists_earlier_picks_at_a_better_line(tmp_path):
    from datetime import datetime, timedelta

    # night run: home -7.5 at DK, DS by 13 (+5.5), MB by 17 (+9.5) -> top pick
    s = slate(game("1", "ncaab", -7.5, 150, (13, 150), (17, 150)))
    t0 = datetime.fromisoformat(s["created_at"])
    mp.write_run(s, t0, root=tmp_path)
    # next run: DK now -5.5, Circa -6 -> posted game, line moved our way -> repriced, not top
    s2 = dict(slate(game("1", "ncaab", -5.5, 150, (13, 150), (17, 150))),
              created_at=(t0 + timedelta(hours=16)).isoformat())  # fmt: skip
    books = _books(("circa", "1", "spread", "home", -6, -105))
    run, text = mp.write_run(s2, t0 + timedelta(hours=16), root=tmp_path, books=books)
    saved = json.loads((run / "picks.json").read_text())
    assert saved["top"] == [] and len(saved["repriced"]) == 1
    r = saved["repriced"][0]
    assert (r["line"], r["was_line"], r.get("book")) == (-5.5, -7.5, None)
    assert "Posted earlier, now at a better line" in text and "was -7.5" in text
    assert "1 game already posted in an earlier run left out." in text
    # a third run at the same line: the repriced -5.5 now counts as posted -> nothing new
    s3 = dict(s2, created_at=(t0 + timedelta(hours=20)).isoformat())
    run3, _ = mp.write_run(s3, t0 + timedelta(hours=20), root=tmp_path, books=books)
    assert json.loads((run3 / "picks.json").read_text())["repriced"] == []


def test_repriced_skips_worse_lines_and_big_college_dogs():
    posted = {("1", "spread", "away"): 16.5, ("2", "total", "over"): 140.0}
    picks = [
        {"game_id": "1", "league": "ncaab", "market": "spread", "side": "away", "line": 15.0,
         "min_edge": 6.0},
        {"game_id": "2", "league": "ncaab", "market": "total", "side": "over", "line": 140.5,
         "min_edge": 4.0},
    ]  # fmt: skip
    assert mp.better_than_posted(picks, posted) == []
    dog = [dict(picks[0], line=17.5)]  # better than +16.5, but beyond the big-dog cap
    assert mp.better_than_posted(dog, posted) == []


def test_grade_book_pick_pairs_with_draftkings_line():
    s = slate(game("1", "nba", -3.5, 220, (7, 220), (10, 220)))
    books = _books(("circa", "1", "spread", "home", -3.0, -110))
    picks = mp.find_picks(s, books)
    top = mp.top_picks(picks)
    mp.attach_books(top, books)
    con = _db([("1", "nba", 110, 107)], [])  # home by 3: -3 pushes, -3.5 loses
    rec = mp.grade_picks(con, [{"run": "r", "picks": picks, "top": top}])
    assert rec["top"]["record"] == "0-0-1" and rec["top_books"]["record"] == "0-0-1"
    assert rec["top_books_dk"]["record"] == "0-1-0"
