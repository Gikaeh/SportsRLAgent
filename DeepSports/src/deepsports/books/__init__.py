"""Book lines from OddsPapi (watch-only): Circa and William Hill (Caesars' feed) for NBA + NCAAB.

`deepsports books grab` writes one lines file per book and day, in the Circa lines contract
(docs/API.md, Circa), so the moon proposal and the model-picks message can show each book's real
line and price. Nothing here places a bet.
"""

# Our book name -> OddsPapi bookmaker slug. William Hill NV has no feed of its own; Caesars' feed
# (an out-of-state Caesars line, e.g. Arizona) stands in for it (owner, 2026-11-14).
BOOKS = {"circa": "circasports", "williamhill": "caesars"}
LABELS = {"circa": "Circa", "williamhill": "WH"}
