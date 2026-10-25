"""Signal construction copied verbatim from the research lab's engine
(lab/backend/app/pipeline_engine/engine.py, error.py, engine_axis.py) so a
strategy researched in the lab produces the SAME long/short signal when Forge
runs it as a bot. Do not edit by hand: re-copy from the lab when it changes,
and keep tests/test_signal_adapter.py green.

Only the signal half is copied (build_signal -> masks -> state machine ->
regime overlay). Fills, stops, take-profit, max-hold and fees are Forge's own
(engine/core.py, engine/signal_adapter.py).
"""
import inspect
import math
import re

import numpy as np
import pandas as pd

from .primitive import SignalFn, SignalOutput, _ffill, _state_from_edges


# ---- from error.py ----

class StrategyDataError(Exception):
    """Raised in place of a bare KeyError when a strategy's build_data()/
    build_signal() fails accessing a dataframe column."""


def _raise_clear(exc: KeyError, hook_name: str, df) -> None:
    column = exc.args[0] if exc.args else str(exc)
    raise StrategyDataError(
        f"strategy's {hook_name}() expects column {column!r}, dataset has: {list(df.columns)}"
    ) from exc


def call_build_data(alpha_cls, df):
    """alpha_cls.build_data(df) if the strategy defines it, else df
    unchanged -- same hasattr guard every call site already used, now with a
    clear error instead of a bare traceback on a missing-column KeyError, plus
    a return-type check (must be a DataFrame, NAFrame included) so a strategy
    author's mistake surfaces here instead of deep inside the engine."""
    if not hasattr(alpha_cls, "build_data"):
        return df
    try:
        ret = alpha_cls.build_data(df)
    except KeyError as exc:
        _raise_clear(exc, "build_data", df)
    if not isinstance(ret, pd.DataFrame):
        raise TypeError(f"strategy's build_data() must return a DataFrame, got {type(ret).__name__}")
    return ret


def call_build_signal(strategy, df, strategy_kwargs):
    """Wraps the one call site inside engine.py's _strategy_signal() where a
    strategy's build_signal is actually invoked."""
    try:
        return strategy(df, **strategy_kwargs)
    except KeyError as exc:
        _raise_clear(exc, "build_signal", df)


# ---- from engine_axis.py ----

ENGINE_ROUTED_AXES = ('lag', 'max_hold')


def signal_axis_names(axis_names):
    """`axis_names` minus ENGINE_ROUTED_AXES, in order -- the PARAMS axes
    build_signal() is actually called with. The ONE filter every build_signal
    kwargs builder goes through (run_backtest_kwargs_from_entry(),
    build_grid_signals()/score_grid()'s signal key, the causality-check
    endpoint), so a new caller can't forward max_hold into a hook that has no
    such parameter."""
    return tuple(name for name in axis_names if name not in ENGINE_ROUTED_AXES)


def normalize_max_hold(max_hold):
    """None (no cap) or a whole number of bars >= 1. Swept values arrive as
    floats (a {'min','max','step'} spec expands through np.arange, and request
    strategy_params are floats), so round half up instead of truncating;
    anything that rounds below 1 -- including the 0 a grid uses to mean "off" --
    and a NaN/inf mean no cap."""
    if max_hold is None:
        return None
    try:
        bars = float(max_hold)
    except (TypeError, ValueError):
        raise ValueError(f"max_hold must be a number of bars, got {max_hold!r}") from None
    if not math.isfinite(bars):
        return None
    bars = math.floor(bars + 0.5)
    return bars if bars >= 1 else None


# ---- from engine.py ----

# Signal-column conventions a build_signal/build_regime hook's returned
# DataFrame must use. See _adapt_signal_df()'s docstring.
_ENTRY_COLS = ('long_entry', 'short_entry')     # always required
_EXIT_COLS = ('long_exit', 'short_exit')        # 0 present = persistent-state form; 2 = edge form
_EDGE_COLS = _ENTRY_COLS + _EXIT_COLS           # kept as a 4-tuple: check_causality() iterates
                                                 # SignalOutput's own field names via this, not a
                                                 # DataFrame column check -- unaffected by the split above.
# 2026-09-08 pre-rename names -- long_ok/short_ok, a persistent per-bar state.
# Retired: superseded by the 2-of-4-columns long_entry/short_entry form below,
# so every hook uses ONE vocabulary (entry/exit) instead of two. Kept here
# only so a straggler upload gets a rename hint instead of a bare "missing
# column" error.
_LEGACY_STATE_COLS = ('long_ok', 'short_ok')

# Rolling-window-style calls whose warmup NaN a strategy author must land on
# a df column for the engine to see (a bare local variable can lose that NaN
# the moment it's compared, unless the whole chain stays nullable-dtype end
# to end) -- see _check_warmup_blind_spot()'s docstring.
_WARMUP_CALL_RE = re.compile(r'\.(rolling|ewm|expanding)\(')


def _adapt_signal_df(ret, hook_name, report=None):
    '''build_signal()/build_regime() now return a plain DataFrame (any number
    of the author's own intermediate columns, plus the signal columns) rather
    than a SignalOutput NamedTuple -- this is the one adapter that turns that
    DataFrame into the SignalOutput the rest of the engine still works with
    internally. `hook_name` is 'build_signal' or 'build_regime', used only for
    error messages.

    One vocabulary, two shapes, dispatched by how many of _EXIT_COLS are
    present (2026-09-08: replaces the old long_ok/short_ok vs.
    long_entry/short_entry/long_exit/short_exit two-name-set contract -- see
    webapp/CLAUDE.md's same-dated entry for why):
    - `long_entry`/`short_entry` ONLY (no exit columns) -- a persistent
      per-bar state ("is this side currently permitted/held"), routed through
      SignalOutput.from_state(). Numerically identical to the old
      long_ok/short_ok form -- only the column names changed.
    - All four _EDGE_COLS -- raw entry/exit transition columns, for an
      edge-shaped signal like donchian_breakout's differing entry/exit
      channel widths that can't be expressed as one persistent state.
    - Exactly one of _EXIT_COLS present is ambiguous (ValueError) -- there is
      no reasonable way to guess whether the author meant the edge form and
      forgot a column, or the state form and left a stray column behind.
    _ENTRY_COLS missing (either or both) is always an error -- these are
    never optional, unlike _EXIT_COLS.

    `valid` (the warmup mask) is DERIVED, not read off any single column the
    author named -- it's `~ret[scan].isna().any(axis=1)`, scanning EVERY
    column on the returned frame EXCEPT one whose name starts with '_', the
    signal columns included. Scanning the signal columns too (not just
    "everything else") is deliberate, not redundant: a second computation
    layer built anonymously off a NAMED first layer (e.g.
    `df["long_entry"] = df["vol"] < df["vol"].rolling(window).median()`,
    where the `.rolling(window).median()` on the right is never itself
    assigned to a df column) has NO OTHER column to surface its own warmup
    through -- NAFrame's nullable-dtype comparison still carries that second
    layer's NA into `long_entry`/`short_entry` themselves, so only including
    the signal columns in this scan catches it (verified: excluding them from
    the scan silently truncates a multi-layer warmup to just the first
    layer's own boundary -- caught by this task's own test_two_stage_
    anonymous_second_layer_warmup_exact during self-review, not assumed). If
    `ret`'s columns have no NaN anywhere, every bar is valid (no computation
    to warm up from) -- see _check_warmup_blind_spot() for the backstop
    against an author whose chain fully severs the nullable lineage instead
    (so nothing anywhere on `ret`, signal columns included, ever carries the
    warmup NA).

    The '_'-prefix opt-out (added alongside FeatureScale.quantile()'s
    NaN-warmup fix) exists because a column that's sparse BY DESIGN (e.g.
    FeatureScale.quantile()'s low/mid/high, mutually exclusive across tiers)
    isn't a warmup signal -- without it, assigning such a column onto the
    hook's df would poison `valid` to all-False. Signal columns can never be
    '_'-prefixed (fixed names, _ENTRY_COLS/_EXIT_COLS), so `scan` is never
    empty. No column anywhere in this codebase starts with '_' today, so
    this opt-out is behavior-neutral until an author uses it.

    report: optional dict, filled IN PLACE with invalid-bar diagnostics for
    worker/task.py's post-run `invalid_report` -- see
    _fill_invalid_report(). None (the default, used by sweep()'s fast path)
    skips this entirely, so the per-column NaN attribution never costs
    anything inside a grid.
    '''
    if not isinstance(ret, pd.DataFrame):
        raise TypeError(f"strategy's {hook_name}() must return a DataFrame, got {type(ret).__name__}")
    cols = set(ret.columns)
    missing_entry = [c for c in _ENTRY_COLS if c not in cols]
    if missing_entry:
        legacy = [c for c in _LEGACY_STATE_COLS if c in cols]
        hint = (f" -- {legacy} is the OLD pre-rename name for {list(_ENTRY_COLS)}; "
                f"rename those columns (same meaning, same behavior)") if legacy else ""
        raise ValueError(
            f"strategy's {hook_name}() must return a DataFrame with {list(_ENTRY_COLS)} as "
            f"columns (add {list(_EXIT_COLS)} too only if exit is a DIFFERENT condition than "
            f"'entry stopped being true') -- missing {missing_entry}, found {sorted(cols)}{hint}"
        )
    present_exit = [c for c in _EXIT_COLS if c in cols]
    if len(present_exit) == 1:
        missing = [c for c in _EXIT_COLS if c not in cols]
        raise ValueError(
            f"strategy's {hook_name}() returned {present_exit[0]!r} without its counterpart "
            f"{missing[0]!r} -- return BOTH {list(_EXIT_COLS)} (edge form) or NEITHER "
            f"(persistent-state form), found {sorted(cols)}"
        )
    has_edge = len(present_exit) == 2
    scan = [c for c in ret.columns if not str(c).startswith('_')]
    valid = (~ret[scan].isna().any(axis=1)).to_numpy()
    if report is not None:
        _fill_invalid_report(report, ret, scan, valid)

    def _mask(col):
        s = ret[col]
        try:
            return s.fillna(False).to_numpy(dtype=bool)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"strategy's {hook_name}() column {col!r} is not boolean-like "
                f"(dtype={s.dtype}) -- {exc}"
            ) from exc

    if has_edge:
        out = SignalOutput(_mask('long_entry'), _mask('short_entry'),
                           _mask('long_exit'), _mask('short_exit'), valid)
    else:
        out = SignalOutput.from_state(_mask('long_entry'), _mask('short_entry'), valid)
    return out


def _fill_invalid_report(report, ret, scan, valid):
    '''Fills `report` (a plain, JSON-serializable dict, in place) with
    invalid-bar diagnostics -- travels to the frontend as
    BacktestResult.kwargs['invalid_report'], the same way `join_report`
    already does (see worker/task.py). `scan`/`valid` are
    _adapt_signal_df()'s own (the '_'-prefix-filtered column list and the
    resulting mask), so this never recomputes anything already paid for.

    leading_warmup/mid_series_gap split: the FIRST True in `valid` (if any)
    marks the end of the leading run -- every invalid bar before it is
    warmup by construction (argmax() returns the first True's index, so
    valid[:first_valid] is all False); every invalid bar after it is a
    mid-series gap (e.g. a fill_policy='none' data hole).
    '''
    n = len(valid)
    n_invalid = int((~valid).sum())
    report['total_bars'] = n
    report['invalid_bars'] = n_invalid
    if not n_invalid:
        return
    if valid.any():
        leading_warmup = int(valid.argmax())
    else:
        leading_warmup = n_invalid
    report['leading_warmup'] = leading_warmup
    report['mid_series_gap'] = n_invalid - leading_warmup
    na_counts = ret[scan].isna().sum()
    na_counts = na_counts[na_counts > 0].sort_values(ascending=False)
    top = na_counts.head(5)
    report['na_by_column'] = {str(k): int(v) for k, v in top.items()}
    report['na_by_column_more'] = max(0, len(na_counts) - len(top))


def _check_warmup_blind_spot(hook_fn, valid, hook_name):
    '''Best-effort static backstop for the one blind spot NAFrame's automatic
    nullable-dtype propagation cannot close on its own: an author who keeps a
    rolling/ewm/expanding intermediate as a bare local variable (or explicitly
    drops to .to_numpy()/.values and rebuilds a plain Series/DataFrame),
    severing the nullable NA lineage before it ever reaches a df column --
    see NAFrame's own docstring for why only a column assignment can carry
    that NaN through to where _adapt_signal_df() can see it.

    Only fires when EVERY bar came back valid (nothing for _adapt_signal_df()
    to have derived a warmup from) AND the hook's own source text calls
    .rolling()/.ewm()/.expanding() somewhere -- a hook that does neither is
    not this failure mode (a genuine no-warmup strategy, e.g. `df["close"] >
    df["open"]`, is EXPECTED to have every bar valid and must never trip
    this).

    Deliberately gives up silently (returns without raising) when the source
    can't be read -- inspect.getsource() raises OSError for any hook exec'd
    from uploaded strategy source (compiled with a synthetic <strategy:name>
    filename, never backed by a real file or a linecache entry -- verified
    empirically, not assumed) rather than risk a false positive/negative on
    code this function structurally cannot see. This means the check is
    effectively a dev/test-time and template-function backstop, not the
    primary defense for real uploaded strategies -- the upload-time static
    check (which has the raw source STRING available, before any exec ever
    happens) is the one that actually covers that case for production use.
    '''
    if not valid.all():
        return
    try:
        src = inspect.getsource(hook_fn)
    except (OSError, TypeError):
        return
    if _WARMUP_CALL_RE.search(src):
        raise ValueError(
            f"strategy's {hook_name}() calls rolling()/ewm()/expanding() but every "
            f"bar came back valid -- if an intermediate value is only a local "
            f"variable (not assigned to a df column, e.g. df[\"vol\"] = ... instead "
            f"of vol = ...), the engine cannot see its warmup NaNs. Assign every "
            f"intermediate rolling/ewm/expanding result to a df column so its NaN "
            f"reaches the returned signal columns."
        )


def _strategy_signal(df, strategy: SignalFn, strategy_kwargs, mode, on_missing_data='hold', report=None):
    '''build_signal -> masks -> pass-1 signal, BEFORE any regime overlay --
    the part of _build_position() that depends only on strategy_kwargs/mode,
    never on regime_kwargs. sweep()'s fast path computes this once per
    DISTINCT strategy combination and reuses it across every regime
    combination in the grid, instead of once per (strategy, regime) cell (see
    sweep()'s docstring) -- build_signal's own output never depends on
    regime_kwargs.

    build_signal is called with a COPY of `df`, never the caller's own
    object -- build_signal now writes its intermediates directly onto the
    DataFrame it's handed (see _adapt_signal_df()'s docstring), and this
    function's caller (build_grid_signals()'s Phase A, in particular) invokes
    the SAME strategy repeatedly against the SAME `df` for every distinct
    param combo; without a fresh copy each time, one combo's leftover
    intermediate columns (and their warmup NaN) would still be sitting on
    `df` the next time it's read here, corrupting that combo's own valid
    derivation with a PRIOR combo's warmup. Verified empirically that this
    leak is real without the copy, and that .copy() on an NAFrame instance
    stays an NAFrame (pandas' own _constructor mechanism) -- see the Task 3
    self-review notes.

    on_missing_data ('hold' default | 'liquidate'): governs what happens to an
    OPEN position when df carries a mid-series invalid stretch that begins
    AFTER the series' first-ever valid bar -- e.g. a feature dataset with
    Dataset.fill_policy=='none' leaving a real NaN gap that _adapt_signal_df()
    derives into `valid=False` for those bars, same mechanism as warmup.
    'hold' (default, and the pre-existing behavior) just masks entries/exits
    to nothing across the invalid stretch -- whatever position was open going
    in stays open, unchanged, until valid data resumes. 'liquidate' instead
    force-exits on the FIRST bar of each such stretch. Never touches the
    warmup blind spot (the leading invalid run before the series' first-ever
    valid bar, restored by the `fv` block below) -- that boundary-seeding
    mechanism is protected by test_donchian_valid_gating_matches_naive_post_warmup
    and must stay byte-for-byte unchanged in both modes.

    Returns (raw, signal, valid_mask). `raw` is np.select()'s own pre-ffill
    array (NaN where neither side ever triggered) -- kept because
    _apply_regime_overlay() below needs to re-derive signal from raw after
    zeroing hostile entries; re-ffilling the ALREADY-ffilled `signal` again
    would be wrong wherever an entry gets suppressed.

    report: optional dict, filled with this hook's invalid-bar diagnostics --
    see _adapt_signal_df()'s own `report` param. Only worker/task.py's
    run_backtest task passes one; sweep()'s fast path never does, so this
    costs nothing inside a grid.
    '''
    if on_missing_data not in ('hold', 'liquidate'):
        raise ValueError(f"on_missing_data must be 'hold' or 'liquidate', got {on_missing_data!r}")
    strategy_kwargs = strategy_kwargs or {}
    ret = call_build_signal(strategy, df.copy(), strategy_kwargs)
    out = _adapt_signal_df(ret, 'build_signal', report=report)
    n = len(df)
    long_entry = np.asarray(out.long_entry, dtype=bool)
    short_entry = np.asarray(out.short_entry, dtype=bool)
    long_exit = np.asarray(out.long_exit, dtype=bool)
    short_exit = np.asarray(out.short_exit, dtype=bool)
    for name, arr in (('long_entry', long_entry), ('short_entry', short_entry),
                      ('long_exit', long_exit), ('short_exit', short_exit)):
        if len(arr) != n:
            raise ValueError(f'strategy output {name!r} length must match df')

    valid_mask = np.ones(n, dtype=bool) if out.valid is None else np.asarray(out.valid, dtype=bool)
    # Defense in depth: _adapt_signal_df() always derives `valid` from `ret`
    # itself, so its length structurally matches the four masks above
    # whenever _adapt_signal_df() succeeds -- this can't currently fire, but
    # costs nothing and guards against a future refactor bypassing that
    # guarantee.
    if len(valid_mask) != n:
        raise ValueError("strategy output 'valid' length must match df")
    _check_warmup_blind_spot(strategy, valid_mask, 'build_signal')

    # valid-gate the raw edges themselves, not just the final stats filter:
    # without this, a warmup-period entry still opens a REAL position (the
    # ffill state machine below carries it forward unchanged), and only gets
    # dropped from the scored frame afterward -- so its entry fee is charged
    # on a row that then vanishes, making the position look free. Compress
    # invalid-region events to nothing, but if the RAW (pre-gating) edges
    # implied a held position at the first valid bar, restore that one bar's
    # entry so a persistent-state template (SignalOutput.from_state()) still
    # opens its position exactly where its own state said it should -- naively
    # zeroing every invalid-region event and restoring nothing would silently
    # drop that first real entry instead. This is NOT the same as re-deriving
    # state -> edges over the whole array (_regime_mask()'s convention for
    # regime permission): that full round-trip is LOSSY for an edge-shaped
    # signal with asymmetric entry/exit widths (donchian_breakout's
    # entry_window != exit_window) -- verified empirically that round-tripping
    # shifts donchian's own trade count. Touching only the single first-valid
    # bar leaves every edge-shaped signal's post-warmup behavior byte-for-byte
    # unchanged (see test_donchian_valid_gating_matches_naive_post_warmup),
    # while still closing the entry-fee gap for state-shaped templates.
    if not valid_mask.all():
        l_state = _state_from_edges(long_entry, long_exit)
        s_state = _state_from_edges(short_entry, short_exit)
        if report is not None:
            report['entries_suppressed'] = {
                'long': int((long_entry & ~valid_mask).sum()),
                'short': int((short_entry & ~valid_mask).sum()),
            }
        long_entry = long_entry & valid_mask
        short_entry = short_entry & valid_mask
        long_exit = long_exit & valid_mask
        short_exit = short_exit & valid_mask
        if valid_mask.any():
            fv = int(valid_mask.argmax())
            if l_state[fv]:
                long_entry[fv] = True
            if s_state[fv]:
                short_entry[fv] = True
            if on_missing_data == 'liquidate':
                # Force-exit on the first bar of every invalid stretch that
                # starts AFTER fv (the warmup boundary above is untouched --
                # invalid_after_fv is False there by construction). l_state/
                # s_state are the PRE-masking persistent state, so indexing
                # them at a stretch's first (invalid) bar reflects whichever
                # side was actually open coming out of the last valid bar --
                # exactly the position 'hold' mode would otherwise carry
                # through the whole gap unchanged.
                invalid_after_fv = ~valid_mask
                invalid_after_fv = invalid_after_fv & (np.arange(n) > fv)
                stretch_start = invalid_after_fv & ~np.r_[False, invalid_after_fv[:-1]]
                if stretch_start.any():
                    long_exit = long_exit | (stretch_start & l_state)
                    short_exit = short_exit | (stretch_start & s_state)

    # Fold the suppressed side's implicit exit into the exit mask BEFORE zeroing
    # its entry -- a stateful strategy can encode an exit as a transition ON an
    # entry mask; naively zeroing it would discard that exit.
    if mode == 'long_only':
        long_exit = long_exit | short_entry
        short_entry = np.zeros(n, bool)
    elif mode == 'short_only':
        short_exit = short_exit | long_entry
        long_entry = np.zeros(n, bool)

    # Entries first, so an entry wins wherever it overlaps an exit (flip
    # straight from long to short rather than via flat).
    raw = np.select([long_entry, short_entry, long_exit, short_exit], [1.0, -1.0, 0.0, 0.0], default=np.nan)
    signal = np.nan_to_num(_ffill(raw), nan=0.0)
    return raw, signal, valid_mask


def _regime_mask(df, regime_filter: SignalFn, regime_kwargs, report=None):
    '''build_regime -> (long_ok, short_ok, regime_valid) -- the part of
    _build_position()'s regime block that depends only on regime_kwargs, never
    on strategy_kwargs. sweep()'s fast path computes this once per DISTINCT
    regime combination and reuses it across every strategy combination in the
    grid (the mirror of _strategy_signal() above). Re-derives the persistent
    long_ok/short_ok permission state from build_regime's long_entry/
    short_entry/long_exit/short_exit transitions via _state_from_edges().

    build_regime is called with a COPY of `df`, for the same reason
    _strategy_signal() copies before calling `strategy` -- see that
    function's docstring.

    report: see _strategy_signal()'s docstring -- same optional out-param,
    filled with this hook's own invalid-bar diagnostics.
    '''
    regime_kwargs = regime_kwargs or {}
    ret = regime_filter(df.copy(), **regime_kwargs)
    out = _adapt_signal_df(ret, 'build_regime', report=report)
    n = len(df)
    long_entry = np.asarray(out.long_entry, dtype=bool)
    short_entry = np.asarray(out.short_entry, dtype=bool)
    long_exit = np.asarray(out.long_exit, dtype=bool)
    short_exit = np.asarray(out.short_exit, dtype=bool)
    for name, arr in (('long_entry', long_entry), ('short_entry', short_entry),
                      ('long_exit', long_exit), ('short_exit', short_exit)):
        if len(arr) != n:
            raise ValueError(f'regime output {name!r} length must match df')
    long_ok = _state_from_edges(long_entry, long_exit)
    short_ok = _state_from_edges(short_entry, short_exit)
    regime_valid = np.ones(n, dtype=bool) if out.valid is None else np.asarray(out.valid, dtype=bool)
    # Defense in depth -- see the identical comment in _strategy_signal().
    if len(regime_valid) != n:
        raise ValueError("regime output 'valid' length must match df")
    _check_warmup_blind_spot(regime_filter, regime_valid, 'build_regime')
    if report is not None:
        report['entries_suppressed'] = {
            'long': int((long_ok & ~regime_valid).sum()),
            'short': int((short_ok & ~regime_valid).sum()),
        }
    # Never let an invalid/warmup bar grant permission -- signal/pos are
    # stateful over the FULL array, so a bogus permission here could open a
    # position that persists into valid rows.
    long_ok = long_ok & regime_valid
    short_ok = short_ok & regime_valid
    return long_ok, short_ok, regime_valid


def _apply_regime_overlay(raw, signal, valid_mask, long_ok, short_ok, regime_valid):
    '''Cross-combine one strategy's pass-1 (raw, signal, valid_mask) with one
    regime's (long_ok, short_ok, regime_valid) -- the one part of the
    strategy/regime cross product that's genuinely different per (strategy,
    regime) PAIR, so unlike _strategy_signal()/_regime_mask() it can't be
    hoisted out of sweep()'s per-cell loop. Mirrors _build_position()'s old
    inline regime block exactly (one pass suffices: the only value ever
    written is 0.0, never hostile).
    '''
    hostile = ((signal > 0) & ~long_ok) | ((signal < 0) & ~short_ok)
    raw2 = np.where(hostile, 0.0, raw)
    signal2 = np.nan_to_num(_ffill(raw2), nan=0.0)
    valid_mask2 = valid_mask & regime_valid
    return signal2, valid_mask2


# ---- from engine.py: the lab's position logic. NOT used to trade (Forge fills
# and stops are engine/core.py); kept as the reference tests/test_signal_adapter.py
# compares Forge's traded position against. ----

def _apply_stops(target, close, high, low, stop_loss, take_profit, max_hold=None):
    '''Close a position early when its stop/target is touched, or once it has
    been held max_hold bars. Path dependent (the one sequential loop here);
    levels are fractions of the entry price.

    Touched bar is still held (intrabar exit), flat from the next; stays flat
    until the signal asks for something different; both levels hit the same
    bar -> the stop wins (pessimistic), and a stop/target touched on the bar
    the cap is reached wins over the cap.

    max_hold (None, or bars >= 1 -- see normalize_max_hold()) counts from the
    first bar the (lagged) target is non-zero: that bar is hold-bar 1, the cap
    fires on hold-bar max_hold, so the position is held exactly max_hold bars.
    The count restarts on a side flip and after going flat, and it runs on this
    unfiltered path, so a bar a time_filter or an invalid-data stretch later
    drops from the stats still counts.
    '''
    n = len(target)
    prev_close = np.r_[np.nan, close[:-1]]
    pos = np.zeros(n)
    gross = np.zeros(n)
    exit_type = np.full(n, '', dtype=object)

    held = 0.0
    entry = np.nan
    blocked = np.nan
    held_bars = 0

    for i in range(n):
        tgt = target[i]
        if tgt != blocked:
            blocked = np.nan
        want = 0.0 if tgt == blocked else tgt

        if want == 0.0:
            held, entry, held_bars = 0.0, np.nan, 0
            continue

        if want != held:
            held, entry, held_bars = want, prev_close[i], 1
        else:
            held_bars += 1

        pos[i] = held

        up = held * (high[i] / entry - 1.0)
        dn = held * (low[i] / entry - 1.0)
        best, worst = max(up, dn), min(up, dn)

        hit_stop = stop_loss is not None and worst <= -stop_loss
        hit_target = take_profit is not None and best >= take_profit

        if hit_stop or hit_target:
            level = -stop_loss if hit_stop else take_profit
            exit_price = entry * (1.0 + held * level)
            gross[i] = held * (exit_price / prev_close[i] - 1.0)
            exit_type[i] = 'stop' if hit_stop else 'target'
            blocked, held, entry = tgt, 0.0, np.nan
        elif max_hold is not None and held_bars >= max_hold:
            # Exits at this bar's close, like a signal exit: the whole bar is earned.
            gross[i] = held * (close[i] / prev_close[i] - 1.0)
            exit_type[i] = 'max_hold'
            blocked, held, entry = tgt, 0.0, np.nan
        else:
            gross[i] = held * (close[i] / prev_close[i] - 1.0)

    return pos, gross, exit_type


def _position_from_signal(signal, close, high, low, pct_chg, lag, stop_loss, take_profit, max_hold=None):
    '''signal -> traded position -> pnl_gross -- the lag-shift/stops tail of
    _build_position(), applied AFTER any regime overlay. Shared by
    run_backtest() (via _build_position()) and sweep()'s fast path (called
    directly per cell, post regime overlay, since lag/stops/max_hold can vary
    per cell even when the strategy/regime signal doesn't). max_hold is
    normalized here, the one choke point both paths share.
    '''
    n = len(signal)
    pos = np.empty(n)
    pos[:lag] = 0.0
    pos[lag:] = signal[:n - lag]

    max_hold = normalize_max_hold(max_hold)
    # pnl_gross lives on the UNFILTERED history -- the stop loop is path
    # dependent and needs rows a time_filter would drop.
    use_stops = stop_loss is not None or take_profit is not None or max_hold is not None
    exit_type = None
    if use_stops:
        pos, pnl_gross, exit_type = _apply_stops(pos, close, high, low, stop_loss, take_profit, max_hold)
    else:
        pnl_gross = pos * pct_chg

    return pos, pnl_gross, exit_type
