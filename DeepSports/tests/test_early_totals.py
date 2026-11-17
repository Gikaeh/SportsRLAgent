from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from deepsports.analysis import early_totals as et
from deepsports.analysis import early_totals_cli as cli

NOW = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)  # 21:00 PT on Nov 14
TIP = datetime(2026, 11, 15, 20, 0, tzinfo=UTC)


def early(*quotes):
    lines = []
    for gid, line, over_price, under_price in quotes:
        for side, price in (("over", over_price), ("under", under_price)):
            lines.append({"game_id": gid, "league": "ncaab", "away": "A", "home": "H",
                          "market": "total", "side": side, "line": line, "price": price,
                          "rotation": None})  # fmt: skip
        lines.append({"game_id": gid, "league": "ncaab", "away": "A", "home": "H",
                      "market": "spread", "side": "home", "line": -3, "price": -110})  # fmt: skip
    return {"date": "2026-11-15", "grabbed_at": "2026-11-14T21:00:00-08:00", "book": "williamhill",
            "lines": lines}  # fmt: skip


def mb(*games, created=NOW - timedelta(hours=7)):
    return {"created_at": created.isoformat(),
            "ncaab": {"games": [{"game_id": g, "model": {"total": t}, "gated": True}
                                for g, t in games]}}  # fmt: skip


def games(*ids, tip=TIP):
    return [{"game_id": g, "away": f"A{g}", "home": f"H{g}", "start_time_utc": tip,
             "min_rest_days": 3.0} for g in ids]  # fmt: skip


def ds(**totals):
    return {g: {"model_version": "ncaab-v1-early", "pred_total": t,
                "created_at": NOW - timedelta(hours=7)} for g, t in totals.items()}  # fmt: skip


def test_qualify_needs_both_models_same_side_and_avg_four():
    q = {"over": {"line": 140.0, "price": -110}, "under": {"line": 140.0, "price": -110}}
    assert et.qualify(146, 143, q) == ("over", 6, 3)  # avg 4.5, both over
    assert et.qualify(147, 140.5, q) is None  # avg 3.75
    assert et.qualify(150, 139, q) is None  # models on opposite sides
    assert et.qualify(134, 136, q) == ("under", 6, 4)
    assert et.qualify(None, 150, q) is None
    # each side uses its own line
    q2 = {"over": {"line": 141.0, "price": -110}, "under": {"line": 140.0, "price": -110}}
    assert et.qualify(145, 145, q2) == ("over", 4, 4)
    assert et.qualify(136, 136, q2) == ("under", 4, 4)


def test_find_bets_row_and_counts():
    bets, counts = et.find_bets(
        games("1", "2", "3", "4"),
        ds(**{"1": 150.0, "2": 141.0, "3": 150.0}),
        mb(("1", 146.0), ("2", 141.0), ("4", 150.0)),
        early(("1", 140.0, -105, -115), ("2", 140.0, -110, -110), ("3", 140.0, -110, -110)),
        NOW,
        "2026-11-15",
    )
    assert counts == {"games": 4, "too_soon": 0, "ds": 3, "mb": 3, "book": 3, "all_inputs": 2,
                      "bets": 1, "mb_export_ok": 1}  # fmt: skip
    (b,) = bets
    assert (b["game_id"], b["side"], b["line"], b["price"]) == ("1", "over", 140.0, -105)
    assert (b["ds_edge"], b["mb_edge"], b["avg_edge"]) == (10.0, 6.0, 8.0)
    assert b["rule_version"] == et.RULE_VERSION and b["book"] == "williamhill"
    assert "stake" not in b and b["min_rest_days"] == 3.0 and b["mb_gated"] is True


def test_find_bets_skips_soon_tips_and_stale_manualbets():
    args = (ds(**{"1": 150.0}), mb(("1", 150.0)), early(("1", 140.0, -110, -110)))
    bets, c = et.find_bets(games("1", tip=NOW + timedelta(minutes=30)), *args, NOW, "d")
    assert bets == [] and c["too_soon"] == 1
    stale = mb(("1", 150.0), created=NOW - timedelta(hours=40))
    bets, c = et.find_bets(games("1"), args[0], stale, args[2], NOW, "d")
    assert bets == [] and c["mb_export_ok"] == 0
    assert et.find_bets(games("1"), args[0], None, args[2], NOW, "d")[0] == []


def test_new_rows_is_idempotent():
    b = {"rule_version": et.RULE_VERSION, "game_id": "1", "line": 140}
    assert et.new_rows([], [b, dict(b)]) == [b]
    assert et.new_rows([b], [dict(b, line=141)]) == []
    assert et.new_rows([b], [dict(b, rule_version="et-v2")]) != []


def bet(gid="1", side="over", line=140.0, price=-110, day="2026-11-15", edge=5.0):
    return {"rule_version": et.RULE_VERSION, "game_id": gid, "league": "ncaab", "side": side,
            "line": line, "price": price, "game_date": day, "avg_edge": edge,
            "ds_version": "ncaab-v1", "min_rest_days": 1.0}  # fmt: skip


def test_grade_bet_clv_result_and_close_grade():
    g = et.grade_bet(bet(), {"home_score": 75, "away_score": 70}, 143.0, {"over": {"line": 142}})
    assert (g["grade"], g["clv"], g["clv_dayof"]) == ("win", 3.0, 2.0)
    assert g["profit"] == pytest.approx(100 / 110, abs=1e-4) and g["close_grade"] == "win"
    u = et.grade_bet(bet(side="under"), {"home_score": 70, "away_score": 70}, 143.0)
    assert (u["grade"], u["profit"], u["clv"], u["close_grade"]) == ("push", 0.0, -3.0, "win")
    p = et.grade_bet(bet(), None, 999.0)  # not final; insane close dropped
    assert (p["grade"], p["clv"], p["profit"]) == ("pending", None, None)


def test_summary_and_verdicts():
    rows = []
    for i in range(300):
        day = f"2026-12-{1 + i % 30:02d}"
        win = i % 5 < 3  # 60%
        final = {"home_score": 80, "away_score": 70 if win else 50}  # 150 / 130 vs 140
        rows.append(et.grade_bet(bet(str(i), day=day), final, 141.0))
    s = et.summarize(rows)
    assert s["bets"] == 300 and s["win_pct"] == 0.6 and s["clv_mean"] == 1.0
    assert s["clv_ci"] == (1.0, 1.0) and s["break_even"] == round(110 / 210, 3)
    assert s["verdict"] == "PASS"
    assert s["splits"]["side"]["over"]["bets"] == 300 and "<2d" in s["splits"]["rest"]
    assert "PASS" in et.render(s)
    assert et.verdict({**s, "bets": 10}).startswith("collecting")
    assert et.verdict({**s, "clv_mean": -0.1, "clv_ci": (-0.5, 0.3)}) == "FAIL"
    assert et.verdict({**s, "win_pct": 0.49, "clv_ci": (-0.1, 0.5)}) == "FAIL"
    mid = {**s, "win_pct": 0.51, "clv_ci": (-0.1, 0.5), "clv_mean": 0.2}
    assert et.verdict(mid).startswith("inconclusive")
    assert et.verdict({**mid, "bets": 600}).startswith("FAIL")


def test_day_ci_needs_two_days():
    assert et.day_ci([("d", 1.0), ("d", 2.0)]) is None
    lo, hi = et.day_ci([("a", 0.0), ("b", 2.0)], reps=200)
    assert 0.0 <= lo <= hi <= 2.0


# ---------- CLI (files + an in-memory warehouse) ----------


def _warehouse(path):
    import duckdb

    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE teams (league VARCHAR, team_id VARCHAR, abbreviation VARCHAR)")
    con.execute(
        "CREATE TABLE games (game_id VARCHAR, league VARCHAR, state VARCHAR, season_year INT,"
        " season_type INT, start_time_utc TIMESTAMPTZ, home_team_id VARCHAR, away_team_id VARCHAR,"
        " home_score INT, away_score INT, completed BOOLEAN, status VARCHAR)"
    )
    con.execute(
        "CREATE TABLE predictions (game_id VARCHAR, model VARCHAR, model_version VARCHAR,"
        " created_at TIMESTAMPTZ, p_home_win DOUBLE, pred_home_margin DOUBLE, pred_total DOUBLE)"
    )
    con.execute(
        "CREATE TABLE odds_snapshots (game_id VARCHAR, source VARCHAR, captured_at TIMESTAMPTZ,"
        " provider VARCHAR, details VARCHAR, spread_home DOUBLE, over_under DOUBLE,"
        " home_moneyline INT, away_moneyline INT)"
    )
    con.execute("INSERT INTO teams VALUES ('ncaab','h','HOME'), ('ncaab','a','AWAY')")
    con.execute(
        "INSERT INTO games VALUES ('1','ncaab','pre',2027,2,?, 'h','a',NULL,NULL,false,'pre'),"
        " ('0','ncaab','post',2027,2,?, 'a','h',70,60,true,'STATUS_FINAL')",
        [TIP, TIP - timedelta(days=2)],
    )
    con.execute(
        "INSERT INTO predictions VALUES ('1','v1','ncaab-v1-early',?,0.5,0,150.0),"
        " ('1','v1','ncaab-v1-early',?,0.5,0,100.0)",  # made after the log time: ignored
        [NOW - timedelta(hours=7), NOW + timedelta(hours=1)],
    )
    con.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "w.duckdb"
    _warehouse(db)
    books = tmp_path / "books"
    (books / "williamhill" / "early").mkdir(parents=True)
    (books / "williamhill" / "early" / "2026-11-15.json").write_text(
        json.dumps(early(("1", 140.0, -108, -112)))
    )
    mbf = tmp_path / "mb.json"
    mbf.write_text(json.dumps(mb(("1", 146.0))))
    monkeypatch.setattr(cli.config, "DB_PATH", db)
    monkeypatch.setattr(cli.config, "BOOKS_DIR", books)
    monkeypatch.setattr(cli.config, "WH_LINES_DIR", tmp_path / "wh" / "lines")
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(cli, "datetime", Clock)
    return tmp_path, mbf


def test_cli_log_is_idempotent_then_grades(env, capsys):
    out, mbf = env
    argv = ["log", "--date", "2026-11-15", "--manualbets", str(mbf), "--out-dir", str(out / "r")]
    assert cli.main(argv) == 0
    assert "1 qualify, 1 new" in capsys.readouterr().out
    assert cli.main(argv) == 0
    assert "1 qualify, 0 new" in capsys.readouterr().out
    bets = cli.read_jsonl(out / "r" / "bets.jsonl")
    assert len(bets) == 1 and bets[0]["price"] == -108 and bets[0]["ds_total"] == 150.0
    assert bets[0]["min_rest_days"] == 2.0
    assert len(cli.read_jsonl(out / "r" / "runs.jsonl")) == 2

    import duckdb

    con = duckdb.connect(str(cli.config.DB_PATH))
    con.execute("UPDATE games SET home_score=80, away_score=72, completed=true,"
                " status='STATUS_FINAL', state='post' WHERE game_id='1'")  # fmt: skip
    con.execute("INSERT INTO odds_snapshots VALUES ('1','closing',?,'x','',-3,142.5,NULL,NULL)",
                [TIP])  # fmt: skip
    con.close()
    assert cli.main(["grade", "--json", "--out-dir", str(out / "r")]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["record"] == "1-0-0" and s["clv_mean"] == 2.5
    assert (out / "r" / "grade.json").exists()
    assert cli.main(["status", "--out-dir", str(out / "r")]) == 0
    assert "1 bets logged" in capsys.readouterr().out


def test_cli_busy_warehouse_fails_with_one_line(env, capsys, monkeypatch):
    out, mbf = env
    monkeypatch.setattr(cli, "_open", lambda lock_wait: None)
    argv = ["log", "--date", "2026-11-15", "--manualbets", str(mbf), "--out-dir", str(out / "r")]
    assert cli.main(argv) == cli.BUSY_EXIT
    text = capsys.readouterr().out.strip()
    assert "\n" not in text and "busy" in text
    assert not (out / "r" / "bets.jsonl").exists()
    assert cli.read_jsonl(out / "r" / "runs.jsonl")[0]["status"] == "busy"


def test_cli_log_prefers_wh_screenshot_openers(env, capsys):
    """Amendment 2026-11-16: the owner's WH opening screenshots win over the Caesars feed; the
    feed fills sides they lack; each bet records its line_source."""
    out, mbf = env
    shots = early(("1", 139.5, -110, -110))
    shots["lines"] = [q for q in shots["lines"] if q["side"] == "over"]  # over only
    shots |= {"read_at": "2026-11-14T20:30:00-08:00", "early": True}
    d = out / "wh" / "lines" / "early"
    d.mkdir(parents=True)
    (d / "2026-11-15.json").write_text(json.dumps(shots))
    argv = ["log", "--date", "2026-11-15", "--manualbets", str(mbf), "--out-dir", str(out / "r")]
    assert cli.main(argv) == 0
    assert "with DS+MB+WH line" in capsys.readouterr().out
    (b,) = cli.read_jsonl(out / "r" / "bets.jsonl")
    assert (b["side"], b["line"], b["price"], b["line_source"]) == (
        "over",
        139.5,
        -110,
        "screenshot",
    )
    assert b["book_read_at"] == "2026-11-14T20:30:00-08:00"
    run = cli.read_jsonl(out / "r" / "runs.jsonl")[-1]
    assert run["status"] == "ok" and run["line_sources"] == {"screenshots": 1, "feed": 2}
    early_lines = cli.load_early_lines(datetime(2026, 11, 15).date())
    under = [q for q in early_lines["lines"] if q["side"] == "under"]
    assert under and under[0]["source"] == "feed" and under[0]["line"] == 140.0


def test_cli_log_feed_only_marks_feed(env, capsys):
    out, mbf = env
    argv = ["log", "--date", "2026-11-15", "--manualbets", str(mbf), "--out-dir", str(out / "r")]
    assert cli.main(argv) == 0
    (b,) = cli.read_jsonl(out / "r" / "bets.jsonl")
    assert b["line_source"] == "feed" and b["line"] == 140.0
