"""Shared trading engine: one strategy interface for backtest, paper and live.

Every bot lives in bots/<name>/ with:
  strategy.py   a single Strategy subclass (the only code a submitter writes)
  config.json   symbol, exchange, timeframe, size, leverage, params, risk
  hypothesis.md the idea being tested and what would prove it wrong
"""

from .strategy import Context, Order, Position, Strategy  # noqa: F401

__version__ = "1.0.0"
