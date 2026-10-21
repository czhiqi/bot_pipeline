"""Live and paper runner. Started by run_bot.py.

Paper (default): real candles from the exchange, simulated fills (same SimBroker
as the backtest). Live: real market orders through ccxt, only when MODE=live AND
ALLOW_LIVE=true are both set in .env.

Every poll the runner fetches recent candles, keeps only CLOSED ones, and feeds
each new closed candle to the shared Engine. On start it loads exactly
`lookback` candles of history first, which is also how every backtest starts.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from pathlib import Path

from .core import Engine, RiskGuard, SimBroker, stop_price
from .loader import build_strategy
from .strategy import Position
from .timeframes import tf_ms

log = logging.getLogger("bot")


class LiveRunner:
    def __init__(self, bot_dir, cfg: dict, broker, persist: bool = True):
        self.bot_dir = Path(bot_dir)
        self.cfg = cfg
        self.broker = broker
        self.tf = tf_ms(cfg["timeframe"])
        self.lookback = int(cfg["lookback"])
        self.persist = persist
        self.kill_file = self.bot_dir / "KILL"
        self.engine = Engine(build_strategy(bot_dir, cfg), cfg, broker, kill_check=self.kill_file.exists)
        self.started = False
        self.state_file = self.bot_dir / "state.json"
        if persist:
            self._restore()

    # The core of the runner, kept free of network calls so tests can replay it.
    def poll(self, raw: list, now_ms: int) -> list:
        """raw: candles as returned by the exchange (may include the forming one,
        duplicates or gaps). Returns the times of candles processed."""
        closed = sorted({c["t"]: c for c in raw if c["t"] + self.tf <= now_ms}.values(), key=lambda c: c["t"])
        if not closed:
            return []
        done = []
        if not self.started:
            history = closed[:-1][-self.lookback :]
            if len(history) < self.lookback:
                log.warning("Only %d candles of history (lookback %d); indicators may differ from the backtest at first.", len(history), self.lookback)
            self.engine.warm(history)
            self.started = True
            closed = closed[-1:]
        for c in closed:
            if self.engine.last_t is not None and c["t"] <= self.engine.last_t:
                continue
            if self.engine.last_t is not None and c["t"] - self.engine.last_t > self.tf:
                log.warning("Gap in candles: %d missing before %s", (c["t"] - self.engine.last_t) // self.tf - 1, _fmt(c["t"]))
            orders = self.engine.on_closed_candle(c)
            done.append(c["t"])
            for o in orders:
                log.info("%s  %s %s %s", _fmt(c["t"]), o.action.upper(), o.qty or "", o.reason)
        if done and self.persist:
            self._save()
        return done

    def _save(self) -> None:
        data = {"last_t": self.engine.last_t, "strategy_state": _jsonable(self.engine.state)}
        if isinstance(self.broker, SimBroker):
            data["paper"] = self.broker.dump()
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.state_file)
        if isinstance(self.broker, SimBroker):
            self._append_trades()

    def _restore(self) -> None:
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("state.json unreadable, starting fresh")
            return
        self.engine.state.update(data.get("strategy_state") or {})
        if isinstance(self.broker, SimBroker) and data.get("paper"):
            self.broker.load(data["paper"])
            log.info("Paper position restored: %s", self.broker.pos)

    def _append_trades(self) -> None:
        trades = self.broker.trades
        if not trades:
            return
        path = self.bot_dir / "trades.csv"
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
            if new:
                w.writeheader()
            w.writerows(trades)
        trades.clear()


class CcxtBroker:
    """Real orders. Position, stop and balance come from the exchange."""

    def __init__(self, cfg: dict, exchange, risk: RiskGuard):
        self.cfg = cfg
        self.ex = exchange
        self.symbol = cfg["symbol"]
        self.risk = risk
        self.leverage = float(cfg["leverage"])
        self.pos = Position()
        self.last_price = 0.0
        self.stop_id = None
        self.stop_at = None
        self.day_pnl: dict = {}
        self.ex.load_markets()
        self.market = self.ex.market(self.symbol)
        self.contract_size = float(self.market.get("contractSize") or 1)
        try:
            self.ex.set_margin_mode(cfg["margin_mode"], self.symbol)
        except Exception as e:  # already set, or not supported
            log.info("set_margin_mode: %s", e)
        try:
            self.ex.set_leverage(int(self.leverage), self.symbol)
        except Exception as e:
            log.info("set_leverage: %s", e)
        self.sync()

    def sync(self) -> None:
        positions = self.ex.fetch_positions([self.symbol])
        p = next((x for x in positions if x.get("symbol") == self.symbol and float(x.get("contracts") or 0) > 0), None)
        if p is None:
            self.pos = Position()
            return
        qty = float(p["contracts"]) * self.contract_size
        entries = self.pos.entries if not self.pos.is_flat and self.pos.side == p["side"] else 1
        self.pos = Position(p["side"], qty, float(p.get("entryPrice") or 0), entries, self.pos.opened_at or int(time.time() * 1000))

    def position(self) -> Position:
        return self.pos.copy()

    def equity(self) -> float:
        try:
            bal = self.ex.fetch_balance()
            return float(bal.get("total", {}).get("USDT") or 0)
        except Exception:
            return 0.0

    def realized_today(self, now: int) -> float:
        return self.day_pnl.get(now // 86_400_000, 0.0)

    def mark(self, c: dict) -> None:
        self.last_price = c["c"]

    def on_candle(self, c: dict) -> None:
        self.last_price = c["c"]
        self.sync()
        self.ensure_stop()

    def tick(self, price: float) -> None:
        """Backup software stop, checked on every poll."""
        sp = stop_price(self.pos, self.risk.stop_loss_pct)
        if sp is None:
            return
        if (self.pos.side == "long" and price <= sp) or (self.pos.side == "short" and price >= sp):
            log.warning("Price %.6g crossed the stop %.6g; closing at market", price, sp)
            self._close_all("software stop")

    def submit(self, orders: list, candle: dict) -> None:
        for o in orders:
            if o.action == "close":
                self._close_all(o.reason or "strategy close")
                continue
            side = "buy" if o.action == "buy" else "sell"
            amount = float(self.ex.amount_to_precision(self.symbol, o.qty / self.contract_size))
            if amount <= 0:
                log.warning("Order size %s rounds to 0 on %s; skipped", o.qty, self.symbol)
                continue
            self.ex.create_order(self.symbol, "market", side, amount)
            if self.pos.is_flat:
                self.pos.opened_at = candle["t"]
                self.pos.entries = 1
            else:
                self.pos.entries += 1
            self.sync()
        self.ensure_stop()

    def _close_all(self, reason: str) -> None:
        self.sync()
        if self.pos.is_flat:
            return
        side = "sell" if self.pos.side == "long" else "buy"
        amount = float(self.ex.amount_to_precision(self.symbol, self.pos.qty / self.contract_size))
        before = self.pos.copy()
        self.ex.create_order(self.symbol, "market", side, amount, None, {"reduceOnly": True})
        est = before.unrealized(self.last_price)
        d = int(time.time() * 1000) // 86_400_000
        self.day_pnl[d] = self.day_pnl.get(d, 0.0) + est
        log.info("CLOSE %s %s (%s), estimated PnL %.4f", before.side, before.qty, reason, est)
        self.cancel_stop()
        self.sync()

    def ensure_stop(self) -> None:
        sp = stop_price(self.pos, self.risk.stop_loss_pct)
        if sp is None:
            self.cancel_stop()
            return
        sp = float(self.ex.price_to_precision(self.symbol, sp))
        if self.stop_id and self.stop_at == (sp, self.pos.qty):
            return
        self.cancel_stop()
        side = "sell" if self.pos.side == "long" else "buy"
        amount = float(self.ex.amount_to_precision(self.symbol, self.pos.qty / self.contract_size))
        try:
            o = self.ex.create_order(self.symbol, "market", side, amount, None, {"stopLossPrice": sp, "reduceOnly": True})
            self.stop_id, self.stop_at = o.get("id"), (sp, self.pos.qty)
            log.info("Stop-loss placed at %s", sp)
        except Exception as e:
            log.error("Could not place the exchange stop (%s). The software stop is still active.", e)

    def cancel_stop(self) -> None:
        if not self.stop_id:
            return
        try:
            self.ex.cancel_order(self.stop_id, self.symbol, {"stop": True, "trigger": True})
        except Exception as e:
            log.info("cancel stop: %s", e)
        self.stop_id = self.stop_at = None


def fetch_recent(ex, symbol: str, tf: str, n: int) -> list:
    step = tf_ms(tf)
    now = int(time.time() * 1000)
    since = now - (n + 2) * step
    out = []
    cursor = since
    while cursor < now:
        rows = ex.fetch_ohlcv(symbol, tf, since=cursor, limit=1000)
        if not rows:
            break
        out.extend({"t": int(r[0]), "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5] or 0.0} for r in rows)
        nxt = int(rows[-1][0]) + step
        if nxt <= cursor:
            break
        cursor = nxt
    return out


def run_forever(bot_dir: str, cfg: dict) -> None:
    from .data import make_exchange

    mode = os.environ.get("MODE", "paper").strip().lower()
    allow = os.environ.get("ALLOW_LIVE", "false").strip().lower() == "true"
    risk = RiskGuard(cfg["risk"])
    if mode == "live":
        if not allow:
            raise SystemExit("MODE=live needs ALLOW_LIVE=true in .env. Refusing to trade.")
        keys = {"apiKey": os.environ["EXCHANGE_API_KEY"], "secret": os.environ["EXCHANGE_SECRET"]}
        if os.environ.get("EXCHANGE_PASSWORD"):
            keys["password"] = os.environ["EXCHANGE_PASSWORD"]
        ex = make_exchange(cfg["exchange"], keys)
        if os.environ.get("EXCHANGE_SANDBOX", "").lower() == "true":
            ex.set_sandbox_mode(True)
        broker = CcxtBroker(cfg, ex, risk)
    else:
        ex = make_exchange(cfg["exchange"])
        broker = SimBroker(cfg["costs"], risk, cfg["leverage"], cfg["backtest"]["start_equity"])
    runner = LiveRunner(bot_dir, cfg, broker)
    poll = max(3, int(cfg["live"].get("poll_seconds", 10)))
    log.info("Started %s on %s %s %s, mode=%s, lookback=%d", cfg["name"], cfg["exchange"], cfg["symbol"], cfg["timeframe"], mode, runner.lookback)
    while True:
        try:
            if runner.kill_file.exists():
                log.warning("KILL file found: closing the position and stopping.")
                if isinstance(broker, CcxtBroker):
                    broker._close_all("kill switch")
                elif not broker.pos.is_flat:
                    broker._close(broker.last_price, int(time.time() * 1000), "kill switch")
                    runner._save()
                return
            n = runner.lookback + 2 if not runner.started else 5
            raw = fetch_recent(ex, cfg["symbol"], cfg["timeframe"], n)
            now = int(ex.milliseconds())
            runner.poll(raw, now)
            if isinstance(broker, CcxtBroker) and raw:
                broker.tick(raw[-1]["c"])
        except KeyboardInterrupt:
            log.info("Stopped by user")
            return
        except Exception as e:  # keep running through network errors
            log.exception("Poll failed: %s", e)
        time.sleep(poll)


def _fmt(t: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t / 1000))


def _jsonable(d: dict) -> dict:
    try:
        json.dumps(d)
        return d
    except (TypeError, ValueError):
        return {}
