"""The `mix` tier (straights + a parlay, paced on the month's deposit) and Circa repricing."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, date, datetime

import numpy as np
import pytest

from deepsports.moon import circa, ledger, picks, sim, tiers
from deepsports.moon.cli import DEFAULT_TIER, main


def game(gid, home_line=-1.5):
    return {
        "game_id": gid,
        "league": "ncaab",
        "tip_local": "Thu Nov 5 4:00 PM PST",
        "home": {"abbr": f"H{gid}", "name": f"Home {gid}"},
        "away": {"abbr": f"A{gid}", "name": f"Away {gid}"},
        "markets": {
            "spread": {"home_line": home_line, "home_price": -110,
                       "away_line": -home_line, "away_price": -110},
            "total": {"line": 140.5, "over_price": -110, "under_price": -110},
        },
    }  # fmt: skip


def pick(gid, market="spread", side="home", line=-1.5, price=-110):
    label = f"Over {line:g}" if market == "total" else f"H{gid} {line:+g}"
    return {"game_id": gid, "league": "ncaab", "market": market, "side": side, "line": line,
            "price": price, "label": label}  # fmt: skip


MIX = tiers.get("mix")
NOV = "2026-11"


@pytest.fixture
def run():
    slate = {"created_at": "2026-11-13T22:00:00+00:00",
             "games": [game(str(i)) for i in range(1, 6)]}  # fmt: skip
    top = [pick("1"), pick("2"), pick("3", market="total", side="over", line=140.5),
           pick("4"), pick("5", side="away", line=1.5)]  # fmt: skip
    return {"top": top, "picks": top}, slate


def ts(day: str, hour: int = 20) -> str:  # 20:00 UTC = noon in Los Angeles
    return f"{day}T{hour:02d}:00:00+00:00"


def deposit(rid, amount, day):
    return {"id": str(rid), "kind": "deposit", "month": NOV, "created_at": ts(day),
            "amount": str(amount), "tier": "", "stake": "", "market": "", "ref": ""}  # fmt: skip


def bet(rid, stake, day, tier="manual", market="spread"):
    return {"id": str(rid), "kind": "bet", "month": NOV, "created_at": ts(day), "tier": tier,
            "stake": str(stake), "amount": str(-stake), "market": market, "ref": ""}  # fmt: skip


def mix_plan(run, mb, balance=50.0, circa_payload=None):
    payload, slate = run
    return picks.propose(MIX, payload, slate, balance=balance, month=1, budget=mb.deposit,
                         target=1000.0, month_budget=mb, circa=circa_payload)  # fmt: skip


# ---------- tier, units, pacing ----------


def test_mix_is_the_default_and_units_at_50():
    assert DEFAULT_TIER == "mix"
    assert MIX.id == 12 and MIX.stake == "mix"
    assert picks.mix_units(MIX, 50) == (3.0, 2.0)
    assert picks.mix_units(MIX, 75) == (5.0, 3.0)  # 4.5 rounds half up
    assert tiers.unit_usd(0.0, 50) == 0.0


def test_pace_allowance_spreads_and_ends_with_everything():
    assert tiers.pace_allowance(30.0, 30, 1) == pytest.approx(1.0)
    assert tiers.pace_allowance(30.0, 30, 3) == pytest.approx(3 * 30 / 32)
    assert tiers.pace_allowance(12.0, 1, 5) == pytest.approx(12.0)


def test_mix_card_bets_what_the_allowance_covers():
    n, p = tiers.mix_card(8.0, 50.0, 3.0, 2.0, 2)
    assert (n, bool(p)) == (2, True)
    n, p = tiers.mix_card(7.9, 50.0, 3.0, 2.0, 2)  # $1.90 short of the parlay
    assert (n, bool(p)) == (2, False)
    n, p = tiers.mix_card(5.0, 50.0, 3.0, 2.0, 2)
    assert (n, bool(p)) == (1, True)
    n, p = tiers.mix_card(2.5, 50.0, 3.0, 2.0, 2)  # no single fits, the parlay does
    assert (n, bool(p)) == (0, True)
    n, p = tiers.mix_card(1.5, 50.0, 3.0, 2.0, 2)
    assert (n, bool(p)) == (0, False)
    n, p = tiers.mix_card(20.0, 4.0, 3.0, 2.0, 2)  # the month's remaining budget caps it
    assert (n, bool(p)) == (1, False)


def test_sim_never_stakes_more_than_the_deposit():
    for unit, pu in ((0.06, 0.04), (0.2, 0.1), (0.5, 0.2)):
        t = dataclasses.replace(MIX, unit=unit, parlay_unit=pu)
        r = sim.simulate(t, 50, 1000, months=3, paths=2000)
        assert r.staked_per_path <= 3 * 50 + 1e-9
    r = sim.simulate(MIX, 50, 1000, months=1, paths=5000)
    assert 40 <= r.staked_per_path <= 50
    assert 10 <= r.bets_per_path <= 25
    assert r.mean_end == pytest.approx(50 * (1 + sim.DEFAULT_EV), abs=1.5)
    assert r.p_lose_half < 0.1


def test_sim_month_cap_holds_on_every_path():
    t = dataclasses.replace(MIX, unit=0.3, parlay_unit=0.2)
    bal, touched, done = np.zeros(4000) + 50, np.zeros(4000, bool), np.zeros(4000, bool)
    bets, staked = np.zeros(4000), np.zeros(4000)
    sim._mix_month(t, 50.0, 1e9, sim.DEFAULT_EV, np.random.default_rng(1), bal, touched, done,
                   bets, staked, True)  # fmt: skip
    assert staked.max() <= 50 + 1e-9


# ---------- month budget from the ledger ----------


def test_month_budget_counts_manual_stakes():
    rows = [deposit(1, 27, "2026-11-13"), bet(2, 5, "2026-11-13"),
            bet(3, 2, "2026-11-13", market="parlay"), deposit(4, 23, "2026-11-13")]  # fmt: skip
    mb = picks.month_budget(rows, "mix", date(2026, 11, 14))
    assert (mb.deposit, mb.staked, mb.left) == (50, 7, 43)
    assert (mb.gap, mb.days_left, mb.staked_today) == (1, 17, 0)
    assert mb.allowance() == pytest.approx(43 / 17, abs=0.01)


def test_plan_money_leaves_out_stakes_before_a_top_up():
    """November 2026 as logged: $27 deposit and $27 of manual picks, then $23 + $27 more. The
    plan's money is $50, so units are $3 / $2 (at $77 they would be $5 / $3). Bets after the
    latest deposit only cut what's left."""
    rows = [deposit(1, 27, "2026-11-13"), bet(2, 27, "2026-11-13"),
            deposit(3, 23, "2026-11-14"), deposit(4, 27, "2026-11-14")]  # fmt: skip
    rows[1]["created_at"] = ts("2026-11-13", 23)
    mb = picks.month_budget(rows, "mix", date(2026, 11, 14))
    assert (mb.deposit, mb.left, mb.plan_money) == (77, 50, 50)
    assert picks.mix_units(MIX, mb.plan_money) == (3.0, 2.0)
    later = rows + [bet(5, 3, "2026-11-15", tier="mix"), bet(6, 10, "2026-11-15")]
    mb = picks.month_budget(later, "mix", date(2026, 11, 16))
    assert (mb.plan_money, mb.left) == (50, 37)


def test_month_budget_ignores_voids_and_other_months():
    rows = [deposit(1, 50, "2026-11-01"), bet(2, 10, "2026-11-02"),
            {**bet(3, 99, "2026-10-30"), "month": "2026-10"},
            {"id": "4", "kind": "void", "ref": "2", "month": NOV, "created_at": ts("2026-11-02"),
             "amount": "10", "tier": "", "stake": "", "market": ""}]  # fmt: skip
    mb = picks.month_budget(rows, "mix", date(2026, 11, 5))
    assert (mb.staked, mb.left, mb.gap) == (0, 50, 5)  # nothing bet yet: paced since Nov 1


def test_mix_manual_stakes_reduce_what_is_proposed(run):
    rows = [deposit(1, 50, "2026-11-01"), bet(2, 45, "2026-11-01")]
    mb = picks.month_budget(rows, "mix", date(2026, 11, 30))
    p = mix_plan(run, mb)
    assert mb.left == 5
    assert sum(pr.stake for pr in p.proposals) <= 5
    assert [pr.stake for pr in p.proposals] == [3.0, 2.0]  # 1 single + the parlay fit


def test_mix_paced_day_and_no_bet_day(run):
    rows = [deposit(1, 50, "2026-11-01")]
    mb = picks.month_budget(rows, "mix", date(2026, 11, 5))  # 5/30 x 50 = $8.33 >= $8 card
    p = mix_plan(run, mb)
    assert [pr.stake for pr in p.proposals] == [3.0, 3.0, 2.0]
    single_ids = {p.proposals[0].legs[0].game_id, p.proposals[1].legs[0].game_id}
    assert not single_ids & {lg.game_id for lg in p.proposals[2].legs}  # separate parlay legs
    assert p.proposals[2].price == 264
    mb = picks.month_budget(rows, "mix", date(2026, 11, 3))  # $5 share: a smaller day
    p = mix_plan(run, mb)
    assert [pr.stake for pr in p.proposals] == [3.0, 2.0]
    mb = picks.month_budget(rows, "mix", date(2026, 11, 1))  # $1.67 share: under the $2 parlay
    p = mix_plan(run, mb)
    assert not p.proposals and "No bet today" in p.messages[0] and "Nov 2" in p.messages[0]


def test_mix_today_bets_count_and_cap_never_exceeded(run):
    rows = [deposit(1, 50, "2026-11-01"), bet(2, 3, "2026-11-05", tier="mix")]
    mb = picks.month_budget(rows, "mix", date(2026, 11, 5))
    assert mb.tier_singles_today == 1
    p = mix_plan(run, mb)
    assert sum(pr.stake for pr in p.proposals) <= mb.allowance()
    for left in (0.0, 0.5, 2.0, 7.0):
        rows = [deposit(1, 50, "2026-11-01"), bet(2, 50 - left, "2026-11-01")]
        mb = picks.month_budget(rows, "mix", date(2026, 11, 30))
        p = mix_plan(run, mb)
        assert sum(pr.stake for pr in p.proposals) <= left + 1e-9


def test_mix_balance_caps_too(run):
    mb = picks.month_budget([deposit(1, 50, "2026-11-01")], "mix", date(2026, 11, 30))
    p = mix_plan(run, mb, balance=4.0)
    assert sum(pr.stake for pr in p.proposals) <= 4.0


# ---------- Circa ----------


def lines(*entries):
    return {"date": "2026-11-13", "read_at": "2026-11-13T21:00:00+00:00", "files": [],
            "lines": list(entries)}  # fmt: skip


def q(gid, market="spread", side="home", line=-1.5, price=-110, **kw):
    return {"game_id": gid, "league": "ncaab", "away": f"A{gid}", "home": f"H{gid}",
            "market": market, "side": side, "line": line, "price": price,
            "rotation": None} | kw  # fmt: skip


def legs(run):
    return picks.single_legs(*run)


def test_circa_same_better_worse_missing(run):
    lg = legs(run)
    kept, notes = circa.reprice(lg, lines(
        q("1", price=-105),                                   # same line, better price
        q("2", line=-1.0, price=-110, rotation="823"),         # better line, same price
        q("3", "total", "over", 141.5),                        # worse total for an over
        q("4", price=-120),                                    # same line, worse price
    ))  # fmt: skip
    by = {k.game_id: k for k in kept}
    assert set(by) == {"1", "2", "5"}
    assert (by["1"].price, by["1"].source) == (-105, "circa")
    assert (by["2"].line, by["2"].price, by["2"].source) == (-1.0, -110, "circa")
    assert by["2"].label == "H2 -1 (#823)"
    assert by["5"].source == "unchecked"
    assert len(notes) == 2 and all(n.startswith("Dropped") for n in notes)


def test_circa_line_and_price_must_both_be_at_least_as_good(run):
    lg = legs(run)
    kept, notes = circa.reprice(lg[:4], lines(
        q("1", line=-1.0, price=-130),                 # line better, price worse: drop
        q("2", line=-2.5, price=120),                  # line worse, price better: drop
        q("3", "total", "over", 139.5, price=-105),    # both better: keep at Circa
        q("4", line=-2.5, price=-120),                 # both worse: drop
    ))  # fmt: skip
    assert [(k.game_id, k.line, k.price) for k in kept] == [("3", 139.5, -105)]
    assert notes[0] == ("Dropped H1 -1.5: Circa -1 -130 vs -1.5 -110: line better, price worse;"
                        " check by hand")  # fmt: skip
    assert notes[1].endswith("line worse, price better; check by hand")
    assert notes[2].endswith("line worse, price worse")


def test_circa_line_direction():
    assert circa.line_cmp("spread", "away", 8.0, 8.5) == 1
    assert circa.line_cmp("spread", "home", -1.5, -2.0) == -1
    assert circa.line_cmp("total", "over", 138.0, 137.5) == 1
    assert circa.line_cmp("total", "under", 138.0, 137.5) == -1
    assert circa.line_cmp("moneyline", "home", None, None) == 0


def test_circa_matches_by_team_names_without_game_id(run):
    lg = legs(run)[:1]
    kept, _ = circa.reprice(lg, lines(q(None, price=100, away="a1", home="h-1")))
    assert kept[0].source == "circa" and kept[0].price == 100


def test_circa_parlay_price_recomputed(run):
    mb = picks.month_budget([deposit(1, 50, "2026-11-01")], "mix", date(2026, 11, 5))
    p = mix_plan(run, mb, circa_payload=lines(q("3", "total", "over", 140.5, 100),
                                             q("4", price=100)))  # fmt: skip
    par = p.proposals[-1]
    assert len(par.legs) == 2 and par.price == 300  # +100 x +100
    assert "Circa" in par.circa_line()
    assert "check by hand" in p.proposals[0].circa_line()


def test_circa_load_missing_and_bad(tmp_path):
    assert circa.load(tmp_path / "nope.json")[0] is None
    (tmp_path / "bad.json").write_text("{not json")
    data, why = circa.load(tmp_path / "bad.json")
    assert data is None and "unreadable" in why
    (tmp_path / "ok.json").write_text(json.dumps(lines()))
    assert circa.load(tmp_path / "ok.json")[0]["lines"] == []


def test_circa_team_names_match_whole_names_only():
    assert circa._team_match("Kansas", ("KU", "Kansas"))
    assert circa._team_match("st. mary's", ("SMC", "St Marys"))
    assert not circa._team_match("Kansas", ("ARK", "Arkansas"))
    assert not circa._team_match("Arkansas", ("KU", "Kansas"))
    assert not circa._team_match("Texas", ("TTU", "Texas Tech"))
    assert not circa._team_match("Texas Tech", ("TEX", "Texas"))
    assert not circa._team_match("", ("TEX", "Texas"))


def test_circa_lines_dir_from_circa_dir_env(monkeypatch, tmp_path):
    monkeypatch.delenv(circa.ENV_LINES, raising=False)
    monkeypatch.setenv(circa.ENV_DIR, str(tmp_path))
    assert circa.default_path(date(2026, 11, 14)) == tmp_path / "lines" / "2026-11-14.json"


def test_circa_lines_dir_from_lines_env(monkeypatch, tmp_path):
    monkeypatch.setenv(circa.ENV_DIR, str(tmp_path / "ignored"))
    monkeypatch.setenv(circa.ENV_LINES, str(tmp_path / "l"))
    assert circa.default_path(date(2026, 11, 14)) == tmp_path / "l" / "2026-11-14.json"


def test_circa_lines_dir_defaults_to_config(monkeypatch):
    from deepsports import config

    monkeypatch.delenv(circa.ENV_LINES, raising=False)
    monkeypatch.delenv(circa.ENV_DIR, raising=False)
    assert circa.lines_dir() == config.CIRCA_LINES_DIR


# ---------- CLI: discord format ----------


def _write_run(run, tmp_path):
    payload, slate = run
    d = tmp_path / "runs" / "20261113T220000Z"
    d.mkdir(parents=True)
    (d / "picks.json").write_text(json.dumps(payload))
    (d / "slate.json").write_text(json.dumps(slate))
    return d


def test_cli_discord_format_short_with_circa(run, tmp_path, capsys, monkeypatch):
    d = _write_run(run, tmp_path)
    led = tmp_path / "l.csv"
    ledger.add_deposit(50, path=led, month=NOV, now=datetime(2026, 11, 1, 20, tzinfo=UTC))
    cdir = tmp_path / "circa"
    cdir.mkdir()
    (cdir / "2026-11-05.json").write_text(json.dumps(lines(q("1", price=-105))))
    monkeypatch.setenv(circa.ENV_LINES, str(cdir))
    before = led.read_bytes()
    rc = main(["--ledger", str(led), "propose", "--run", str(d), "--months", "1",
               "--paths", "500", "--format", "discord", "--date", "2026-11-05"])  # fmt: skip
    assert rc == 0
    out = capsys.readouterr().out
    assert len(out) < picks.DISCORD_MAX
    assert "Balance $50.00" in out and "of $50 left" in out
    assert "H1 -1.5 -105 [Circa]: $3 -> $5.86" in out
    assert "moon log bet --tier mix" in out and "moon log parlay --tier mix" in out
    assert out.rstrip().endswith(picks.WATCH_ONLY)
    assert led.read_bytes() == before  # propose never writes the ledger


def test_cli_discord_falls_back_without_circa_file(run, tmp_path, capsys, monkeypatch):
    d = _write_run(run, tmp_path)
    monkeypatch.setenv(circa.ENV_LINES, str(tmp_path / "none"))
    rc = main(["--ledger", str(tmp_path / "l.csv"), "propose", "--run", str(d), "--months",
               "1", "--paths", "500", "--format", "discord", "--date", "2026-11-30"])  # fmt: skip
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("no Circa lines file") == 1
    assert not (tmp_path / "l.csv").exists()


def test_discord_never_exceeds_limit(run):
    mb = picks.month_budget([deposit(1, 5000, "2026-11-01")], "mix", date(2026, 11, 30))
    p = mix_plan(run, mb, balance=5000)
    p.messages += ["x" * 300] * 10
    text = picks.render_discord(p, sim_line="sim")
    assert len(text) <= picks.DISCORD_MAX
    assert text.endswith(picks.WATCH_ONLY)
