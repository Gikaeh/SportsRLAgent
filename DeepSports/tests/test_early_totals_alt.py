"""et-v1-alt: the altitude shadow of et-v1 (analysis/early_totals_alt.py and the CLI's alt path).
The key guarantee: et-v1's files and output are exactly what they were before the shadow existed."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import duckdb
import pytest
from early_alt_fixture import GAME_DATE, MADE, NOW, TIP, setup

from deepsports.analysis import early_totals as et
from deepsports.analysis import early_totals_alt as eta
from deepsports.analysis import early_totals_cli as cli

# ---------- pure logic ----------


def pred(version, total, made=MADE):
    return {"model_version": version, "pred_total": total, "created_at": made}


def test_alt_ds_preds_swaps_only_ncaab_v1_games():
    base = {"1": pred("ncaab-v1", 150.0), "2": pred("ncaab-v1-early", 150.0),
            "3": pred("ncaab-v1", 148.0), "4": pred("ncaab-v1", 147.0)}  # fmt: skip
    alt = {"1": pred("ncaab-v1.1alt", 151.0), "2": pred("ncaab-v1.1alt", 140.0),
           "4": pred("ncaab-v1.1alt", 130.0, MADE - timedelta(days=1))}  # fmt: skip
    out, c = eta.alt_ds_preds(base, alt)
    assert out["1"]["pred_total"] == 151.0 and out["1"]["model_version"] == "ncaab-v1.1alt"
    assert out["2"] == base["2"]  # et-v1 used the early model: so does the shadow
    assert out["3"] == base["3"]  # no alt row: v1 fallback
    assert out["4"] == base["4"]  # stale alt row (yesterday's run): v1 fallback
    assert c == {"alt": 1, "fallback_v1": 2, "other": 1}
    assert base["1"]["pred_total"] == 150.0  # input untouched


def test_differences_kinds():
    b = lambda g, side="over": {"game_id": g, "side": side}  # noqa: E731
    d = eta.differences([b("1"), b("3"), b("4")], [b("1"), b("2"), b("4", "under")])
    assert [(x["game_id"], x["kind"]) for x in d] == [("2", "alt_only"), ("3", "v1_only"),
                                                      ("4", "flip")]  # fmt: skip


def graded(gid, day, profit, side="over", rule=et.RULE_VERSION):
    grade = "pending" if profit is None else "win" if profit > 0 else "loss"
    return {"rule_version": rule, "game_id": gid, "game_date": day, "side": side,
            "grade": grade, "profit": profit, "price": -110, "avg_edge": 5.0, "clv": None,
            "close_grade": None}  # fmt: skip


def test_paired_units_counts_only_differing_games_on_paired_nights():
    w, lo = 0.9091, -1.0
    v1 = [graded("1", "d1", w), graded("3", "d1", lo), graded("9", "d0", lo),
          graded("5", "d2", None)]  # fmt: skip
    alt = [graded("1", "d1", w), graded("2", "d1", w), graded("6", "d2", lo),
           graded("7", "d2", None)]  # fmt: skip
    p = eta.paired_units(v1, alt, {"d1", "d2"})
    # d0 is not a paired night; 1 agrees; 2 alt-only win, 3 v1-only loss, 6 alt-only loss;
    # 5 and 7 are pending
    assert p["differing"] == 3 and p["differing_pending"] == 2
    assert p["diff_units"] == round(w - lo + lo, 2)
    assert p["by_kind"]["alt_only"]["record"] == "1-1-0"
    assert p["by_kind"]["v1_only"]["record"] == "0-1-0"
    assert p["diff_units_ci"] is not None
    assert eta.paired_units(v1, alt, {"d1"}, through=date(2000, 1, 1))["differing"] == 0


def test_model_compare_and_verdict():
    rows = [
        {"day": "2026-12-01", "elevation_m": 2200, "actual": 150, "v1": 140, "alt": 144},
        {"day": "2026-12-02", "elevation_m": 100, "actual": 140, "v1": 141, "alt": 141.5},
        {"day": "2026-12-03", "elevation_m": None, "actual": 130, "v1": 131, "alt": 131},
    ]
    m = eta.model_compare(rows)
    assert m["games"] == 3 and m["high_venue_games"] == 1
    assert (m["high_bias_v1"], m["high_bias_alt"]) == (10.0, 6.0)
    assert m["mae_v1"] == 4.0 and m["mae_alt"] == pytest.approx((6 + 1.5 + 1) / 3, abs=1e-3)
    assert m["mae_diff"] == pytest.approx((-4 + 0.5 + 0) / 3, abs=1e-3)
    paired = {"diff_units": 0.5}
    assert eta.verdict(paired, m, date(2027, 3, 14)).startswith("collecting")
    after = date(2027, 3, 15)
    assert eta.verdict(paired, m, after).startswith("PASS")
    assert eta.verdict({"diff_units": -0.1}, m, after) == "FAIL"
    assert eta.verdict(paired, m | {"mae_diff": 0.03}, after) == "FAIL"
    assert eta.verdict(paired, m | {"high_bias_alt": -11.0}, after) == "FAIL"
    assert eta.verdict(paired, None, after).startswith("no verdict")


def test_summarize_and_render():
    v1 = [graded("3", "d1", -1.0)]
    alt = [graded("2", "d1", 0.9091, rule=eta.ALT_RULE_VERSION)]
    s = eta.summarize(v1, alt, {"d1"}, [], date(2026, 12, 1))
    assert s["paired"]["diff_units"] == 1.91 and s["record"]["bets"] == 1
    assert "verdict" not in s["record"] and s["verdict"].startswith("collecting")
    text = eta.render(s)
    assert "et-v1-alt" in text and "+1.91u" in text
    assert "unavailable" in eta.render(eta.summarize(v1, alt, {"d1"}, None, date(2026, 12, 1)))


# ---------- CLI ----------


@pytest.fixture
def env(tmp_path, monkeypatch):
    db, mbf = setup(tmp_path, monkeypatch, cli)
    return tmp_path, db, mbf


def log_argv(out, mbf, *extra):
    return ["log", "--date", GAME_DATE, "--manualbets", str(mbf), "--out-dir", str(out), *extra]


# et-v1's output on the fixture, captured with the code as it was before the shadow existed
# (commit 30c69fc). Times are normalised to UTC (DuckDB returns them in the session time zone).
GOLDEN_STDOUT = (
    "early-totals 2026-11-23: 5 games, 5 with DS+MB+WH line, 4 qualify, 4 new\n"
    "  A1 @ H1 over 140 -110 (DS +10.0, MB +6.0)\n"
    "  A3 @ H3 over 140 -110 (DS +8.0, MB +4.0)\n"
    "  A4 @ H4 over 140 -110 (DS +10.0, MB +6.0)\n"
    "  A5 @ H5 over 140 -110 (DS +10.0, MB +6.0)\n"
)
GOLDEN_RUN = {"rule_version": "et-v1", "ran_at": "2026-11-23T05:00:00+00:00",
              "game_date": "2026-11-23", "status": "ok",
              "book_grabbed_at": "2026-11-22T21:00:00-08:00", "book_read_at": None,
              "line_sources": {"screenshots": 0, "feed": 10},
              "mb_created_at": "2026-11-22T22:00:00+00:00", "games": 5, "too_soon": 0,
              "ds": 5, "mb": 5, "book": 5, "all_inputs": 5, "bets": 4, "mb_export_ok": 1,
              "new": 4}  # fmt: skip


def golden_bet(gid, ds_total, mb_total, ds_edge, mb_edge, version="ncaab-v1"):
    return {"rule_version": "et-v1", "logged_at": "2026-11-23T05:00:00+00:00",
            "game_date": "2026-11-23", "game_id": gid, "league": "ncaab", "away": f"A{gid}",
            "home": f"H{gid}", "tip_utc": (TIP + timedelta(minutes=int(gid))).isoformat(),
            "market": "total", "side": "over", "line": 140.0, "price": -110,
            "book": "williamhill", "line_source": "feed",
            "book_grabbed_at": "2026-11-22T21:00:00-08:00", "book_read_at": None,
            "ds_total": ds_total, "ds_version": version, "ds_created_at": MADE.isoformat(),
            "mb_total": mb_total, "mb_gated": True, "mb_created_at": "2026-11-22T22:00:00+00:00",
            "ds_edge": ds_edge, "mb_edge": mb_edge, "avg_edge": (ds_edge + mb_edge) / 2,
            "min_rest_days": None}  # fmt: skip


GOLDEN_BETS = [
    golden_bet("1", 150.0, 146.0, 10.0, 6.0),
    golden_bet("3", 148.0, 144.0, 8.0, 4.0),
    golden_bet("4", 150.0, 146.0, 10.0, 6.0, "ncaab-v1-early"),
    golden_bet("5", 150.0, 146.0, 10.0, 6.0),
]


def _utc(rows):
    out = []
    for r in rows:
        r = dict(r)
        for k in ("tip_utc", "ds_created_at"):
            if k in r:
                r[k] = datetime.fromisoformat(r[k]).astimezone(NOW.tzinfo).isoformat()
        out.append(r)
    return out


def test_et_v1_log_is_unchanged_by_the_shadow(env, capsys):
    """Golden: et-v1's bets.jsonl, runs.jsonl and stdout lines match the pre-shadow output, and
    the files are byte-identical with and without the shadow (`--no-alt`)."""
    tmp, _, mbf = env
    assert cli.main(log_argv(tmp / "with", mbf)) == 0
    out = capsys.readouterr().out
    assert out.startswith(GOLDEN_STDOUT)
    assert cli.main(log_argv(tmp / "without", mbf, "--no-alt")) == 0
    assert capsys.readouterr().out == GOLDEN_STDOUT
    for name in ("bets.jsonl", "runs.jsonl"):
        assert (tmp / "with" / name).read_bytes() == (tmp / "without" / name).read_bytes()
    assert _utc(cli.read_jsonl(tmp / "with" / "bets.jsonl")) == GOLDEN_BETS
    assert cli.read_jsonl(tmp / "with" / "runs.jsonl") == [GOLDEN_RUN]
    assert sorted(p.name for p in (tmp / "without").iterdir()) == [
        ".lock", "bets.jsonl", "runs.jsonl"]  # fmt: skip


def test_cli_logs_the_shadow_to_its_own_file(env, capsys):
    tmp, _, mbf = env
    out = tmp / "r"
    assert cli.main(log_argv(out, mbf)) == 0
    text = capsys.readouterr().out
    assert "early-totals et-v1-alt 2026-11-23: 4 qualify, 4 new" in text
    assert "alt DS on 3 games, v1 fallback 1" in text
    assert "differs from et-v1 on: 2 alt_only, 3 v1_only" in text
    alt = cli.read_jsonl(out / "alt" / "bets.jsonl")
    assert [(b["game_id"], b["ds_version"]) for b in alt] == [
        ("1", "ncaab-v1.1alt"), ("2", "ncaab-v1.1alt"), ("4", "ncaab-v1-early"),
        ("5", "ncaab-v1")]  # fmt: skip
    assert {b["rule_version"] for b in alt} == {"et-v1-alt"}
    assert alt[1]["ds_total"] == 146.0  # the alt row made after the log time is ignored
    (run,) = cli.read_jsonl(out / "alt" / "runs.jsonl")
    assert run["status"] == "ok" and run["ds_alt"] == 3 and run["new"] == 4
    # first row per game is frozen: a re-run adds nothing to either log
    assert cli.main(log_argv(out, mbf)) == 0
    assert "4 qualify, 0 new" in capsys.readouterr().out
    assert len(cli.read_jsonl(out / "alt" / "bets.jsonl")) == 4
    assert len(cli.read_jsonl(out / "bets.jsonl")) == 4


def test_shadow_failure_leaves_et_v1_alone(env, capsys, monkeypatch):
    tmp, _, mbf = env

    def boom(*a, **k):
        raise RuntimeError("no alt")

    monkeypatch.setattr(cli, "load_alt_predictions", boom)
    assert cli.main(log_argv(tmp / "r", mbf)) == 0
    cap = capsys.readouterr()
    assert cap.out == GOLDEN_STDOUT and "shadow failed" in cap.err
    assert _utc(cli.read_jsonl(tmp / "r" / "bets.jsonl")) == GOLDEN_BETS
    assert not (tmp / "r" / "alt" / "bets.jsonl").exists()
    assert cli.read_jsonl(tmp / "r" / "alt" / "runs.jsonl")[0]["status"].startswith("error")


def test_busy_writes_a_busy_row_for_both(env, capsys, monkeypatch):
    tmp, _, mbf = env
    monkeypatch.setattr(cli, "_open", lambda lock_wait: None)
    assert cli.main(log_argv(tmp / "r", mbf)) == cli.BUSY_EXIT
    assert "\n" not in capsys.readouterr().out.strip()
    assert cli.read_jsonl(tmp / "r" / "runs.jsonl")[0]["status"] == "busy"
    assert cli.read_jsonl(tmp / "r" / "alt" / "runs.jsonl")[0]["status"] == "busy"


def test_grade_alt_reports_the_preregistered_metrics(env, capsys):
    tmp, db, mbf = env
    out = tmp / "r"
    assert cli.main(log_argv(out, mbf)) == 0
    # finals: 1 = 150 (over wins), 2 = 150 (alt-only win), 3 = 130 (v1-only loss)
    con = duckdb.connect(str(db))
    for gid, total in (("1", 150), ("2", 150), ("3", 130), ("4", 150), ("5", 150)):
        con.execute("UPDATE games SET home_score=?, away_score=?, completed=true,"
                    " status='STATUS_FINAL', state='post' WHERE game_id=?",
                    [total // 2 + 1, total - total // 2 - 1, gid])  # fmt: skip
    con.execute("INSERT INTO odds_snapshots VALUES ('1','closing',?,'x','',-3,142.5,NULL,NULL)",
                [TIP])  # fmt: skip
    con.close()
    capsys.readouterr()
    assert cli.main(["grade", "--json", "--out-dir", str(out)]) == 0
    v1_grade_before = (out / "grade.json").read_bytes()
    capsys.readouterr()
    assert cli.main(["grade", "--alt", "--json", "--out-dir", str(out)]) == 0
    s = json.loads(capsys.readouterr().out)
    assert (out / "grade.json").read_bytes() == v1_grade_before  # et-v1's grade untouched
    assert (out / "alt" / "grade.json").exists()
    p = s["paired"]
    assert p["differing"] == 2 and p["diff_units"] == round(100 / 110 + 1, 2)
    m = s["models"]
    # games 1, 2, 3 have both versions; 1 (2184 m) and 2 (1600 m) are high venues
    assert m["games"] == 3 and m["high_venue_games"] == 2
    assert m["high_bias_v1"] == pytest.approx(((150 - 150) + (150 - 141)) / 2)
    # grading uses the latest pre-tip row: game 2's alt re-prediction (100) after the 21:00 log
    assert m["high_bias_alt"] == pytest.approx(((150 - 151) + (150 - 100)) / 2)
    assert s["verdict"].startswith("collecting")
    assert cli.main(["grade", "--alt", "--out-dir", str(out)]) == 0
    assert "Differing bets 2" in capsys.readouterr().out
    assert cli.main(["status", "--alt", "--out-dir", str(out)]) == 0
    assert "et-v1-alt (shadow): 4 bets logged" in capsys.readouterr().out
