"""Sport-independent helpers for time-based data splitting (no leakage)."""

import pandas as pd


def chronologicalSplit(df, date_col='date', test_frac=0.2, val_frac_of_test=0.5):
    """Split a game-level dataframe chronologically: earliest rows train,
    then validation, latest rows test. Preserves the repo's existing
    proportions (test_split=0.2, validation_split=0.5 -> 80/10/10), where
    test_frac is the TOTAL holdout and val_frac_of_test is the share of that
    holdout given to test.

    Returns (train_df, val_df, test_df) sorted by date_col.
    """
    if df is None or df.empty:
        raise ValueError("chronologicalSplit requires a non-empty dataframe")

    df = df.sort_values(date_col).reset_index(drop=True)
    n = len(df)

    test_size = int(round(n * test_frac * val_frac_of_test))
    val_size = int(round(n * test_frac * (1 - val_frac_of_test)))

    test_size = min(max(test_size, 1), n - 2)
    val_size = min(max(val_size, 1), n - test_size - 1)

    train_end = n - test_size - val_size
    val_end = n - test_size

    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]
