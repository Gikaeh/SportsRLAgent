"""Betting library (deepsports.analysis.betting): exact grading semantics, CLV signs, the
day-clustered bootstrap, price sensitivity, the line-move audit, and the loaders.
Ported from the DeepSeek edge study's lab tests; synthetic data only."""

import json
from datetime import UTC, datetime
from fractions import Fraction

import pytest

from deepsports.analysis.betting import (
    AuditResult,
    GradeResult,
    audit,
    bootstrap_ci,
    bootstrap_rois,
    drawdown,
    flag_moves,
    grade,
    grade_bet,
    load_games,
    load_lines,
    load_odds,
    load_odds_raw,
    move_medians,
    read_raw_summary,
)
from deepsports.store import Store

P110 = 10 / 11  # profit on a winning 1-unit bet at -110


def game(gid, home, away, date="2025-01-01", **kw):
    row = {"game_id": gid, "home_score": home, "away_score": away, "tip_date": date}
    row.update(kw)
    return row


def bet(gid, market, side, line=None, price=None, stake=1.0, timing="close", **kw):
    row = {
        "game_id": gid,
        "market": market,
        "side": side,
        "stake": stake,
        "timing": timing,
        "variant": "t",
        "notes": "n",
    }
    if line is not None:
        row["line"] = line
    if price is not None:
        row["price"] = price
    row.update(kw)
    return row


def single(b, g, lines=None):
    out = grade_bet(
        {
            "game_id": "g",
            "market": b[0],
            "side": b[1],
            "line": b[2] if b[0] != "moneyline" else None,
            "price": b[3] if len(b) > 3 else None,
            "stake": 1.0,
            "timing": "close",
        },
        {
            "game_id": "g",
            "home_score": g[0],
            "away_score": g[1],
            "margin": g[0] - g[1],
            "total": g[0] + g[1],
            "tip_date": "2025-01-01",
        },
        lines,
    )
    return out["grade"], out["profit"]


# ---------------------------------------------------------------------------
# Spread
# ---------------------------------------------------------------------------
def test_spread_home_win_push_loss():
    # margin +10
    for line, want in [(-4, "win"), (-10, "push"), (-12, "loss")]:
        got, profit = single(("spread", "home", line, -110), (110, 100))
        assert got == want
        assert profit == pytest.approx({"win": P110, "push": 0.0, "loss": -1.0}[want])


def test_spread_away_win_push_loss():
    # margin +10 (home won by 10); away at line L wins iff margin + L < 0
    for line, want in [(-12, "win"), (-10, "push"), (-4, "loss"), (12, "loss")]:
        got, profit = single(("spread", "away", line, -110), (110, 100))
        assert got == want
        assert profit == pytest.approx({"win": P110, "push": 0.0, "loss": -1.0}[want])


def test_spread_away_negative_margin():
    # margin -10 (away won by 10): away -4 is a win, home -4 is a loss
    assert single(("spread", "away", -4, -110), (90, 100)) == ("win", pytest.approx(P110))
    assert single(("spread", "home", -4, -110), (90, 100)) == ("loss", -1.0)
    # away +4 (away favored by 4, i.e. home +4): away won by 10 -> win
    assert single(("spread", "away", 4, -110), (90, 100)) == ("win", pytest.approx(P110))
    # away at L = -10 means away GETS 10 points: away won by 10 -> win by 20
    assert single(("spread", "away", -10, -110), (90, 100)) == ("win", pytest.approx(P110))
    # away at L = +10 means away LAYS 10: away must win by > 10; won by exactly 10 -> push
    assert single(("spread", "away", 10, -110), (90, 100)) == ("push", 0.0)


def test_spread_default_price_is_minus_110():
    res = grade(
        [
            {
                "game_id": "g1",
                "market": "spread",
                "side": "home",
                "line": -4,
                "stake": 1.0,
                "timing": "close",
            }
        ],
        [game("g1", 110, 100)],
    )
    out = res.bets[0]
    assert out["grade"] == "win"
    assert out["profit"] == pytest.approx(P110)
    assert out["price"] == -110


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------
def test_total_over_under():
    for side, line, want in [
        ("over", 209.5, "win"),
        ("over", 210, "push"),
        ("over", 215, "loss"),
        ("under", 211, "win"),
        ("under", 210, "push"),
        ("under", 205, "loss"),
    ]:
        got, profit = single(("total", side, line, -110), (110, 100))
        assert got == want
        assert profit == pytest.approx({"win": P110, "push": 0.0, "loss": -1.0}[want])


# ---------------------------------------------------------------------------
# Moneylines
# ---------------------------------------------------------------------------
def test_moneyline_payouts():
    # home won by 10; stake 1 in `single` (unit profits below)
    for price, want in [(150, 1.5), (-150, 100 / 150), (100, 1.0), (0, 1.0)]:
        got, profit = single(("moneyline", "home", None, price), (110, 100))
        assert got == "win"
        assert profit == pytest.approx(want)
    # away moneyline: away won by 10
    assert single(("moneyline", "away", None, 130), (90, 100))[0] == "win"
    assert single(("moneyline", "away", None, 130), (90, 100))[1] == pytest.approx(1.3)
    # losing bets lose the stake
    assert single(("moneyline", "away", None, -200), (110, 100)) == ("loss", -1.0)
    assert single(("moneyline", "home", None, -110), (90, 100)) == ("loss", -1.0)


def test_moneyline_has_no_push():
    # a tie is impossible in basketball, so margin == 0 would be a loss for home
    assert single(("moneyline", "home", None, -110), (100, 100)) == ("loss", -1.0)


def test_invalid_price_rejected():
    with pytest.raises(ValueError, match="American price"):
        grade([bet("g1", "moneyline", "home", price=-90)], [game("g1", 110, 100)])
    with pytest.raises(ValueError, match="require a price"):
        grade([bet("g1", "moneyline", "home")], [game("g1", 110, 100)])


# ---------------------------------------------------------------------------
# Push accounting
# ---------------------------------------------------------------------------
def test_push_excluded_from_winpct_but_in_roi_denominator():
    bets = [
        bet("g1", "spread", "home", line=-4),  # win, +10/11
        bet("g1", "total", "over", line=210),  # push, 0
    ]
    res = grade(bets, [game("g1", 110, 100)])
    assert res.summary["record"] == "1-0-1"
    assert res.summary["win_pct"] == 1.0
    assert res.summary["roi"] == pytest.approx(P110 / 2)
    assert res.summary["units"] == pytest.approx(P110)


# ---------------------------------------------------------------------------
# CLV sign conventions (all six market x side cases, exact numbers)
# ---------------------------------------------------------------------------
LINES = {
    "game_id": "g1",
    "open_spread_home": -5,
    "close_spread_home": -7,
    "open_total": 220,
    "close_total": 224,
    "open_home_ml": -120,
    "open_away_ml": 100,
    "close_home_ml": -150,
    "close_away_ml": 130,
}
# exact devigged probabilities:
#   open: d_home = 11/6, d_away = 2   -> p_open = 12/23
#   close: d_home = 5/3, d_away = 2.3 -> p_close = 69/119
P_OPEN, P_CLOSE = Fraction(12, 23), Fraction(69, 119)


def clv_of(market, side, lines=LINES, timing="open"):
    out = grade_bet(
        {
            "game_id": "g1",
            "market": market,
            "side": side,
            "line": 0 if market == "moneyline" else -5,
            "price": -110,
            "stake": 1.0,
            "timing": timing,
            "variant": "",
            "notes": "",
        },
        {
            "game_id": "g1",
            "home_score": 110,
            "away_score": 100,
            "margin": 10,
            "total": 210,
            "tip_date": "2025-01-01",
        },
        lines,
    )
    return out["clv"]


def test_clv_spread_home_exact():
    assert clv_of("spread", "home") == pytest.approx(-5 - -7)  # +2


def test_clv_spread_away_exact():
    assert clv_of("spread", "away") == pytest.approx(-7 - -5)  # -2


def test_clv_total_over_exact():
    assert clv_of("total", "over") == pytest.approx(224 - 220)  # +4


def test_clv_total_under_exact():
    assert clv_of("total", "under") == pytest.approx(220 - 224)  # -4


def test_clv_moneyline_home_exact():
    expected = float(P_CLOSE - P_OPEN) * 100
    assert clv_of("moneyline", "home") == pytest.approx(expected)


def test_clv_moneyline_away_exact():
    expected = float(P_OPEN - P_CLOSE) * 100
    assert clv_of("moneyline", "away") == pytest.approx(expected)


def test_clv_positive_means_beat_the_close():
    # home -5 at the open, closes -3 (market moved toward the bet) -> negative CLV
    lines = {**LINES, "close_spread_home": -3}
    assert clv_of("spread", "home", lines) == pytest.approx(-2.0)


def test_clv_only_for_opening_bets_and_only_with_both_lines():
    assert clv_of("spread", "home", timing="close") is None
    assert clv_of("spread", "home", {**LINES, "open_spread_home": None}) is None
    assert clv_of("total", "over", {**LINES, "close_total": None}) is None
    assert clv_of("moneyline", "home", {**LINES, "close_away_ml": None}) is None


def test_clv_stats_exclude_ineligible_bets():
    bets = [
        bet("g1", "spread", "home", line=-5, timing="open"),
        bet("g2", "spread", "home", line=-5, timing="open"),  # no lines row -> no CLV
        bet("g3", "spread", "home", line=-5, timing="close"),
    ]
    lines = [
        {**LINES, "game_id": "g1"},
    ]
    res = grade(
        bets,
        [
            game("g1", 110, 100),
            game("g2", 110, 100, date="2025-01-02"),
            game("g3", 110, 100, date="2025-01-03"),
        ],
        lines,
    )
    assert res.summary["clv_n"] == 1
    assert res.summary["clv_mean"] == pytest.approx(2.0)
    assert res.summary["clv_pct_positive"] == 100.0
    assert res.bets[0]["clv"] == pytest.approx(2.0)
    assert res.bets[1]["clv"] is None
    assert res.bets[2]["clv"] is None


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------
def test_drawdown():
    units, pct = drawdown([-1, 2, -3], bankroll=10)
    assert units == pytest.approx(3.0)
    assert pct == pytest.approx(3 / 11)
    assert drawdown([], 10) == (None, None)
    assert drawdown([1], 0) == (None, None)
    # always profitable: no drawdown
    assert drawdown([1, 1], 10) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Day-clustered bootstrap
# ---------------------------------------------------------------------------
def test_bootstrap_resamples_whole_days():
    # day A: +1 on 1 staked; day B: -1 on 1 staked. Resampling DAYS means every
    # resample ROI is one of {-1, 0, +1} — a bet-level bootstrap could produce
    # values like +0.5 if it mixed, but days are the unit.
    rois = bootstrap_rois([1.0, -1.0], [1.0, 1.0], seed=42, n=2000)
    assert set(rois) == {-1.0, 0.0, 1.0}
    lo, hi = bootstrap_ci([1.0, -1.0], [1.0, 1.0], seed=42, n=2000)
    assert lo == -1.0
    assert hi == 1.0


def test_bootstrap_reproducible_with_fixed_seed():
    ci1 = bootstrap_ci([1.0, -1.0, 0.5], [1.0, 2.0, 1.0], seed=7, n=500)
    ci2 = bootstrap_ci([1.0, -1.0, 0.5], [1.0, 2.0, 1.0], seed=7, n=500)
    assert ci1 == ci2
    assert ci1[0] <= ci1[1]


def test_grade_bootstrap_reproducible_and_ci_contains_mean():
    bets = [bet(f"g{i}", "spread", "home", line=-4) for i in range(10)]
    games = [game(f"g{i}", 110 + i, 100, date=f"2025-01-{i // 5 + 1:02d}") for i in range(10)]
    r1 = grade(bets, games)
    r2 = grade(bets, games)
    assert r1.summary["ci_low"] == r2.summary["ci_low"]
    assert r1.summary["ci_high"] == r2.summary["ci_high"]
    assert r1.summary["ci_low"] <= r1.summary["roi"] <= r1.summary["ci_high"]


# ---------------------------------------------------------------------------
# Price sensitivity
# ---------------------------------------------------------------------------
def test_price_sensitivity_exact():
    # two winning spread bets, stake 100 each; ROI = profit / staked, so a winning
    # -105 pair returns 2*100*(100/105) profit on 200 staked = 20/21, etc.
    bets = [
        bet("g1", "spread", "home", line=-4, stake=100),  # margin +10 -> win
        bet("g2", "spread", "away", line=-4, stake=100),  # margin -10 -> win
    ]
    res = grade(bets, [game("g1", 110, 100), game("g2", 90, 100, date="2025-01-02")])
    ps = res.summary["price_sensitivity"]
    assert ps["roi_neg105"] == pytest.approx(20 / 21)
    assert ps["roi_neg110"] == pytest.approx(10 / 11)
    assert ps["roi_neg115"] == pytest.approx(20 / 23)
    # slippage: home -4 -> -4.5 (still a win by 5.5), away -4 -> -3.5 (still a win)
    assert ps["roi_neg110_slip05"] == pytest.approx(10 / 11)


def test_price_sensitivity_slippage_flips_grades():
    bets = [
        bet("g1", "total", "over", line=220.5, stake=1),  # total 221 -> win by 0.5
        bet("g2", "total", "under", line=220.5, stake=1),  # total 220 -> win by 0.5
    ]
    res = grade(bets, [game("g1", 111, 110), game("g2", 110, 110, date="2025-01-02")])
    ps = res.summary["price_sensitivity"]
    assert ps["roi_neg110"] == pytest.approx(2 * P110 / 2)
    # 0.5-pt slippage against the bettor turns both half-point wins into pushes
    assert ps["roi_neg110_slip05"] == 0.0


def test_price_sensitivity_none_without_spread_total_bets():
    bets = [bet("g1", "moneyline", "home", price=-110)]
    res = grade(bets, [game("g1", 110, 100)])
    ps = res.summary["price_sensitivity"]
    assert all(v is None for v in ps.values())


# ---------------------------------------------------------------------------
# End-to-end with hand-computed numbers
# ---------------------------------------------------------------------------
def test_end_to_end_hand_computed():
    bets = [
        bet("g1", "spread", "home", line=-4),  # win   +10/11
        bet("g1", "total", "over", line=200),  # loss  -1
        bet("g2", "spread", "away", line=-5),  # win   +10/11 (away won by 5, +5)
        bet("g2", "moneyline", "home", price=150),  # loss  -1
        bet("g3", "spread", "home", line=-1.5),  # loss  -1
        bet("g3", "total", "under", line=240),  # win   +10/11
        bet("g4", "spread", "away", line=5),  # push   0
        bet("g4", "moneyline", "away", price=-200),  # win   +1/2
        bet("g5", "total", "over", line=209.5),  # loss  -1
        bet("g5", "moneyline", "home", price=-110),  # win   +10/11
    ]
    games = [
        game("g1", 100, 90, "2025-01-01"),
        game("g2", 110, 115, "2025-01-01"),
        game("g3", 120, 119, "2025-01-02"),
        game("g4", 95, 100, "2025-01-03"),
        game("g5", 105, 104, "2025-01-03"),
    ]
    res = grade(bets, games)
    s = res.summary
    assert s["n"] == 10
    assert s["record"] == "5-4-1"
    assert s["win_pct"] == 5 / 9
    assert s["total_staked"] == 10.0
    assert s["roi"] == pytest.approx(3 / 220)
    assert s["units"] == pytest.approx(3 / 22)
    assert s["max_drawdown_units"] == pytest.approx(3 / 11)
    assert s["max_drawdown_pct"] == pytest.approx(3 / 110)
    assert s["n_days"] == 3
    # daily P&L: 01-01: -2/11, 01-02: -1/11, 01-03: +9/22
    assert [d["profit"] for d in res.daily] == pytest.approx([-2 / 11, -1 / 11, 9 / 22])
    assert [d["n"] for d in res.daily] == [4, 2, 4]
    assert res.daily[-1]["cum_profit"] == pytest.approx(3 / 22)
    # per-bet rows carry the pass-throughs and the grade
    assert res.bets[0]["variant"] == "t" and res.bets[0]["notes"] == "n"
    assert [b["grade"] for b in res.bets] == [
        "win",
        "loss",
        "win",
        "loss",
        "loss",
        "win",
        "push",
        "win",
        "loss",
        "win",
    ]


def test_end_to_end_open_bets_clv_and_no_tip_date():
    # no tip_date on games: grading still works, daily/CI/drawdown are absent
    bets = [bet("g1", "spread", "home", line=-4, timing="open")]
    res = grade(bets, [game("g1", 110, 100, date=None)], [{**LINES, "game_id": "g1"}])
    assert res.bets[0]["clv"] == pytest.approx(2.0)
    assert res.summary["n_days"] == 0
    assert res.summary["n_bets_no_tip_date"] == 1
    assert res.summary["max_drawdown_pct"] is None
    assert res.summary["ci_low"] is None and res.summary["ci_high"] is None


# ---------------------------------------------------------------------------
# Validation and input shapes
# ---------------------------------------------------------------------------
def test_missing_game_raises():
    with pytest.raises(ValueError, match="missing from `games`"):
        grade([bet("nope", "spread", "home", line=-4)], [game("g1", 110, 100)])


def test_duplicate_game_rows_raise():
    with pytest.raises(ValueError, match="duplicate game_id"):
        grade([bet("g1", "spread", "home", line=-4)], [game("g1", 110, 100), game("g1", 110, 100)])


def test_schema_validation():
    with pytest.raises(ValueError, match="market must be"):
        grade([bet("g1", "futures", "home", line=-4)], [game("g1", 110, 100)])
    with pytest.raises(ValueError, match="side"):
        grade([bet("g1", "spread", "over", line=-4)], [game("g1", 110, 100)])
    with pytest.raises(ValueError, match="side"):
        grade([bet("g1", "total", "home", line=210)], [game("g1", 110, 100)])
    with pytest.raises(ValueError, match="timing"):
        grade([bet("g1", "spread", "home", line=-4, timing="intraday")], [game("g1", 110, 100)])
    with pytest.raises(ValueError, match="require a line"):
        grade([bet("g1", "spread", "home")], [game("g1", 110, 100)])
    with pytest.raises(ValueError, match="require a line"):
        grade([bet("g1", "total", "over")], [game("g1", 110, 100)])
    with pytest.raises(ValueError, match="stake must be >= 0"):
        grade([bet("g1", "spread", "home", line=-4, stake=-1)], [game("g1", 110, 100)])


def test_dict_of_columns_and_dataframe_inputs():
    bets_cols = {
        "game_id": ["g1", "g1"],
        "market": ["spread", "spread"],
        "side": ["home", "home"],
        "line": [-4, -12],
        "stake": [1.0, 1.0],
        "timing": ["close", "close"],
    }
    games_cols = {
        "game_id": ["g1"],
        "home_score": [110],
        "away_score": [100],
        "tip_date": ["2025-01-01"],
    }
    r1 = grade(bets_cols, games_cols)
    assert [b["grade"] for b in r1.bets] == ["win", "loss"]

    class FakeFrame:
        def __init__(self, rows):
            self.rows = rows

        def to_dict(self, orient):
            assert orient == "records"
            return [dict(r) for r in self.rows]

    r2 = grade(
        FakeFrame(
            [
                {
                    "game_id": "g1",
                    "market": "spread",
                    "side": "home",
                    "line": -4,
                    "stake": 1.0,
                    "timing": "close",
                },
            ]
        ),
        FakeFrame(
            [
                {"game_id": "g1", "home_score": 110, "away_score": 100, "tip_date": "2025-01-01"},
            ]
        ),
    )
    assert r2.summary["record"] == "1-0-0"
    assert r2.summary["roi"] == pytest.approx(P110)


def test_to_csv(tmp_path):
    bets = [bet("g1", "spread", "home", line=-4), bet("g1", "total", "over", line=210)]
    res = grade(bets, [game("g1", 110, 100)])
    paths = res.to_csv(tmp_path, "fam1")
    assert len(paths) == 3
    bets_csv = tmp_path / "fam1_bets.csv"
    assert bets_csv.read_text().splitlines()[0].startswith("game_id")
    assert len(bets_csv.read_text().splitlines()) == 3  # header + 2 bets
    summary = json.loads((tmp_path / "fam1_summary.json").read_text())
    assert summary["record"] == "1-0-1"
    assert summary["roi"] == pytest.approx(P110 / 2)


def test_grade_result_type():
    res = grade([bet("g1", "spread", "home", line=-4)], [game("g1", 110, 100)])
    assert isinstance(res, GradeResult)
    assert isinstance(res.bets, list) and isinstance(res.summary, dict)


# ---------- audit ----------


def make_lines():
    """9 NBA games: spread moves [0.5 x3, 1.0 x5, 12.0] (median 1.0), total moves 2.0,
    moneyline moves 0."""
    spreads = [0.5, 0.5, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 12.0]
    rows = []
    for i, mv in enumerate(spreads):
        rows.append(
            {
                "game_id": f"g{i}",
                "league": "nba",
                "season_year": 2025,
                "open_spread_home": -5.0,
                "close_spread_home": -5.0 + mv,
                "open_total": 220.0,
                "close_total": 222.0,
                "open_home_ml": -110,
                "open_away_ml": -110,
                "close_home_ml": -110,
                "close_away_ml": -110,
            }
        )
    return rows


def make_games():
    return [
        {
            "game_id": f"g{i}",
            "league": "nba",
            "season_year": 2025,
            "home_score": 120,
            "away_score": 105,
            "tip_date": f"2025-01-{i + 1:02d}",
        }
        for i in range(9)
    ]


def test_move_medians_grouped_by_league_season_market():
    lines = make_lines() + [
        {
            **make_lines()[0],
            "game_id": "c0",
            "league": "ncaab",
            "season_year": 2026,
            "close_spread_home": -5.0 + 30.0,
        }
    ]
    medians = {  # (league, season, market) -> median
        (m["league"], m["season_year"], m["market"]): m["median_abs_move"]
        for m in move_medians(lines)
    }
    assert medians[("nba", 2025, "spread")] == 1.0
    assert medians[("nba", 2025, "total")] == 2.0
    assert medians[("nba", 2025, "ml")] == 0.0
    assert medians[("ncaab", 2026, "spread")] == 30.0


def test_flag_rule_more_than_3x_median():
    lines = make_lines()
    flagged = flag_moves(lines)  # default multiplier 3.0
    assert len(flagged) == 1
    f = flagged[0]
    assert f["game_id"] == "g8"
    assert f["market"] == "spread"
    assert f["abs_move"] == 12.0
    assert f["median_abs_move"] == 1.0
    assert f["ratio"] == 12.0
    # exactly 3x is NOT flagged
    lines[7]["close_spread_home"] = -5.0 + 3.0  # move 3.0 == 3 x median
    assert all(f["game_id"] == "g8" for f in flag_moves(lines))
    # a huge multiplier flags nothing
    assert flag_moves(lines, multiplier=20.0) == []


def test_audit_drops_only_flagged_market_and_lists_top_edges():
    lines = make_lines()
    games = make_games()
    bet_rows = [
        {"game_id": "g0", "market": "spread", "side": "home", "line": -4, "league": "nba"},
        {"game_id": "g1", "market": "spread", "side": "home", "line": -4, "league": "nba"},
        # flagged: g8 spread move is 12x the median
        {"game_id": "g8", "market": "spread", "side": "home", "line": -4, "league": "nba"},
        # kept: the total market is not flagged
        {"game_id": "g8", "market": "total", "side": "over", "line": 220, "league": "nba"},
        {"game_id": "g2", "market": "moneyline", "side": "home", "price": -110, "league": "nba"},
    ]
    graded = grade(bet_rows, games, lines).bets
    odds_raw = [
        {
            "game_id": "g0",
            "source": "opening",
            "captured_at": "2025-01-01T12:00:00Z",
            "spread_home": -5.0,
            "over_under": 220.0,
            "home_moneyline": -110,
            "away_moneyline": -110,
        },
        {
            "game_id": "g0",
            "source": "closing",
            "captured_at": "2025-01-02T01:00:00Z",
            "spread_home": -4.5,
            "over_under": 222.0,
            "home_moneyline": -110,
            "away_moneyline": -110,
        },
    ]
    res = audit(graded, games, lines, odds_raw, top_n=3)
    assert isinstance(res, AuditResult)
    assert res.dropped_count == 1
    assert res.dropped_bets[0]["game_id"] == "g8"
    assert res.dropped_bets[0]["market"] == "spread"
    assert res.dropped_bets[0]["flag_ratio"] == 12.0
    # kept winning bets sorted by edge:
    #   ml g2: margin 15 -> p_close = 0.5 -> edge 50.0 pct pts
    #   spread g0/g1: margin 15, line -4 -> edge 15 + (-4) = 11.0 points
    #   total over g8: total 225, line 220 -> edge 5.0 points
    assert [b["game_id"] for b in res.top_bets] == ["g2", "g0", "g1"]
    assert res.top_bets[0]["edge"] == pytest.approx(50.0)
    assert res.top_bets[1]["edge"] == pytest.approx(11.0)
    # raw odds rows attached to the game
    assert len(res.top_bets[1]["raw_odds"]) == 2
    assert res.top_bets[2]["raw_odds"] == []
    # dropped bets are not in the top list
    assert all(b["game_id"] != "g8" or b["market"] != "spread" for b in res.top_bets)
    assert "dropped 1" in res.report()


def test_audit_ml_edge_none_sorted_last():
    lines = make_lines()
    games = make_games()
    # g3 has no moneylines -> edge for the ml bet is None -> sorts last
    lines[3]["close_home_ml"] = None
    bet_rows = [
        {"game_id": "g0", "market": "spread", "side": "home", "line": -4, "league": "nba"},
        {"game_id": "g3", "market": "moneyline", "side": "home", "price": -110, "league": "nba"},
    ]
    graded = grade(bet_rows, games, lines).bets
    res = audit(graded, games, lines, top_n=5)
    assert res.top_bets[0]["game_id"] == "g0"
    assert res.top_bets[-1]["game_id"] == "g3"
    assert res.top_bets[-1]["edge"] is None


def test_audit_requires_graded_rows():
    # ungraded bet rows (no grade) raise a clear error instead of silently mis-auditing
    lines = make_lines()
    games = make_games()
    with pytest.raises(ValueError, match="missing 'grade'"):
        audit([{"game_id": "g0", "market": "spread", "side": "home"}], games, lines)


def test_audit_drops_flagged_moneyline_bets():
    """Regression (lab bug): the audit flags moneyline moves under market 'ml', and bets on a
    flagged game's moneyline must be dropped too (the lab version never matched them)."""
    lines = make_lines()
    for r in lines:  # small ML moves everywhere ...
        r["close_home_ml"], r["close_away_ml"] = -115, -105
    lines[4]["close_home_ml"], lines[4]["close_away_ml"] = -300, 250  # ... one huge one
    games = make_games()
    graded = grade(
        [{"game_id": "g4", "market": "moneyline", "side": "home", "price": -110}], games, lines
    ).bets
    res = audit(graded, games, lines)
    assert any(f["game_id"] == "g4" and f["market"] == "ml" for f in res.flagged_games)
    assert res.dropped_count == 1 and res.dropped_bets[0]["market"] == "moneyline"


# ---------- loaders (temp warehouse) ----------


def _loader_store() -> Store:
    s = Store(":memory:")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    s.upsert_teams(
        {"team_id": t, "league": "nba", "abbreviation": f"T{t}", "display_name": f"Team {t}"}
        for t in ("1", "2")
    )
    base = {
        "league": "nba",
        "season_year": 2026,
        "season_type": 2,
        "home_team_id": "1",
        "away_team_id": "2",
    }
    s.upsert_games(
        [
            {
                **base,
                "game_id": "g1",
                "start_time_utc": datetime(2026, 1, 2, 3, 30, tzinfo=UTC),  # 2026-01-01 ET
                "status": "STATUS_FINAL",
                "state": "post",
                "completed": True,
                "home_score": 110,
                "away_score": 100,
            },
            {
                **base,
                "game_id": "g2",
                "start_time_utc": datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
                "status": "STATUS_SCHEDULED",
                "state": "pre",
                "completed": False,
                "home_score": None,
                "away_score": None,
            },
        ]
    )

    def odds(source, at, spread, total, hml=-150, aml=130):
        return {
            "game_id": "g1",
            "source": source,
            "captured_at": at,
            "provider": "p",
            "details": "",
            "spread_home": spread,
            "over_under": total,
            "home_moneyline": hml,
            "away_moneyline": aml,
        }

    s.add_odds(
        [
            odds("opening", now, -4.0, 29.5),  # a broken total: outside the NBA limits
            odds("closing", now, -5.5, 221.5),
        ]
    )
    return s


def test_loaders_shape_and_sanity():
    s = _loader_store()
    games = load_games(s.con, league="nba")
    assert [g["game_id"] for g in games] == ["g1"]  # the scheduled game is not final
    g = games[0]
    assert g["tip_date"] == "2026-01-01"  # US/Eastern date of a 03:30 UTC tip
    assert (g["margin"], g["total"], g["home_abbr"]) == (10, 210, "T1")
    (line,) = load_lines(s.con, league="nba")
    assert line["open_spread_home"] == -4.0 and line["close_spread_home"] == -5.5
    assert line["open_total"] is None  # 29.5 fails the sanity limits
    assert line["close_total"] == 221.5
    assert load_lines(s.con, apply_sane=False)[0]["open_total"] == 29.5
    assert load_odds(s.con, "closing")[0]["over_under"] == 221.5
    assert {r["source"] for r in load_odds_raw(s.con, game_ids=["g1"])} == {"opening", "closing"}
    with pytest.raises(ValueError):
        load_odds(s.con, "midday")
    # grading straight from the loaders: home -4 at the open, closed -5.5 -> CLV +1.5
    res = grade(
        [{"game_id": "g1", "market": "spread", "side": "home", "line": -4, "timing": "open"}],
        games,
        load_lines(s.con),
    )
    assert res.bets[0]["grade"] == "win" and res.bets[0]["clv"] == pytest.approx(1.5)
    s.close()


def test_read_raw_summary(tmp_path):
    import gzip

    d = tmp_path / "espn" / "nba" / "summary"
    d.mkdir(parents=True)
    with gzip.open(d / "123.json.gz", "wt") as fh:
        json.dump({"header": {"id": "123"}}, fh)
    assert read_raw_summary("nba", "123", raw_dir=tmp_path) == {"header": {"id": "123"}}
    with pytest.raises(FileNotFoundError):
        read_raw_summary("nba", "999", raw_dir=tmp_path)
