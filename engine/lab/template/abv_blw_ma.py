"""abv_blw_ma -- long above col's rolling (or ewm) mean, short below.
long_entry/short_entry are complementary, so this is safe as EITHER
build_signal or build_regime.
"""


def abv_blw_ma(df, col, window, reverse=False, ema=False, cache=None, cache_key=None):
    '''long while col is above its rolling (or ewm) mean, short while below.
    Distinct from abv_blw_dev: this compares col to the mean DIRECTLY
    (works for any col, including one that crosses zero); abv_blw_dev
    compares a deviation from that mean instead (fractional col/mean - 1 by
    default), which needs col to keep one sign.

    The mean's window ENDS at the current bar (col's own value is one of its
    members), matching FeatureScale's convention -- no .shift(1).

    Returns df with df["ma"] (the intermediate) plus df["long_entry"]/
    df["short_entry"] written on (persistent-state form) -- no explicit
    valid/warmup column, see abv_blw_zscore's docstring for why.

    cache/cache_key are an opt-in memoization hook for sweep() -- see
    FeatureScale.zscore()'s docstring for the convention (`cache`+`cache_key`
    together mark a LEAF that needs its cache key built externally, since
    unlike FeatureScale.zscore() this has no other kwarg sweep() could derive
    one from on its own). Both None (default) reproduces the plain
    computation exactly.
    '''
    if col not in df.columns:
        raise KeyError(f'col={col!r} not in df; available: {sorted(df.columns)}')
    window = int(round(window))
    if cache is not None and cache_key in cache:
        df["ma"] = cache[cache_key]
    else:
        df["ma"] = (df[col].ewm(span=window, adjust=False).mean() if ema
                     else df[col].rolling(window).mean())
        if cache is not None:
            cache[cache_key] = df["ma"]
    df["long_entry"] = df[col] > df["ma"]
    df["short_entry"] = df[col] < df["ma"]
    if reverse:
        df["long_entry"], df["short_entry"] = df["short_entry"], df["long_entry"]
    return df
