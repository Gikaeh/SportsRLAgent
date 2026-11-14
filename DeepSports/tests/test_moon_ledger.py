from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from deepsports.moon import ledger
from deepsports.moon.cli import main, parse_leg

NOW = datetime(2026, 11, 13, 22, 0, tzinfo=UTC)
LEGS = [
    {"game_id": "g1", "league": "nba", "market": "spread", "side": "home", "line": -1.5,
     "price": -110},
    {"game_id": "g2", "league": "ncaab", "market": "total", "side": "over", "line": 148.5,
     "price": -110},
]  # fmt: skip


@pytest.fixture
def path(tmp_path):
    return tmp_path / "moon" / "bets.csv"


def single(path, **kw):
    args = dict(stake=10, price=-110, market="spread", game_id="g1", league="nba",
                side="home", line=-1.5, path=path, now=NOW)  # fmt: skip
    return ledger.add_bet(**(args | kw))


def test_init_writes_header_only(path):
    ledger.init(path)
    assert path.read_text() == ",".join(ledger.COLUMNS) + "\n"
    assert ledger.read_rows(path) == []
    ledger.init(path)  # idempotent
    assert path.read_text() == ",".join(ledger.COLUMNS) + "\n"


def test_appends_never_rewrite_existing_bytes(path):
    ledger.add_deposit(75, path=path, now=NOW)
    before = path.read_bytes()
    single(path)
    ledger.add_bet(stake=5, price=264, market="parlay", legs=LEGS, path=path, now=NOW)
    ledger.add_result("2", "win", path=path, now=NOW)
    ledger.add_void("3", "logged by mistake", path=path, now=NOW)
    after = path.read_bytes()
    assert after.startswith(before)
    mid = after
    ledger.add_note("hello", path=path, now=NOW)
    assert path.read_bytes().startswith(mid)
    assert [r["id"] for r in ledger.read_rows(path)] == ["1", "2", "3", "4", "5", "6"]


def test_refuses_bad_file_layouts(path):
    path.parent.mkdir(parents=True)
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ledger.LedgerError, match="header"):
        ledger.add_deposit(75, path=path)
    path.write_text(",".join(ledger.COLUMNS) + "\n1,x,deposit")  # no trailing newline
    with pytest.raises(ledger.LedgerError, match="newline"):
        ledger.add_deposit(75, path=path)
    assert path.read_text().endswith("deposit")  # untouched


def test_duplicate_id_refused(path):
    ledger.add_deposit(75, path=path, now=NOW)
    with pytest.raises(ledger.LedgerError, match="duplicate"):
        ledger._append([{"id": "1", "kind": "note"}], path)


def test_bet_validation(path):
    with pytest.raises(ledger.LedgerError):
        single(path, side="over")
    with pytest.raises(ledger.LedgerError):
        single(path, stake=0)
    with pytest.raises(ValueError):
        single(path, price=50)
    with pytest.raises(ledger.LedgerError, match="same-game"):
        ledger.add_bet(stake=5, price=264, market="parlay", path=path,
                       legs=[LEGS[0], LEGS[0] | {"market": "total", "side": "over"}])  # fmt: skip
    with pytest.raises(ledger.LedgerError, match="2 legs"):
        ledger.add_bet(stake=5, price=-110, market="parlay", legs=LEGS[:1], path=path)
    assert not path.exists() or ledger.read_rows(path) == []


def test_summary_and_results(path):
    ledger.add_deposit(75, path=path, now=NOW)
    single(path)  # id 2, win at -110 -> payout 19.09
    single(path, stake=20, price=150, market="moneyline", line=None)  # id 3, loss
    single(path, stake=5)  # id 4, open
    ledger.add_result("2", "win", path=path, now=NOW)
    ledger.add_result("3", "loss", path=path, now=NOW)
    with pytest.raises(ledger.LedgerError, match="already settled"):
        ledger.add_result("2", "loss", path=path)
    s = ledger.summary(ledger.read_rows(path))
    assert s["deposits"] == 75
    assert s["balance"] == pytest.approx(75 - 10 - 20 - 5 + 19.09)
    assert s["record"] == "1-1-0"
    assert s["profit"] == pytest.approx(9.09 - 20)
    assert [b["id"] for b in s["open"]] == ["4"]
    assert s["first_month"] == "2026-11"
    assert ledger.plan_month("2026-11", datetime(2027, 2, 1, 20, tzinfo=UTC)) == 4


def test_void_reverses_and_reopens(path):
    ledger.add_deposit(75, path=path, now=NOW)
    single(path)  # 2
    ledger.add_result("2", "loss", path=path, now=NOW)  # 3
    with pytest.raises(ledger.LedgerError, match="void the result"):
        ledger.add_void("2", "x", path=path)
    ledger.add_void("3", "wrong result", path=path, now=NOW)  # 4
    assert [b["id"] for b in ledger.open_bets(ledger.read_rows(path))] == ["2"]
    ledger.add_void("2", "never placed", path=path, now=NOW)  # 5
    with pytest.raises(ledger.LedgerError, match="already voided"):
        ledger.add_void("2", "again", path=path)
    with pytest.raises(ledger.LedgerError, match="voided"):
        ledger.add_result("2", "win", path=path)
    s = ledger.summary(ledger.read_rows(path))
    assert s["balance"] == 75 and s["settled"] == 0 and not s["open"]


def test_grade_appends_results_from_finals(path):
    ledger.add_deposit(75, path=path, now=NOW)
    single(path)  # 2: home -1.5
    single(path, side="away", line=1.5)  # 3: away +1.5
    ledger.add_bet(stake=10, price=264, market="parlay", legs=LEGS, path=path, now=NOW)  # 4
    single(path, game_id="g9")  # 5: not final
    rows = ledger.read_rows(path)
    assert ledger.game_ids(rows) == ["g1", "g2", "g9"]
    finals = {"g1": {"home_score": 100, "away_score": 98},  # home by 2: -1.5 covers
              "g2": {"home_score": 75, "away_score": 73.5}}  # total 148.5: push  # fmt: skip
    dry = ledger.grade(finals, path=path, dry_run=True)
    assert len(ledger.read_rows(path)) == len(rows)
    out = ledger.grade(finals, path=path, now=NOW)
    assert [(r["ref"], r["result"]) for r in out] == [(d["ref"], d["result"]) for d in dry]
    got = {r["ref"]: r for r in out}
    assert got["2"]["result"] == "win" and float(got["2"]["payout"]) == pytest.approx(19.09)
    assert got["3"]["result"] == "loss" and float(got["3"]["payout"]) == 0
    # parlay with one pushed leg pays the remaining leg (-110) on the taken price
    assert got["4"]["result"] == "win"
    assert float(got["4"]["payout"]) == pytest.approx(10 * 3.64 / 1.9091, abs=0.02)
    assert [b["id"] for b in ledger.open_bets(ledger.read_rows(path))] == ["5"]
    assert ledger.grade(finals, path=path) == []  # nothing left to grade


def test_parlay_legs_stored_as_json(path):
    row = ledger.add_bet(stake=5, price=264, market="parlay", legs=LEGS, path=path, now=NOW)
    legs = json.loads(row["legs"])
    assert [lg["game_id"] for lg in legs] == ["g1", "g2"]
    assert row["league"] == "nba/ncaab"


def test_cli_log_and_status(path, capsys):
    assert main(["--ledger", str(path), "log", "deposit", "--amount", "75"]) == 0
    assert main(["--ledger", str(path), "log", "bet", "--tier", "units", "--game-id", "g1",
                 "--league", "nba", "--market", "spread", "--side", "home", "--line", "-1.5",
                 "--price", "-110", "--stake", "7.5"]) == 0  # fmt: skip
    assert main(["--ledger", str(path), "log", "parlay", "--leg", "g1:nba:spread:home:-1.5:-110",
                 "--leg", "g2:ncaab:moneyline:away::250", "--price", "600",
                 "--stake", "10"]) == 0  # fmt: skip
    assert main(["--ledger", str(path), "log", "void", "--ref", "1"]) == 2  # needs a note
    assert main(["--ledger", str(path), "status"]) == 0
    out = capsys.readouterr().out
    assert "$57.50" in out and "+600" in out
    assert parse_leg("g2:ncaab:moneyline:away::250")["line"] is None


def test_status_splits_manual_and_flags_stakes_over_deposit(path, capsys):
    assert main(["--ledger", str(path), "log", "deposit", "--amount", "10"]) == 0
    for _ in range(3):
        assert main(["--ledger", str(path), "log", "bet", "--tier", "manual", "--game-id", "g1",
                     "--league", "nba", "--market", "spread", "--side", "home", "--line", "-1.5",
                     "--price", "-110", "--stake", "5"]) == 0  # fmt: skip
    capsys.readouterr()
    assert main(["--ledger", str(path), "status"]) == 0
    out = capsys.readouterr().out
    assert "of it manual" in out and "$15.00" in out
    assert "over this month's deposit ($10.00)" in out
    assert "of 12" not in out
