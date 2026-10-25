"""The engine loop shared by backtest, paper and live.

Per closed candle, in this order:
  1. broker.on_candle(candle)   fills orders from the previous close at this open,
                                checks the stop-loss inside the candle (simulated brokers)
  2. indicators.update(candle)
  3. strategy.on_candle(ctx)    -> orders
  4. risk guard                 trims or drops orders (caps, entries, daily loss, kill switch)
  5. broker.submit(orders)
"""

from __future__ import annotations

from collections import deque

from .indicators import Indicators
from .strategy import Context, Order, Position, Strategy

DAY_MS = 86_400_000


def stop_price(pos: Position, stop_loss_pct: float):
    if pos.is_flat or stop_loss_pct <= 0:
        return None
    f = stop_loss_pct / 100
    return pos.avg_price * (1 - f) if pos.side == "long" else pos.avg_price * (1 + f)


def target_price(pos: Position, take_profit_pct: float):
    if pos.is_flat or take_profit_pct <= 0:
        return None
    f = take_profit_pct / 100
    return pos.avg_price * (1 + f) if pos.side == "long" else pos.avg_price * (1 - f)


class RiskGuard:
    def __init__(self, risk: dict):
        self.stop_loss_pct = float(risk.get("stop_loss_pct", 0) or 0)
        self.take_profit_pct = float(risk.get("take_profit_pct", 0) or 0)
        self.max_qty = float(risk["max_position_qty"])
        self.max_entries = int(risk.get("max_entries", 1) or 1)
        self.daily_limit = float(risk.get("daily_loss_limit_usdt", 0) or 0)
        self.blocked: list = []  # (time, reason) of dropped orders, for the report

    def filter(self, orders: list, pos: Position, now: int, realized_today: float, kill: bool = False) -> list:
        out = []
        p = pos.copy()
        for o in orders or []:
            if not isinstance(o, Order):
                raise TypeError("on_candle must return a list of engine.Order")
            if o.action == "close":
                if not p.is_flat:
                    out.append(o)
                    p = Position()
                continue
            side = "long" if o.action == "buy" else "short"
            if kill:
                self.blocked.append((now, "kill switch"))
                continue
            flipping = not p.is_flat and p.side != side
            if flipping:
                # A flip is a close plus a fresh entry; the close always goes through.
                out.append(Order("close", reason=f"flip: {o.reason}".strip()))
                p = Position()
            if self.daily_limit > 0 and realized_today <= -self.daily_limit:
                self.blocked.append((now, "daily loss limit"))
                continue
            if not p.is_flat and p.entries >= self.max_entries:
                self.blocked.append((now, "max entries"))
                continue
            room = self.max_qty - (0.0 if p.is_flat else p.qty)
            qty = min(o.qty, room)
            if qty <= 1e-12:
                self.blocked.append((now, "max position size"))
                continue
            if qty < o.qty:
                self.blocked.append((now, "size trimmed to max position"))
            out.append(Order(o.action, qty, o.reason))
            if p.is_flat:
                p = Position(side, qty, 1.0, 1, now)
            else:
                p = Position(side, p.qty + qty, 1.0, p.entries + 1, p.opened_at)
        return out


class SimBroker:
    """Simulated fills for backtest and paper trading."""

    def __init__(self, costs: dict, risk: RiskGuard, leverage: float, start_equity: float = 1000.0):
        self.fee = float(costs["taker_fee_pct"]) / 100
        self.slip = float(costs["slippage_pct"]) / 100
        self.risk = risk
        self.leverage = float(leverage)
        self.start_equity = float(start_equity)
        self.pos = Position()
        self.pending: list = []
        self.realized = 0.0
        self.trades: list = []
        self._open_fees = 0.0
        self._entry_fills: list = []
        self.day_pnl: dict = {}
        self.peak_equity = self.start_equity
        self.max_dd = 0.0
        self.peak_margin = 0.0
        self.last_price = 0.0

    # --- engine hooks -------------------------------------------------------
    def position(self) -> Position:
        return self.pos.copy()

    def equity(self) -> float:
        return self.start_equity + self.realized + self.pos.unrealized(self.last_price)

    def realized_today(self, now: int) -> float:
        return self.day_pnl.get(now // DAY_MS, 0.0)

    def on_candle(self, c: dict) -> None:
        if self.pending:
            for o in self.pending:
                self._execute(o, c["o"], c["t"])
            self.pending = []
        # Stop first: when stop and target are both touched in one candle the
        # order inside the candle is unknown, so assume the worse (same rule as
        # the research lab's _apply_stops()).
        sp = stop_price(self.pos, self.risk.stop_loss_pct)
        if sp is not None:
            if self.pos.side == "long" and c["l"] <= sp:
                self._close(min(c["o"], sp), c["t"], "stop-loss")
            elif self.pos.side == "short" and c["h"] >= sp:
                self._close(max(c["o"], sp), c["t"], "stop-loss")
        tp = target_price(self.pos, self.risk.take_profit_pct)
        if tp is not None:
            if self.pos.side == "long" and c["h"] >= tp:
                self._close(max(c["o"], tp), c["t"], "take-profit")
            elif self.pos.side == "short" and c["l"] <= tp:
                self._close(min(c["o"], tp), c["t"], "take-profit")
        self.last_price = c["c"]
        eq = self.equity()
        self.peak_equity = max(self.peak_equity, eq)
        self.max_dd = max(self.max_dd, self.peak_equity - eq)

    def submit(self, orders: list, candle: dict) -> None:
        self.pending.extend(orders)

    def mark(self, c: dict) -> None:
        self.last_price = c["c"]

    # --- paper-mode persistence --------------------------------------------
    def dump(self) -> dict:
        p = self.pos
        return {
            "pos": [p.side, p.qty, p.avg_price, p.entries, p.opened_at],
            "pending": [[o.action, o.qty, o.reason] for o in self.pending],
            "realized": self.realized,
            "open_fees": self._open_fees,
            "day_pnl": {str(k): v for k, v in self.day_pnl.items()},
        }

    def load(self, d: dict) -> None:
        from .strategy import Order as _O

        self.pos = Position(*d["pos"])
        self.pending = [_O(a, q, r) for a, q, r in d.get("pending", [])]
        self.realized = d.get("realized", 0.0)
        self._open_fees = d.get("open_fees", 0.0)
        self.day_pnl = {int(k): v for k, v in d.get("day_pnl", {}).items()}

    # --- fills --------------------------------------------------------------
    def _execute(self, o: Order, price: float, t: int) -> None:
        if o.action == "close":
            if not self.pos.is_flat:
                self._close(price, t, o.reason or "strategy close")
            return
        side = "long" if o.action == "buy" else "short"
        if not self.pos.is_flat and self.pos.side != side:
            self._close(price, t, "flip")
        fill = price * (1 + self.slip) if side == "long" else price * (1 - self.slip)
        fee = fill * o.qty * self.fee
        self.realized -= fee
        self._book_day(t, -fee)
        self._open_fees += fee
        if self.pos.is_flat:
            self.pos = Position(side, o.qty, fill, 1, t)
            self._entry_fills = [(t, fill, o.qty)]
        else:
            q = self.pos.qty + o.qty
            self.pos.avg_price = (self.pos.avg_price * self.pos.qty + fill * o.qty) / q
            self.pos.qty = q
            self.pos.entries += 1
            self._entry_fills.append((t, fill, o.qty))
        self.peak_margin = max(self.peak_margin, self.pos.qty * fill / self.leverage)

    def _close(self, price: float, t: int, reason: str) -> None:
        p = self.pos
        fill = price * (1 - self.slip) if p.side == "long" else price * (1 + self.slip)
        fee = fill * p.qty * self.fee
        gross = p.unrealized(fill)
        self.realized += gross - fee
        self._book_day(t, gross - fee)
        self.trades.append(
            {
                "side": p.side,
                "entry_time": p.opened_at,
                "exit_time": t,
                "qty": round(p.qty, 10),
                "entries": p.entries,
                "avg_entry": p.avg_price,
                "exit_price": fill,
                "fees": self._open_fees + fee,
                "pnl": gross - fee - self._open_fees,
                "reason": reason,
            }
        )
        self.pos = Position()
        self._open_fees = 0.0
        self._entry_fills = []

    def _book_day(self, t: int, amount: float) -> None:
        d = t // DAY_MS
        self.day_pnl[d] = self.day_pnl.get(d, 0.0) + amount


class Engine:
    def __init__(self, strategy: Strategy, cfg: dict, broker, kill_check=None):
        self.strategy = strategy
        self.cfg = cfg
        self.broker = broker
        self.lookback = int(cfg["lookback"])
        self.candles: deque = deque(maxlen=self.lookback)
        self.ind = Indicators(cfg["timeframe"])
        self.state: dict = {}
        self.risk: RiskGuard = broker.risk
        self.kill_check = kill_check or (lambda: False)
        self.last_t = None

    def warm(self, candles: list) -> None:
        """Load history without trading. Backtest and live both start with exactly
        `lookback` candles of history, so the strategy sees the same window."""
        for c in candles:
            if self.last_t is not None and c["t"] <= self.last_t:
                continue
            self.last_t = c["t"]
            self.candles.append(c)
            self.broker.mark(c)

    def on_closed_candle(self, c: dict) -> list:
        if self.last_t is not None and c["t"] <= self.last_t:
            return []  # already processed
        self.last_t = c["t"]
        self.candles.append(c)
        self.broker.on_candle(c)
        self.ind.update(c)
        if len(self.candles) < max(1, int(self.strategy.warmup())):
            return []
        pos = self.broker.position()
        ctx = Context(
            candles=list(self.candles),
            position=pos,
            params=dict(self.strategy.params),
            equity=self.broker.equity(),
            state=self.state,
            _ind=self.ind,
            _tf=self.cfg["timeframe"],
        )
        orders = self.strategy.on_candle(ctx) or []
        orders = self.risk.filter(orders, pos, c["t"], self.broker.realized_today(c["t"]), self.kill_check())
        if orders:
            self.broker.submit(orders, c)
        return orders
