"""allow_quantile -- permit-to-trade template gated on a column's rolling
tier rank. THE ONE TEMPLATE THAT IS UNSAFE AS build_signal -- see its own
docstring below.

Merges what used to be two separate methods (RegimeFilter.quantile/
quantile_ls) into one: pass col= for the old quantile()'s symmetric gate,
long_col=+short_col= for the old quantile_ls()'s independent per-side gate.
"""
from ..primitive import FeatureScale, _tier_names


def allow_quantile(df, window, tier='low', col=None, long_col=None, short_col=None):
    '''Permit-to-trade template: col (or a long_col/short_col pair) smoothed
    then tier-ranked against the cutoffs of a window ENDING at the current
    bar (see FeatureScale.quantile() and FeatureScale's class docstring),
    permitting trading only in the given tier(s).

    Pass col= for a SYMMETRIC gate -- the SAME mask permits both long and
    short (e.g. "only trade in low-volatility regimes"). Pass
    long_col=+short_col= for an INDEPENDENT gate per side (e.g. a
    liquidation-imbalance column split into long_liquidation/
    short_liquidation, each tier-ranked on its own). Exactly one of {col} or
    {long_col, short_col} must be given.

    tier is one tier name ('low'/'mid'/'high') or a list of them.

    Returns df with df["smoothed"] (col= form) or df["long_smoothed"]/
    df["short_smoothed"] (long_col=/short_col= form) plus df["permitted"]/
    df["long_entry"]/df["short_entry"] (col= form) or df["long_entry"]/
    df["short_entry"] (long_col=/short_col= form) written on
    (persistent-state form -- no long_exit/short_exit columns) -- no
    explicit valid/warmup column, see abv_blw_zscore's docstring for why:
    FeatureScale.quantile()'s `tier` element is NaN during warmup (and on
    any bar where the smoothed value itself is NaN), so `tier_raw.isin(tiers)
    .mask(tier_raw.isna())` below carries that NaN straight into `permitted`
    -- no separate cutoff recomputation needed (that used to be required
    here specifically because quantile() masked warmup to the STRING 'mid'
    instead of NaN; fixed at the source, see webapp/CLAUDE.md).

    !!! ONLY EVER USE THIS AS build_regime, NEVER build_signal !!!
    Under the symmetric col= form, long_entry IS short_entry (the identical
    mask) -- a permission gate has no notion of "which direction", unlike
    every other template in this package. If handed to build_signal anyway,
    the engine's np.select() collapse (see engine.py's _strategy_signal())
    picks long_entry over short_entry on every tie, so the strategy silently
    becomes ALWAYS-LONG-NEVER-SHORT inside the permitted tier -- no error, no
    warning, just a wrong backtest. See webapp/CLAUDE.md's Known gaps for
    why this isn't yet caught at runtime.
    '''
    window = int(round(window))
    tiers = _tier_names(tier)
    if (col is None) == (long_col is None and short_col is None):
        raise ValueError('pass exactly one of col=, or long_col=+short_col=')

    if col is not None:
        if col not in df.columns:
            raise KeyError(f'col={col!r} not in df; available: {sorted(df.columns)}')
        df["smoothed"] = df[col].rolling(window).mean()
        *_, tier_raw = FeatureScale.quantile(df["smoothed"], window)
        df["permitted"] = tier_raw.isin(tiers).astype("boolean").mask(tier_raw.isna())
        df["long_entry"] = df["permitted"]
        df["short_entry"] = df["permitted"]
        return df

    for side, c in (('long', long_col), ('short', short_col)):
        if c is None or c not in df.columns:
            raise KeyError(f'{side}_col={c!r} not in df; available: {sorted(df.columns)}')
        df[f"{side}_smoothed"] = df[c].rolling(window).mean()
        *_, tier_raw = FeatureScale.quantile(df[f"{side}_smoothed"], window)
        df[f"{side}_entry"] = tier_raw.isin(tiers).astype("boolean").mask(tier_raw.isna())
    return df
