"""Engine tests. Run: python -m unittest discover -s tests -v"""

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.config import PIPELINE_DEFAULTS, load_bot_config  # noqa: E402
from engine.core import Engine, RiskGuard, SimBroker  # noqa: E402
from engine.data import data_path, write_csv  # noqa: E402
from engine.indicators import Indicators, Resampler  # noqa: E402
from engine.pipeline import evaluate, parity  # noqa: E402
from engine.sandbox_check import check_source  # noqa: E402
from engine.strategy import Order, Position, Strategy  # noqa: E402
from engine.timeframes import tf_ms  # noqa: E402

EXAMPLE = ROOT / "bots" / "example-ema-flip"


def synthetic(n: int, tf: str = "1h", seed: int = 7, end_ms: int | None = None) -> list:
    """Random walk with alternating trends, ending at end_ms."""
    rng = random.Random(seed)
    step = tf_ms(tf)
    end_ms = end_ms or (int(time.time() * 1000) // step) * step - step
    t = end_ms - (n - 1) * step
    price, out = 30000.0, []
    drift = 0.0
    for i in range(n):
        if i % 300 == 0:
            drift = rng.choice([-1, 1]) * rng.uniform(0.0003, 0.0015)
        o = price
        c = o * math.exp(drift + rng.gauss(0, 0.006))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.002)))
        l = min(o, c) * (1 - abs(rng.gauss(0, 0.002)))
        out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": 1.0})
        price, t = c, t + step
    return out


def ema_list(xs, n):
    a, v, out = 2 / (n + 1), None, []
    for i, x in enumerate(xs):
        if i + 1 < n:
            out.append(None)
            continue
        v = sum(xs[: n]) / n if v is None else v + a * (x - v)
        out.append(v)
    return out


class TestIndicators(unittest.TestCase):
    def test_ema_matches_list(self):
        cs = synthetic(400)
        ind = Indicators("1h")
        got = ind.get("ema", 50, "1h", cs)
        self.assertAlmostEqual(got, ema_list([c["c"] for c in cs], 50)[-1], places=8)

    def test_resampler_drops_partial_bucket(self):
        cs = synthetic(20, "1h", end_ms=4 * 3_600_000 * 100 + 2 * 3_600_000)
        r = Resampler(tf_ms("1h"), tf_ms("4h"))
        done = [x for x in (r.push(c) for c in cs) if x]
        for d in done:
            self.assertEqual(d["t"] % tf_ms("4h"), 0)
        first_full = next(c for c in cs if c["t"] % tf_ms("4h") == 0)
        self.assertEqual(done[0]["t"], first_full["t"])

    def test_htf_value_only_changes_on_htf_close(self):
        cs = synthetic(600)
        ind = Indicators("1h")
        vals = []
        for i in range(400, 600):
            ind.update(cs[i]) if i > 400 else None
            vals.append((cs[i]["t"], ind.get("ema", 20, "4h", cs[: i + 1][-400:])))
        changes = [t for (t, v), (_, pv) in zip(vals[1:], vals) if v != pv]
        for t in changes:
            self.assertEqual((t + tf_ms("1h")) % tf_ms("4h"), 0)


class TestSandbox(unittest.TestCase):
    def test_example_passes(self):
        self.assertEqual(check_source((EXAMPLE / "strategy.py").read_text()), [])

    def test_blocks_dangerous_code(self):
        bad = {
            "import os\nfrom engine import Strategy\nclass S(Strategy): pass": "import os",
            "from engine import Strategy\nclass S(Strategy):\n  def on_candle(self, c): open('x')": "open",
            "from engine import Strategy\nclass S(Strategy):\n  x = ().__class__": "__class__",
            "from engine import Strategy\nimport subprocess\nclass S(Strategy): pass": "subprocess",
            "from engine import Strategy\nclass S(Strategy):\n  def f(self): eval('1')": "eval",
            "class S: pass": "exactly one",
        }
        for src, word in bad.items():
            problems = check_source(src)
            self.assertTrue(problems and any(word in p for p in problems), (src, problems))


class TestRiskAndBroker(unittest.TestCase):
    risk = {"stop_loss_pct": 2, "max_position_qty": 0.05, "max_entries": 2, "daily_loss_limit_usdt": 10}

    def test_caps_and_entries(self):
        g = RiskGuard(self.risk)
        out = g.filter([Order("buy", 0.03), Order("buy", 0.03), Order("buy", 0.01)], Position(), 0, 0.0)
        self.assertEqual([(o.action, round(o.qty, 6)) for o in out], [("buy", 0.03), ("buy", 0.02)])

    def test_daily_limit_blocks_entries_not_closes(self):
        g = RiskGuard(self.risk)
        pos = Position("long", 0.01, 100, 1, 0)
        out = g.filter([Order("close"), Order("sell", 0.01)], pos, 0, -12.0)
        self.assertEqual([o.action for o in out], ["close"])

    def test_flip_emits_close_first(self):
        g = RiskGuard(self.risk)
        out = g.filter([Order("sell", 0.01)], Position("long", 0.01, 100, 1, 0), 0, 0.0)
        self.assertEqual([o.action for o in out], ["close", "sell"])

    def test_stop_loss_fill_and_gap(self):
        b = SimBroker({"taker_fee_pct": 0, "slippage_pct": 0}, RiskGuard(self.risk), 3)
        b.submit([Order("buy", 0.01)], None)
        b.on_candle({"t": 1, "o": 100, "h": 101, "l": 99, "c": 100})
        b.on_candle({"t": 2, "o": 99, "h": 99.5, "l": 97, "c": 98})  # stop at 98
        self.assertEqual(b.trades[-1]["reason"], "stop-loss")
        self.assertAlmostEqual(b.trades[-1]["exit_price"], 98.0)
        b.submit([Order("buy", 0.01)], None)
        b.on_candle({"t": 3, "o": 100, "h": 100, "l": 100, "c": 100})
        b.on_candle({"t": 4, "o": 90, "h": 91, "l": 89, "c": 90})  # gap through the stop: filled at the open
        self.assertAlmostEqual(b.trades[-1]["exit_price"], 90.0)

    def test_fees_and_slippage(self):
        b = SimBroker({"taker_fee_pct": 0.1, "slippage_pct": 0.1}, RiskGuard({**self.risk, "stop_loss_pct": 0}), 3)
        b.submit([Order("buy", 1)], None)
        b.on_candle({"t": 1, "o": 100, "h": 100, "l": 100, "c": 100})
        b.submit([Order("close")], None)
        b.on_candle({"t": 2, "o": 100, "h": 100, "l": 100, "c": 100})
        tr = b.trades[0]
        self.assertAlmostEqual(tr["pnl"], (99.9 - 100.1) - 0.1001 - 0.0999, places=6)


CHASER_SRC = '''from engine import Order, Strategy


class Chaser(Strategy):
    """Trades often (adds, flips, closes) to stress parity."""

    default_params = {"qty": 0.01}

    def warmup(self):
        return 30

    def on_candle(self, ctx):
        f, s = ctx.ema(5), ctx.ema(20)
        h = ctx.ema(10, "4h")
        n = ctx.state.get("n", 0) + 1
        ctx.state["n"] = n
        if f is None or s is None:
            return []
        if ctx.position.is_flat:
            if h is not None and n % 3 == 0:
                return [Order("buy" if f > s else "sell", 0.01)]
            return []
        gain = ctx.position.pnl_pct(ctx.close)
        if gain > 2.0:
            return [Order("close", reason="take profit")]
        if gain > 0.6 and ctx.position.entries < 3:
            return [Order(ctx.position.side == "long" and "buy" or "sell", 0.01)]  # add
        if (ctx.position.side == "long") != (f > s):
            return [Order("sell" if f < s else "buy", 0.01, "flip")]
        return []
'''


class TestParity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _bot(self, src: str, cfg_over: dict) -> Path:
        d = self.tmp / "bots" / "t"
        d.mkdir(parents=True)
        (d / "strategy.py").write_text(src)
        cfg = json.loads((EXAMPLE / "config.json").read_text())
        cfg.update(cfg_over)
        (d / "config.json").write_text(json.dumps(cfg))
        (d / "hypothesis.md").write_text("# test\n")
        return d

    def test_example_parity(self):
        d = self._bot((EXAMPLE / "strategy.py").read_text(), {"timeframe": "1h", "lookback": 400, "params": {"qty": 0.001, "fast": 20, "slow": 50, "slope_bars": 3, "direction": "auto", "trend_tf": "4h"}})
        cfg = load_bot_config(d)
        same, detail = parity(d, cfg, synthetic(3000), cfg["costs"])
        self.assertTrue(same, detail)
        self.assertNotIn(" 0 trades", detail)

    def test_busy_strategy_parity(self):
        src = CHASER_SRC
        d = self._bot(src, {"timeframe": "1h", "lookback": 300, "risk": {"stop_loss_pct": 3, "max_position_qty": 0.03, "max_entries": 3, "daily_loss_limit_usdt": 5}})
        cfg = load_bot_config(d)
        same, detail = parity(d, cfg, synthetic(2500, seed=3), cfg["costs"])
        self.assertTrue(same, detail)
        self.assertGreater(int(detail.split()[0]), 50, detail)

    def test_pipeline_report(self):
        d = self._bot((EXAMPLE / "strategy.py").read_text(), {"timeframe": "1h", "lookback": 400, "params": {"qty": 0.001, "fast": 20, "slow": 50, "slope_bars": 3, "direction": "auto", "trend_tf": ""}, "backtest": {"months": 12, "start_equity": 1000}})
        cfg = load_bot_config(d)
        root = self.tmp / "data"
        write_csv(data_path(cfg["exchange"], cfg["symbol"], cfg["timeframe"], root), synthetic(8000, seed=11))
        rules = dict(PIPELINE_DEFAULTS, parity_candles=800)
        r = evaluate(d, rules, [], allow_download=False, data_root=root)
        ids = [g["id"] for g in r["gates"]]
        self.assertEqual(ids[:7], ["scope", "files", "config", "code", "risk", "data", "backtest"])
        status = {g["id"]: g["status"] for g in r["gates"]}
        self.assertEqual(status["backtest"], "pass")
        self.assertEqual(status["parity"], "pass", r["gates"])
        self.assertIn("out_of_sample", r)
        r2 = evaluate(d, rules, ["engine/core.py"], allow_download=False, data_root=root)
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["gates"][0]["status"], "fail")

    def test_risk_gate_rejects_stop_past_liquidation(self):
        d = self._bot((EXAMPLE / "strategy.py").read_text(), {"leverage": 5, "risk": {"stop_loss_pct": 19, "max_position_qty": 0.001, "max_entries": 1}})
        r = evaluate(d, dict(PIPELINE_DEFAULTS), [], allow_download=False, data_root=self.tmp / "nodata")
        g = {x["id"]: x for x in r["gates"]}
        self.assertEqual(g["risk"]["status"], "fail")
        self.assertEqual(g["data"]["status"], "skip")


class TestLiveRunnerRestart(unittest.TestCase):
    def test_restart_keeps_paper_position(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            d = tmp / "bot"
            shutil.copytree(EXAMPLE, d)
            cfg = load_bot_config(d)
            cfg["lookback"] = 300
            cfg["timeframe"] = "1h"
            cfg["params"].update({"fast": 10, "slow": 30, "slope_bars": 2, "direction": "auto"})
            from engine.live import LiveRunner

            cs = synthetic(1200, seed=5)
            mk = lambda: SimBroker(cfg["costs"], RiskGuard(cfg["risk"]), cfg["leverage"])  # noqa: E731
            r1 = LiveRunner(d, cfg, mk())
            for i in range(301, 900):
                r1.poll(cs[: i], cs[i - 1]["t"] + tf_ms("1h") + 1)
            saved = r1.broker.pos.copy()
            r2 = LiveRunner(d, cfg, mk())
            self.assertEqual((r2.broker.pos.side, r2.broker.pos.qty), (saved.side, saved.qty))
            self.assertEqual(r2.engine.state.get("last"), r1.engine.state.get("last"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class FakeExchange:
    """Just enough of ccxt for CcxtBroker."""

    def __init__(self):
        self.orders, self.cancelled, self.pos = [], [], None
        self.n = 0

    def load_markets(self):
        return {}

    def market(self, s):
        return {"contractSize": 0.01}  # 1 contract = 0.01 base

    def set_margin_mode(self, *a):
        pass

    def set_leverage(self, *a):
        pass

    def amount_to_precision(self, s, a):
        return f"{a:.0f}"

    def price_to_precision(self, s, p):
        return f"{p:.1f}"

    def fetch_positions(self, syms):
        return [self.pos] if self.pos else []

    def fetch_balance(self):
        return {"total": {"USDT": 500}}

    def cancel_order(self, oid, sym, params=None):
        self.cancelled.append(oid)

    def create_order(self, sym, typ, side, amount, price=None, params=None):
        params = params or {}
        self.n += 1
        self.orders.append((side, amount, params))
        if "stopLossPrice" not in params:
            c = float(amount)
            if params.get("reduceOnly"):
                self.pos = None
            elif self.pos is None:
                self.pos = {"symbol": sym, "side": "long" if side == "buy" else "short", "contracts": c, "entryPrice": 100.0}
            else:
                self.pos["contracts"] += c
                self.pos["entryPrice"] = 101.0
        return {"id": f"o{self.n}"}


class TestCcxtBroker(unittest.TestCase):
    def test_orders_stop_and_close(self):
        from engine.live import CcxtBroker

        ex = FakeExchange()
        cfg = load_bot_config(EXAMPLE)
        b = CcxtBroker(cfg, ex, RiskGuard({"stop_loss_pct": 5, "max_position_qty": 1, "max_entries": 3}))
        b.submit([Order("buy", 0.02)], {"t": 1, "c": 100})
        self.assertEqual(ex.orders[0], ("buy", 2.0, {}))  # 0.02 base / 0.01 contract size
        self.assertEqual((b.pos.side, round(b.pos.qty, 6)), ("long", 0.02))
        stop = ex.orders[1]
        self.assertEqual(stop[0], "sell")
        self.assertEqual(stop[2], {"stopLossPrice": 95.0, "reduceOnly": True})
        b.submit([Order("buy", 0.01)], {"t": 2, "c": 101})  # add -> stop re-placed for the new size/avg
        self.assertIn("o2", ex.cancelled)
        self.assertEqual(ex.orders[-1][2]["stopLossPrice"], 95.9)
        self.assertEqual(ex.orders[-1][1], 3.0)
        b.tick(96.0)  # above the stop: nothing
        n = len(ex.orders)
        b.tick(95.0)  # crossed: software stop closes at market
        self.assertEqual(ex.orders[n][2], {"reduceOnly": True})
        self.assertTrue(b.pos.is_flat)
        b.submit([Order("close")], {"t": 3, "c": 95})  # already flat: no order
        self.assertEqual(len(ex.orders), n + 1)
