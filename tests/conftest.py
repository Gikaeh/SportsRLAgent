import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for sport in ("basketball", "hockey"):
    sport_path = str(ROOT / sport)
    if sport_path not in sys.path:
        sys.path.insert(0, sport_path)
