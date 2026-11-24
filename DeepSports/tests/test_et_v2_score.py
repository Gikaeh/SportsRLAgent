import math

import numpy as np
import pytest

from deepsports.analysis import et_v2_score as S

WH = "williamhill_us"


def game(ds=150.0, mb=150.0, wh=140.0, **kw):
    g = {
        "season": 2024,
        "day": "2024-01-10",
        "ds": ds,
        "ds_alt": kw.pop("ds_alt", ds),
        "mb": mb,
        "gp": kw.pop("gp", 12),
        "played_d1": False,
        "lines": {WH: (wh, -110, -110)},
        "open15": {},
    }
    g["lines"].update(kw.pop("lines", {}))
    g.update(kw)
    return g


def test_base_side():
    assert S.base_side(150, 146, 140) == "over"  # edges 10 and 6, avg 8
    assert S.base_side(136, 135, 140) == "under"
    assert S.base_side(150, 139, 140) is None  # disagree
    assert S.base_side(143, 144, 140) is None  # avg 3.5
    assert S.base_side(144, 144, 140) == "over"  # avg exactly 4
    assert S.base_side(None, 150, 140) is None
    assert S.base_side(float("nan"), 150, 140) is None


def test_payout_implied_grade():
    assert S.payout(-110) == pytest.approx(100 / 110)
    assert S.payout(120) == pytest.approx(1.2)
    assert S.implied(-110) == pytest.approx(110 / 210)
    assert S.grade("over", 140.5, -110, 150)[:2] == (pytest.approx(100 / 110), 1)
    assert S.grade("under", 140.5, None, 150)[:2] == (-1.0, 0)
    assert S.grade("under", 140, -105, 140)[:2] == (0.0, None)


def test_toward():
    assert S.toward("over", 137.5, 139.5) == 2  # over, line up: with us
    assert S.toward("under", 149.5, 146.5) == 3  # under, line down: with us
    assert S.toward("under", 149.5, 150.5) == -1


def test_c0_c1_use_their_ds():
    g = game(ds=150, mb=150, ds_alt=139)
    assert S.pick("C0", g, WH) == "over"
    assert S.pick("C1", g, WH) is None
    assert S.pick("C0", game(lines={}, wh=140) | {"lines": {}}, WH) is None  # no WH quote


def test_c2():
    assert S.pick("C2", game(ds=150, mb=150, gp=9), WH) == "over"  # avg 10
    assert S.pick("C2", game(ds=150, mb=150, gp=10), WH) is None
    assert S.pick("C2", game(ds=147, mb=147, gp=3), WH) is None  # avg 7


def test_c3_pinnacle():
    assert S.pick("C3", game(lines={"pinnacle": (140.5, -105, -105)}), WH) == "over"
    assert S.pick("C3", game(lines={"pinnacle": (140.0, -105, -105)}), WH) == "over"
    assert S.pick("C3", game(lines={"pinnacle": (139.5, -105, -105)}), WH) is None
    assert S.pick("C3", game(), WH) is None  # no Pinnacle quote
    u = game(ds=130, mb=130, lines={"pinnacle": (139.5, -105, -105)})
    assert S.pick("C3", u, WH) == "under"


def test_c4_opener_reference():
    assert S.pick("C4", game(open15={WH: 139.0}), WH) == "over"  # 139 -> 140, toward over
    assert S.pick("C4", game(open15={WH: 140.0}), WH) == "over"  # 0 counts
    assert S.pick("C4", game(open15={WH: 141.0}), WH) is None
    # WH missing at 15:00 -> DraftKings 15:00 -> DraftKings at T
    g = game(open15={"draftkings": 142.0}, lines={"draftkings": (141.0, -110, -110)})
    assert S.pick("C4", g, WH) is None
    g = game(open15={"draftkings": 140.0}, lines={"draftkings": (141.0, -110, -110)})
    assert S.pick("C4", g, WH) == "over"
    assert S.pick("C4", game(), WH) is None  # neither


def test_c5_shrink_fit_and_rule():
    rng = np.random.default_rng(1)
    rows = []
    for _ in range(400):
        line = 140.0
        ds, mb = line + rng.normal(0, 6), line + rng.normal(0, 6)
        final = line + 0.3 * (ds - line) + 0.2 * (mb - line) + rng.normal(0, 1)
        rows.append((ds, mb, line, final))
    b = S.fit_shrink(rows)
    assert b[0] == pytest.approx(0.3, abs=0.05) and b[1] == pytest.approx(0.2, abs=0.05)
    assert S.fit_shrink([(150, 150, 140, 200), (130, 130, 140, 80), (150, 130, 140, 140)]) == (
        1.0,
        1.0,
    )
    g = game(ds=145, mb=145)  # edges 5, 5
    assert S.pick("C5", g, WH, (0.15, 0.15)) == "over"  # s = 1.5
    assert S.pick("C5", g, WH, (0.1, 0.1)) is None
    assert S.pick("C5", g, WH, None) is None


def test_c6_off_market_guard():
    others = {"draftkings": (141.0, -110, -110), "fanduel": (141.5, -110, -110)}
    assert S.pick("C6", game(lines=others), WH) is None  # median 141.25 - 140 >= 1 for an over
    others = {"draftkings": (140.5, -110, -110), "fanduel": (140.5, -110, -110)}
    assert S.pick("C6", game(lines=others), WH) == "over"
    assert S.pick("C6", game(lines={"draftkings": (145.0, -110, -110)}), WH) == "over"  # < 2 others
    u = game(
        ds=130, mb=130, lines={"draftkings": (141.0, -110, -110), "fanduel": (141.0, -110, -110)}
    )
    assert S.pick("C6", u, WH) == "under"  # off market against an under: not skipped


def test_k1_k2():
    others = {"draftkings": (141.0, -110, -110), "fanduel": (141.5, -110, -110)}
    assert S.pick("K1", game(ds_alt=150, lines=others), WH) is None
    assert S.pick("K1", game(ds=139, ds_alt=150), WH) == "over"
    g = game(lines={"pinnacle": (140.5, -105, -105)}, open15={WH: 139.5})
    assert S.pick("K2", g, WH) == "over"
    g = game(lines={"pinnacle": (140.5, -105, -105)}, open15={WH: 141.5})
    assert S.pick("K2", g, WH) is None


def test_boot_and_holm():
    days = ["a"] * 10 + ["b"] * 10
    pnl = [S.payout(-110)] * 15 + [-1.0] * 5
    win = [1.0] * 15 + [0.0] * 5
    be = [S.implied(-110)] * 20
    out = S.boot_stats(days, pnl, win, be, reps=500, seed=0)
    assert out["roi_lo"] <= sum(pnl) / 20 <= out["roi_hi"]
    assert 0 <= out["p"] <= 1
    # all wins: never at or below break-even
    assert S.boot_stats(days, [1.0] * 20, [1.0] * 20, be, reps=200)["p"] == 0.0
    assert math.isnan(S.boot_stats([], [], [], [])["p"])
    rej = S.holm({"a": 0.001, "b": 0.02, "c": 0.04})
    assert rej == {"a": True, "b": True, "c": True}  # 0.001<=.0167, .02<=.025, .04<=.05
    assert S.holm({"a": 0.001, "b": 0.03, "c": 0.04}) == {"a": True, "b": False, "c": False}


def test_pass_parts():
    ps = {
        2023: {"n": 120, "roi": 0.01},
        2024: {"n": 200, "roi": 0.02},
        2025: {"n": 160, "roi": 0.03},
    }
    assert S.season_rule_ok(ps)
    assert not S.practical(ps)
    ps[2023]["roi"] = -0.01
    assert not S.season_rule_ok(ps)
    ps[2023]["n"] = 90  # below 100: not counted, but now only 2 seasons >= 100
    assert not S.season_rule_ok(ps)
    assert S.tie_break({"C1": 0.010, "C0": 0.007, "K1": 0.02}) == "K1"
    assert S.tie_break({"C1": 0.010, "C0": 0.007}) == "C0"
    assert S.tie_break({}) is None


def test_summarize():
    rows = [
        {"pnl": 1.0, "win": 1, "be": 0.5},
        {"pnl": -1.0, "win": 0, "be": 0.5},
        {"pnl": 0.0, "win": None, "be": 0.5},
    ]
    s = S.summarize(rows)
    assert (s["n"], s["w"], s["l"], s["push"], s["win"], s["roi"]) == (3, 1, 1, 1, 0.5, 0.0)
