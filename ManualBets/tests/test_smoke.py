"""Smoke tests: core modules import and betting configs keep their guardrails.

Hockey and basketball reuse the same top-level package names (`betting`, `model`,
`data_pipeline`), so per-sport imports must run in isolated interpreters with that
sport's directory on PYTHONPATH — mirroring how `.venv/bin/python <sport>/main.py`
runs.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_shared_base_classes_import():
    from shared.base_data_fetcher import BaseDataFetcher
    from shared.base_data_preparer import BaseTrainingDataPreparer

    assert BaseDataFetcher.__abstractmethods__
    assert BaseTrainingDataPreparer.__abstractmethods__


SPORT_CHECK = """
import betting.betting_config as cfg_mod
cfg = cfg_mod.BettingConfig
assert 0 < cfg.STARTING_BANKROLL <= 10_000
assert 0 < cfg.MAX_BET_SIZE_PCT <= 0.25
assert 0 < cfg.KELLY_FRACTION <= 1.0
assert cfg.MIN_PROBABILITY >= 0.5
assert cfg.UNDERDOG_KELLY_MULTIPLIER <= 1.0

import betting.betting_recommender as rec_mod
assert hasattr(rec_mod, "BettingRecommender")

for bet_type, camel in (("h2h", "H2H"), ("spread", "Spread"), ("total", "Total")):
    mod = __import__(f"model.model_{bet_type}", fromlist=["x"])
    assert hasattr(mod, "@PREFIX@" + camel + "Model"), (
        f"missing @PREFIX@{camel}Model"
    )

import data_pipeline.odd_scraping as odds_mod
assert any("OddScraping" in n for n in dir(odds_mod))
print("ok")
"""


@pytest.mark.parametrize("sport", ["hockey", "basketball"])
def test_sport_modules_import_and_config_guardrails(sport):
    prefix = sport.capitalize() if sport == "basketball" else "Hockey"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / sport)
    result = subprocess.run(
        [sys.executable, "-c", SPORT_CHECK.replace("@PREFIX@", prefix)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, f"{sport} smoke import failed:\n{result.stderr}"
