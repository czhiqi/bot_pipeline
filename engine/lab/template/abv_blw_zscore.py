"""abv_blw_zscore -- long above +threshold, short below -threshold, on col's
rolling z-score. long_entry/short_entry are complementary, so this is safe
as EITHER build_signal or build_regime.

Absorbed what used to be two separate, functionally-identical
implementations: RegimeFilter.zscore() and Strategy.threshold_cross()'s
scale='z'/exit_condition=1 branch both computed this exact abv/blw test --
see webapp/CLAUDE.md's derivation for why threshold_cross was removed instead
of kept alongside this.
"""
from ..primitive import FeatureScale


def abv_blw_zscore(df, col, window, threshold=0.0, reverse=False, cache=None, cache_key=None):
    '''long while col's rolling z-score is above +threshold, short while below
    -threshold, flat in the dead zone between. FeatureScale.zscore() computes
    that z over a window ENDING at the current bar -- col's own value is one
    of the window members (see FeatureScale's class docstring), no .shift(1).

    Returns df with df["z"] (the intermediate) plus df["long_entry"]/
    df["short_entry"] written on (persistent-state form -- no long_exit/
    short_exit columns, see engine.py's _adapt_signal_df() for what that
    dispatches to) -- no explicit valid/warmup column: the engine derives the
    warmup mask itself from df["z"]'s own NaNs (via whichever other columns
    end up on df), so every intermediate a signal column reads from must
    land on df too, not stay a bare local variable.

    cache/cache_key are an opt-in memoization hook for sweep() -- see
    FeatureScale.zscore()'s own docstring. Forwarded unchanged; declaring
    them here is what lets sweep()'s _cache_kwarg_name() detect and share a
    per-sweep-call rolling-zscore cache across every combination that reuses
    the same (col, window).
    '''
    if col not in df.columns:
        raise KeyError(f'col={col!r} not in df; available: {sorted(df.columns)}')
    window = int(round(window))
    df["z"] = FeatureScale.zscore(df[col], window, cache=cache, cache_key=cache_key)
    df["long_entry"] = df["z"] > threshold
    df["short_entry"] = df["z"] < -threshold
    if reverse:
        df["long_entry"], df["short_entry"] = df["short_entry"], df["long_entry"]
    return df
