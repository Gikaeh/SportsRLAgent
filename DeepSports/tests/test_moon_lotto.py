import json

from deepsports.moon import lotto
from deepsports.moon.cli import main


def et_row(gid, edge, side="over", line=140.0, price=-110, date="2026-11-24", rule="et-v1"):
    return {
        "rule_version": rule, "game_date": date, "game_id": gid, "league": "ncaab",
        "away": f"A{gid}", "home": f"H{gid}", "tip_utc": "2026-11-24T19:00:00-08:00",
        "market": "total", "side": side, "line": line, "price": price, "avg_edge": edge,
    }  # fmt: skip


def test_legs_strongest_first_one_per_game_and_only_that_night():
    rows = [et_row("1", 4.5), et_row("2", 7.0), et_row("1", 9.0),  # 2nd row for game 1 ignored
            et_row("3", 5.0, date="2026-11-25"), et_row("4", 6.0, rule="et-v1-alt")]  # fmt: skip
    legs = lotto.legs_for(rows, "2026-11-24")
    assert [lg["game_id"] for lg in legs] == ["2", "1"]
    assert [lg["rank"] for lg in legs] == [1, 2]


def test_leave_out_sets_balance():
    nine = lotto.leave_out_sets(9)
    assert len(nine) == 18 and len(set(nine)) == 18
    assert all(sum(r in out for out in nine) == 4 for r in range(1, 10))  # each leg sits out 4
    assert lotto.leave_out_sets(14) == nine  # only the top 9 are used
    assert lotto.leave_out_sets(8) == [(r,) for r in range(1, 9)]
    assert lotto.leave_out_sets(7) == []


def test_card_shapes_by_leg_count():
    def card(n):
        legs = lotto.legs_for([et_row(str(i), 20 - i) for i in range(n)], "2026-11-24")
        return lotto.build_card(legs, "2026-11-24")

    assert card(6)["tickets"] == [] and card(6)["legs"] == []
    c7 = card(7)
    assert [t["kind"] for t in c7["tickets"]] == ["test"]
    t = c7["tickets"][0]
    assert t["ranks"] == list(range(1, 8)) and t["stake"] == 1.0
    assert abs(t["decimal"] - (210 / 110) ** 7) < 1e-3
    c8 = card(8)
    assert len(c8["tickets"]) == 9 and sum(t["stake"] for t in c8["tickets"]) == 3.0
    c12 = card(12)
    spread = [t for t in c12["tickets"] if t["kind"] == "spread"]
    assert len(spread) == 18 and all(len(t["ranks"]) == 7 for t in spread)
    assert {r for t in spread for r in t["ranks"]} == set(range(1, 10))
    assert len(c12["legs"]) == 9 and sum(t["stake"] for t in c12["tickets"]) == 5.5


def test_grade_settles_tickets_pushes_and_the_test_statistic():
    rows = [et_row(str(i), 20 - i, "over", 140) for i in range(7)]
    card = lotto.build_card(lotto.legs_for(rows, "2026-11-24"), "2026-11-24")

    def fin(total):
        return {"home_score": total // 2, "away_score": total - total // 2}

    finals = {str(i): fin(150) for i in range(7)}
    finals["6"] = fin(140)  # a push drops the leg: a 6-leg payout
    (g,) = lotto.grade_cards([card], finals)
    assert g["result"] == "win" and g["legs_won"] == 6
    assert abs(g["payout"] - (210 / 110) ** 6) < 0.02
    s = lotto.summarize([g])
    assert s["test_nights"] == 1 and s["test_sweeps"] == 1 and s["test_leg_win"] == 1.0
    finals["5"] = fin(130)
    assert lotto.grade_cards([card], finals)[0]["result"] == "loss"
    del finals["5"]
    assert lotto.grade_cards([card], finals)[0]["result"] is None


def test_cli_logs_first_card_once(tmp_path, capsys):
    et = tmp_path / "bets.jsonl"
    et.write_text("".join(json.dumps(et_row(str(i), 20 - i)) + "\n" for i in range(10)))
    cards = tmp_path / "cards.jsonl"
    args = ["lotto", "--date", "2026-11-24", "--cards", str(cards), "--et-bets", str(et)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Test ticket: legs 1-7, $1" in out and "Spread: 18 x $0.25" in out and "$5.50" in out
    with et.open("a") as f:  # a late row doesn't change tonight's logged card
        f.write(json.dumps(et_row("99", 50)) + "\n")
    assert main(args) == 0
    lines = cards.read_text().splitlines()
    assert len(lines) == 1 and '"99"' not in lines[0]
    assert main([*args, "--date", "2026-11-30"]) == 0  # no legs: no card, nothing logged
    assert "no card" in capsys.readouterr().out.splitlines()[-1]
    assert len(cards.read_text().splitlines()) == 1


def test_legs_and_card_use_the_apps_team_names():
    line = {"game_id": "1", "away": "CENTRAL MICHIGAN", "home": "NOTRE DAME", "market": "total"}
    payload = {"lines": [line]}
    names = lotto.app_names(payload)
    assert names == {"1": ("CENTRAL MICHIGAN", "NOTRE DAME")} and lotto.app_names(None) == {}
    rows = [et_row(str(i), 20 - i) for i in range(1, 8)]
    card = lotto.build_card(lotto.legs_for(rows, "2026-11-24", names), "2026-11-24")
    text = lotto.render(card)
    assert "1. CENTRAL MICHIGAN @ NOTRE DAME Over 140 -110" in text
    assert "2. A2 @ H2 Over 140" in text  # no screenshot line: falls back to the abbreviation
