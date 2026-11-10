"""Open-bet labels from the owner's bet logs (api/bets.py) and their attachment to cards."""

from pathlib import Path

from deepsports.api import bets

SPREAD = (
    "game_id,date,matchup,bet_team,bet_side,home_spread,home_odds,away_spread,away_odds,type,result\n"
    "1,d,MEM @ TOR,TOR,home,-2.5,-110,2.5,-110,spread,\n"
    "2,d,LAL @ ATL,ATL,home,2,-110,-2,-110,spread,\n"
    "3,d,LAL @ DET,LAL,away,-4.5,-110,4.5,-110,spread,W\n"
    "4,d,X @ Y,X,away,3.5,-110,-3.5,-110,spread,\n"
)
TOTAL = (
    "game_id,date,matchup,bet_side,total_line,type,result\n"
    "5,d,DEN @ HOU,over,216.5,total,\n"
    "bad,d,A @ B,over,notanumber,total,\n"
)
COLLEGE = (
    "game_id,date,matchup,market,bet,line,odds,result\n"
    "6,d,ILST @ PUR,total,over,145,-110,\n"
    "7,d,SMC @ NEV,spread_1h,NEV,-0.5,-110,\n"
    "8,d,SMC @ NEV,spread,NEV,-1,-110,P\n"
)


def _logs(tmp_path: Path) -> Path:
    nba = tmp_path / "basketball" / "betting"
    nba.mkdir(parents=True)
    (nba / "spread_bets.csv").write_text(SPREAD)
    (nba / "total_bets.csv").write_text(TOTAL)
    col = tmp_path / "college_basketball" / "betting"
    col.mkdir(parents=True)
    (col / "bets.csv").write_text(COLLEGE)
    return tmp_path


def test_open_bets_labels_and_skips_graded(tmp_path):
    got = bets.open_bets(_logs(tmp_path))
    assert got == {
        "1": ["TOR -2.5"],
        "2": ["ATL +2"],
        "4": ["X -3.5"],
        "5": ["Over 216.5"],
        "6": ["Over 145"],
        "7": ["NEV 1H -0.5"],
    }


def test_missing_logs_are_empty(tmp_path):
    assert bets.open_bets(tmp_path) == {}
