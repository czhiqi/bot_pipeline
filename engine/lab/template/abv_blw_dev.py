"""abv_blw_dev -- long/short on col's fractional deviation from its rolling
mean. long_entry/short_entry are complementary, so this is safe as EITHER
build_signal or build_regime.

Renamed from abv_blw_ma_dev (it now delegates to FeatureScale.deviation()) --
strategy source importing the old name must be updated.
"""
from ..primitive import FeatureScale


def abv_blw_dev(df, col, window, threshold=0.0, reverse=False, relative=True):
    '''long while col's deviation from its rolling mean is above +threshold,
    short while below -threshold -- that deviation spelled out by
    FeatureScale.deviation(), i.e. col / rolling_mean - 1 when relative=True
    (the default) or the raw col - rolling_mean when False.

    relative=True (fractional) is scale-free, so a single threshold is
    comparable across cols of different magnitude, but it needs col to KEEP
    ONE SIGN -- a mean crossing zero inverts the ratio; a zero-crossing col
    belongs on abv_blw_zscore instead. relative=False (absolute) drops that
    requirement, at the cost of threshold being an amount in col's own units.
    Reduces to abv_blw_ma()'s test at threshold=0 either way, the one-sign
    guarantee mattering only for relative=True.

    The mean's window ENDS at the current bar (col's own value is one of its
    members), matching FeatureScale's convention -- no .shift(1), so
    deviation == 0 is reachable where col IS the window's mean.

    Returns df with df["deviation"] (the intermediate) plus df["long_entry"]/
    df["short_entry"] written on (persistent-state form -- no long_exit/
    short_exit columns) -- no explicit valid/warmup column, see
    abv_blw_zscore's docstring for why. Warmup is the deviation column's own
    NaNs (FeatureScale.deviation()'s default min_period), not a full window's
    worth -- unlike abv_blw_ma(), which compares against a rolling(window)
    mean directly.
    '''
    if col not in df.columns:
        raise KeyError(f'col={col!r} not in df; available: {sorted(df.columns)}')
    window = int(round(window))
    df["deviation"] = FeatureScale.deviation(df[col], window, relative=relative)
    df["long_entry"] = df["deviation"] > threshold
    df["short_entry"] = df["deviation"] < -threshold
    if reverse:
        df["long_entry"], df["short_entry"] = df["short_entry"], df["long_entry"]
    return df
