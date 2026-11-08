"""Sport-independent bet sizing and bankroll helpers."""
import pandas as pd


def kellyFraction(win_prob, american_odds, kelly_multiplier, max_fraction):
    """Fractional Kelly stake as a share of bankroll: 0 without an edge, capped at max_fraction."""
    profit = american_odds / 100 if american_odds > 0 else 100 / abs(american_odds)
    full_kelly = (win_prob * (profit + 1) - 1) / profit
    return min(max(0, full_kelly * kelly_multiplier), max_fraction)


def wholeDollarStake(fraction, bankroll, min_bet):
    """Stake in whole dollars, or 0 when it would be under the minimum bet."""
    stake = round(fraction * bankroll)
    return stake if stake >= min_bet else 0


def bankrollFromLogs(starting_bankroll, frames, start_date=None):
    """Starting bankroll plus graded results. With start_date, older rows are ignored,
    so the log files keep their history while a new bankroll starts clean."""
    bankroll = starting_bankroll
    cutoff = pd.Timestamp(start_date) if start_date else None
    for frame in frames:
        for _, row in frame.iterrows():
            if cutoff is not None and not pd.to_datetime(row['timestamp'], errors='coerce') >= cutoff:
                continue
            if row['result'] == 'W':
                bankroll += row['potential_profit']
            elif row['result'] == 'L':
                bankroll -= row['bet_amount']
    return bankroll
