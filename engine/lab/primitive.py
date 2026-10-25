"""Shared primitives for pipeline_engine's pluggable Signal API --
SignalOutput/SignalFn/FeatureScale plus the low-level array helpers
(_ffill/_edges_from_ok/_state_from_edges/_tier_names) both engine.py's core
and template/*.py depend on.

Split out from engine.py so template/*.py can import these without a
circular dependency on engine.py -- engine.py itself re-exports every name
here (plus every template/*.py function) so uploaded strategy source's
`from tool.engine import ...` keeps working unchanged (see
strategy_loader.py's `tool.engine` shim).
"""
from typing import Callable, NamedTuple, Optional

import numpy as np
import pandas as pd


def _ffill(a):
    '''Forward-fill NaNs in a 1-D float array.'''
    idx = np.where(~np.isnan(a), np.arange(len(a)), 0)
    np.maximum.accumulate(idx, out=idx)
    return a[idx]


def _edges_from_ok(ok):
    '''Rising/falling edges of a boolean permission mask -- ok turning True is
    an entry, ok turning False is an exit. Feeding these back through
    _state_from_edges() below reproduces `ok` exactly, bar for bar. Used by
    SignalOutput.from_state() to express a persistent-state template
    (abv_blw_*, allow_quantile) as entry/exit transitions.
    '''
    ok = np.asarray(ok, dtype=bool)
    prev = np.r_[False, ok[:-1]]
    return ok & ~prev, ~ok & prev


def _state_from_edges(entry, exit_):
    '''Inverse of _edges_from_ok(): forward-fill entry/exit transitions into a
    persistent boolean state -- entry turns it on, exit turns it off, held
    between events (entry wins on a same-bar overlap). Starts False before the
    first event.
    '''
    entry = np.asarray(entry, dtype=bool)
    exit_ = np.asarray(exit_, dtype=bool)
    raw = np.select([entry, exit_], [1.0, 0.0], default=np.nan)
    return np.nan_to_num(_ffill(raw), nan=0.0).astype(bool)


def _tier_names(tier):
    '''Normalise a tier spec to a set of names, matching FeatureScale.quantile()/template/allow_quantile.py.'''
    ts = tier if isinstance(tier, (list, tuple, set)) else [tier]
    return {t if t in ('low', 'high') else 'mid'
            for t in (str(x).strip().lower() for x in ts)}


class NAFrame(pd.DataFrame):
    '''DataFrame subclass: every column assignment auto-upgrades the result to
    a pandas nullable dtype (Float64/boolean). rolling()/ewm() etc. return
    plain float64 (the NA info survives as NaN, but degrades to False/True the
    moment it participates in a boolean comparison -- see below); re-upgrading
    to nullable dtype at the point of assignment back onto an instance of this
    class means later comparisons involving that column preserve NA (instead
    of evaluating NaN < x as False). This lets build_signal/build_regime chain
    computations to any depth while still letting warmup-period NaNs
    propagate through to the final signal column(s), so the engine can derive
    a valid mask -- no author-written astype required.

    Verified boundaries (don't re-litigate these at implementation time, see
    the session transcript for the worked examples):
    - .rolling()/.ewm()/.expanding() always return plain float64 themselves;
      re-upgrading has to happen at the moment of assignment onto an instance
      of this class.
    - A comparison is nullable boolean, with NA as the union of both sides'
      NaN, as soon as either side is nullable dtype -- this covers a fully
      anonymous intermediate step too.
    - The one case this can't save: an author explicitly calling
      .to_numpy()/.values to drop to numpy and wrapping the result back in a
      plain Series/DataFrame, severing the nullable lineage on purpose. Task
      3's runtime discriminator is the backstop for that case -- not this
      class's job.
    '''
    @property
    def _constructor(self): return NAFrame

    def __setitem__(self, key, value):
        if isinstance(value, (pd.Series, np.ndarray, list)):
            v = value if isinstance(value, pd.Series) else pd.Series(value, index=self.index)
            if pd.api.types.is_bool_dtype(v.dtype):
                value = v.astype("boolean")
            elif pd.api.types.is_numeric_dtype(v.dtype):
                value = v.convert_dtypes(convert_string=False, convert_boolean=False)
        super().__setitem__(key, value)


class SignalOutput(NamedTuple):
    '''Universal output shape for both engine hooks -- build_signal (owns
    entry+exit for one exclusive position: long xor short xor flat) and
    build_regime (owns long-permission and short-permission independently,
    NOT mutually exclusive -- a bar can permit both sides, one side, or
    neither). Which hook a template is used as decides how the engine
    collapses these four masks (see engine.py's _strategy_signal()/
    _regime_mask()) -- the shape alone doesn't distinguish the two roles, so
    pick a template by its documented role (see template/__init__.py's
    `allow_` naming convention: only those are safe as build_regime ONLY;
    every other template's long_entry/short_entry are complementary, so
    it's safe as either hook).

    Length validation (including `valid`) happens at the call site
    (_strategy_signal()/_regime_mask() in engine.py), not here.
    '''
    long_entry: np.ndarray            # bool, len(df) -- long turns ON this bar
    short_entry: np.ndarray           # bool, len(df) -- short turns ON this bar
    long_exit: np.ndarray             # bool, len(df) -- long turns OFF this bar
    short_exit: np.ndarray            # bool, len(df) -- short turns OFF this bar
    valid: Optional[np.ndarray] = None   # bool, True past warmup; None = every bar valid

    @classmethod
    def from_state(cls, long_ok, short_ok, valid=None):
        '''Construct from a PERSISTENT "is this side currently
        permitted/held" state instead of pre-computed transitions -- most
        templates think in this shape (e.g. "long while z-score >
        threshold"), not in raw entry/exit edges. Internally derives
        entry/exit transitions via _edges_from_ok(); the engine's own
        ffill-based state machine (_strategy_signal()/_regime_mask())
        reconstructs long_ok/short_ok from them exactly -- so
        from_state(long_ok, short_ok) round-trips losslessly through either
        hook.
        '''
        long_entry, long_exit = _edges_from_ok(long_ok)
        short_entry, short_exit = _edges_from_ok(short_ok)
        valid_arr = None if valid is None else np.asarray(valid, dtype=bool)
        return cls(long_entry, short_entry, long_exit, short_exit, valid_arr)


# build_signal(df, **kwargs) -> SignalOutput, or build_regime(df, **kwargs) ->
# SignalOutput -- same callable shape either way; see SignalOutput's own
# docstring for how the engine tells them apart (by which hook it's assigned
# to, never by inspecting the returned masks).
SignalFn = Callable[..., SignalOutput]


class FeatureScale:
    '''Namespace grouping shared feature-scaling helpers. Every rolling
    window here ENDS at the current bar, so a bar's own value is one of the
    window members used to scale it. Still no lookahead: nothing here reads
    a bar newer than the current one (no negative shift, no centered
    window), and the engine supplies the delay -- run_backtest()'s lag=1
    default means bar t's signal is first traded at t+1
    (engine.py's _position_from_signal()). That lag is what keeps these
    boundaries causal, so lag=0 buys a lookahead backtest, and a strategy
    that genuinely means "the PRIOR N bars" has to say so with its own
    .shift(1) (see template/donchian_breakout.py and
    frontend/public/example_strategy.md's HysteresisExample).

    template/*.py mostly follows this convention too -- abv_blw_ma and
    abv_blw_dev had their .shift(1) removed to match, abv_blw_zscore()
    calls zscore() below, allow_quantile() calls quantile() below, and
    abv_blw_dev() calls deviation() below. One deliberate exception:
    donchian_breakout keeps its channel .shift(1), where the shift is
    definitional ("the PRIOR N bars") rather than a guard -- with an
    inclusive window its breakout test is unsatisfiable.

    One shift survives here deliberately, and it is DEFINITIONAL rather than
    a guard: log()'s, since a 1-bar return is bar t against bar t-1. Nothing
    else in this class shifts -- rsi() has no window at all (it reads the
    series' own changes up to and including the current bar), and every other
    method reads the window ENDING at the current bar by design.
    '''

    @staticmethod
    def zscore(series: pd.Series, window: int, min_period: int | None = None, cache=None, cache_key=None) -> pd.Series:
        '''Rolling mean/std over a window ENDING at the current bar (the
        current value is one of the window members the mean/std are computed
        from -- see the class docstring), z = (series - mean) / std. A flat
        window (std 0) -> NaN, not inf.

        cache/cache_key are an opt-in memoization hook for sweep() -- see
        sweep()'s docstring. Both None (the default) reproduces the plain
        computation exactly; a cache hit returns a previously-computed result
        unchanged.

        min_period: rolling min_periods, defaults to round(window * 0.7)
        clamped into [1, window] so values go live before a full window is
        available.
        '''
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        window = max(1, int(window))
        mp = min_period if min_period is not None else round(window * 0.7)
        min_period = max(1, min(window, int(mp)))
        mean = series.rolling(window, min_periods=min_period).mean()
        std = series.rolling(window, min_periods=min_period).std().replace(0, np.nan)
        result = ((series - mean) / std).replace([np.inf, -np.inf], np.nan)
        if cache is not None:
            cache[cache_key] = result
        return result

    @staticmethod
    def bb(series: pd.Series, window: int, min_period: int | None = None, cache=None, cache_key=None) -> pd.Series:
        '''Bollinger-Bands-style normalization, oriented for MEAN REVERSION
        (short above the upper band, long below the lower band) -- matches
        oi_bb.ipynb's convention. Literally -zscore() -- agrees with 'z' on
        the band math, not the trading direction. A deliberate divergence
        from 'z', not a bug. See CLAUDE.md.

        cache/cache_key are forwarded to zscore() unchanged -- use the SAME
        cache_key a 'z' call for this (df, column, window) would use, since
        bb() is just -zscore(); the two can then share one cached rolling
        computation.
        '''
        return -FeatureScale.zscore(series, window, min_period=min_period, cache=cache, cache_key=cache_key)

    @staticmethod
    def min_max(series: pd.Series, window: int, min_period: int | None = None, cache=None, cache_key=None) -> pd.Series:
        '''Rolling min-max scale against a window ENDING at the current bar,
        in [0, 1] by construction -- the current value is one of the window's
        own members, so it can never fall outside the band. A flat window
        (span 0) -> NaN, not divide-by-zero.

        min_period: rolling min_periods, defaults to round(window * 0.7)
        clamped into [1, window] so values go live before a full window is
        available.
        cache/cache_key: see zscore()'s docstring.
        '''
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        window = max(1, int(window))
        mp = min_period if min_period is not None else round(window * 0.7)
        min_period = max(1, min(window, int(mp)))
        roll_min = series.rolling(window, min_periods=min_period).min()
        roll_max = series.rolling(window, min_periods=min_period).max()
        span = (roll_max - roll_min).replace(0, np.nan)
        result = (series - roll_min) / span
        if cache is not None:
            cache[cache_key] = result
        return result

    @staticmethod
    def percentile(series: pd.Series, window: int, min_period: int | None = None, cache=None, cache_key=None) -> pd.Series:
        '''Rolling percentile rank of the current bar within the window ENDING
        at it, in {1/window, ..., 1.0} -- pandas' .rolling().rank(pct=True),
        i.e. (count of window values <= the current value) / (count of window
        values), ties averaged. The current bar is one of those values, so a
        window-max reads exactly 1.0 and a fully flat window reads
        (window + 1) / (2 * window) -- 0.6 at window=5, i.e. the middle of the
        range, neutral, rather than the bottom. The inclusive "<=" boundary also
        matches the convention quantile() uses for its low/high tiers.

        min_period: rolling min_periods, defaults to round(window * 0.7)
        clamped into [1, window] so values go live before a full window is
        available.
        cache/cache_key: see zscore()'s docstring.
        '''
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        window = max(1, int(window))
        mp = min_period if min_period is not None else round(window * 0.7)
        min_period = max(1, min(window, int(mp)))
        result = series.rolling(window, min_periods=min_period).rank(pct=True)
        if cache is not None:
            cache[cache_key] = result
        return result

    @staticmethod
    def log(series: pd.Series, cache=None, cache_key=None) -> pd.Series:
        '''1-bar log-return: log(series / series.shift(1)). The shift(1) here
        IS the return's definition (bar t against bar t-1), not a look-ahead
        guard -- dropping it would divide the series by itself and return
        log(1) == 0 everywhere. No window -- unlike zscore()/min_max()/
        percentile()/quantile()/mad()/deviation(), this isn't a rolling-window
        computation at all.
        cache/cache_key: see zscore()'s docstring.
        '''
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        result = np.log(series / series.shift(1)).replace([np.inf, -np.inf], np.nan)
        if cache is not None:
            cache[cache_key] = result
        return result

    @staticmethod
    def quantile(series: pd.Series, window: int, min_period: int | None = None, lower_pct=0.25, upper_pct=0.75, cache=None, cache_key=None) -> pd.Series:
        '''Label each bar low/mid/high against a trailing rolling window whose
        cutoffs come from that same window ENDING at the current bar: the
        current value is one of the members the cutoffs are computed from
        (see the class docstring), so a bar's own value can move its own
        cutoff. Warmup, AND any bar whose own value is NaN (e.g. a
        fill_policy='none' data gap) -> tier is NaN, not a fabricated label
        -- matches every other FeatureScale method's warmup contract (NaN,
        never a fake value).

        Returns a (low, mid, high, tier) tuple of 4 Series, same shape as
        series -- matches every other FeatureScale method's "returns a
        Series" contract, just 4 of them. tier holds the label itself, one
        of 'low'/'mid'/'high'/NaN; the boundaries are low_cut-inclusive
        ((-inf, low_cut]), high_cut-inclusive ([high_cut, +inf)), mid strictly
        between. low/mid/high hold the series' OWN VALUE on the rows that
        fall in that tier (NaN elsewhere) -- NOT the rolling cutoffs
        themselves (those aren't returned; recompute them the same way if
        needed). Caller names/assigns columns, same as zscore() etc.'s
        callers do -- with one difference: low/mid/high are NaN on ~2/3 of
        rows by design (mutually exclusive across the three tiers), so
        assigning them as plain df columns inside a build_signal/
        build_regime hook makes engine.py's valid-derivation (NaN across
        every returned column) mark every bar invalid. Only assign `tier`
        (dense: NaN only where truly unknown) as a plain column; if
        low/mid/high are wanted on the frame too (e.g. for plotting), prefix
        them with '_' so the engine's valid scan skips them, e.g.:
            *_, df["tier"] = FeatureScale.quantile(df["close"], window)
            df["long_entry"] = df["tier"] == "low"
            # want the masked values on the frame too?
            df["_lo"], df["_mid"], df["_hi"], df["tier"] = FeatureScale.quantile(df["close"], window)
        See frontend/public/example_strategy.md's QuantileDirectExample and
        template/allow_quantile.py for real callers (allow_quantile.py only
        uses the `tier` element).

        np.select() needs plain numpy bool arrays -- series is a nullable
        Float64 column (NAFrame), so this comparison comes back nullable
        "boolean" dtype, which np.select() rejects outright. .fillna(False)
        is safe here because the .mask() below explicitly covers
        series.isna() too, on top of low.isna() -- a NaN-valued bar can't
        slip through to the 'high' default the way it used to. Same cast
        used everywhere else this repo hits the same nullable-dtype
        np.select() problem (engine.py's _strategy_signal(), the notebook
        pipeline's equivalent).

        min_period: rolling min_periods, defaults to round(window * 0.7)
        clamped into [1, window] so values go live before a full window is
        available.
        cache/cache_key: see zscore()'s docstring.
        '''
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        window = max(1, int(window))
        mp = min_period if min_period is not None else round(window * 0.7)
        min_period = max(1, min(window, int(mp)))
        low = series.rolling(window, min_periods=min_period).quantile(lower_pct)
        high = series.rolling(window, min_periods=min_period).quantile(upper_pct)
        cond_low = (series <= low).fillna(False).to_numpy(dtype=bool)
        cond_mid = (series < high).fillna(False).to_numpy(dtype=bool)
        tier = pd.Series(np.select([cond_low, cond_mid], ['low', 'mid'], default='high'),
                        index=series.index)
        tier = tier.mask(low.isna() | series.isna())
        result = (series.where(tier == 'low'), series.where(tier == 'mid'), series.where(tier == 'high'), tier)
        if cache is not None:
            cache[cache_key] = result
        return result

    @staticmethod
    def rsi(series: pd.Series, window: int, min_period: int | None = None, cache=None, cache_key=None) -> pd.Series:
        '''Wilder's Relative Strength Index in [0, 100], as a float64 Series
        on series.index.

        No boundary: unlike zscore()/min_max()/percentile()/quantile()/
        mad()/deviation() there is no window here at all -- the value at bar t
        averages changes up to and including bar t, exactly like log(). No
        .shift(1) anywhere: the engine's `lag` is what delays execution by a
        bar.

        Works on any numeric column (close, a feature, a derived column):
        changes are taken between consecutive NON-NaN values, so a
        zero-crossing or negative series is fine. A bar whose own value is
        NaN outputs NaN, and the first valid bar after a gap measures its
        change against the last valid value before the gap, so the move
        across the gap counts once.

        Smoothing is the classic Wilder recursion, matching TradingView's
        ta.rsi and TA-Lib: the first average gain/loss is the plain mean of
        the first `window` changes, after which avg += (x - avg) / window. A
        pure uptrend gives 100, a pure downtrend 0, and a series that never
        moves (0 / 0) NaN. RS is deliberately never formed, so the sibling
        methods' .replace([np.inf, -np.inf], np.nan) idiom is NOT applied
        here -- it would turn a pure uptrend into NaN. ewm(alpha=1 / window)
        is the same recursion, but only after the NaN positions are punched
        out of its input: pandas carries the last average ACROSS NaN inputs,
        which would invent an RSI on the gap bars themselves.

        min_period: bar index of the first output (result[:min_period] ->
        NaN), defaults to round(window * 0.7) clamped into [1, window]. This
        is a hard floor on the RESULT, not a rolling min_periods like the
        other methods' min_period: the Wilder seed already keeps the first
        output at index `window`, so a min_period below that changes nothing.
        A series with len(series) <= window -> all NaN, no error.
        cache/cache_key: see zscore()'s docstring.
        '''
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        window = max(1, int(window))
        mp = min_period if min_period is not None else round(window * 0.7)
        min_period = max(1, min(window, int(mp)))

        s = pd.Series(series, dtype='float64')
        valid = s.notna().to_numpy()
        s = s[valid]
        result = np.full(len(series), np.nan, dtype='float64')
        if len(s) > window:
            d = s.diff().to_numpy()
            avgs = []
            for x in (np.clip(d, 0, None), np.clip(-d, 0, None)):
                y = x.copy()
                y[:window] = np.nan
                y[window] = np.nanmean(x[1:window + 1])
                avgs.append(pd.Series(y).ewm(alpha=1 / window, adjust=False).mean().to_numpy())
            gain, loss = avgs
            denom = gain + loss
            # gain / denom is evaluated before the *100 so a pure uptrend
            # (gain == denom) lands on exactly 100.0 rather than 99.999...
            # denom == 0 (a series that never moves) and the NaN warmup keep
            # their pre-filled NaN instead of raising a divide-by-zero.
            ratio = np.full(len(s), np.nan, dtype='float64')
            np.divide(gain, denom, out=ratio, where=np.isfinite(denom) & (denom != 0))
            rsi = 100.0 * ratio
            rsi[:min_period] = np.nan
            result[valid] = rsi
        out = pd.Series(result, index=series.index, dtype='float64')
        if cache is not None:
            cache[cache_key] = out
        return out

    @staticmethod
    def mad(series: pd.Series, window: int, min_period: int | None = None, relative: bool = False,
            cache=None, cache_key=None) -> pd.Series:
        '''Rolling mean absolute deviation of the window about that window's
        own mean: mean(|x - mean(x)|) over a window ENDING at the current bar
        (the current value is one of the x's -- see the class docstring).
        relative=False -> that MAD; relative=True -> the same MAD divided by
        the window's absolute mean (mad / |mean|), which makes it scale-free
        and comparable across columns of different magnitude (and turns a
        zero mean into NaN, not inf).

        NOT the same statistic as deviation() below -- this one is unsigned
        and averages over the whole window; deviation() is the current
        value's own signed distance from the mean.

        min_period: rolling min_periods, defaults to round(window * 0.7)
        clamped into [1, window] so values go live before a full window
        is available.
        cache/cache_key: see zscore()'s docstring. The key must be unique per
        parameterization (sweep() only keys on swept kwargs), so relative=True
        must not reuse relative=False's entry.
        '''
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        window = max(1, int(window))
        mp = min_period if min_period is not None else round(window * 0.7)
        min_period = max(1, min(window, int(mp)))
        mad = series.rolling(
            window=window,
            min_periods=min_period,
        ).apply(
            lambda v: np.mean(np.abs(v - v.mean())),
            raw=True,
        )
        if relative:
            mean = series.rolling(
                window=window,
                min_periods=min_period,
            ).mean()
            # Avoid division by zero when the rolling mean is zero.
            mad = mad / mean.abs().replace(0, np.nan)
        if cache is not None:
            cache[cache_key] = mad
        return mad

    @staticmethod
    def deviation(series: pd.Series, window: int, min_period: int | None = None, relative: bool = False,
                  cache=None, cache_key=None) -> pd.Series:
        '''Signed distance of each bar from the mean of the window ENDING at
        it: series - mean(window), the current value being one of the window
        members that mean is computed from (see the class docstring).
        relative=False -> that raw deviation, in the series' own units;
        relative=True -> the same deviation divided by the window's mean
        (series / mean - 1), i.e. how far from the mean in "mean units",
        which makes it scale-free and comparable across columns of different
        magnitude. A zero mean gives NaN, not inf.

        Signed and current-bar-only, unlike the other window methods'
        distance-in-window-units: deviation == 0 exactly where the bar IS its
        window's mean. With relative=True the series must KEEP ONE SIGN -- a
        mean crossing zero inverts the ratio (use zscore() for a
        zero-crossing series).

        NOT the same statistic as mad() above -- this is the current bar's own
        signed offset from the mean (so it can point either way); mad() is the
        unsigned mean absolute deviation of every window member.

        min_period: rolling min_periods, defaults to round(window * 0.7)
        clamped into [1, window] so values go live before a full window is
        available.
        cache/cache_key: see zscore()'s docstring. The key must be unique per
        parameterization (sweep() only keys on swept kwargs), so relative=True
        must not reuse relative=False's entry.
        '''
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        window = max(1, int(window))
        mp = min_period if min_period is not None else round(window * 0.7)
        min_period = max(1, min(window, int(mp)))
        mean = series.rolling(window, min_periods=min_period).mean()
        result = series - mean
        if relative:
            result = (result / mean).replace([np.inf, -np.inf], np.nan)
        if cache is not None:
            cache[cache_key] = result
        return result
