"""Run a research-lab strategy (vectorized `build_signal`) as a Forge bot.

A lab strategy is a class with SYMBOL / TIMEFRAME / DATASET / PARAMS and a
`build_signal(df, **params)` returning `long_entry` / `short_entry` (and
optionally `long_exit` / `short_exit`) columns, optionally `build_regime` and
`build_data`. The lab file goes into bots/<name>/strategy.py unchanged;
engine/loader.py wraps it in SignalStrategy.

Each closed candle:
  1. the lab's own signal code (engine/lab/signal.py, copied verbatim) turns the
     candle window into the lab's target position: +1 long, -1 short, 0 flat,
     including its forward-filled state machine, warmup gating and regime overlay
  2. `lag` is applied like the lab does (target decided on bar t is held from
     bar t+lag; Forge fills at the next open, so lag 1 = the next candle)
  3. orders move the position to the target

Exits that are not the signal's (stop-loss, take-profit from config risk,
max_hold from params) block re-entry until the signal changes, as in the lab's
_apply_stops(). Differences from the lab's backtest, by design: fills are at
the next open with Forge's fees and slippage (the lab books the close), and the
stop/target are measured from the fill price.

config.json params for a lab bot:
  {"qty": 0.001, "mode": "long_short", "lag": 1, "on_missing_data": "hold",
   "signal": {...build_signal kwargs, max_hold optional...},
   "regime": {...build_regime kwargs...}}
"""
from __future__ import annotations

import pandas as pd

from .lab.primitive import NAFrame
from .lab.signal import (
    _apply_regime_overlay, _regime_mask, _strategy_signal, call_build_data, normalize_max_hold,
)
from .strategy import Order, Strategy
from .timeframes import tf_ms

LAB_REQUIRED = ("SYMBOL", "TIMEFRAME", "DATASET", "PARAMS")
MODES = ("long_only", "short_only", "long_short")


def is_lab_strategy(obj) -> bool:
    return isinstance(obj, type) and all(hasattr(obj, a) for a in LAB_REQUIRED) and callable(getattr(obj, "build_signal", None))


def candles_to_frame(candles: list) -> NAFrame:
    """The lab's input shape: naive-UTC DatetimeIndex named 'datetime', columns
    open/high/low/close/volume, as an NAFrame (nullable dtypes on assignment)."""
    df = pd.DataFrame(
        {
            "open": [c["o"] for c in candles],
            "high": [c["h"] for c in candles],
            "low": [c["l"] for c in candles],
            "close": [c["c"] for c in candles],
            "volume": [c.get("v", 0.0) for c in candles],
        },
        index=pd.to_datetime([c["t"] for c in candles], unit="ms"),
    )
    df.index.name = "datetime"
    return NAFrame(df)


class SignalStrategy(Strategy):
    name = "lab-signal"

    def __init__(self, lab_cls, params: dict | None = None, timeframe: str = "1h"):
        if not is_lab_strategy(lab_cls):
            raise TypeError("not a lab strategy class (needs SYMBOL, TIMEFRAME, DATASET, PARAMS, build_signal)")
        if lab_cls.DATASET:
            raise ValueError(
                f"{lab_cls.__name__} needs feature datasets {list(lab_cls.DATASET)}; a Forge bot only receives the "
                "exchange's OHLCV candles, so only lab strategies with DATASET = [] can be deployed"
            )
        super().__init__(params)
        p = self.params
        self.lab_cls = lab_cls
        self.tf_ms = tf_ms(timeframe)
        self.mode = p.get("mode", "long_short")
        if self.mode not in MODES:
            raise ValueError(f"params.mode must be one of {MODES}")
        self.lag = int(p.get("lag", 1))
        if self.lag < 1:
            raise ValueError("params.lag must be >= 1 (lag 0 would trade on the same candle the signal is computed from)")
        self.on_missing = p.get("on_missing_data", "hold")
        signal = dict(p.get("signal") or {})
        self.max_hold = normalize_max_hold(signal.pop("max_hold", None))
        signal.pop("lag", None)  # engine-routed in the lab, never a build_signal kwarg
        self.signal_kwargs = signal
        self.has_regime = callable(getattr(lab_cls, "build_regime", None))
        self.regime_kwargs = dict(p.get("regime") or {}) if self.has_regime else None
        if float(p.get("qty", 0)) <= 0:
            raise ValueError("params.qty must be > 0")
        self._precomputed: dict | None = None

    def warmup(self) -> int:
        return self.lag + 1

    # --- the lab's signal ------------------------------------------------------
    def signals(self, candles: list):
        """Lab target position (+1/-1/0) for every candle in `candles`."""
        df = call_build_data(self.lab_cls, candles_to_frame(candles))
        raw, signal, valid = _strategy_signal(df, self.lab_cls.build_signal, self.signal_kwargs, self.mode, self.on_missing)
        if self.has_regime:
            long_ok, short_ok, regime_valid = _regime_mask(df, self.lab_cls.build_regime, self.regime_kwargs)
            signal, valid = _apply_regime_overlay(raw, signal, valid, long_ok, short_ok, regime_valid)
        return signal

    def prepare(self, candles: list) -> None:
        sig = self.signals(candles)
        k = self.lag - 1
        self._precomputed = {c["t"]: (float(sig[i - k]) if i - k >= 0 else 0.0) for i, c in enumerate(candles)}

    def target(self, ctx) -> float:
        if self._precomputed is not None and ctx.time in self._precomputed:
            return self._precomputed[ctx.time]
        sig = self.signals(ctx.candles)
        k = self.lag - 1
        return float(sig[-1 - k]) if len(sig) > k else 0.0

    # --- position management -----------------------------------------------------
    def on_candle(self, ctx):
        tgt = self.target(ctx)
        st = ctx.state
        pos = ctx.position
        held = 0.0 if pos.is_flat else (1.0 if pos.side == "long" else -1.0)

        blocked = st.get("blocked")
        # We expected to be in a position but are flat, and we never asked to
        # close: a stop-loss / take-profit (or the risk guard) took us out. Like
        # the lab, stay out until the signal asks for something different.
        if st.get("expect", 0.0) != 0.0 and held == 0.0:
            blocked = st.get("expect_tgt")
        if blocked is not None and tgt != blocked:
            blocked = None
        want = 0.0 if (blocked is not None and tgt == blocked) else tgt

        out = []
        if want != 0.0 and held == want and self.max_hold is not None:
            held_bars = (ctx.time - pos.opened_at) // self.tf_ms + 1
            if held_bars >= self.max_hold:
                out.append(Order("close", reason=f"max_hold {self.max_hold}"))
                blocked, want = tgt, 0.0
        if not out and want != held:
            if want == 0.0:
                out.append(Order("close", reason="signal flat"))
            else:
                side = "buy" if want > 0 else "sell"
                out.append(Order(side, float(self.params["qty"]), reason="signal long" if want > 0 else "signal short"))
        st["blocked"] = blocked
        st["expect"] = want
        st["expect_tgt"] = tgt
        return out
