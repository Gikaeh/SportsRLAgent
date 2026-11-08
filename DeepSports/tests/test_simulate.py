"""Betting simulation (analysis/simulate.py). Synthetic data only."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from deepsports.analysis import simulate as S
from deepsports.analysis.simulate import (
    PRICE_110,
    Bet,
    bootstrap,
    coin_flip,
    flat_dollars,
    flat_pct,
    kelly_fraction,
    quarter_kelly,
    select_bets,
    simulate,
)

T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)  # 7 pm Eastern on Dec 31


def bet(i: int, result: int, day: int | None = None, decimal: float = PRICE_110, p=None) -> Bet:
    start = T0 + timedelta(days=i if day is None else day, minutes=i)
    return Bet(
        game_id=f"g{i}",
        start=start,
        day=S.game_day(start),
        season=2024,
        market="spread",
        side="home",
        decimal=decimal,
        result=result,
        alt_side="away",
        alt_decimal=decimal,
        alt_result=-result,
        p_win=p,
    )


def test_known_sequence_exact_bankroll():
    # win, loss, push, win on separate days at -110, flat $2
    bets = [bet(0, 1), bet(1, -1), bet(2, 0), bet(3, 1)]
    sim = simulate(bets, flat_dollars(2), 100)
    expect = 100 + 2 * (100 / 110) - 2 + 0 + 2 * (100 / 110)
    assert sim["summary"]["final"] == pytest.approx(expect)
    assert [round(d["bankroll"], 6) for d in sim["daily"]] == [
        round(100 + 200 / 110, 6),
        round(100 + 200 / 110 - 2, 6),
        round(100 + 200 / 110 - 2, 6),
        round(expect, 6),
    ]
    s = sim["summary"]
    assert (s["wins"], s["losses"], s["pushes"], s["bets"]) == (2, 1, 1, 4)
    assert s["staked"] == pytest.approx(8)
    assert s["roi"] == pytest.approx((expect - 100) / 8)
    assert s["hit_rate"] == pytest.approx(2 / 3)


def test_percent_sizing_compounds_and_rounds_down_to_cents():
    bets = [bet(0, 1), bet(1, 1)]
    sim = simulate(bets, flat_pct(0.02), 100)
    b1 = 100 + 2 * (100 / 110)  # 101.8181...
    st2 = int(b1 * 0.02 * 100) / 100  # 2.03
    assert sim["ledger"][1]["stake"] == pytest.approx(st2)
    assert sim["summary"]["final"] == pytest.approx(b1 + st2 * 100 / 110)


def test_push_returns_stake():
    sim = simulate([bet(0, 0), bet(1, 0)], flat_dollars(5), 100)
    assert sim["summary"]["final"] == pytest.approx(100)
    assert sim["summary"]["pushes"] == 2
    assert sim["summary"]["staked"] == pytest.approx(10)


def test_same_day_sized_from_start_of_day_bankroll():
    # three games the same evening: all 10% of the start-of-day $100, even after a win
    same = [bet(i, r, day=0) for i, r in enumerate([1, 1, -1])]
    sim = simulate(same, flat_pct(0.10), 100)
    assert [x["stake"] for x in sim["ledger"]] == [10, 10, 10]
    assert len(sim["daily"]) == 1
    assert sim["summary"]["final"] == pytest.approx(100 + 2 * 10 * 100 / 110 - 10)
    # the next day is sized from the updated bankroll
    nxt = simulate(same + [bet(9, 1, day=1)], flat_pct(0.10), 100)
    assert nxt["ledger"][-1]["stake"] == pytest.approx(
        int((100 + 2000 / 110 - 10) * 0.1 * 100) / 100
    )


def test_day_stakes_never_exceed_bankroll():
    # $30 bankroll, flat $20 on two games the same day: the second gets only the $10 left
    sim = simulate([bet(0, -1, day=0), bet(1, -1, day=0)], flat_dollars(20), 30)
    assert [x["stake"] for x in sim["ledger"]] == [20, 10]
    assert sim["summary"]["final"] == 0


def test_stops_at_zero():
    bets = [bet(i, -1) for i in range(10)] + [bet(20, 1)]
    sim = simulate(bets, flat_dollars(30), 100)
    assert [x["stake"] for x in sim["ledger"]] == [30, 30, 30, 10]
    assert sim["summary"]["final"] == 0
    assert sim["summary"]["busted"] is not None
    assert sim["summary"]["bets"] == 4  # the later winner was never placed
    assert all(d["bankroll"] >= 0 for d in sim["daily"])


def test_no_lookahead_future_results_do_not_change_earlier_bets():
    rng = random.Random(1)
    bets = [bet(i, rng.choice([1, -1, 0]), day=i // 3) for i in range(60)]
    base = simulate(bets, flat_pct(0.05), 100)
    cut = 30  # day 10 starts at bet 30
    future = [b.result for b in bets[cut:]]
    rng.shuffle(future)
    shuffled = bets[:cut] + [
        Bet(**{**b.__dict__, "result": r, "alt_result": -r})
        for b, r in zip(bets[cut:], future, strict=True)
    ]
    other = simulate(shuffled, flat_pct(0.05), 100)
    # every stake through day 10 (bets 0-32) only depends on results of days before it
    stakes = lambda s: [x["stake"] for x in s["ledger"]][: cut + 3]  # noqa: E731
    assert stakes(base) == stakes(other)
    assert base["daily"][:10] == other["daily"][:10]


def _game(i, margin, total, spread=-3.0, ou=220.0, pm=5.0, pt=225.0, p=0.6, hml=-150, aml=130):
    start = T0 + timedelta(days=i)
    line = {"spread_home": spread, "over_under": ou, "home_ml": hml, "away_ml": aml}
    return {
        "game_id": f"g{i}",
        "season": 2024,
        "start": start,
        "p_home_win": p,
        "pred_home_margin": pm,
        "pred_total": pt,
        "home_margin": margin,
        "total": total,
        "lines": {"closing": line},
        "b2b": False,
    }


def test_select_bets_sides_and_results():
    g = _game(0, margin=3, total=215)  # home wins by 3 on a -3 spread: push; under
    (sp,) = select_bets([g], "spread", rule="model", threshold=1.0)
    assert (sp.side, sp.result, sp.alt_result) == ("home", 0, 0)  # model 5 vs market 3
    (tot,) = select_bets([g], "total", rule="model", threshold=4.0)
    assert (tot.side, tot.result) == ("over", -1)
    assert select_bets([g], "total", rule="model", threshold=6.0) == []
    (ml,) = select_bets([g], "moneyline", rule="model", threshold=0.0)
    # market: 0.6/(0.6+0.4348) = 0.58 < model 0.6 -> home at -150
    assert ml.side == "home" and ml.result == 1 and ml.decimal == pytest.approx(1 + 100 / 150)
    assert select_bets([g], "moneyline", rule="model", threshold=0.05) == []
    (fav,) = select_bets([g], "moneyline", rule="favorite")
    assert fav.side == "home"
    away = _game(1, margin=-4, total=230, pm=-1.0)  # model -1 vs market +3: away
    (sp,) = select_bets([away], "spread")
    assert (sp.side, sp.result) == ("away", 1)
    assert select_bets([away], "spread", timing="opening") == []  # no opening line


def test_bet_selection_ignores_outcomes():
    gs = [_game(i, margin=random.Random(i).randint(-20, 20), total=220) for i in range(20)]
    flipped = [{**g, "home_margin": -g["home_margin"], "total": 440 - g["total"]} for g in gs]
    for market in ("spread", "total", "moneyline"):
        a = [(b.game_id, b.side) for b in select_bets(gs, market)]
        b = [(b.game_id, b.side) for b in select_bets(flipped, market)]
        assert a == b


def test_kelly_fraction():
    assert kelly_fraction(0.55, 2.0, 1.0, 1.0) == pytest.approx(0.10)
    assert kelly_fraction(0.55, 2.0) == pytest.approx(0.025)  # quarter
    assert kelly_fraction(0.9, 2.0) == pytest.approx(0.05)  # capped at 5%
    assert kelly_fraction(0.4, 2.0) == 0.0  # no value: no bet
    bets = [bet(0, 1, decimal=2.0, p=0.4), bet(1, 1, decimal=2.0, p=0.55)]
    sim = simulate(bets, quarter_kelly(), 100)
    assert [x["bet"].game_id for x in sim["ledger"]] == ["g1"]
    assert sim["summary"]["final"] == pytest.approx(102.5)


def test_bootstrap_and_coin_flip_are_seeded_and_sane():
    bets = [bet(i, 1 if i % 2 else -1) for i in range(40)]
    a = bootstrap(bets, flat_dollars(2), 100, n_boot=300, seed=3)
    b = bootstrap(bets, flat_dollars(2), 100, n_boot=300, seed=3)
    assert a == b
    assert a["p5"] <= a["median"] <= a["p95"]
    # 50% at -110: the median ends a little under the start
    assert 90 < a["median"] < 100
    all_win = bootstrap([bet(i, 1) for i in range(10)], flat_dollars(2), 100, n_boot=50)
    assert all_win["p5"] == pytest.approx(100 + 10 * 200 / 110)
    c = coin_flip(bets, flat_dollars(2), 100, runs=200, seed=3)
    assert c == coin_flip(bets, flat_dollars(2), 100, runs=200, seed=3)
    assert c["p5"] <= c["mean_final"] <= c["p95"]


def test_drawdown_and_streak():
    bets = [bet(0, 1), bet(1, -1), bet(2, 0), bet(3, -1), bet(4, -1), bet(5, 1), bet(6, -1)]
    s = simulate(bets, flat_dollars(10), 100)["summary"]
    assert s["longest_losing"] == 3  # the push doesn't break the streak
    peak = 100 + 1000 / 110
    trough = peak - 30 + 1000 / 110 - 10  # three losses, a win, a loss
    assert s["max_dd_usd"] == pytest.approx(peak - trough)
    assert s["max_dd"] == pytest.approx((peak - trough) / peak)


def test_game_day_is_eastern():
    late = datetime(2024, 1, 2, 3, 30, tzinfo=UTC)  # 10:30 pm ET on Jan 1
    assert S.game_day(late).isoformat() == "2024-01-01"


def test_out_of_order_bets_rejected():
    with pytest.raises(ValueError):
        simulate([bet(5, 1), bet(1, 1)], flat_dollars(2), 100)


# ---------- real spread/total prices ----------


def _priced(i, sh=-120, sa=100, ov=-105, un=None, **kw):
    g = _game(i, **kw)
    ln = dict(g["lines"]["closing"])
    ln.update(spread_home_price=sh, spread_away_price=sa, over_price=ov, under_price=un)
    return {**g, "lines": {"closing": ln}}


def test_side_price_real_fallback_and_flat():
    ln = {"spread_home_price": -120, "spread_away_price": 100, "over_price": 50,
          "under_price": None}  # fmt: skip
    assert S.side_price(ln, "home") == (pytest.approx(1 + 100 / 120), True)
    assert S.side_price(ln, "away") == (pytest.approx(2.0), True)
    assert S.side_price(ln, "over") == (PRICE_110, False)  # invalid American price
    assert S.side_price(ln, "under") == (PRICE_110, False)  # NULL
    assert S.side_price({}, "home") == (PRICE_110, False)  # row without price columns
    assert S.side_price(ln, "home", "-110") == (PRICE_110, False)
    with pytest.raises(ValueError):
        S.side_price(ln, "home", "-115")


def test_select_bets_prices_each_side_and_never_changes_the_pick():
    g = _priced(0, margin=3, total=215)
    (sp,) = select_bets([g], "spread", threshold=1.0)  # model likes home
    assert sp.side == "home" and sp.decimal == pytest.approx(1 + 100 / 120) and sp.real_price
    assert sp.alt_decimal == pytest.approx(2.0)  # the coin flip's other side has its own price
    (tot,) = select_bets([g], "total", threshold=4.0)  # over at -105
    assert tot.decimal == pytest.approx(1 + 100 / 105) and tot.real_price
    assert tot.alt_decimal == PRICE_110  # under price NULL -> -110
    flat = select_bets([g], "spread", threshold=1.0, pricing="-110")
    assert flat[0].decimal == PRICE_110 and not flat[0].real_price
    # the same games with very different prices pick exactly the same sides
    cheap = [
        _priced(i, sh=150, sa=-300, margin=i - 5, total=220, pm=i - 2.5, pt=215.5 + i)
        for i in range(10)
    ]
    dear = [
        _priced(i, sh=-300, sa=150, margin=i - 5, total=220, pm=i - 2.5, pt=215.5 + i)
        for i in range(10)
    ]
    for market in ("spread", "total"):
        a = [(b.game_id, b.side) for b in select_bets(cheap, market)]
        b = [(b.game_id, b.side) for b in select_bets(dear, market)]
        assert a == b and len({side for _, side in a}) == 2  # both sides get picked


def test_fallback_bet_uses_minus_110_and_is_counted():
    g = _priced(0, margin=-4, total=230, pm=-1.0, sh=-120, sa=None)  # model likes away
    (sp,) = select_bets([g], "spread")
    assert (sp.side, sp.decimal, sp.real_price) == ("away", PRICE_110, False)
    st = S.price_stats([sp], unit=2.0)
    assert st["fallback"] == 1 and st["n"] == 1


def test_price_stats():
    a = bet(0, 1, decimal=2.0)  # +100, won: +0.1818 extra per $2
    b = bet(1, -1, decimal=1 + 100 / 120)  # -120, lost: costs nothing extra
    st = S.price_stats([a, b], unit=2.0)
    assert st["mean_decimal"] == pytest.approx((2.0 + 1 + 100 / 120) / 2)
    assert st["break_even"] == pytest.approx((0.5 + 120 / 220) / 2)
    assert st["realized"] == pytest.approx(2 * (2.0 - PRICE_110) / 2)
    assert st["win_diff"] == pytest.approx(2 * (st["mean_decimal"] - PRICE_110))
    ml = Bet(**{**a.__dict__, "market": "moneyline"})
    assert S.price_stats([ml]) is None


def test_load_lines_reads_prices_and_tolerates_old_schema():
    import duckdb

    con = duckdb.connect()
    base = """CREATE TABLE odds_snapshots (game_id VARCHAR, source VARCHAR, provider VARCHAR,
        captured_at TIMESTAMP, spread_home DOUBLE, over_under DOUBLE, home_moneyline INT,
        away_moneyline INT{extra})"""
    con.execute(base.format(extra=", spread_home_price INT, spread_away_price INT, "
                                  "over_price INT, under_price INT"))  # fmt: skip
    con.execute("INSERT INTO odds_snapshots VALUES ('g', 'closing', 'p', '2024-01-01', -3, 220,"
                " -150, 130, -115, -105, -110, NULL)")  # fmt: skip
    ln = S.load_lines(con)["g"]["closing"]
    got = (ln["spread_home_price"], ln["spread_away_price"], ln["under_price"])
    assert got == (-115, -105, None)
    old = duckdb.connect()
    old.execute(base.format(extra=""))
    old.execute("INSERT INTO odds_snapshots VALUES ('g', 'closing', 'p', '2024-01-01', -3, 220,"
                " -150, 130)")  # fmt: skip
    ln = S.load_lines(old)["g"]["closing"]
    assert ln["over_price"] is None and S.side_price(ln, "over") == (PRICE_110, False)
