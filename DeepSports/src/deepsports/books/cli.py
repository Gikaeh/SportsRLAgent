"""`deepsports books grab|status`: Circa and William Hill (Caesars feed) lines from OddsPapi.
Never needs the writer lock: `grab` makes one brief read-only open to match games."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from deepsports.books import BOOKS, grab
from deepsports.circa.storage import today

# The evening run grabs William Hill only: Caesars posts college the night before, Circa doesn't.
EARLY_BOOKS = ("williamhill",)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deepsports books", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grab", help="fetch both books into <BOOKS_DIR>/<book>/<date>.json")
    g.add_argument(
        "--date", type=date.fromisoformat, default=None,
        help="YYYY-MM-DD (local); default today, or tomorrow with --early",
    )  # fmt: skip
    g.add_argument(
        "--book", choices=sorted(BOOKS), action="append",
        help="default: all, or williamhill only with --early",
    )  # fmt: skip
    g.add_argument(
        "--early", action="store_true",
        help="night-before snapshot into <BOOKS_DIR>/<book>/early/<date>.json (day file untouched)",
    )  # fmt: skip
    s = sub.add_parser("status", help="what today's files hold")
    s.add_argument("--date", type=date.fromisoformat, default=None)
    s.add_argument("--early", action="store_true", help="the early files (default date tomorrow)")
    s.add_argument("--json", action="store_true")
    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    day = args.date or (grab.tomorrow() if args.early else today())
    try:
        if args.cmd == "status":
            st = {}
            for book in BOOKS:
                data = grab.load_early(book, day) if args.early else grab.load(book, day)
                st[book] = None if data is None else {
                    "grabbed_at": data.get("grabbed_at"),
                    "lines": len(data["lines"]),
                    "games": len({q.get("game_id") for q in data["lines"]}),
                }  # fmt: skip
            if args.json:
                print(json.dumps({"date": day.isoformat(), "early": args.early, "books": st}))
                return 0
            for book, v in st.items():
                print(f"{book}{' early' if args.early else ''} {day}: " + (
                    "no file" if v is None
                    else f"{v['lines']} lines, {v['games']} games (grabbed {v['grabbed_at']})"
                ))  # fmt: skip
            return 0
        names = args.book or (EARLY_BOOKS if args.early else sorted(BOOKS))
        res = grab.grab_day(day, {b: BOOKS[b] for b in names}, early=args.early)
        print(res.message)
        for p in res.problems:
            print(f"  {p}", file=sys.stderr)
        return 0 if res.ok else 1
    except OSError as e:  # e.g. the external drive isn't mounted
        print(f"books: FAILED, {type(e).__name__}: {e}")
        return 1
