"""Model v1.1 player features (players.py): leakage, availability, parity, v1 unchanged."""

import json
import math
import random
from datetime import UTC, datetime

import pytest
from test_model import _bulk, _tiny_store, synth_store

from deepsports.analysis import players
from deepsports.analysis.backtest import run_backtest, walk_forward
from deepsports.analysis.compare import compare, compare_report, paired_deltas
from deepsports.analysis.features import FEATURES, build_features
from deepsports.analysis.model import (
    MODEL_VERSIONS,
    ModelV1,
    make_model,
    predict_upcoming,
    resolve_version,
    training_rows,
    uses_injury_override,
)
from deepsports.analysis.players import PLAYER_FEATURES, PlayerHistory

BASE_MIN = [36, 34, 32, 30, 26, 22, 16, 12, 8]  # player k's usual minutes (k=0 is the star)


def add_players(store, seed=3, p_dnp=0.08) -> None:
    """Nine players per team with stable roles; random DNPs; plus-minus follows the margin."""
    rng = random.Random(seed)
    games = store.con.execute(
        "SELECT game_id, home_team_id, away_team_id, home_score - away_score FROM games "
        "WHERE state = 'post'"
    ).fetchall()
    rows = []
    for gid, h, a, margin in games:
        for team, sign in ((h, 1), (a, -1)):
            for k, m in enumerate(BASE_MIN):
                dnp = rng.random() < p_dnp
                rows.append(
                    {
                        "game_id": gid,
                        "team_id": team,
                        "athlete_id": f"{team}-p{k}",
                        "did_not_play": dnp,
                        "minutes": None if dnp else max(m + rng.randint(-3, 3), 1),
                        "pts": None if dnp else max(round(m * 0.5 + rng.gauss(0, 4)), 0),
                        "plus_minus": None if dnp else round(sign * margin * m / 48),
                        "league": "nba",
                    }
                )
    _bulk(store.con, "player_game_stats", rows)


@pytest.fixture(scope="module")
def pstore():
    s = synth_store(seasons=(2024, 2025, 2026), rounds=3, n_pre=2)
    add_players(s)
    yield s
    s.close()


def _by_id(rows):
    return {r["game_id"]: r for r in rows}


def _same(a: dict, b: dict, names) -> bool:
    return all((math.isnan(a[n]) and math.isnan(b[n])) or a[n] == b[n] for n in names)


def _team_games(con, team):
    return [
        g
        for (g,) in con.execute(
            "SELECT game_id FROM games WHERE state = 'post' AND ? IN (home_team_id, away_team_id) "
            "AND season_year = 2026 ORDER BY start_time_utc",
            [team],
        ).fetchall()
    ]


# ---------- leakage ----------


def test_current_game_box_score_never_changes_its_own_features(pstore):
    """Ranking and availability come only from prior games: rewriting the predicted game's
    minutes / DNPs leaves its features identical, while the team's next game does change."""
    con = pstore.con
    g, nxt = _team_games(con, "1")[5:7]
    before = _by_id(build_features(con, include_players=True))
    con.execute("CREATE TEMP TABLE bk AS SELECT * FROM player_game_stats")
    try:
        con.execute(
            "UPDATE player_game_stats SET did_not_play = NOT did_not_play, "
            "minutes = 48 - coalesce(minutes, 0), plus_minus = -coalesce(plus_minus, 0) "
            "WHERE game_id = ?",
            [g],
        )
        after = _by_id(build_features(con, include_players=True))
    finally:
        con.execute("DELETE FROM player_game_stats")
        con.execute("INSERT INTO player_game_stats SELECT * FROM bk")
        con.execute("DROP TABLE bk")
    assert _same(before[g]["features"], after[g]["features"], PLAYER_FEATURES)
    assert not _same(before[nxt]["features"], after[nxt]["features"], PLAYER_FEATURES)
    # Everything before g is untouched too.
    t0 = before[g]["start_time_utc"]
    for gid, r in before.items():
        if r["start_time_utc"] <= t0:
            assert _same(r["features"], after[gid]["features"], PLAYER_FEATURES), gid


def test_same_evening_games_do_not_see_each_other_box_scores():
    """A game enters the player history only FINISH_LAG after tip (like team form): the
    rematch 1h after g0 has no player history; the one two days later does."""
    s = _tiny_store([("1", "2", 110, 100), ("2", "1", 100, 101), ("1", "2", 100, 99)])
    s.con.execute("UPDATE games SET start_time_utc = start_time_utc - INTERVAL 23 HOUR "
                  "WHERE game_id = 'g1'")  # fmt: skip
    add_players(s, p_dnp=0.0)
    r = _by_id(build_features(s.con, include_players=True))
    assert math.isnan(r["g0"]["features"]["top6_pm_diff"])
    assert math.isnan(r["g1"]["features"]["top6_pm_diff"])  # g0 not finished yet
    assert not math.isnan(r["g2"]["features"]["top3_pts_sum"])
    s.close()


# ---------- availability ----------


def _box(team: str, n: int, absent: set[int] = frozenset(), missing_rows=False):
    box = {}
    for k in range(n):
        a = f"{team}-p{k}"
        if k in absent:
            if not missing_rows:
                box[a] = (False, 0.0, 0.0, 0.0)
            continue
        box[a] = (True, float(BASE_MIN[k]), 10.0, 2.0)
    return box


def test_star_missing_previous_game_raises_missing_share():
    h = PlayerHistory()
    for _ in range(5):
        h.add("A", 2026, _box("A", 9))
    full = h.team_features("A", 2026)
    assert full["miss_share"] == 0 and full["top6_out_last"] == 0
    h.add("A", 2026, _box("A", 9, absent={0}))  # the star sits
    one = h.team_features("A", 2026)
    assert one["top6_out_last"] == 1 and one["top3_out_last"] == 1
    assert one["miss_share"] > 0.15  # ~36 of ~180 top-6 minutes
    assert one["top3_since"] == 1
    assert one["avail_top6_pm"] < one["top6_pm"]
    # Absent from the box score entirely counts the same as did_not_play.
    h2 = PlayerHistory()
    for _ in range(5):
        h2.add("A", 2026, _box("A", 9))
    h2.add("A", 2026, _box("A", 9, absent={0}, missing_rows=True))
    assert h2.team_features("A", 2026)["miss_share"] == pytest.approx(one["miss_share"])
    # Two of the last three missed.
    h.add("A", 2026, _box("A", 9))
    h.add("A", 2026, _box("A", 9, absent={0}))
    assert h.team_features("A", 2026)["top6_out_2of3"] == 1


def test_star_missing_shows_up_in_game_features(pstore):
    """In the warehouse path: team 1's star sits one game -> its next game's miss_share_diff
    moves toward team 1 being short-handed."""
    con = pstore.con
    g, nxt = _team_games(con, "1")[8:10]
    con.execute(
        "UPDATE player_game_stats SET did_not_play = false, minutes = 30 WHERE game_id = ? "
        "AND team_id = '1'",
        [g],
    )
    before = _by_id(build_features(con, include_players=True))[nxt]
    con.execute(
        "UPDATE player_game_stats SET did_not_play = true, minutes = NULL WHERE game_id = ? "
        "AND athlete_id = '1-p0'",
        [g],
    )
    after = _by_id(build_features(con, include_players=True))[nxt]
    sign = 1 if after["home_team_id"] == "1" else -1
    assert sign * (after["features"]["miss_share_diff"] - before["features"]["miss_share_diff"]) > 0
    assert (
        sign * (after["features"]["top6_out_last_diff"] - before["features"]["top6_out_last_diff"])
        >= 1
    )


def test_injury_override_replaces_played_last_game():
    h = PlayerHistory()
    for _ in range(4):
        h.add("A", 2026, _box("A", 9))
    h.add("A", 2026, _box("A", 9, absent={1}))  # p1 sat the last game
    proxy = h.team_features("A", 2026)
    snap = h.team_features("A", 2026, out_override={"A-p0"})  # report: p0 Out, p1 back
    assert proxy["top6_out_last"] == snap["top6_out_last"] == 1
    assert (proxy["top3_out_last"], snap["top3_out_last"]) == (0, 1)  # p1 slips to 4th by mpg
    assert snap["miss_share"] > proxy["miss_share"]  # p0 plays more than p1
    assert h.team_features("A", 2026, out_override=set())["top6_out_last"] == 0
    assert snap["top6_out_2of3"] == proxy["top6_out_2of3"]  # history-based, not overridden


def test_missing_box_score_and_new_season():
    h = PlayerHistory()
    h.add("A", 2026, _box("A", 9))
    h.add("A", 2026, None)  # no player rows for that game: skipped, not "everyone missed"
    assert h.team_features("A", 2026)["top6_out_last"] == 0
    h.add("A", 2027, _box("A", 9))  # a new season starts a fresh window
    assert len(h.games["A"]) == 1
    assert math.isnan(h.team_features("A", 2028)["miss_share"])


def test_injury_override_only_for_scheduled_games():
    st = synth_store(seasons=(2025, 2026), rounds=2, n_pre=2)
    add_players(st, p_dnp=0.0)  # nobody ever sits, so the proxy says "all available"
    con = st.con
    pre = [r for r in build_features(con, include_players=True) if r["state"] == "pre"][0]
    home, gid = pre["home_team_id"], pre["game_id"]
    star = f"{home}-p0"
    now = datetime.now(UTC)
    con.execute("INSERT INTO injury_captures VALUES (?, ?, ?, true, 1, 'nba')", [gid, home, now])
    con.execute(
        "INSERT INTO injury_reports (game_id, team_id, athlete_id, status, captured_at, "
        "captured_before_tip, league) VALUES (?, ?, ?, 'Out', ?, true, 'nba')",
        [gid, home, star, now],
    )
    try:
        off = _by_id(build_features(con, include_players=True))[gid]["features"]
        on_rows = _by_id(build_features(con, include_players=True, injury_override=True))
        on = on_rows[gid]["features"]
        # The snapshot replaces "played last game" for the home side: the star is Out.
        assert on["top6_out_last_diff"] == off["top6_out_last_diff"] + 1
        assert on["miss_share_diff"] > off["miss_share_diff"] + 0.15
        assert on["top6_out_2of3_diff"] == off["top6_out_2of3_diff"]  # history-based
        # Completed games never use snapshots: they are identical with the override on.
        off_rows = _by_id(build_features(con, include_players=True))
        for g, r in on_rows.items():
            if r["state"] == "post":
                assert _same(r["features"], off_rows[g]["features"], PLAYER_FEATURES)
        # The override follows the label: v1.1i uses the snapshot, v1.1 never does.
        by_label = {v: _by_id(predict_upcoming(con, v)) for v in ("v1.1", "v1.1i", "v1.1i-x")}
        assert (
            json.loads(by_label["v1.1i"][gid]["features_json"])["top6_out_last_diff"]
            == (on["top6_out_last_diff"])
        )
        assert (
            json.loads(by_label["v1.1"][gid]["features_json"])["top6_out_last_diff"]
            == (off["top6_out_last_diff"])
        )
        assert by_label["v1.1i"][gid]["p_home_win"] < by_label["v1.1"][gid]["p_home_win"]
        assert by_label["v1.1i-x"][gid]["model_version"] == "v1.1i-x"
        assert by_label["v1.1i-x"][gid]["features_json"] == by_label["v1.1i"][gid]["features_json"]
    finally:
        st.close()


# ---------- versions and parity ----------


def test_resolve_version():
    assert resolve_version("v1.1") == "v1.1" == resolve_version("v1.1-test")
    assert resolve_version("v1.1i") == "v1.1i" == resolve_version("v1.1i-test")
    assert uses_injury_override("v1.1i") and uses_injury_override("v1.1i-test")
    assert not any(uses_injury_override(v) for v in ("v1.0", "v1.1", "v1.1c", "v1.1-test"))
    assert MODEL_VERSIONS["v1.1i"][1:] == MODEL_VERSIONS["v1.1"][1:]
    for v in ("v1", "v1.0", "v1.0-test", "x", "v1.10"):
        assert resolve_version(v) == "v1.0"


@pytest.mark.parametrize("version", ["v1.0", "v1.1"])
def test_train_predict_feature_parity(pstore, version):
    """The columns the model trains on are exactly built for both training and scheduled rows,
    and predict_upcoming stores the same column set it was built with."""
    from deepsports.analysis.model import uses_players

    rows = build_features(pstore.con, include_players=uses_players(version))
    train = training_rows(rows)
    pre = [r for r in rows if r["state"] == "pre"]
    assert pre and train
    keys_train = {frozenset(r["features"]) for r in train}
    keys_pre = {frozenset(r["features"]) for r in pre}
    assert keys_train == keys_pre and len(keys_train) == 1
    (built,) = keys_train
    model = make_model(version).fit(train)
    assert set(model.columns()) <= built
    out = predict_upcoming(pstore.con, version)
    assert out and all(r["model_version"] == version for r in out)
    for r in out:
        assert set(json.loads(r["features_json"])) == built
    expected = set(FEATURES) | (set(PLAYER_FEATURES) if version == "v1.1" else set())
    assert built == expected


def test_model_rejects_rows_missing_a_feature(pstore):
    rows = training_rows(build_features(pstore.con))  # no player features
    with pytest.raises(KeyError, match="lacks model features"):
        make_model("v1.1").fit(rows)
    model = make_model("v1.0").fit(rows)
    bad = [
        {**rows[0], "features": {k: v for k, v in rows[0]["features"].items() if k != "elo_diff"}}
    ]
    with pytest.raises(KeyError):
        model.predict(bad)


def test_v1_output_unchanged_by_player_features(pstore):
    """v1 ignores the player columns: same features, same out-of-sample predictions, same
    predict_upcoming numbers whether or not player features were built."""
    plain = build_features(pstore.con)
    withp = build_features(pstore.con, include_players=True)
    assert all(set(r["features"]) == set(FEATURES) for r in plain)
    for a, b in zip(plain, withp, strict=True):
        assert a["game_id"] == b["game_id"]
        assert _same(a["features"], b["features"], FEATURES)
    pa = walk_forward(plain)["predictions"]
    pb = walk_forward(withp)["predictions"]
    assert pa == pb
    assert walk_forward(plain, model_factory=ModelV1)["predictions"] == pa
    assert run_backtest(pstore.con)["predictions"] == pa
    u0 = predict_upcoming(pstore.con, "v1.0")
    assert all(set(json.loads(r["features_json"])) == set(FEATURES) for r in u0)


def test_compare_runs_on_same_folds(pstore):
    res = compare(pstore.con, repeats=1)
    assert res["same_folds"] and res["versions"] == ["v1.0", "v1.1"]
    assert res["deltas"]["all"]["n"] == len(res["results"]["v1.0"]["predictions"])
    names = {x["feature"] for x in res["importance"]}
    assert set(make_model("v1.1").columns()) == names
    assert {x["feature"] for x in res["group_importance"]} >= {"availability", "elo"}
    md = compare_report(res)
    assert md.startswith("# DeepSports backtest: v1.1 vs v1")
    assert "Fold check: every training game tipped off before its test block (OK)" in md
    assert "Permutation importance" in md and "Ablation" in md


def test_paired_deltas_sign():
    base = [
        {"game_id": "a", "home_win": 1, "p_home_win": 0.5, "home_margin": 5,
         "pred_home_margin": 0.0, "total": 200, "pred_total": 210.0},
        {"game_id": "b", "home_win": 0, "p_home_win": 0.5, "home_margin": -5,
         "pred_home_margin": 0.0, "total": 200, "pred_total": 190.0},
    ]  # fmt: skip
    better = [
        {**base[0], "p_home_win": 0.7, "pred_home_margin": 4.0, "pred_total": 205.0},
        {**base[1], "p_home_win": 0.3, "pred_home_margin": -4.0, "pred_total": 195.0},
    ]
    d = paired_deltas(base, better)
    assert d["n"] == 2
    for k in ("brier", "log_loss", "margin_mae", "total_mae"):
        assert d[k]["mean"] < 0
    assert players.TOP_N == 6 and players.TOP_K == 3
