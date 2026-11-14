from __future__ import annotations

import json

import pytest

from deepsports.moon import picks, tiers
from deepsports.moon.cli import main


def game(gid, home_line=-1.5, ml=(-150, 130)):
    return {
        "game_id": gid,
        "league": "ncaab",
        "tip_local": "Fri Nov 13 4:00 PM PST",
        "home": {"abbr": f"H{gid}"},
        "away": {"abbr": f"A{gid}"},
        "markets": {
            "spread": {"home_line": home_line, "home_price": -110,
                       "away_line": -home_line, "away_price": -110},
            "total": {"line": 140.5, "over_price": -110, "under_price": -110},
            "moneyline": {"home_price": ml[0], "away_price": ml[1]},
        },
    }  # fmt: skip


def pick(gid, market="spread", side="home", line=-1.5, price=-110, edge=5.0):
    return {"game_id": gid, "league": "ncaab", "market": market, "side": side, "line": line,
            "price": price, "tier": "strong", "min_edge": edge,
            "label": f"H{gid} {line:+g}"}  # fmt: skip


@pytest.fixture
def run():
    slate = {"created_at": "2026-11-13T22:00:00+00:00",
             "games": [game("1"), game("2"), game("3"), game("4", 7.5, (-320, 260))]}  # fmt: skip
    top = [pick("1"), pick("2"), pick("3")]
    allp = top + [pick("4", side="away", line=7.5, edge=4.0)]
    return {"top": top, "picks": allp}, slate


def plan(tier, run, **kw):
    payload, slate = run
    args = dict(balance=75.0, month=1, budget=75.0, target=1000.0) | kw
    return picks.propose(tiers.get(tier), payload, slate, **args)


def test_parlay_proposal_price_and_odds_line(run):
    p = plan("ticket3", run, p_reach=0.45)
    assert len(p.proposals) == 1
    pr = p.proposals[0]
    assert pr.stake == 75
    assert pr.price == 596
    assert pr.p_hit == pytest.approx(0.125)
    assert len({lg.game_id for lg in pr.legs}) == 3
    line = pr.odds_line()
    assert line.startswith("3-leg parlay +596: ~12% to hit at -vig")
    assert "reaches $1,000 in 12 months ~45% (sim)" in line
    assert "skip if Circa is worse than +596" in pr.circa_line()


def test_fraction_and_bold_stakes(run):
    p = plan("units", run, balance=200.0)
    assert [pr.stake for pr in p.proposals] == [20.0]
    p = plan("timid", run, balance=200.0)
    assert [pr.stake for pr in p.proposals] == [4.0, 4.0]
    p = plan("bold", run, balance=900.0)
    # needs $100 profit at -110: stake 110
    assert p.proposals[0].stake == pytest.approx(110.0)
    p = plan("bold", run, balance=50.0)
    assert p.proposals[0].stake == 50.0


def test_dog_tier_uses_moneyline_window(run):
    p = plan("dogs", run)
    assert len(p.proposals) == 1
    leg = p.proposals[0].legs[0]
    assert (leg.market, leg.side, leg.price, leg.line) == ("moneyline", "away", 260, None)
    assert 0.2 < leg.fair_p < 0.3


def test_no_bet_reasons(run):
    assert not plan("cash", run).proposals
    p = plan("save-bold", run, month=3)
    assert not p.proposals and "bank the deposit" in p.messages[0]
    assert plan("save-bold", run, month=12, balance=900.0).proposals
    p = plan("ride3", run, balance=1200.0)
    assert not p.proposals and "cash out" in p.messages[0]
    p = plan("ticket3", run, bets_this_month=1)
    assert not p.proposals and "logged" in p.messages[0]
    p = plan("ticket4", run)
    assert not p.proposals and "not enough" in p.messages[0]
    p = picks.propose(tiers.get("units"), None, None, balance=75, month=1, budget=75,
                      target=1000)  # fmt: skip
    assert "No model-picks run" in p.messages[0]


def test_best_price_used_as_reference(run):
    payload, slate = run
    payload["top"][0]["best"] = {"price": -105, "point": -1.5, "book": "lowvig"}
    p = picks.propose(tiers.get("units"), payload, slate, balance=75, month=1, budget=75,
                      target=1000)  # fmt: skip
    assert p.proposals[0].price == -105


def test_render_has_log_command_and_watch_only(run):
    p = plan("parlay2", run)
    text = picks.render(p, 75, 1000)
    assert "log parlay --tier parlay2 --leg 1:ncaab:spread:home:-1.5:-110" in text
    assert "nothing here places a wager" in text


def test_cli_propose_reads_run_dir(run, tmp_path, capsys):
    payload, slate = run
    d = tmp_path / "runs" / "20261113T220000Z"
    d.mkdir(parents=True)
    (d / "picks.json").write_text(json.dumps(payload))
    (d / "slate.json").write_text(json.dumps(slate))
    assert picks.latest_run(tmp_path / "runs") == d
    rc = main(["--ledger", str(tmp_path / "l.csv"), "propose", "--tier", "ticket3",
               "--run", str(d), "--paths", "500"])  # fmt: skip
    assert rc == 0
    out = capsys.readouterr().out
    assert "3-leg parlay +596" in out and "assuming this month's $75" in out
    assert not (tmp_path / "l.csv").exists()  # propose never writes the ledger


def test_odds_line_shows_payout_and_horizon(run):
    pr = plan("ticket2", run, p_reach=0.25, months=1).proposals[0]
    assert pr.stake == 75 and pr.price == 264
    line = pr.odds_line()
    assert "returns $273.00 on $75.00" in line
    assert "reaches $1,000 in 1 month ~25% (sim)" in line


def test_cli_propose_ignores_manual_bets_this_month(run, tmp_path, capsys):
    payload, slate = run
    d = tmp_path / "runs" / "20261113T220000Z"
    d.mkdir(parents=True)
    (d / "picks.json").write_text(json.dumps(payload))
    (d / "slate.json").write_text(json.dumps(slate))
    led = str(tmp_path / "l.csv")
    assert main(["--ledger", led, "log", "deposit", "--amount", "75"]) == 0
    assert main(["--ledger", led, "log", "bet", "--tier", "manual", "--game-id", "1",
                 "--league", "ncaab", "--market", "spread", "--side", "home", "--line", "-1.5",
                 "--price", "-110", "--stake", "5"]) == 0  # fmt: skip
    capsys.readouterr()
    assert main(["--ledger", led, "propose", "--tier", "ticket2", "--run", str(d), "--months", "1",
                 "--paths", "500"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "tier 11 Monthly 2-leg ticket" in out and "2-leg parlay +264" in out
    assert main(["--ledger", led, "log", "parlay", "--tier", "ticket2",
                 "--leg", "1:ncaab:spread:home:-1.5:-110", "--leg", "2:ncaab:spread:home:-1.5:-110",
                 "--price", "264", "--stake", "70"]) == 0  # fmt: skip
    capsys.readouterr()
    assert (
        main(["--ledger", led, "propose", "--tier", "ticket2", "--run", str(d), "--paths", "500"])
        == 0
    )
    assert "This month's 1 bet(s) are logged" in capsys.readouterr().out
