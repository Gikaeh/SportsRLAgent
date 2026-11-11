"""Player impact ratings + injury impact in points (player_impact.py): leakage, OUT lists,
redistribution, rating recovery, and the evaluation helpers. No network; synthetic warehouse."""

import math
import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from test_model import synth_store
from test_players import add_players

from deepsports.analysis import player_impact as pi
from deepsports.analysis import player_impact_eval as pe
from deepsports.analysis.features import FINISH_LAG, build_features
from deepsports.analysis.players import Line


@pytest.fixture(scope="module")
def istore():
    s = synth_store(seasons=(2024, 2025, 2026), rounds=3, n_pre=2)
    add_players(s)
    yield s
    s.close()


def _same(a: dict, b: dict, names) -> bool:
    return all((math.isnan(a[n]) and math.isnan(b[n])) or a[n] == b[n] for n in names)


def _team_games(data: pi.Data, team: str, season: int = 2026) -> list[str]:
    return [data.games[i].game_id for i in data.team_idx[(team, season)]]


def _scrambled(data: pi.Data, gid: str) -> pi.Data:
    return pe._scramble_box(data, [gid])


TEAMS6 = list("ABCDEF")
MINS9 = [36, 34, 32, 30, 26, 22, 16, 12, 8]


def _synth_data(extra=()) -> pi.Data:
    """Hand-built Data, no DB: one game per day at 00:00 UTC for 60 days (random pairs, nine
    players a side with random absences), plus `extra` games (game_id, tip, home, away)."""
    rng = random.Random(4)
    t0 = datetime(2025, 11, 1, tzinfo=UTC)
    sched = [(f"d{i}", t0 + timedelta(days=i), *rng.sample(TEAMS6, 2)) for i in range(60)]
    games, box = [], {}
    for gid, start, h, a in [*sched, *extra]:
        margin = float(rng.randint(-20, 20) or 1)
        games.append(pi.Game(gid, 2026, start, h, a, False, margin, "post"))
        for t in (h, a):
            box[(gid, t)] = {
                f"{t}-p{k}": (True, float(m), 10.0, float(rng.randint(-10, 10)))
                if rng.random() > 0.1
                else (False, 0.0, 0.0, 0.0)
                for k, m in enumerate(MINS9)
            }
    return pi.Data(games, box)


# ---------- leakage ----------


@pytest.mark.parametrize("method", list(pi.METHODS))
def test_own_box_score_never_changes_own_features(istore, method):
    """Rewriting the predicted game's own box score (DNPs flipped, minutes and plus-minus
    inverted) leaves its proxy impact features identical, and every earlier game's too; the
    team's next game changes (the check has teeth). The oracle (LEAKED) does change."""
    data = pi.load_data(istore.con)
    g, nxt = _team_games(data, "1")[6:8]
    before = pi.impact_features(data, method, oracle=True)
    after = pi.impact_features(_scrambled(data, g), method, oracle=True)
    assert _same(before[g], after[g], pi.IMPACT_FEATURES)
    assert not _same(before[g], after[g], pi.ORACLE_FEATURES)
    assert not _same(before[nxt], after[nxt], pi.IMPACT_FEATURES)
    t0 = data.by_id[g].start
    for x in data.games:
        if x.start <= t0:
            assert _same(before[x.game_id], after[x.game_id], pi.IMPACT_FEATURES), x.game_id


def test_rating_as_of_never_uses_later_games(istore):
    """A rating as of time t only reads games with tip + FINISH_LAG <= t: rewriting every later
    result and box score leaves it identical."""
    data = pi.load_data(istore.con)
    mid = data.games[len(data.games) // 2]
    t = mid.start
    win = pi.Ratings(data, "rapm10").window(t)
    assert win and all(g.start + FINISH_LAG <= t for g in win)
    assert mid not in win
    base = pi.Ratings(data, "rapm10").as_of(t)
    later = [
        pi.Game(g.game_id, g.season, g.start, g.home, g.away, g.neutral, -g.margin * 3, g.state)
        if g.margin is not None and g.start + FINISH_LAG > t
        else g
        for g in data.games
    ]
    box = {
        k: ({a: (True, 47.0, 0.0, 99.0) for a in v} if data.by_id[k[0]].start > t else v)
        for k, v in data.box.items()
        if k[0] in data.by_id
    }
    assert pi.Ratings(pi.Data(later, box), "rapm10").as_of(t) == base


@pytest.mark.parametrize("method", list(pi.METHODS))
def test_finish_lag_boundary(method):
    """Two games just before t: one tipped 2h earlier (not finished: tip + 4h > t), one 5h
    earlier (finished). Rewriting the 2h game leaves the rating as of t identical; rewriting
    the 5h game changes it, so the window really is cut at FINISH_LAG, not at the tip."""
    t = datetime(2025, 12, 31, 3, tzinfo=UTC)
    near = ("near", t - timedelta(hours=2), "A", "B")
    far = ("far", t - timedelta(hours=5), "C", "D")
    assert t - near[1] < FINISH_LAG < t - far[1]
    data = _synth_data([near, far])
    win = {g.game_id for g in pi.Ratings(data, method).window(t)}
    assert "far" in win and "near" not in win
    base = pi.Ratings(data, method).as_of(t)
    assert pi.Ratings(pe._scramble_box(data, ["near"]), method).as_of(t) == base
    assert pi.Ratings(pe._scramble_box(data, ["far"]), method).as_of(t) != base


def test_same_evening_games_share_one_as_of():
    """Two games on one slate, 8h apart (longer than FINISH_LAG, so a per-game cut-off would
    let the later one see the earlier): the later game's features ignore the earlier game's
    box score; the next slate's game does see it."""
    first = ("early", datetime(2025, 12, 20, 19, tzinfo=UTC), "A", "B")
    second = ("late", datetime(2025, 12, 21, 3, tzinfo=UTC), "A", "C")
    nxt = ("next", datetime(2025, 12, 22, 3, tzinfo=UTC), "A", "D")
    assert second[1] - first[1] > FINISH_LAG
    assert pi.slate_date(first[1]) == pi.slate_date(second[1]) != pi.slate_date(nxt[1])
    data = _synth_data([first, second, nxt])
    ids = ["late", "next"]
    before = pi.impact_features(data, "pm48", game_ids=ids)
    after = pi.impact_features(pe._scramble_box(data, ["early"]), "pm48", game_ids=ids)
    assert _same(before["late"], after["late"], pi.IMPACT_FEATURES)
    assert not _same(before["next"], after["next"], pi.IMPACT_FEATURES)


def test_oracle_columns_only_on_request(istore):
    data = pi.load_data(istore.con)
    plain = pi.impact_features(data, "pm48")
    assert not set(pi.ORACLE_FEATURES) & set(next(iter(plain.values())))
    rows = pi.with_impact(build_features(istore.con, include_players=True), plain)
    assert not set(pi.ORACLE_FEATURES) & set(rows[0]["features"])
    assert set(pi.ORACLE_FEATURES) <= set(
        pi.impact_features(data, "pm48", oracle=True)["2024-0-1-2"]
    )


def test_data_does_not_reorder_callers_list():
    d = _synth_data()
    rev = list(reversed(d.games))
    pi.Data(rev, d.box)
    assert rev[0].game_id == "d59"


def test_scheduled_games_need_listed_teams(istore):
    """Like build_features: a scheduled game against a team missing from `teams` (All-Star,
    exhibition) is left out of load_data; finals are already filtered by final_sql."""
    con = istore.con
    con.execute(
        "INSERT INTO games (game_id, league, season_year, season_type, start_time_utc, status, "
        "state, completed, home_team_id, away_team_id, neutral_site, updated_at) VALUES "
        "('allstar', 'nba', 2026, 2, ?, 'STATUS_SCHEDULED', 'pre', false, '1', '999', true, ?)",
        [datetime(2026, 12, 1, tzinfo=UTC), datetime.now(UTC)],
    )
    try:
        ids = {g.game_id for g in pi.load_data(con).games}
        assert "allstar" not in ids and "pre-0" in ids
    finally:
        con.execute("DELETE FROM games WHERE game_id = 'allstar'")


def test_features_merge_without_touching_v11_rows(istore):
    rows = build_features(istore.con, include_players=True)
    feats = pi.impact_features(pi.load_data(istore.con), "pm48")
    merged = pi.with_impact(rows, feats)
    assert all(set(pi.IMPACT_FEATURES) <= set(r["features"]) for r in merged)
    assert all(not (set(pi.IMPACT_FEATURES) & set(r["features"])) for r in rows)


# ---------- OUT lists and redistribution ----------


def _box(minutes: list[float], absent: set[int] = frozenset(), team: str = "A"):
    return {
        f"{team}-p{k}": ((False, 0.0, 0.0, 0.0) if k in absent else (True, m, 10.0, 0.0))
        for k, m in enumerate(minutes)
    }


MINS = [36, 34, 32, 30, 26, 22, 16, 12, 8, 4]


def test_allocate_caps_and_fills():
    alloc, left = pi.allocate({"a": 100, "b": 1, "c": 1})
    assert alloc["a"] == pi.MINUTE_CAP and left == pytest.approx(240 - 3 * pi.MINUTE_CAP)
    alloc, left = pi.allocate({str(k): m for k, m in enumerate(MINS)})
    assert sum(alloc.values()) == pytest.approx(240) and left == 0
    assert max(alloc.values()) <= pi.MINUTE_CAP + 1e-9


def test_out_player_minutes_are_redistributed_not_subtracted():
    hist: list[dict[str, Line]] = [_box(MINS) for _ in range(5)]
    ratings = {f"A-p{k}": 5.0 - k for k in range(len(MINS))}  # p0 best
    full = pi.team_impact(hist, ratings, out=set())
    star = pi.team_impact(hist, ratings, out={"A-p0"})
    assert full["missing"] == 0
    assert sum(p["avail_minutes"] for p in star["players"]) == pytest.approx(240)
    p1 = {p["athlete_id"]: p for p in star["players"]}["A-p1"]
    assert p1["avail_minutes"] > p1["exp_minutes"]  # teammates absorb the minutes
    # Losing the star costs less than his full contribution (replacements are not zero).
    p0_minutes = {p["athlete_id"]: p for p in full["players"]}["A-p0"]["exp_minutes"]
    assert 0 < star["missing"] < p0_minutes / 48 * ratings["A-p0"] + 1e-9
    worst = pi.team_impact(hist, ratings, out={"A-p9"})
    assert worst["missing"] < 0  # losing a below-average player raises strength
    # A listed player outside the rotation is ignored.
    assert pi.team_impact(hist, ratings, out={"Z-p0"})["missing"] == 0


def test_proxy_is_previous_game():
    hist = [_box(MINS) for _ in range(4)] + [_box(MINS, absent={0})]
    ratings = {f"A-p{k}": 5.0 - k for k in range(len(MINS))}
    proxy = pi.team_impact(hist, ratings)
    assert proxy["n_out"] == 1 and proxy["missing"] > 0
    assert proxy["missing"] == pytest.approx(pi.team_impact(hist, ratings, out={"A-p0"})["missing"])
    assert math.isnan(pi.team_impact([], ratings)["missing"])


def test_explicit_out_list_for_a_scheduled_game(istore):
    con = istore.con
    data = pi.load_data(con)
    pre = [g for g in data.games if g.state == "pre"][0]
    star = max(
        pi.ImpactEngine(data, "rapm10").game(pre.game_id)["home"]["players"],
        key=lambda p: p["exp_minutes"] * p["rating"],
    )["athlete_id"]
    none_out = pi.missing_impact(con, pre.game_id, out_players=[], method="rapm10")
    one_out = pi.missing_impact(con, pre.game_id, out_players=[star], method="rapm10")
    assert none_out["home"]["missing"] == 0 and none_out["away"]["missing"] == 0
    assert one_out["home"]["missing"] > 0 and one_out["away"]["missing"] == 0
    assert one_out["home"]["full"] == pytest.approx(none_out["home"]["full"])
    assert [p["athlete_id"] for p in one_out["home"]["players"] if p["out"]] == [star]
    # as_of later than the tip is clamped to the tip; earlier as_of sees less history.
    late = pi.missing_impact(
        con, pre.game_id, [star], as_of=pre.start + timedelta(days=3), method="rapm10"
    )
    assert late["as_of"] == pre.start and late["home"]["missing"] == one_out["home"]["missing"]


def test_snapshot_out_needs_both_teams(istore):
    con = istore.con
    pre = [g for g in pi.load_data(con).games if g.state == "pre"][0]
    now = datetime.now(UTC)
    cap = (
        "INSERT INTO injury_captures (game_id, team_id, captured_at, captured_before_tip, "
        "n_listed, league) VALUES (?, ?, ?, true, ?, 'nba')"
    )
    con.execute(cap, [pre.game_id, pre.home, now, 1])
    con.execute(
        "INSERT INTO injury_reports (game_id, team_id, athlete_id, status, captured_at, "
        "captured_before_tip, league) VALUES (?, ?, ?, 'Out', ?, true, 'nba')",
        [pre.game_id, pre.home, f"{pre.home}-p0", now],
    )
    try:
        assert pre.game_id not in pi.snapshot_out(con)  # away team not captured
        con.execute(cap, [pre.game_id, pre.away, now, 0])
        assert pi.snapshot_out(con)[pre.game_id] == {f"{pre.home}-p0"}
    finally:
        con.execute("DELETE FROM injury_reports WHERE game_id = ?", [pre.game_id])
        con.execute("DELETE FROM injury_captures WHERE game_id = ?", [pre.game_id])


# ---------- ratings recover a known truth ----------


def test_rapm_recovers_player_values():
    """Synthetic league: 8 teams x 9 players with known values, random absences; margins are
    the minute-weighted value difference + 2.5 home + noise. RAPM ratings rank players close
    to the truth, and the home edge is recovered."""
    rng = random.Random(1)
    teams = [str(i) for i in range(8)]
    true = {f"{t}-p{k}": rng.gauss(0, 3) for t in teams for k in range(9)}
    games, box = [], {}
    t0 = datetime(2025, 10, 21, 23, tzinfo=UTC)
    for i in range(1500):
        h, a = rng.sample(teams, 2)
        sides = {}
        for team in (h, a):
            out = {k for k in range(9) if rng.random() < 0.15}
            w = {f"{team}-p{k}": MINS[k] for k in range(9) if k not in out}
            alloc, _ = pi.allocate(w)
            sides[team] = alloc
            box[(f"g{i}", team)] = {
                f"{team}-p{k}": (k not in out, alloc.get(f"{team}-p{k}", 0.0), 0.0, 0.0)
                for k in range(9)
            }
        val = {s: sum(m / 48 * true[a] for a, m in al.items()) for s, al in sides.items()}
        margin = round(val[h] - val[a] + 2.5 + rng.gauss(0, 6))
        games.append(pi.Game(f"g{i}", 2026, t0 + timedelta(hours=12 * i), h, a, False,
                             float(margin), "post"))  # fmt: skip
    data = pi.Data(games, box)
    r = pi.Ratings(data, "rapm10").as_of(games[-1].start + timedelta(days=1))
    ids = sorted(true)
    corr = np.corrcoef([true[a] for a in ids], [r[a] for a in ids])[0, 1]
    assert corr > 0.8


# ---------- evaluation helpers ----------


def test_clustered_ci_wider_with_correlated_clusters():
    vals = [1.0, 1.0, -1.0, -1.0] * 25
    indep = pe.clustered_ci(vals, list(range(100)))
    clus = pe.clustered_ci(vals, [i // 2 for i in range(100)])  # pairs share a sign
    assert indep["mean"] == clus["mean"] == 0
    assert clus["hi"] - clus["lo"] > indep["hi"] - indep["lo"]


def test_pearson_ci_and_open_rule():
    x = [float(i) for i in range(50)]
    d = pe.pearson_ci(x, [2 * v + 1 for v in x])
    assert d["r"] == pytest.approx(1.0) and d["slope"] == pytest.approx(2.0)
    preds = [
        {"game_id": "a", "pred_home_margin": 8.0, "home_margin": 10},  # bet home, -5 open: win
        {"game_id": "b", "pred_home_margin": -3.0, "home_margin": 4},  # bet away vs +1: loss
        {"game_id": "c", "pred_home_margin": 5.5, "home_margin": 9},  # |edge| 0.5 < 2: no bet
    ]
    opening = {"a": {"spread_home": -5.0}, "b": {"spread_home": 1.0}, "c": {"spread_home": -5.0}}
    closing = {"a": {"spread_home": -6.0}, "b": {"spread_home": 1.0}}
    b = pe.open_rule(preds, opening, closing)
    assert (b["bets"], b["wins"], b["clv"], b["clv_n"]) == (2, 1, 1.0, 1)


def test_v12_model_reads_impact_features(istore):
    rows = pi.with_impact(
        build_features(istore.con, include_players=True),
        pi.impact_features(pi.load_data(istore.con), "pm48"),
    )
    m = pe.MODELS["v1.2"]()
    assert set(pi.IMPACT_FEATURES) <= set(m.win_features)
    assert not set(pi.ORACLE_FEATURES) & set(m.columns())
    m.fit([r for r in rows if r["state"] == "post"])
    assert len(m.predict([r for r in rows if r["state"] == "pre"])) == 2


def test_scramble_check_on_synthetic_store(istore):
    """The real-data leakage check itself: rewriting a whole slate never changes those games'
    own proxy features, but does change their oracle features and the teams' next games."""
    s = pe.scramble_check(pi.load_data(istore.con), "rapm10", n_slates=5)
    assert s["games"] >= 5 and s["own_changed"] == 0
    assert s["oracle_changed"] == s["games"]
    assert s["next_changed"] > 0.8 * s["next_games"]
