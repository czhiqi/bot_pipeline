"""Incremental indicators shared by backtest and live.

An indicator is created the first time a strategy asks for it and is seeded
from the candles the strategy can see (at most `lookback`, the same window the
live bot fetches). After that it updates once per closed candle. Backtest and
live therefore compute identical values from identical inputs. Keep periods
well under the lookback (period <= lookback / 6) so the seed has faded out;
an EMA150 seeded from only 200 candles is badly off (seen live on ZEC).

Higher timeframes (tf="4h" on a 1h bot) are built from the bot's own candles.
A higher-timeframe value only changes when that higher candle has closed.
"""

from __future__ import annotations

from collections import deque

from .timeframes import tf_ms

KEEP = 50  # past values kept per indicator for ema_prev(back=n)


class _EMA:
    def __init__(self, period: int):
        self.n = period
        self.alpha = 2 / (period + 1)
        self.seed: list = []
        self.value = None

    def push(self, c: dict):
        x = c["c"]
        if self.value is None:
            self.seed.append(x)
            if len(self.seed) >= self.n:
                self.value = sum(self.seed) / len(self.seed)
                self.seed = []
        else:
            self.value += self.alpha * (x - self.value)
        return self.value


class _RSI:
    """Wilder's RSI."""

    def __init__(self, period: int):
        self.n = period
        self.prev = None
        self.gains: list = []
        self.losses: list = []
        self.avg_g = None
        self.avg_l = None
        self.value = None

    def push(self, c: dict):
        x = c["c"]
        if self.prev is None:
            self.prev = x
            return None
        ch = x - self.prev
        self.prev = x
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if self.avg_g is None:
            self.gains.append(g)
            self.losses.append(l)
            if len(self.gains) >= self.n:
                self.avg_g = sum(self.gains) / self.n
                self.avg_l = sum(self.losses) / self.n
        else:
            self.avg_g = (self.avg_g * (self.n - 1) + g) / self.n
            self.avg_l = (self.avg_l * (self.n - 1) + l) / self.n
        if self.avg_g is not None:
            self.value = 100.0 if self.avg_l == 0 else 100 - 100 / (1 + self.avg_g / self.avg_l)
        return self.value


class _ATR:
    def __init__(self, period: int):
        self.n = period
        self.prev_c = None
        self.trs: list = []
        self.value = None

    def push(self, c: dict):
        tr = c["h"] - c["l"]
        if self.prev_c is not None:
            tr = max(tr, abs(c["h"] - self.prev_c), abs(c["l"] - self.prev_c))
        self.prev_c = c["c"]
        if self.value is None:
            self.trs.append(tr)
            if len(self.trs) >= self.n:
                self.value = sum(self.trs) / self.n
        else:
            self.value = (self.value * (self.n - 1) + tr) / self.n
        return self.value


KINDS = {"ema": _EMA, "rsi": _RSI, "atr": _ATR}


class Resampler:
    """Builds higher-timeframe candles from base candles. A bucket whose first
    base candle was not seen (start of the window) is dropped as partial."""

    def __init__(self, base_ms: int, htf_ms: int):
        if htf_ms % base_ms:
            raise ValueError("Higher timeframe must be a whole multiple of the bot timeframe")
        self.base = base_ms
        self.htf = htf_ms
        self.cur = None
        self.partial = True

    def push(self, c: dict):
        start = c["t"] - c["t"] % self.htf
        if self.cur is None or self.cur["t"] != start:
            self.partial = c["t"] != start
            self.cur = {"t": start, "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c.get("v", 0.0)}
        else:
            self.cur["h"] = max(self.cur["h"], c["h"])
            self.cur["l"] = min(self.cur["l"], c["l"])
            self.cur["c"] = c["c"]
            self.cur["v"] += c.get("v", 0.0)
        if c["t"] + self.base == start + self.htf:  # last base candle of the bucket
            done = None if self.partial else dict(self.cur)
            self.cur = None
            return done
        return None


class Indicators:
    def __init__(self, base_tf: str):
        self.base_tf = base_tf.lower()
        self.base_ms = tf_ms(base_tf)
        self.items: dict = {}  # key -> (indicator, deque of values)
        self.resamplers: dict = {}  # tf -> Resampler

    def update(self, candle: dict) -> None:
        """Called by the engine once per closed candle, before the strategy runs."""
        done = {self.base_tf: candle}
        for tf, r in self.resamplers.items():
            htf_candle = r.push(candle)
            if htf_candle is not None:
                done[tf] = htf_candle
        for (kind, period, tf), (ind, hist) in self.items.items():
            if tf in done:
                hist.append(ind.push(done[tf]))

    def get(self, kind: str, period: int, tf: str, window: list, back: int = 0):
        tf = tf.lower()
        key = (kind, int(period), tf)
        if key not in self.items:
            self._create(key, window)
        hist = self.items[key][1]
        if back >= len(hist):
            return None
        return hist[-1 - back]

    def _create(self, key, window: list) -> None:
        kind, period, tf = key
        if kind not in KINDS:
            raise ValueError(f"Unknown indicator {kind}")
        ind = KINDS[kind](period)
        hist: deque = deque(maxlen=KEEP)
        if tf == self.base_tf:
            for c in window:
                hist.append(ind.push(c))
        else:
            # Seed from the visible window with a new resampler. If this timeframe is
            # new, that resampler (now caught up to the current candle) is kept.
            seeder = Resampler(self.base_ms, tf_ms(tf))
            for c in window:
                htf_candle = seeder.push(c)
                if htf_candle is not None:
                    hist.append(ind.push(htf_candle))
            self.resamplers.setdefault(tf, seeder)
        self.items[key] = (ind, hist)
