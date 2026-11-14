"""Circa screenshots: the owner's photos of Circa's odds board (Circa isn't in The Odds API feed),
read into lines before the 14:00 picks. Watch-only: nothing here places or transmits a bet.

Import `load_lines(date)` for the day's lines (contract: docs/API.md, "Circa")."""

from deepsports.circa.reader import load_lines

__all__ = ["load_lines"]
