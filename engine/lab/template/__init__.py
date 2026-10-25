"""Ready-made SignalFn templates -- one file per template, all plain
functions (no namespace class; see webapp/CLAUDE.md for why). Import from
`tool.engine` (the shim uploaded strategy source uses) or this package
directly: `from tool.engine import abv_blw_zscore, allow_quantile`.

Naming: an `allow_` prefix marks a PERMISSION template -- safe ONLY as
build_regime, never build_signal (see allow_quantile's own docstring for
why: its long_entry/short_entry can be identical, which build_signal's
np.select collapse would silently turn into an always-long strategy). Every
other template's long_entry/short_entry are complementary, so it's safe as
either hook.
"""
from .abv_blw_dev import abv_blw_dev
from .abv_blw_ma import abv_blw_ma
from .abv_blw_zscore import abv_blw_zscore
from .allow_quantile import allow_quantile
from .donchian_breakout import donchian_breakout
from .ma_crossover import ma_crossover

__all__ = [
    'abv_blw_dev', 'abv_blw_ma', 'abv_blw_zscore', 'allow_quantile',
    'donchian_breakout', 'ma_crossover',
]
