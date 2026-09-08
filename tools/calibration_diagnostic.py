"""Home vs away calibration diagnostic for the graded betting logs.

Prints the pick share and win rate (W/(W+L), ignoring pushes) by bet_side for
each market type, to see whether the model is over-favoring home teams.

Usage:
    .venv\\Scripts\\python.exe tools\\calibration_diagnostic.py
    .venv\\Scripts\\python.exe tools\\calibration_diagnostic.py <logs_dir>
"""
import sys
from pathlib import Path

import pandas as pd


def winRate(results):
    """Return (wins, decided) where decided = W + L. Pushes (P) are excluded."""
    wins = int((results == 'W').sum())
    decided = int(results.isin(['W', 'L']).sum())
    return wins, decided


def summarizeMarket(df, market):
    if df.empty:
        print(f"\n{market}: no bets")
        return

    decidable = df.dropna(subset=['result'])
    n = len(decidable)
    if n == 0:
        print(f"\n{market}: no graded bets")
        return

    print(f"\n{market} (n={n})")
    for side in ('home', 'away'):
        sub = decidable[decidable['bet_side'] == side]
        wins, decided = winRate(sub['result'])
        conf = sub.get('confidence', pd.Series(dtype=float)).dropna()

        parts = [f"picks {len(sub):>3} ({len(sub) / n * 100:5.1f}%)"]
        if decided:
            parts.append(f"win {wins}/{decided}={wins / decided * 100:5.1f}%")
        else:
            parts.append("win n/a")
        if not conf.empty:
            parts.append(f"avg conf {conf.mean():.3f}")
        print(f"  {side:>4}: " + " | ".join(parts))


def main():
    log_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('logs/basketball/betting')
    files = sorted(log_dir.glob('*_bets.csv'))
    if not files:
        print(f"No bet logs found under {log_dir}")
        return

    print("=" * 68)
    print("Home vs away calibration of graded bets (W/(W+L), pushes excluded)")
    print("=" * 68)
    for f in files:
        print(f"\n# {f}")
        market = f.stem.replace('_bets.csv', '')
        summarizeMarket(pd.read_csv(f), market)


if __name__ == "__main__":
    main()
