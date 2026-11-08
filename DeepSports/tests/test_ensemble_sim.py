import random
from datetime import UTC, date, datetime, timedelta

from test_ensemble_bets import FORM, _line, _raw

from deepsports.analysis import ensemble_bets as eb
from deepsports.analysis import ensemble_sim as sim


def test_choose_days_even_spacing():
    start, end = date(2026, 10, 23), date(2026, 11, 5)
    counts = {start + timedelta(days=i): 8 for i in range(14)}
    counts[date(2026, 10, 29)] = 3  # too few games
    counts[date(2026, 11, 3)] = 0
    counts[date(2026, 11, 5)] = 2
    days = sim.choose_days(counts, start, end, n=10)
    assert len(days) == 10 and days == sorted(days)
    assert date(2026, 10, 29) not in days and date(2026, 11, 5) not in days
    assert days[0] == start and days[-1] == date(2026, 11, 4)
    assert max((b - a).days for a, b in zip(days, days[1:], strict=False)) <= 2
    assert sim.choose_days({start: 5}, start, end) == [start]


def test_day_window_eastern():
    tip = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)  # Wed Nov 4, 7 pm Eastern
    now, until = sim.day_window(tip, date(2026, 11, 4))
    assert now == tip - timedelta(hours=1)
    assert until == datetime(2026, 11, 5, 5, 0, tzinfo=UTC)  # midnight Eastern (EST)


def test_asof_predictions_trains_only_on_finished_games(monkeypatch):
    from deepsports.analysis import model

    now = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)
    seen = {}

    class Fake:
        def fit(self, rows):
            seen["train"] = sorted(r["game_id"] for r in rows)
            return self

        def predict(self, rows):
            return [{"p_home_win": 0.5, "pred_home_margin": 1.0, "pred_total": 220.0} for _ in rows]

    monkeypatch.setattr(model, "make_model", lambda v: Fake())

    def row(gid, start, season=2027, done=True):
        return {"game_id": gid, "season": season, "start_time_utc": start,
                "home_margin": 3 if done else None}  # fmt: skip

    rows = [
        row("burn", now - timedelta(days=800), season=2025),  # burn-in season, never trained on
        row("old", now - timedelta(days=400), season=2026),
        row("y", now - timedelta(hours=5)),  # finished (4h lag) before now
        row("late", now - timedelta(hours=3)),  # tipped before now but not finished
        row("t1", now + timedelta(hours=1)),  # target, already final in the warehouse
    ]
    preds, n = sim.asof_predictions(rows, now, ["t1"])
    assert seen["train"] == ["old", "y"] and n == 2
    assert preds == {"t1": {"model_version": "v1.1", "p_home_win": 0.5, "pred_home_margin": 1.0,
                            "pred_total": 220.0}}  # fmt: skip


def _games():
    pred = lambda m, t: {"model_version": "v1.1", "p_home_win": 0.5,  # noqa: E731
                         "pred_home_margin": m, "pred_total": t}  # fmt: skip
    return [
        eb.build_game(_raw("g1"), {"last": _line(spread=-3.5, total=225.5, hml=-160, aml=135)},
                      pred(4.0, 230.0), FORM, {}, {}),  # total edge +4.5 -> over
        eb.build_game(_raw("g2"), {"last": _line(spread=9.5, total=231.5, hml=380, aml=-480)},
                      pred(-13.5, 230.0), FORM, {}, {}),  # spread edge 4.0 toward away
        eb.build_game(_raw("g3"), {"last": _line(spread=-7.5, total=218.5, hml=-300, aml=240)},
                      None, FORM, {}, {}),
    ]  # fmt: skip


def test_baseline_bets():
    b = sim.baseline_bets(_games(), random.Random(42))
    me = b["model_edge"]
    assert (me["game_id"], me["market"], me["side"], me["line"]) == ("g1", "total", "over", 225.5)
    assert me["edge_points"] == 4.5
    assert (b["home_ml_favorite"]["game_id"], b["home_ml_favorite"]["price"]) == ("g3", -300)
    sd = b["spread_underdog"]
    assert (sd["game_id"], sd["side"], sd["line"], sd["price"]) == ("g2", "home", 9.5, -112)
    assert (b["over_highest_total"]["game_id"], b["over_highest_total"]["line"]) == ("g2", 231.5)
    r = b["random"]
    assert (r["game_id"], r["market"], r["side"]) in sim.offered(_games())
    assert sim.baseline_bets(_games(), random.Random(42))["random"] == r  # seeded
    assert all(v["stake"] == 1 for v in b.values())


def test_plurality_pick_ties():
    def pk(g, m, s, c):
        return {"game_id": g, "market": m, "side": s, "line": 1.5, "price": -110, "confidence": c}

    picks = {
        "a01": [pk("g2", "total", "over", 0.6)],
        "a02": [pk("g2", "total", "over", 0.55)],
        "a03": [pk("g1", "spread", "home", 0.6)],
        "a04": [pk("g1", "spread", "home", 0.6)],
        "a05": [],
    }
    p = sim.plurality_pick(picks)  # 2-2 tie: confidence 1.2 beats 1.15
    assert (p["game_id"], p["votes"], p["n_agents"]) == ("g1", 2, 5)
    picks["a02"] = [pk("g2", "total", "over", 0.6)]  # 1.2 vs 1.2: lower game_id
    assert sim.plurality_pick(picks)["game_id"] == "g1"
    picks["a05"] = [pk("g2", "total", "over", 0.5)]
    assert sim.plurality_pick(picks)["game_id"] == "g2"
    assert sim.plurality_pick({"a01": []}) is None


# ---------- college: sampling, as-of model, anonymization ----------


def test_sample_games_seeded_and_capped():
    ids = [f"g{i:03d}" for i in range(60)]
    a = sim.sample_games(ids, 25, random.Random(20260124))
    assert len(a) == 25 and a == sorted(a) and set(a) <= set(ids)
    assert a == sim.sample_games(list(reversed(ids)), 25, random.Random(20260124))
    assert sim.sample_games(ids[:10], 25, random.Random(1)) == ids[:10]


def test_college_asof_predictions_gate_and_cutoff(monkeypatch):
    from deepsports.analysis import ncaab

    now = datetime(2026, 1, 24, 15, 0, tzinfo=UTC)
    fits = []

    class Fake:
        def __init__(self, fs):
            self.fs = fs

        def fit(self, rows):
            fits.append((self.fs, sorted(r["game_id"] for r in rows)))
            return self

        def predict(self, rows):
            return [{"p_home_win": 0.6, "pred_home_margin": 2.0, "pred_total": 150.0} for _ in rows]

    monkeypatch.setattr(ncaab, "make_model", Fake)
    choice = {t: {"feature_set": "team", "min_games": 5, "mode": "prior_rows"}
              for t in ("win", "margin", "total")}  # fmt: skip

    def row(gid, start, rt_n, state="post", d1=True, has_prior=True):
        return {"game_id": gid, "start_time_utc": start, "rt_n": rt_n, "state": state, "d1": d1,
                "has_prior": has_prior}  # fmt: skip

    rows = [
        row("done", now - timedelta(days=3), 9),
        row("early_row", now - timedelta(days=3), 1),  # v1 drops it (rt_n < 5); prior keeps it
        row("non_d1", now - timedelta(days=3), 9, d1=False),
        row("unfinished", now - timedelta(hours=2), 9),  # tipped, not finished by now
        row("t_v1", now + timedelta(hours=2), 6),
        row("t_early", now + timedelta(hours=2), 2),
        row("t_none", now + timedelta(hours=2), 0),
    ]
    preds, counts = sim.college_asof_predictions(
        rows, rows, now, ["t_v1", "t_early", "t_none"], {"choice": choice}, {"choice": choice}
    )
    assert preds["t_v1"]["model_version"] == "ncaab-v1"
    assert preds["t_early"]["model_version"] == "ncaab-v1-early"
    assert "t_none" not in preds
    assert counts == {"ncaab-v1": 1, "ncaab-v1-early": 1, "none": 1, "train_v1": 2,
                      "train_prior": 2}  # fmt: skip
    v1_train, prior_train = fits[0][1], fits[1][1]
    assert v1_train == ["done"] and prior_train == ["done", "early_row"]


REAL = [("Duke Blue Devils", "DUKE", "Cameron Indoor Stadium"),
        ("North Carolina Tar Heels", "UNC", "Dean Smith Center")]  # fmt: skip


def _college_slate():
    raw = {**_raw("401800001", league="ncaab"), "season_year": 2026,
           "start_time_utc": datetime(2026, 1, 25, 1, 0, tzinfo=UTC),
           "venue": REAL[0][2], "broadcasts": "ESPN2",
           "home_abbr": REAL[0][1], "home_name": REAL[0][0],
           "away_abbr": REAL[1][1], "away_name": REAL[1][0]}  # fmt: skip
    pred = {"model_version": "ncaab-v1", "p_home_win": 0.7, "pred_home_margin": 6.0,
            "pred_total": 150.0}  # fmt: skip
    g = eb.build_game(raw, {"last": _line(spread=-5.5, total=148.5)}, pred, FORM, {}, {})
    return {"created_at": "2026-01-24T23:00:00+00:00", "context_version": "x",
            "unlined_games": 0, "max_picks": 1, "max_stake": 1,
            "brief_notes": ["No injury data for this date."], "games": [g]}  # fmt: skip


def test_anonymized_context_has_no_real_names_or_years():
    terms = sorted({t for row in REAL for t in row} | {"Duke", "Blue Devils", "2025", "2026",
                                                       "ESPN2"})  # fmt: skip
    slate = _college_slate()
    plain = eb.render_context(slate, seed=0, one_pick=True)
    assert set(sim.find_leaks(plain, terms)) >= {"DUKE", "UNC", "2026"}  # the check works
    anon, key = sim.anonymize_slate(slate, random.Random(7), forbidden={"DUKE", "UNC", "QAB"})
    for seed in range(5):
        text = eb.render_context(anon, seed=seed, one_pick=True)
        assert sim.find_leaks(text, terms) == []
        assert "Cameron" not in text and "ESPN" not in text and "401800001" not in text
        assert sim.ANON_NOTE in text and "UTC" not in text
    g = anon["games"][0]
    assert g["game_id"] == "G01" and g["real_game_id"] == "401800001"
    assert g["home"]["name"] == f"Team {g['home']['abbr']}" and g["home"]["abbr"].startswith("Q")
    assert g["home"]["abbr"] != g["away"]["abbr"] and "QAB" not in (g["home"]["abbr"],)
    assert anon["context_version"] == sim.ANON_CONTEXT_VERSION
    assert key["games"]["G01"]["game_id"] == "401800001"
    assert key["teams"][g["home"]["abbr"]] == "Duke Blue Devils"
    # picks validate against the anonymized ids, at the slate's price
    picks, _ = eb.validate_picks({"picks": [{"game_id": "G01", "market": "spread",
                                             "side": "home"}]}, anon)  # fmt: skip
    assert picks[0]["line"] == -5.5
    # labels differ between days (seeded per day)
    other, _ = sim.anonymize_slate(slate, random.Random(8), forbidden=set())
    assert (
        other["games"][0]["home"]["abbr"] != g["home"]["abbr"]
        or other["games"][0]["away"]["abbr"] != g["away"]["abbr"]
    )


def test_baseline_ml_fallback():
    games = [
        eb.build_game(_raw("g1"), {"last": _line(hml=150, aml=-180)}, None, FORM, {}, {}),
        eb.build_game(_raw("g2"), {"last": _line(hml=None, aml=None)}, None, FORM, {}, {}),
    ]
    assert sim.baseline_bets(games, random.Random(1))["home_ml_favorite"] is None
    b = sim.baseline_bets(games, random.Random(1), ml_fallback=True)["home_ml_favorite"]
    assert (b["game_id"], b["side"], b["price"], b["fallback"]) == ("g1", "away", -180, True)
