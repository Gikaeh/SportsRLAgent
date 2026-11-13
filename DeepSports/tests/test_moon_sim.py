from __future__ import annotations

import pytest

from deepsports.moon import sim, tiers


def test_single_minus_110_ev_is_minus_vig():
    o = sim.bet_odds(1, -110)
    assert o.american == -110
    assert o.p_hit == pytest.approx(0.5)
    assert o.ev == pytest.approx(-0.04545, abs=1e-4)
    assert pytest.approx(-1 / 22) == sim.DEFAULT_EV


def test_parlay_pricing_compounds_vig_per_leg():
    assert sim.american(sim.parlay_decimal([-110, -110])) == 264
    assert sim.american(sim.parlay_decimal([-110] * 3)) == 596
    assert sim.american(sim.parlay_decimal([-110] * 4)) == 1228
    for n in (2, 3, 4):
        o = sim.bet_odds(n, -110)
        assert o.p_hit == pytest.approx(0.5**n)
        assert o.ev == pytest.approx((1 + sim.DEFAULT_EV) ** n - 1)
    assert sim.bet_odds(3).ev < sim.bet_odds(2).ev < sim.bet_odds(1).ev < 0


def test_american_round_trip():
    for p in (-250, -110, 100, 150, 300, 1228):
        assert sim.american(sim.decimal(p)) == p
    with pytest.raises(ValueError):
        sim.decimal(50)


def test_impossible_edge_rejected():
    with pytest.raises(ValueError):
        sim.bet_odds(1, -1000, ev_leg=0.2)


def test_keep_the_cash_is_exact():
    r = sim.simulate("cash", 75, 1000, paths=500)
    assert r.median == r.p10 == r.p90 == 900
    assert r.p_reach == 0 and r.p_lose_half == 0 and r.months_mostly_lost == 0
    r = sim.simulate("cash", 100, 1000, paths=500)
    assert r.p_reach == 1


def test_seeded_and_reproducible():
    a = sim.simulate("bold", 75, 1000, paths=2000, seed=3)
    b = sim.simulate("bold", 75, 1000, paths=2000, seed=3)
    c = sim.simulate("bold", 75, 1000, paths=2000, seed=4)
    assert a == b
    assert a != c


def test_mean_ending_balance_reflects_negative_ev():
    # every betting tier loses money on average at -vig
    for t in tiers.TIERS[1:]:
        r = sim.simulate(t, 75, 1000, paths=4000)
        assert r.mean_end < r.deposits, t.key


def test_bold_beats_timid_on_p_target_with_negative_ev():
    """Dubins-Savage: with a subfair game, bold play maximises P(reach target)."""
    timid = sim.simulate("timid", 75, 1000, paths=6000)
    units = sim.simulate("units", 75, 1000, paths=6000)
    bold = sim.simulate("bold", 75, 1000, paths=6000)
    save = sim.simulate("save-bold", 75, 1000, paths=6000)
    assert timid.p_reach < units.p_reach < bold.p_reach < save.p_reach
    # ...and the bold tiers' downside is visible, not hidden
    assert bold.p_lose_half > timid.p_lose_half
    assert save.p_zero > 0.05


def test_save_then_bold_matches_bold_play_theory():
    # $900 saved, $1,000 target: a fair game gives 0.9; the vig costs a few points
    r = sim.simulate("save-bold", 75, 1000, paths=20000)
    assert 0.83 < r.p_reach < 0.9


def test_touch_at_least_reach_and_cash_out_locks_it():
    for key in ("timid", "units", "ticket4"):
        r = sim.simulate(key, 75, 1000, paths=3000)
        assert r.p_touch >= r.p_reach
    off = sim.simulate("units", 75, 1000, paths=3000, cash_out=False)
    on = sim.simulate("units", 75, 1000, paths=3000, cash_out=True)
    assert on.p_reach == pytest.approx(on.p_touch)
    assert on.p_reach > off.p_reach


def test_hypothetical_edge_raises_odds():
    base = sim.simulate("units", 75, 1000, paths=4000)
    edge = sim.simulate("units", 75, 1000, paths=4000, ev_leg=0.03)
    assert edge.p_reach > base.p_reach
    assert edge.mean_end > base.mean_end


def test_monthly_ticket_months_mostly_lost_is_high():
    r = sim.simulate("ticket4", 75, 1000, paths=4000, cash_out=False)
    assert r.months_mostly_lost > 0.9  # most monthly tickets go to zero


def test_ladder_and_render():
    res = sim.ladder(75, 1000, paths=500)
    assert [r.tier_id for r in res] == [t.id for t in tiers.TIERS]
    text = sim.render_ladder(res)
    assert "Keep the cash" in text and "Save, then bold" in text
    md = sim.render_ladder(res, markdown=True)
    assert md.startswith("| # |")
    assert sim.best_tier(res).tier_id == 10


def test_tier_lookup():
    assert tiers.get(9).key == "bold"
    assert tiers.get("9").key == "bold"
    assert tiers.get("Bold").id == 9
    with pytest.raises(ValueError):
        tiers.get("moonshot")
