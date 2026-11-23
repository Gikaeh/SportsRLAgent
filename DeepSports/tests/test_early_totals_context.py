"""Market context of et-v1 / et-v1-alt bets (analysis/early_totals_context.py and `early-totals
context`). Pure logic is tested on real bets and inputs
(tests/fixtures/early_totals_context_real.json); the CLI on the shared et-v1 fixture, where
et-v1's own files must stay byte-identical."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
from early_alt_fixture import GAME_DATE, NOW, TIP, setup

from deepsports.analysis import early_totals_cli as cli
from deepsports.analysis import early_totals_context as etc

REAL = json.loads(
    (Path(__file__).parent / "fixtures" / "early_totals_context_real.json").read_text()
)
WRITTEN = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)


def real_row(gid, **kw):
    (bet,) = [b for b in REAL["bets"] if b["game_id"] == gid]
    d = REAL["days"][gid]
    return etc.context_row(bet, REAL["snaps"][gid], d["wh_shots"], d["feed"], d["circa"],
                           WRITTEN, **kw)  # fmt: skip


# ---------- pure, on real data ----------


def test_screenshot_bet_under_with_opener_and_circa():
    """ALA-KSU 2026-11-17, under 175 (WH screenshot read 20:13): opener 172.5, DraftKings 174.5 at
    19:45 (the 20:15 capture is after the bet), Circa 176."""
    r = real_row("401906761")
    assert (r["bet_time"], r["bet_time_from"]) == ("2026-11-16T20:13:07-08:00", "book_read_at")
    assert (r["opener_total"], r["first_pregame_total"]) == (172.5, 172.5)
    assert r["dk_total"] == 174.5 and r["dk_age_min"] == 28.0
    assert r["dk_captured_at"].startswith("2026-11-16T19:45")
    assert (r["feed_total"], r["wh_shot_total"], r["circa_total"]) == (175.0, 175.0, 176.0)
    # line went up from the opener: against an under
    assert (r["momentum"], r["momentum_from"]) == (-2.0, "opening")
    assert (r["wh_minus_dk"], r["wh_better_than_dk"]) == (0.5, 0.5)  # 175 beats 174.5 for under
    assert (r["circa_minus_wh"], r["circa_better_than_wh"]) == (1.0, 1.0)
    assert r["backfilled"] is False and r["written_at"] == "2026-11-23T08:00:00+00:00"


def test_feed_bet_over_uses_grabbed_at():
    """2026-11-18 over 153 from the Caesars feed (no WH screenshot quote for the game)."""
    r = real_row("401911473", backfilled=True)
    assert r["bet_time_from"] == "book_grabbed_at" and r["line_source"] == "feed"
    assert r["wh_shot_total"] is None and r["feed_total"] == 153.0
    assert (r["opener_total"], r["dk_total"]) == (153.5, 152.5)
    assert r["momentum"] == -1.0  # down from the opener: against an over
    assert r["wh_better_than_dk"] == -0.5  # over 153 is worse than DraftKings' 152.5
    assert (r["circa_minus_wh"], r["circa_better_than_wh"]) == (-1.5, 1.5)
    assert r["backfilled"] is True


def test_no_opener_yet_falls_back_to_first_pregame():
    """The night-before case: the warehouse has no opening row until the game is final."""
    r = real_row("401909743")
    assert r["opener_total"] is None and r["first_pregame_total"] == 158.5
    assert (r["momentum"], r["momentum_from"]) == (0.0, "first_pregame")
    assert json.dumps(r).count("-0.0") == 0  # signed zeros are written as 0.0
    assert r["feed_total"] is None and r["circa_better_than_wh"] == 0.5


def test_market_at_ignores_later_and_insane_rows():
    snaps = [
        {"source": "pregame", "provider": "x", "captured_at": "2026-11-22T10:00:00+00:00",
         "over_under": 9.0},  # insane total
        {"source": "pregame", "provider": "x", "captured_at": "2026-11-22T11:00:00+00:00",
         "over_under": 141.0},
        {"source": "pregame", "provider": "x", "captured_at": "2026-11-22T13:00:00+00:00",
         "over_under": 143.0},  # after the bet
    ]  # fmt: skip
    m = etc.market_at(snaps, datetime(2026, 11, 22, 12, 0, tzinfo=UTC))
    assert m["first_pregame_total"] == m["dk_total"] == 141.0 and m["dk_age_min"] == 60.0
    assert etc.market_at(snaps, None)["dk_total"] is None
    assert etc.market_at([], None)["opener_total"] is None


def test_bet_time_order():
    b = {"line_source": "screenshot", "book_read_at": "2026-11-22T19:00:00-08:00",
         "book_grabbed_at": "2026-11-22T21:00:00-08:00", "logged_at": "x"}  # fmt: skip
    assert etc.bet_time(b)[1] == "book_read_at"
    assert etc.bet_time(b | {"line_source": "feed"})[1] == "book_grabbed_at"
    assert etc.bet_time({"line_source": "feed", "logged_at": "2026-11-23T05:00:00+00:00"})[1] == (
        "logged_at"
    )
    assert etc.bet_time({}) == (None, None)


def test_derive_signs():
    d = etc.derive("over", 140.0, dk=141.0, opener=139.0, first_pregame=None, circa=139.5)
    assert d["momentum"] == 2.0 and d["wh_better_than_dk"] == 1.0
    assert d["circa_better_than_wh"] == 0.5 and d["circa_minus_wh"] == -0.5
    d = etc.derive("under", 140.0, dk=141.0, opener=139.0, first_pregame=None, circa=139.5)
    assert d["momentum"] == -2.0 and d["wh_better_than_dk"] == -1.0
    assert d["circa_better_than_wh"] == -0.5
    assert etc.derive("over", 140.0, None, 139.0, None, None)["momentum"] is None


def test_summarize_splits_and_rebases_on_the_opener():
    rows = [real_row(g) for g in ("401906761", "401911473", "401909743")]
    graded = []
    for b, profit in zip(REAL["bets"], (0.9091, -1.0, None), strict=True):
        grade = "pending" if profit is None else "win" if profit > 0 else "loss"
        graded.append(b | {"grade": grade, "profit": profit, "clv": 1.0, "close_grade": grade})
    # a later warehouse opener for the third game re-bases its momentum (under: 160 -> 158.5 = +1.5)
    s = etc.summarize(graded, rows + [rows[0] | {"momentum": 99.0}], {"401909743": 160.0})
    assert s["bets"] == 3 and s["graded"] == 2 and s["with_context"] == 3
    assert s["coverage"]["opener_espn"] == 3 and s["coverage"]["circa"] == 3
    assert etc.momentum_now(rows[2], 160.0) == 1.5
    m = s["splits"]["momentum"]
    assert list(m) == ["<0 (against pick)"] and m["<0 (against pick)"]["record"] == "1-1-0"
    assert s["splits"]["circa_vs_wh"]["Circa better"]["bets"] == 2
    text = etc.render(s)
    assert "describe-only" in text and "Circa better: 2 (1-1-0)" in text


def test_missing_keys_on_rule_and_game():
    v1, alt = (
        {"rule_version": "et-v1", "game_id": "1"},
        {"rule_version": "et-v1-alt", "game_id": "1"},
    )
    bets = [v1, alt, dict(v1)]
    assert etc.missing(bets, [{"rule_version": "et-v1", "game_id": "1"}]) == [bets[1]]
    assert len(etc.missing(bets, [])) == 2


# ---------- CLI ----------


@pytest.fixture
def env(tmp_path, monkeypatch):
    db, mbf = setup(tmp_path, monkeypatch, cli)
    monkeypatch.setattr(cli.config, "CIRCA_LINES_DIR", tmp_path / "circa" / "lines")
    con = duckdb.connect(str(db))
    for gid, at, total in (("1", NOW - timedelta(hours=6), 138.0), ("1", NOW - timedelta(hours=1),
                           139.0), ("1", NOW + timedelta(hours=1), 145.0)):  # fmt: skip
        con.execute("INSERT INTO odds_snapshots VALUES (?, 'pregame', ?, 'Draft Kings', '', -3,"
                    " ?, NULL, NULL)", [gid, at, total])  # fmt: skip
    con.close()
    circa = tmp_path / "circa" / "lines" / "early"
    circa.mkdir(parents=True)
    q = {"game_id": "1", "market": "total", "side": "over", "line": 139.5, "price": -110}
    payload = {"date": GAME_DATE, "read_at": "x", "lines": [q]}
    (circa / f"{GAME_DATE}.json").write_text(json.dumps(payload))
    return tmp_path, db, mbf


def log_argv(out, mbf, *extra):
    return ["log", "--date", GAME_DATE, "--manualbets", str(mbf), "--out-dir", str(out), *extra]


def test_context_log_writes_rows_and_leaves_et_v1_files_alone(env, capsys):
    tmp, _, mbf = env
    out = tmp / "r"
    assert cli.main(log_argv(out, mbf)) == 0
    before = {n: (out / n).read_bytes() for n in ("bets.jsonl", "runs.jsonl")}
    alt_before = (out / "alt" / "bets.jsonl").read_bytes()
    capsys.readouterr()
    argv = ["context", "--log", "--date", GAME_DATE, "--out-dir", str(out)]
    assert cli.main(argv) == 0
    assert "8 rows written (DK at bet time 2, Circa 2)" in capsys.readouterr().out
    rows = cli.read_jsonl(out / "context.jsonl")
    assert {(r["rule_version"], r["game_id"]) for r in rows} == {
        ("et-v1", g) for g in "1345"} | {("et-v1-alt", g) for g in "1245"}  # fmt: skip
    r1 = [r for r in rows if r["game_id"] == "1" and r["rule_version"] == "et-v1"][0]
    # feed grabbed 21:00 PT = NOW: the capture an hour after is not used
    assert r1["bet_time_from"] == "book_grabbed_at" and r1["dk_total"] == 139.0
    assert r1["momentum"] == 1.0 and r1["momentum_from"] == "first_pregame"
    assert r1["circa_better_than_wh"] == 0.5 and r1["backfilled"] is False
    for n, b in before.items():
        assert (out / n).read_bytes() == b
    assert (out / "alt" / "bets.jsonl").read_bytes() == alt_before
    # first row per bet is frozen
    assert cli.main(argv) == 0
    assert "0 bets need a row" in capsys.readouterr().out
    assert cli.main(["context", "--backfill", "--out-dir", str(out)]) == 0
    assert "0 bets need a row" in capsys.readouterr().out
    assert len(cli.read_jsonl(out / "context.jsonl")) == 8


def test_context_backfill_flags_rows_and_view_prints_splits(env, capsys):
    tmp, db, mbf = env
    out = tmp / "r"
    assert cli.main(log_argv(out, mbf, "--no-alt")) == 0
    assert cli.main(["context", "--backfill", "--out-dir", str(out)]) == 0
    rows = cli.read_jsonl(out / "context.jsonl")
    assert len(rows) == 4 and all(r["backfilled"] for r in rows)
    con = duckdb.connect(str(db))
    for gid in "1345":
        con.execute("UPDATE games SET home_score=80, away_score=70, completed=true,"
                    " status='STATUS_FINAL', state='post' WHERE game_id=?", [gid])  # fmt: skip
    con.execute("INSERT INTO odds_snapshots VALUES ('1','opening',?,'DraftKings','',-3,141.0,"
                "NULL,NULL)", [TIP])  # fmt: skip
    con.close()
    capsys.readouterr()
    assert cli.main(["context", "--json", "--out-dir", str(out)]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["graded"] == 4 and s["coverage"]["opener_espn"] == 1
    # game 1 re-based on the opener now in the warehouse: over, 141 -> 139 = -2
    assert s["splits"]["momentum"]["<0 (against pick)"]["bets"] == 1
    assert s["splits"]["momentum"]["?"]["bets"] == 3
    assert s["splits"]["circa_vs_wh"]["Circa better"]["record"] == "1-0-0"
    assert cli.main(["context", "--out-dir", str(out)]) == 0
    assert "market context (describe-only" in capsys.readouterr().out
    assert not (out / "grade.json").exists()  # the view prints only


def test_context_errors_go_to_stderr_and_busy_exits_3(env, capsys, monkeypatch):
    tmp, _, mbf = env
    out = tmp / "r"
    assert cli.main(log_argv(out, mbf, "--no-alt")) == 0
    real = etc.context_row

    def flaky(bet, *a, **k):
        if bet["game_id"] == "3":
            raise ValueError("bad")
        return real(bet, *a, **k)

    monkeypatch.setattr(cli.etc, "context_row", flaky)
    capsys.readouterr()
    assert cli.main(["context", "--log", "--date", GAME_DATE, "--out-dir", str(out)]) == 0
    cap = capsys.readouterr()
    assert "3 rows written" in cap.out and "1 errors" in cap.out and "ValueError" in cap.err
    monkeypatch.setattr(cli, "_open", lambda lock_wait: None)
    assert cli.main(["context", "--log", "--date", GAME_DATE, "--out-dir", str(out)]) == 3
    assert "busy" in capsys.readouterr().out
