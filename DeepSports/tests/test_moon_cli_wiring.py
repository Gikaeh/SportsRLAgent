"""`deepsports moon ...` hands everything after `moon` to the moon CLI."""

from deepsports import cli


def test_deepsports_moon_status_uses_moon_cli(tmp_path, capsys):
    ledger = tmp_path / "bets.csv"
    assert cli.main(["moon", "--ledger", str(ledger), "status"]) == 0
    assert "Empty: no deposits or bets yet" in capsys.readouterr().out


def test_moon_listed_in_main_help():
    assert "moon" in cli.build_parser().format_help()
