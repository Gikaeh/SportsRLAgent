"""Paths and runtime settings. Override with environment variables."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("DEEPSPORTS_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.environ.get("DEEPSPORTS_DB", DATA_DIR / "deepsports.duckdb"))
# Reports and run outputs: next to data/ on the external drive (data/ is a symlink there).
REPORTS_DIR = Path(
    os.environ.get("DEEPSPORTS_REPORTS_DIR", "/Volumes/ExFATStorag/DeepSports/reports")
)
# The API server's live ESPN responses are cached on the internal disk: they're transient (the
# scheduled `update` lands the same data in RAW_DIR) and live scores must keep working when
# the external drive is unmounted or not yet permitted for background processes.
LIVE_CACHE_DIR = Path(
    os.environ.get(
        "DEEPSPORTS_LIVE_CACHE", Path.home() / "Library" / "Caches" / "DeepSports" / "live"
    )
)

# The user's timezone, used for calendar output.
LOCAL_TZ = ZoneInfo(os.environ.get("DEEPSPORTS_TZ", "America/Los_Angeles"))
# ESPN's `dates=YYYYMMDD` scoreboard parameter is a US/Eastern game day.
LEAGUE_TZ = ZoneInfo("America/New_York")

# Default identity for plain HTTP fetches (browser automation is allowed when a source needs it).
USER_AGENT = "DeepSports/0.1 (personal sports research project)"
# Minimum seconds between network requests.
MIN_REQUEST_INTERVAL = float(os.environ.get("DEEPSPORTS_MIN_INTERVAL", "1.0"))

# Prediction versions that are written and graded (their own record via
# /api/predictions/record?model_version=...) but never shown on game cards, the glasses or the
# calendar, which keep the league's display version.
HIDDEN_MODEL_VERSIONS = ("ncaab-v1p",)


class DataDirUnavailable(RuntimeError):
    pass


def require_data_dir() -> Path:
    """`data/` is a symlink to the external volume (see docs/PIPELINE.md). Fail clearly when
    the drive isn't mounted instead of creating a stray local directory."""
    if DATA_DIR.is_symlink() and not DATA_DIR.exists():
        raise DataDirUnavailable(
            f"data directory {DATA_DIR} -> {os.readlink(DATA_DIR)} is not available. "
            "Is the external drive (ExFATStorag) mounted?"
        )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
