from test_ensemble_bets import FORM, PRED, _line, _raw

from deepsports.analysis import ensemble_bets as eb
from deepsports.analysis import manualbets_context as mbc


def _slate():
    g1 = eb.build_game(_raw(), {"last": _line()}, PRED, FORM, {}, {})  # BOS @ LAL, NBA
    g2 = eb.build_game(_raw("c1", "ncaab"), {"last": _line(total=140.5)}, None, FORM, {}, {})
    g3 = eb.build_game(_raw("g3"), {"last": _line()}, None, FORM, {}, {})
    g3["home"]["abbr"], g3["away"]["abbr"] = "NY", "SA"
    return {"created_at": "2026-11-07T22:00:00+00:00", "context_version": "ctx-v1",
            "unlined_games": 0, "games": [g1, g2, g3]}  # fmt: skip


EXPORT = {
    "created_at": "2026-11-07T21:55:00+00:00",
    "errors": {},
    "nba": {"games": [
        {"home": "LAL", "away": "BOS", "tip": "2026-11-07 19:10:00-08:00", "date": "2026-11-07",
         "model": {"home_win_prob": 0.55, "home_margin": 2.0},
         "best_prices": {"spread": {"books": 9,
                                    "home": {"point": -3.0, "price": -110, "book": "fanduel"},
                                    "away": {"point": 3.5, "price": -105, "book": "betmgm"}},
                         "moneyline": {"books": 9, "home": {"price": -150, "book": "lowvig"}}},
         "recommendations": [{"market": "spread", "side": "away", "team": "BOS", "line": 3.5,
                              "price": -105, "book": "betmgm", "win_prob": 0.61, "edge": 4.2,
                              "edge_unit": "points", "kelly_fraction": 0.04}]},
        {"home": "NYK", "away": "SAS", "tip": "2026-11-07 19:10:00-08:00",
         "model": {"home_win_prob": 0.7, "home_margin": 6.5}, "recommendations": []},
        {"home": "LAL", "away": "BOS", "tip": "2026-11-09 19:10:00-08:00",  # another day
         "model": {"home_win_prob": 0.1}, "recommendations": []},
    ]},
    "ncaab": {"min_games_played_gate": 5, "games": [
        {"game_id": "c1", "home": "LAL", "away": "BOS", "gated": True, "min_games_played": 2,
         "model": {"home_win_prob": 0.8, "home_margin": 9.1, "total": 141.2},
         "recommendations": []}]},
}  # fmt: skip


def test_attach_matches_by_team_date_and_game_id():
    slate = mbc.attach_manualbets(_slate(), EXPORT)
    g1, g2, g3 = slate["games"]
    assert g1["manualbets"]["model"]["home_win_prob"] == 0.55  # same day, not Nov 9's
    assert g2["manualbets"]["gated"] is True
    assert g3["manualbets"]["model"]["home_margin"] == 6.5  # NYK/SAS -> NY/SA
    assert slate["manualbets"]["matched_games"] == 3
    assert slate["context_version"] == "ctx-v1+mb1"


def test_render_shows_model_prices_and_kelly_fraction():
    slate = mbc.attach_manualbets(_slate(), EXPORT)
    text = eb.render_context(slate, seed=0)
    assert "- ManualBets model: LAL 55% to win, margin LAL +2" in text
    assert "spread BOS +3.5 -105 (betmgm) / LAL -3 -110 (fanduel) across 9 books" in text
    assert (
        "BOS spread +3.5 -105 (betmgm): win prob 61%, edge 4.2 pts, Kelly 4.0% of bankroll" in text
    )
    assert "bets withheld: a team has played only 2 games" in text
    assert "second, independent pipeline" in text
    assert "ManualBets recommends: nothing on this game" in text  # NY game, no picks
    assert "$" not in text  # stakes never in dollars


def test_missing_export_or_league_is_said_out_loud():
    slate = mbc.attach_manualbets(_slate(), None)
    assert "unavailable for this slate" in eb.render_context(slate, seed=0)
    assert slate["context_version"] == "ctx-v1"
    slate = mbc.attach_manualbets(
        _slate(), {"errors": {"nba": "timeout"}, "ncaab": EXPORT["ncaab"]}
    )
    text = eb.render_context(slate, seed=0)
    assert "ManualBets NBA facts are missing today (timeout)" in text
    assert "ManualBets model" in text  # college still attached
