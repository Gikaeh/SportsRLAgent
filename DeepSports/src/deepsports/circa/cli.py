"""`deepsports circa read|ingest|status`. Never needs the warehouse writer lock: `read` makes one
brief read-only open (with a lock wait) to match games; `ingest` and `status` never open DuckDB."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from deepsports.circa import reader, storage, upload_code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deepsports circa", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read", help="ingest, then read unread screenshots into lines/<date>.json")
    r.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD (local)")
    r.add_argument("--force", action="store_true", help="read again even if nothing is new")
    sub.add_parser("ingest", help="copy new images from the iCloud inbox into today's folder")
    s = sub.add_parser("status", help="today's screenshot count and read state")
    s.add_argument("--date", type=date.fromisoformat, default=None)
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("code", help="show the LAN upload code for the /circa page (owner only)")
    c.add_argument("--rotate", action="store_true", help="make a new code (phones must re-enter)")
    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        if args.cmd == "ingest":
            res = storage.ingest()
            print(res.summary())
            return 0 if res.state in ("ok", "disabled", "missing") else 1
        if args.cmd == "code":  # for the owner's own terminal; the server never shows the code
            code = upload_code.rotate() if args.rotate else upload_code.get_code()
            if code is None:
                print(f"circa: {upload_code.code_file()} is malformed; run with --rotate")
                return 1
            print(f"Circa upload code: {code}")
            return 0
        if args.cmd == "status":
            st = reader.status(args.date)
            if args.json:
                print(json.dumps(st))
                return 0
            r = st["read"]
            read = (
                f"read {r['read_at']}: {r['lines']} lines, {r['matched']} matched, "
                f"{len(reader.unread(args.date))} unread screenshots"
                if r
                else "not read"
            )
            print(
                f"circa {st['date']}: {st['count']} screenshots (latest {st['latest_at']}); {read}"
            )
            return 0
        res = reader.read_day(args.date, force=args.force)
        print(res.message)
        for p in res.problems:
            print(f"  {p}", file=sys.stderr)
        return 0 if res.ok else 1
    except OSError as e:  # e.g. the external drive isn't mounted
        print(f"circa: FAILED, {e}", file=sys.stderr)
        print(f"circa: FAILED, {type(e).__name__}")
        return 1
