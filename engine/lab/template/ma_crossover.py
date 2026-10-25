"""ma_crossover -- classic dual moving-average crossover. long_entry/
short_entry are complementary, so this is safe as EITHER build_signal or
build_regime.
"""


def ma_crossover(df, fast_window, slow_window, col='close', ema=False, reverse=False):
    '''Always-in-market: long while the fast MA is above the slow MA, short
    while below (momentum-oriented by default; pass reverse=True for
    mean-reverting). Hold-until-opposite-crossover exit -- expressed as a
    persistent state (df["long_entry"]/df["short_entry"], no long_exit/
    short_exit columns), not a one-shot trigger, since "fast above slow" IS
    the held state, not an edge event.

    Unlike abv_blw_ma/abv_blw_dev there is no boundary to shift at all:
    fast and slow are both smoothed versions of the SAME price series
    compared against EACH OTHER at the same bar, so nothing is tested against
    a boundary built partly from itself.

    Returns df with df["fast"]/df["slow"] (the intermediates) plus
    df["long_entry"]/df["short_entry"] written on (persistent-state form) --
    no explicit valid/warmup column, see abv_blw_zscore's docstring for why.
    '''
    fast_window = int(round(fast_window))
    slow_window = int(round(slow_window))
    if col not in df.columns:
        raise KeyError(f'col={col!r} not in df; available: {sorted(df.columns)}')
    price = df[col]
    if ema:
        df["fast"] = price.ewm(span=fast_window, adjust=False).mean()
        df["slow"] = price.ewm(span=slow_window, adjust=False).mean()
    else:
        df["fast"] = price.rolling(fast_window, min_periods=fast_window).mean()
        df["slow"] = price.rolling(slow_window, min_periods=slow_window).mean()

    df["long_entry"] = df["fast"] > df["slow"]
    df["short_entry"] = df["fast"] < df["slow"]
    if reverse:
        df["long_entry"], df["short_entry"] = df["short_entry"], df["long_entry"]
    return df
