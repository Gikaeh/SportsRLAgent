"""Play-by-play parser (deepsports.parse_pbp) on trimmed real ESPN summaries in tests/fixtures/
(one NBA, one college game; header/format/plays/boxscore.players kept). Ported from the
DeepSeek edge study's lab tests."""

import gzip
import json
import math
from pathlib import Path

import pytest

from deepsports.parse_pbp import (
    clock_to_seconds,
    garbage_time,
    parse_events,
    parse_summary,
    shot_distance,
)

FIXTURES = Path(__file__).parent / "fixtures"
NBA_GAME = "401358773"  # MIL 127 - BKN 104, 2021-10-19 (opening night)
CBB_GAME = "401804830"  # NMSU 87 - SHSU 78, 2025-12-21


def _load(game_id: str, league: str) -> dict:
    path = FIXTURES / f"espn_{league}_summary_pbp_{game_id}.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize(
    ("game_id", "league", "home_score", "away_score", "n_periods"),
    [(NBA_GAME, "nba", 127, 104, 4), (CBB_GAME, "ncaab", 87, 78, 2)],
)
def test_parse_summary_invariants(game_id, league, home_score, away_score, n_periods):
    raw = _load(game_id, league)
    parsed = parse_summary(raw, league=league)

    assert parsed["game_id"] == game_id
    assert parsed["home_score"] == home_score
    assert parsed["away_score"] == away_score
    assert parsed["regulation_periods"] == n_periods
    assert parsed["regulation_clock"] == (720.0 if league == "nba" else 1200.0)
    assert parsed["overtime_clock"] == 300.0
    assert parsed["home_team_id"] is not None and parsed["away_team_id"] is not None
    assert parsed["start_time_utc"]

    events = parsed["events"]
    assert len(events) > 100, "expected a full play-by-play"
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs), "events must be chronological"

    # Every play carries a real clock (regression: period displayValue bug).
    clocks = [e["clock_sec"] for e in events]
    assert all(c is not None for c in clocks), "clock_sec must parse for every play"

    # Cumulative scores: non-decreasing, and the last event matches the final.
    hs = [e["home_score"] for e in events if e["home_score"] is not None]
    aws = [e["away_score"] for e in events if e["away_score"] is not None]
    assert all(b >= a for a, b in zip(hs, hs[1:], strict=False)), "home score must be monotone"
    assert all(b >= a for a, b in zip(aws, aws[1:], strict=False)), "away score must be monotone"
    assert hs[-1] == home_score and aws[-1] == away_score

    # Points conservation: sum of scoring-play points equals the game total.
    total = sum(e["points"] for e in events)
    assert total == home_score + away_score, "scoring points must sum to the final total"

    # Every made shot/free-throw has the right point value.
    for e in events:
        if e["event_type"] in ("SHOT", "FREETHROW") and e["made"]:
            assert e["points"] > 0
            assert e["points"] == e["shot_value"]

    # Player ids on substitution events are present for NBA (in/out pairs).
    if league == "nba":
        subs = [e for e in events if e["event_type"] == "SUBSTITUTION"]
        assert subs, "an NBA game has substitutions"
        for e in subs[:5]:
            assert len(e["player_ids"]) == 2

    # Parsed players agree with the boxscore minutes formatting.
    players = parsed["players"]
    assert players
    for p in players:
        assert p["team_id"] in (parsed["home_team_id"], parsed["away_team_id"])
        if p["minutes"] is not None:
            assert 0.0 <= p["minutes"] <= 60.0


def test_shot_distances_match_text():
    raw = _load(NBA_GAME, "nba")
    parsed = parse_summary(raw, league="nba")
    checked = 0
    for e in parsed["events"]:
        if e["event_type"] != "SHOT" or e["distance"] is None:
            continue
        m = None
        for word in e["text"].split():
            if word.endswith("-foot") and word[:-5].isdigit():
                m = int(word[:-5])
        if m is None:
            continue
        # ESPN rounds the text distance; allow 1.5 ft slack.
        assert abs(e["distance"] - m) <= 1.5, f"distance mismatch in {e['text']!r}"
        checked += 1
    assert checked >= 10


def test_garbage_time_rule():
    # Lead >= 20 in the 4th quarter (NBA) is garbage; a 19-point lead is not.
    def ev(period, hs, aws):
        return {"period": period, "home_score": hs, "away_score": aws}

    events = [
        ev(1, 10, 5),
        ev(3, 60, 41),  # lead 19, period 3: not garbage anywhere
        ev(4, 62, 42),  # lead 20 in Q4: garbage
        ev(4, 70, 42),  # still garbage
        ev(4, 70, 52),  # lead back to 18: clean again
        ev(5, 100, 100),
    ]
    mask = garbage_time(events, "nba")
    assert mask == [False, False, True, True, False, False]

    cbb = [ev(1, 30, 10), ev(2, 50, 25), ev(2, 60, 35), ev(3, 80, 80)]
    assert garbage_time(cbb, "ncaab") == [False, True, True, False]


def test_clock_parsing():
    assert clock_to_seconds("12:00") == 720.0
    assert clock_to_seconds("0:00") == 0.0
    assert clock_to_seconds("7:44") == 464.0
    assert clock_to_seconds(None) is None
    assert clock_to_seconds("END") is None


def test_shot_distance_sentinels():
    assert shot_distance(-214748340, -214748365) is None
    assert shot_distance(25, 21) == 21.0
    assert math.isclose(shot_distance(9, 21), math.hypot(9 - 25, 21))


def test_events_sorted_by_sequence_not_list_order():
    plays = [
        {"sequenceNumber": "3", "type": {"text": "Jump Shot"}, "shootingPlay": True},
        {"sequenceNumber": "1", "type": {"text": "Jumpball"}},
        {"id": "g12", "type": {"text": "Substitution"}},  # no sequenceNumber: id suffix
    ]
    ev = parse_events(plays, "g")
    assert [e["seq"] for e in ev] == [1, 3, 12]
    assert [e["event_type"] for e in ev] == ["JUMPBALL", "SHOT", "SUBSTITUTION"]
    # an NBA miss carries no point value: inferred from the text
    assert ev[1]["shot_value"] == 2


def test_stale_scores_are_repaired_and_anchored_to_the_final():
    raw = {
        "header": {
            "competitions": [
                {
                    "id": "g",
                    "competitors": [
                        {"id": "1", "homeAway": "home", "score": "4"},
                        {"id": "2", "homeAway": "away", "score": "2"},
                    ],
                }
            ]
        },
        "plays": [
            {"sequenceNumber": "1", "homeScore": 2, "awayScore": 0},
            {"sequenceNumber": "2", "homeScore": 0, "awayScore": 2},  # stale home score
            {"sequenceNumber": "3", "homeScore": 2, "awayScore": 2},
        ],
    }
    parsed = parse_summary(raw, "nba")
    assert [(e["home_score"], e["away_score"]) for e in parsed["events"]] == [
        (2, 0),
        (2, 2),
        (4, 2),
    ]
    assert parse_summary({}, "ncaab")["events"] == []
