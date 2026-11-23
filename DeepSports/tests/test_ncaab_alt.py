"""`ncaab-v1.1alt`: the hidden altitude shadow of ncaab-v1 (docs/results/
2026-11-22-altitude-feature.md). Same rows, gate, win and margin as ncaab-v1; the total model adds
the frozen config's altitude features. ncaab-v1's own output must not change."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest
from test_ncaab import live_store

from deepsports import config
from deepsports.analysis import ncaab
from deepsports.store import Store

ELEV = {"5": 2200, "6": 1300, "7": 100, "8": 50, "901": 20, "902": 20}


def with_venues(s: Store) -> Store:
    """Every game at its home team's arena; team 5 is an altitude school."""
    s.con.execute("UPDATE games SET venue_id = 'v' || home_team_id WHERE league = 'ncaab'")
    for team, elev in ELEV.items():
        s.con.execute(
            "INSERT INTO venues (venue_id, name, elevation_m, tz, games, neutral_games, updated_at)"
            " VALUES (?, ?, ?, 'America/Denver', 0, 0, now())",
            [f"v{team}", f"Arena {team}", elev],
        )
    return s


def test_alt_config_is_frozen_and_points_at_v1():
    cfg = ncaab.load_alt_config()
    assert cfg["model_version"] == ncaab.ALT_VERSION == "ncaab-v1.1alt"
    assert cfg["total_extra_features"] == ["venue_elev_km", "alt_gain_sum", "alt_drop_sum"]
    assert cfg["base_config"] == "models/ncaab_v1/config.json"
    assert ncaab.ALT_VERSION in config.HIDDEN_MODEL_VERSIONS
    assert ncaab.ALT_VERSION in config.CALENDAR_EXCLUDED_VERSIONS
    assert ncaab.ALT_VERSION not in ncaab.VERSIONS  # `--model-version all` is unchanged
    assert ncaab.VERSION_MIN_GAMES[ncaab.ALT_VERSION] == ncaab.MIN_GAMES_TO_PREDICT


def test_alt_config_refuses_a_changed_v1_config(tmp_path):
    base = tmp_path / "v1.json"
    base.write_bytes(ncaab.CONFIG_PATH.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        ncaab.load_alt_config(base_path=base)
    bad = tmp_path / "alt.json"
    cfg = json.loads(ncaab.ALT_CONFIG_PATH.read_text())
    bad.write_text(json.dumps(cfg | {"total_extra_features": ["nope"]}))
    with pytest.raises(ValueError, match="bad"):
        ncaab.load_alt_config(path=bad)


def test_attach_altitude_copies_rows():
    rows = [{"game_id": "g", "features": {"a": 1.0}}, {"game_id": "x", "features": {"a": 2.0}}]
    out = ncaab.attach_altitude(rows, {"g": {"venue_elev_km": 2.2, "alt_gain_sum": 1.0}},
                                ["venue_elev_km", "alt_gain_sum"])  # fmt: skip
    assert rows[0]["features"] == {"a": 1.0}  # inputs untouched
    assert out[0]["features"] == {"a": 1.0, "venue_elev_km": 2.2, "alt_gain_sum": 1.0}
    assert math.isnan(out[1]["features"]["venue_elev_km"])  # no venue: NaN (imputed)


def test_alt_matches_v1_except_the_total():
    s = with_venues(live_store(datetime.now(UTC)))
    alone = ncaab.predict_upcoming_versions(s.con, [ncaab.MODEL_VERSION])
    both = ncaab.predict_upcoming_versions(s.con, [ncaab.MODEL_VERSION, ncaab.ALT_VERSION])
    s.close()
    strip = lambda rows: [{k: v for k, v in r.items() if k != "created_at"} for r in rows]  # noqa: E731
    # ncaab-v1 is identical whether or not the shadow runs in the same call
    assert strip(alone[ncaab.MODEL_VERSION]) == strip(both[ncaab.MODEL_VERSION])
    v1 = {r["game_id"]: r for r in both[ncaab.MODEL_VERSION]}
    alt = {r["game_id"]: r for r in both[ncaab.ALT_VERSION]}
    assert v1.keys() == alt.keys()
    for gid, a in alt.items():
        b = v1[gid]
        assert a["model_version"] == "ncaab-v1.1alt" and a["skip_reason"] == b["skip_reason"]
        if b["skip_reason"] is not None:
            assert a["pred_total"] is None
            continue
        assert a["p_home_win"] == b["p_home_win"]
        assert a["pred_home_margin"] == b["pred_home_margin"]
        assert a["pred_total"] != b["pred_total"] and 100 < a["pred_total"] < 180
        feats = json.loads(a["features_json"])
        assert feats["venue_elev_km"] == 2.2  # u-ok is at team 5's arena
        assert feats["alt_gain_sum"] == pytest.approx(0.9)  # team 6 climbs 1300 -> 2200
        assert "venue_elev_km" not in json.loads(b["features_json"])


def test_cli_predict_alt_is_hidden(tmp_path, monkeypatch, capsys):
    from deepsports import cli

    path = tmp_path / "w.duckdb"
    with_venues(live_store(datetime.now(UTC), path)).close()
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli, "Store", lambda read_only=False: Store(path, read_only))
    monkeypatch.setattr(cli, "load_calendar_config", lambda: {"ncaab": {"teams": ["C5"]}})

    assert cli.main(["predict", "--league", "ncaab"]) == 0
    capsys.readouterr()
    assert cli.main(["predict", "--league", "ncaab", "--model-version", "ncaab-v1.1alt"]) == 0
    out = capsys.readouterr().out
    assert "model_version=ncaab-v1.1alt predictions=1 skipped_started=1" in out
    assert "skipped_few_games=1 skipped_non_d1=1" in out
    # written after ncaab-v1, but the calendar export keeps ncaab-v1
    assert cli.main(["upcoming", "--league", "ncaab", "--json", "--days", "3"]) == 0
    games = {g["game_id"]: g for g in json.loads(capsys.readouterr().out)}
    assert games["u-ok"]["prediction"]["model_version"] == "ncaab-v1"
    s = Store(path, read_only=True)
    n = dict(s.con.execute("SELECT model_version, count(*) FROM predictions GROUP BY 1").fetchall())
    from deepsports.api.warehouse import pre_tip_predictions

    shown = pre_tip_predictions(s.con, ["u-ok"], prefer_versions=["ncaab-v1.1alt"])
    s.close()
    assert n == {"ncaab-v1": 1, "ncaab-v1.1alt": 1}
    assert shown["u-ok"]["model_version"] == "ncaab-v1"  # cards never pick the hidden shadow
