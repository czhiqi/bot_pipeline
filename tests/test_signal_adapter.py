"""Research-lab strategies run as Forge bots (engine/signal_adapter.py).

The core check: bar by bar, the position a Forge bot holds equals the position
the lab's own engine computes for the same strategy and data (the lab's
_position_from_signal / _apply_stops are vendored in engine/lab/signal.py as
the reference). Candles are built with open == previous close and slippage 0,
so Forge's next-open fills and the lab's previous-close entries are the same
price and stop/target levels line up exactly.
"""

from __future__ import annotations

import json
import math
import random
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.backtest import run as run_backtest  # noqa: E402
from engine.config import PIPELINE_DEFAULTS, load_bot_config  # noqa: E402
from engine.data import data_path, write_csv  # noqa: E402
from engine.lab.signal import _position_from_signal  # noqa: E402
from engine.loader import build_strategy, load_strategy_class  # noqa: E402
from engine.pipeline import evaluate, parity  # noqa: E402
from engine.sandbox_check import check_source  # noqa: E402
from engine.signal_adapter import SignalStrategy  # noqa: E402
from engine.timeframes import tf_ms  # noqa: E402

DAY = tf_ms("1d")

ZSCORE = '''from tool.engine import FeatureScale


class ZscoreRevert:
    SYMBOL = ["btcusdt"]
    TIMEFRAME = "1d"
    DATASET = []
    PARAMS = {"window": {"min": 10, "max": 100, "step": 10}, "threshold": {"min": 0.5, "max": 3.0, "step": 0.5}}

    @staticmethod
    def build_signal(df, window, threshold):
        df["z"] = FeatureScale.zscore(df["close"], window)
        df["long_entry"] = df["z"] < -threshold
        df["short_entry"] = df["z"] > threshold
        return df
'''

DONCHIAN_WITH_REGIME = '''from tool.engine import donchian_breakout, abv_blw_ma


class Breakout:
    SYMBOL = ["ethusdt"]
    TIMEFRAME = "1d"
    DATASET = []
    PARAMS = {"entry_window": {"min": 10, "max": 60, "step": 5}, "exit_window": {"min": 5, "max": 30, "step": 5}}
    REGIME_PARAMS = {"regime_window": {"min": 20, "max": 200, "step": 20}}

    @staticmethod
    def build_signal(df, entry_window, exit_window):
        return donchian_breakout(df, entry_window=entry_window, exit_window=exit_window)

    @staticmethod
    def build_regime(df, regime_window):
        return abv_blw_ma(df, col="close", window=regime_window)
'''

LOOKAHEAD = '''class Peek:
    SYMBOL = ["btcusdt"]
    TIMEFRAME = "1d"
    DATASET = []
    PARAMS = {"window": {"min": 5, "max": 50, "step": 5}}

    @staticmethod
    def build_signal(df, window):
        df["fut"] = df["close"].shift(-1)
        df["long_entry"] = df["fut"] > df["close"]
        df["short_entry"] = df["fut"] < df["close"]
        return df
'''

EXPANDING = '''class VolRegime:
    SYMBOL = ["btcusdt"]
    TIMEFRAME = "1d"
    DATASET = []
    PARAMS = {"window": {"min": 10, "max": 100, "step": 10}}

    @staticmethod
    def build_signal(df, window):
        df["vol"] = df["close"].pct_change().rolling(window).std()
        df["long_entry"] = df["vol"] < df["vol"].expanding().median()
        df["short_entry"] = ~df["long_entry"]
        return df
'''

FEATURE = ZSCORE.replace('DATASET = []', 'DATASET = ["funding"]')


def candles(n: int, seed: int = 3, start_ms: int | None = None) -> list:
    """Daily candles with open == previous close (so lab and Forge entry prices match)."""
    rng = random.Random(seed)
    t = start_ms or (int(time.time() * 1000) // DAY) * DAY - n * DAY
    price, out, drift = 100.0, [], 0.0
    for i in range(n):
        if i % 120 == 0:
            drift = rng.choice([-1, 1]) * rng.uniform(0.0, 0.004)
        o = price
        c = o * math.exp(drift + rng.gauss(0, 0.025))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.01)))
        l = min(o, c) * (1 - abs(rng.gauss(0, 0.01)))
        out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": 1.0})
        price, t = c, t + DAY
    return out


class LabBot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bot(self, source: str, params: dict, risk: dict | None = None, lookback: int = 400, name: str = "lab") -> tuple:
        d = self.tmp / "bots" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "strategy.py").write_text(source)
        cfg = {
            "name": name, "exchange": "bitget", "symbol": "BTC/USDT:USDT", "timeframe": "1d", "lookback": lookback,
            "leverage": 2, "params": {"qty": 1.0, **params},
            "risk": {"stop_loss_pct": 0, "take_profit_pct": 0, "max_position_qty": 1.0, "max_entries": 1,
                     "daily_loss_limit_usdt": 0, **(risk or {})},
            "costs": {"taker_fee_pct": 0, "slippage_pct": 0},
            "backtest": {"months": 60, "start_equity": 1000},
        }
        (d / "config.json").write_text(json.dumps(cfg))
        (d / "hypothesis.md").write_text("# h\n")
        return d, load_bot_config(d)

    def forge_held(self, trades: list, cs: list) -> np.ndarray:
        """+1/-1/0 held during each candle, rebuilt from the trade list."""
        idx = {c["t"]: i for i, c in enumerate(cs)}
        held = np.zeros(len(cs))
        for tr in trades:
            a = idx[tr["entry_time"]]
            b = idx[tr["exit_time"]]
            intrabar = tr["reason"] in ("stop-loss", "take-profit", "open")
            held[a:b + 1 if intrabar else b] = 1.0 if tr["side"] == "long" else -1.0
        return held

    def lab_pos(self, d, cfg, cs, stop=None, target=None, max_hold=None):
        strat = build_strategy(d, cfg)
        sig = strat.signals(cs)
        c = np.array([x["c"] for x in cs])
        h = np.array([x["h"] for x in cs])
        lo = np.array([x["l"] for x in cs])
        pos, _, _ = _position_from_signal(sig, c, h, lo, np.r_[np.nan, c[1:] / c[:-1] - 1], 1, stop, target, max_hold)
        return pos

    def compare(self, d, cfg, cs, **lab_kwargs):
        res = run_backtest(str(d), cfg, cs)
        trades = res["trades"] + ([] if res["open_position"].is_flat else [{
            "side": res["open_position"].side, "entry_time": res["open_position"].opened_at,
            "exit_time": cs[-1]["t"], "reason": "open", }])
        forge = self.forge_held(trades, cs)
        lab = self.lab_pos(d, cfg, cs, **lab_kwargs)
        lb = cfg["lookback"]
        # Forge trades from candle lookback+1 on (its first decision is on candle lookback).
        lab[: lb + 1] = 0.0
        # the lab may be mid-position when Forge starts; skip until both are flat once
        start = next(i for i in range(lb + 1, len(cs)) if lab[i] == 0 and forge[i] == 0)
        mismatch = np.nonzero(forge[start:] != lab[start:])[0]
        self.assertEqual(len(mismatch), 0, f"first mismatch at candle {start + mismatch[0] if len(mismatch) else '-'}: "
                                           f"forge {forge[start + mismatch[0]] if len(mismatch) else ''} "
                                           f"lab {lab[start + mismatch[0]] if len(mismatch) else ''}")
        return len(res["trades"])

    # --- tests --------------------------------------------------------------------
    def test_loads_lab_file_with_tool_engine_import(self):
        d, cfg = self.bot(ZSCORE, {"signal": {"window": 20, "threshold": 1.0}})
        self.assertEqual(load_strategy_class(d).__name__, "ZscoreRevert")
        self.assertIsInstance(build_strategy(d, cfg), SignalStrategy)
        self.assertEqual(check_source(ZSCORE), [])

    def test_same_position_as_lab_long_short(self):
        d, cfg = self.bot(ZSCORE, {"mode": "long_short", "signal": {"window": 20, "threshold": 1.0}})
        n = self.compare(d, cfg, candles(1600))
        self.assertGreater(n, 20)

    def test_same_position_as_lab_long_only(self):
        d, cfg = self.bot(ZSCORE, {"mode": "long_only", "signal": {"window": 30, "threshold": 0.8}})
        self.assertGreater(self.compare(d, cfg, candles(1600, seed=9)), 10)

    def test_same_position_with_stop_target_and_max_hold(self):
        d, cfg = self.bot(
            ZSCORE, {"signal": {"window": 20, "threshold": 0.7, "max_hold": 6}},
            risk={"stop_loss_pct": 4, "take_profit_pct": 6},
        )
        cs = candles(1800, seed=5)
        n = self.compare(d, cfg, cs, stop=0.04, target=0.06, max_hold=6)
        res = run_backtest(str(d), cfg, cs)
        reasons = {t["reason"] for t in res["trades"]}
        self.assertTrue({"stop-loss", "take-profit"} <= reasons, reasons)
        self.assertTrue(any(r.startswith("max_hold") for r in reasons), reasons)
        self.assertGreater(n, 30)

    def test_same_position_edge_form_with_regime(self):
        d, cfg = self.bot(DONCHIAN_WITH_REGIME, {"signal": {"entry_window": 20, "exit_window": 10},
                                                 "regime": {"regime_window": 60}})
        self.assertGreater(self.compare(d, cfg, candles(1600, seed=11)), 5)

    def test_parity_live_window_equals_backtest(self):
        d, cfg = self.bot(ZSCORE, {"signal": {"window": 20, "threshold": 1.0}}, lookback=300)
        t0 = time.time()
        same, detail = parity(d, cfg, candles(300 + 400), cfg["costs"])
        self.assertTrue(same, detail)
        self.assertNotIn(" 0 trades", detail)
        self.assertLess(time.time() - t0, 60, "parity replay too slow")

    def test_parity_catches_look_ahead(self):
        d, cfg = self.bot(LOOKAHEAD, {"signal": {"window": 5}}, lookback=200)
        same, detail = parity(d, cfg, candles(200 + 300), cfg["costs"])
        self.assertFalse(same, "a strategy reading the next candle must fail the live = backtest gate")

    def test_parity_catches_full_history_dependence(self):
        # .expanding() sees all history in the backtest but only `lookback` candles live
        d, cfg = self.bot(EXPANDING, {"signal": {"window": 20}}, lookback=150)
        same, _ = parity(d, cfg, candles(150 + 600, seed=4), cfg["costs"])
        self.assertFalse(same)

    def test_feature_dataset_strategy_rejected(self):
        d, cfg = self.bot(FEATURE, {"signal": {"window": 20, "threshold": 1.0}})
        with self.assertRaisesRegex(ValueError, "feature datasets"):
            build_strategy(d, cfg)

    def test_lag_zero_rejected(self):
        d, cfg = self.bot(ZSCORE, {"lag": 0, "signal": {"window": 20, "threshold": 1.0}})
        with self.assertRaisesRegex(ValueError, "lag"):
            build_strategy(d, cfg)

    def test_full_gates_on_lab_bot(self):
        d, cfg = self.bot(ZSCORE, {"signal": {"window": 20, "threshold": 1.0}},
                          risk={"stop_loss_pct": 8}, lookback=300)
        root = self.tmp / "data"
        write_csv(data_path(cfg["exchange"], cfg["symbol"], cfg["timeframe"], root), candles(2200, seed=2))
        r = evaluate(d, dict(PIPELINE_DEFAULTS, parity_candles=300, min_trades=5, min_trades_oos=1), [],
                     allow_download=False, data_root=root)
        status = {g["id"]: g["status"] for g in r["gates"]}
        for gid in ("scope", "files", "config", "code", "risk", "data", "backtest", "parity"):
            self.assertEqual(status[gid], "pass", (gid, r["gates"]))


if __name__ == "__main__":
    unittest.main()
