"""`deepsports momentum-freeze`: freeze the model inputs of the momentum forward test at T.

Pre-registration `docs/results/2026-11-23-momentum-forward-preregistration.md` ("Model inputs at
T"): `predictions` is upserted per (game, model, version) and the D syncs rewrite it, and
`.sync/manualbets-export.json` is overwritten by every export, so the values at T (19:00 PT on
night D-1; 18:30 and 19:30 are the fallbacks) must be copied when T happens. Run by
`tools/oddsapi-live.sh` right after the 18:30, 19:00 and 19:30 captures.

Writes, write-once (an existing file is never replaced), under
REPORTS_DIR/momentum-forward/frozen/<D>/<HHMM>/:
- `ds_predictions.json`: every college game on D (ESPN/Eastern date, plus Pacific date D) with its
  rows for ncaab-v1, ncaab-v1-early and ncaab-v1.1alt (game_id, model_version, pred_total,
  created_at), from one read-only warehouse open (lock wait; busy -> retry once, then give up).
- `manualbets-export.json`: a byte copy of DeepSports/.sync/manualbets-export.json, and
  `manualbets-export.meta.json` (its mtime, size, sha256, its own created_at, copy time).
Never a writer. Prints one line; exits 0 even when a part fails (non-fatal, said in the line).
Grading is not here (data-analyst).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from deepsports import config

DS_VERSIONS = ("ncaab-v1", "ncaab-v1-early", "ncaab-v1.1alt")
MB_EXPORT = config.ROOT / ".sync" / "manualbets-export.json"
SUBDIR = Path("momentum-forward") / "frozen"
PRED_FILE = "ds_predictions.json"
MB_FILE = "manualbets-export.json"
MB_META = "manualbets-export.meta.json"

GAMES_PREDS_SQL = """
WITH g AS (
  SELECT game_id, start_time_utc, state FROM games
  WHERE league = 'ncaab' AND season_type IN (2, 3)
    AND (CAST(timezone('America/New_York', start_time_utc) AS DATE) = ?
         OR CAST(timezone(?, start_time_utc) AS DATE) = ?)
)
SELECT g.game_id, g.start_time_utc, g.state, p.model_version, p.pred_total, p.created_at
FROM g LEFT JOIN predictions p
  ON p.game_id = g.game_id AND p.model = 'v1' AND p.model_version IN ({versions})
ORDER BY g.start_time_utc, g.game_id, p.model_version
"""


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(v)


def slot_hhmm(now: datetime, tz=config.LOCAL_TZ) -> str:
    """Local 30-minute slot of `now`: 19:07 PT -> '1900'."""
    loc = now.astimezone(tz)
    return f"{loc.hour:02d}{0 if loc.minute < 30 else 30:02d}"


def game_day(now: datetime, tz=config.LOCAL_TZ) -> date:
    """D = tomorrow (Pacific): the freeze runs on night D-1."""
    return now.astimezone(tz).date() + timedelta(days=1)


def freeze_dir(day: date, slot: str, reports_dir: Path | None = None) -> Path:
    return (reports_dir or config.REPORTS_DIR) / SUBDIR / day.isoformat() / slot


def write_once(path: Path, data: bytes) -> bool:
    """Write `path` only if it doesn't exist (tmp file + rename). False if it was there."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    if path.exists():  # lost a race: keep the first one
        tmp.unlink()
        return False
    tmp.replace(path)
    return True


def prediction_rows(con, day: date, versions: Sequence[str] = DS_VERSIONS) -> list[dict]:
    """One dict per college game on D with a `predictions` list (possibly empty)."""
    sql = GAMES_PREDS_SQL.format(versions=", ".join("?" for _ in versions))
    rows = con.execute(sql, [day, config.LOCAL_TZ.key, day, *versions]).fetchall()
    games: dict[str, dict] = {}
    for gid, start, state, ver, total, created in rows:
        g = games.setdefault(
            gid,
            {"game_id": gid, "start_time_utc": _iso(start), "state": state, "predictions": []},
        )
        if ver is not None:
            g["predictions"].append(
                {
                    "game_id": gid,
                    "model_version": ver,
                    "pred_total": total,
                    "created_at": _iso(created),
                }
            )
    return list(games.values())


def open_read_only(lock_wait: float, retry_after: float, sleep: Callable = time.sleep):
    """A read-only Store, or None when the warehouse stayed busy (one retry)."""
    import duckdb

    from deepsports.store import Store, is_lock_conflict

    for attempt in range(2):
        try:
            return Store(config.DB_PATH, read_only=True, lock_wait=lock_wait)
        except duckdb.IOException as e:
            if not is_lock_conflict(e):
                raise
            if attempt == 0:
                sleep(retry_after)
    return None


def freeze_predictions(out: Path, day: date, now: datetime, opener: Callable) -> str:
    if (out / PRED_FILE).exists():
        return "ds already frozen"
    db = opener()
    if db is None:
        return "ds FAILED: warehouse busy (retried once)"
    try:
        games = prediction_rows(db.con, day)
    finally:
        db.close()
    body = {
        "frozen_at": _iso(now),
        "game_day": day.isoformat(),
        "versions": list(DS_VERSIONS),
        "games": games,
    }
    write_once(out / PRED_FILE, json.dumps(body, indent=1).encode())
    n = sum(len(g["predictions"]) for g in games)
    return f"ds {len(games)} games {n} rows"


def freeze_manualbets(out: Path, now: datetime, src: Path = MB_EXPORT) -> str:
    if (out / MB_FILE).exists():
        return "mb already frozen"
    try:
        raw = src.read_bytes()
        mtime = src.stat().st_mtime
    except OSError as e:
        return f"mb FAILED: {type(e).__name__} reading {src.name}"
    try:
        created = json.loads(raw).get("created_at")
    except (ValueError, AttributeError):
        created = None
    meta = {
        "source": str(src),
        "mtime": _iso(datetime.fromtimestamp(mtime, UTC)),
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "created_at": created,
        "copied_at": _iso(now),
    }
    write_once(out / MB_FILE, raw)
    write_once(out / MB_META, json.dumps(meta, indent=1).encode())
    return f"mb copied (created_at {created})"


def run(
    now: datetime,
    *,
    day: date | None = None,
    slot: str | None = None,
    reports_dir: Path | None = None,
    opener: Callable | None = None,
    mb_src: Path = MB_EXPORT,
) -> str:
    day = day or game_day(now)
    slot = slot or slot_hhmm(now)
    out = freeze_dir(day, slot, reports_dir)
    parts = []
    try:
        parts.append(freeze_predictions(out, day, now, opener or (lambda: None)))
    except Exception as e:  # non-fatal by contract: one line, keep going with MB
        parts.append(f"ds FAILED: {type(e).__name__}: {str(e)[:120]}")
    try:
        parts.append(freeze_manualbets(out, now, mb_src))
    except Exception as e:
        parts.append(f"mb FAILED: {type(e).__name__}: {str(e)[:120]}")
    return f"momentum freeze D={day} slot {slot}: " + "; ".join(parts)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="deepsports momentum-freeze", description=__doc__)
    p.add_argument("--day", type=date.fromisoformat, help="game day D (default: tomorrow, PT)")
    p.add_argument("--slot", help="HHMM folder (default: the current 30-min PT slot)")
    p.add_argument("--lock-wait", type=float, default=30.0)
    p.add_argument("--retry-after", type=float, default=30.0)
    args = p.parse_args(argv)
    now = datetime.now(UTC)
    try:
        config.require_data_dir()
    except config.DataDirUnavailable as e:
        print(f"momentum freeze: skipped, data dir unavailable ({e})")
        return 0
    try:
        line = run(
            now,
            day=args.day,
            slot=args.slot,
            opener=lambda: open_read_only(args.lock_wait, args.retry_after),
        )
    except Exception as e:  # e.g. the reports drive went away
        line = f"momentum freeze: FAILED {type(e).__name__}: {str(e)[:160]}"
    print(line)
    sys.stdout.flush()
    return 0
