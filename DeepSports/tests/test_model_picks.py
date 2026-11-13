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


def test_write_and_grade(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    import duckdb

    s = slate(game("1", "nba", -5, 200, (10, 196), (10, 195)))
    run, _ = mp.write_run(s, datetime(2026, 11, 13, 22, tzinfo=UTC), root=tmp_path)
    saved = json.loads((run / "picks.json").read_text())
    assert saved["rule_version"] == mp.RULE_VERSION and len(saved["top"]) == 1
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE games (game_id VARCHAR, home_score INT, away_score INT,"
        " completed BOOLEAN, status VARCHAR)"
    )
    con.execute("INSERT INTO games VALUES ('1', 110, 100, true, 'STATUS_FINAL')")
    rec = mp.grade_runs(con, root=tmp_path)
    # home -5 wins by 10 -> win; under 200 with 210 -> loss
    assert rec["strong"]["record"] == "1-1-0" and rec["top"]["bets"] == 1
