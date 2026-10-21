"""The strategy interface. A bot's strategy.py defines exactly one subclass of Strategy.

The engine calls on_candle() once per CLOSED candle of the bot's timeframe, in
backtest, paper and live alike. Orders returned there are executed at market
right after the close (the backtest fills them at the next candle's open, with
slippage and fees). Stop-losses, size caps, daily loss limits and the kill
switch are applied by the engine from config.json "risk", not by the strategy.

Actions:
  Order("buy", qty)   open or add to a long; while short, closes the short and opens a long
  Order("sell", qty)  open or add to a short; while long, closes the long and opens a short
  Order("close")      close the whole position
qty is in base units (e.g. ETH). Use ctx.params["qty"] for the configured size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ACTIONS = ("buy", "sell", "close")


@dataclass(frozen=True)
class Order:
    action: str
    qty: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"Order action must be one of {ACTIONS}, got {self.action!r}")
        if self.action != "close" and not (self.qty > 0):
            raise ValueError("buy/sell orders need qty > 0")


@dataclass
class Position:
    side: str = "flat"  # "long" | "short" | "flat"
    qty: float = 0.0
    avg_price: float = 0.0
    entries: int = 0
    opened_at: int = 0  # ms timestamp of the first fill

    @property
    def is_flat(self) -> bool:
        return self.side == "flat" or self.qty <= 0

    def unrealized(self, price: float) -> float:
        if self.is_flat:
            return 0.0
        sign = 1 if self.side == "long" else -1
        return sign * (price - self.avg_price) * self.qty

    def pnl_pct(self, price: float) -> float:
        """Price move in % from the average entry, positive when in profit."""
        if self.is_flat or self.avg_price <= 0:
            return 0.0
        sign = 1 if self.side == "long" else -1
        return sign * (price / self.avg_price - 1) * 100

    def copy(self) -> "Position":
        return Position(self.side, self.qty, self.avg_price, self.entries, self.opened_at)


@dataclass
class Context:
    """What a strategy sees on each closed candle (read-only except `state`)."""

    candles: list  # closed candles, oldest first: dicts with t, o, h, l, c, v (at most `lookback`)
    position: Position
    params: dict
    equity: float
    state: dict = field(default_factory=dict)  # free scratch space, kept between candles
    _ind: Any = None
    _tf: str = "1h"

    @property
    def candle(self) -> dict:
        return self.candles[-1]

    @property
    def close(self) -> float:
        return self.candles[-1]["c"]

    @property
    def time(self) -> int:
        return self.candles[-1]["t"]

    def closes(self, n: int | None = None) -> list:
        src = self.candles if n is None else self.candles[-n:]
        return [c["c"] for c in src]

    # Incremental indicators. Same values in backtest and live (see engine/indicators.py).
    def ema(self, period: int, tf: str | None = None) -> float | None:
        return self._ind.get("ema", period, tf or self._tf, self.candles)

    def ema_prev(self, period: int, tf: str | None = None, back: int = 1) -> float | None:
        return self._ind.get("ema", period, tf or self._tf, self.candles, back=back)

    def rsi(self, period: int = 14, tf: str | None = None) -> float | None:
        return self._ind.get("rsi", period, tf or self._tf, self.candles)

    def atr(self, period: int = 14, tf: str | None = None) -> float | None:
        return self._ind.get("atr", period, tf or self._tf, self.candles)


class Strategy:
    """Base class. Override default_params, warmup() and on_candle()."""

    name = "strategy"
    default_params: dict = {}

    def __init__(self, params: dict | None = None) -> None:
        self.params = {**self.default_params, **(params or {})}

    def warmup(self) -> int:
        """Closed candles needed before on_candle() is first called."""
        return 1

    def on_candle(self, ctx: Context) -> list:
        raise NotImplementedError
