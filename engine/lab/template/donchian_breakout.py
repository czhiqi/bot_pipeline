"""donchian_breakout -- classic Donchian/Turtle channel breakout.
long_entry/short_entry are complementary, so this is safe as EITHER
build_signal or build_regime.
"""


def donchian_breakout(df, entry_window, exit_window=None, col='close',
                      high_col='high', low_col='low', reverse=False):
    '''long above the trailing entry_window-bar high, short below the
    trailing low (pass reverse=True to fade the channel instead).
    exit_window (defaults to entry_window) lets the exit channel be
    narrower, the original Turtle shape (e.g. 20-bar entry / 10-bar exit) --
    reacts faster and gives back less profit.

    Genuinely edge-shaped, NOT expressible as the two-column persistent-state
    form (long_entry/short_entry alone, no exit columns): the entry and exit
    channels can have different widths, so this isn't "hold until the SAME
    boundary flips" (which the two-column form captures) -- it's "enter on a
    wide breakout, exit on a narrower reversal channel", a genuine
    hysteresis between two different tests. Returns df with all four edge
    columns df["long_entry"]/df["short_entry"]/df["long_exit"]/
    df["short_exit"] written on (edge form -- dispatched by having BOTH exit
    columns present, see engine.py's _adapt_signal_df()), plus the
    intermediates df["entry_upper"]/df["entry_lower"]/df["exit_upper"]/
    df["exit_lower"] -- no explicit valid/warmup column, see
    abv_blw_zscore's docstring for why.

    Channels DO .shift(1): "broke out above the last N highs" means the PRIOR
    N bars, so today's own high must not be one of them. That is
    definitional, NOT a look-ahead guard, and unlike FeatureScale's window
    convention it has to stay: with an inclusive window close > max(high) is
    unsatisfiable for well-formed OHLC (close <= own high <= window max), so
    the template would never enter at all.
    '''
    entry_window = int(round(entry_window))
    exit_window = entry_window if exit_window is None else int(round(exit_window))
    for c in (col, high_col, low_col):
        if c not in df.columns:
            raise KeyError(f'{c!r} not in df; available: {sorted(df.columns)}')
    price = df[col]
    df["entry_upper"] = df[high_col].rolling(entry_window, min_periods=entry_window).max().shift(1)
    df["entry_lower"] = df[low_col].rolling(entry_window, min_periods=entry_window).min().shift(1)
    df["exit_upper"] = df[high_col].rolling(exit_window, min_periods=exit_window).max().shift(1)
    df["exit_lower"] = df[low_col].rolling(exit_window, min_periods=exit_window).min().shift(1)

    abv_entry = price > df["entry_upper"]
    blw_entry = price < df["entry_lower"]
    blw_exit = price < df["exit_lower"]
    abv_exit = price > df["exit_upper"]
    long_entry, short_entry = (blw_entry, abv_entry) if reverse else (abv_entry, blw_entry)
    long_exit, short_exit = (abv_exit, blw_exit) if reverse else (blw_exit, abv_exit)

    df["long_entry"] = long_entry
    df["short_entry"] = short_entry
    df["long_exit"] = long_exit
    df["short_exit"] = short_exit
    return df
