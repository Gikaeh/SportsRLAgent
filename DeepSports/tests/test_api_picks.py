"""GET /api/picks/today: latest picks run for the apps (files only, no stakes)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from deepsports.api import picks


def _run(root, name, created, top, all_picks):
    d = root / name
    d.mkdir(parents=True)
    (d / "picks.json").write_text(
        json.dumps({"rule_version": "mp-v1", "created_at": created, "picks": all_picks, "top": top})
    )
    slate = {
        "games": [
            {
                "game_id": "401",
                "tip_utc": "2026-11-15T18:00:00+00:00",
                "home": {"abbr": "PHI", "name": "76ers", "record": "5-5"},
                "away": {"abbr": "IND", "name": "Pacers"},
            }
        ]
    }
    (d / "slate.json").write_text(json.dumps(slate))


P = {
    "game_id": "401",
    "league": "nba",
    "label": "PHI -7.5",
    "market": "spread",
    "side": "home",
    "line": -7.5,
    "price": -110,
    "stake": 1,
    "tier": "strong",
    "ds_edge": 5.1,
    "mb_edge": 4.2,
    "min_edge": 4.2,
    "early": False,
    "books": {"circa": {"line": -7.5, "price": -110}, "williamhill": {"line": -7, "price": -115}},
}
LEAN = dict(P, market="total", side="under", label="Under 224.5", line=224.5, tier="lean")


def test_latest_run_shape(tmp_path):
    _run(tmp_path, "20261114T220000Z", "2026-11-14T22:00:00+00:00", [P], [P, LEAN])
    _run(tmp_path, "20261113T220000Z", "2026-11-13T22:00:00+00:00", [], [])  # older: ignored
    out = picks.latest_run(tmp_path, datetime(2026, 11, 15, 8, tzinfo=UTC))
    assert out["available"] and out["run_at"] == "2026-11-14T22:00:00+00:00"
    (t,) = out["top"]
    assert t["label"] == "PHI -7.5" and t["home"] == {"abbr": "PHI", "name": "76ers"}
    assert t["books"]["williamhill"] == {"line": -7, "price": -115}
    assert t["tip_utc"] == "2026-11-15T18:00:00+00:00" and t["best"] is None
    assert "stake" not in t and "stake" not in json.dumps(out)  # never any stake field
    assert [m["label"] for m in out["more"]] == ["Under 224.5"]
    assert out["counts"] == {"strong": 1, "lean": 1}


def test_stale_or_missing(tmp_path):
    _run(tmp_path, "20261110T220000Z", "2026-11-10T22:00:00+00:00", [P], [P])
    out = picks.latest_run(tmp_path, datetime(2026, 11, 15, 8, tzinfo=UTC))
    assert out["available"] is False and out["top"] == []
    assert picks.latest_run(tmp_path / "nope")["available"] is False


def test_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from deepsports.api.app import create_app

    monkeypatch.setattr("deepsports.analysis.model_picks.RUNS_DIR", tmp_path)
    now = datetime.now(UTC).isoformat()
    _run(tmp_path, "r1", now, [P], [P])
    client = TestClient(create_app(db_path=tmp_path / "none.duckdb"))
    r = client.get("/api/picks/today")
    assert r.status_code == 200 and r.json()["top"][0]["label"] == "PHI -7.5"
