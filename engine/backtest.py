"""Backtest = the live engine fed with historical closed candles and a simulated broker.

  python -m engine.backtest bots/example-ema-flip [--months 12]
"""

from __future__ import annotations

import argparse
import json

from .config import load_bot_config
from .core import Engine, RiskGuard, SimBroker
from .data import load_candles
from .loader import build_strategy


def run(bot_dir: str, cfg: dict, candles: list, costs: dict | None = None) -> dict:
    strategy = build_strategy(bot_dir, cfg)
    broker = SimBroker(costs or cfg["costs"], RiskGuard(cfg["risk"]), cfg["leverage"], cfg["backtest"]["start_equity"])
    engine = Engine(strategy, cfg, broker)
    lb = int(cfg["lookback"])
    if int(strategy.warmup()) > lb:
        raise ValueError(f"strategy warmup ({strategy.warmup()}) is longer than lookback ({lb})")
    # Same start as a live bot: `lookback` candles of history, then trade candle by candle.
    strategy.prepare(candles)
    engine.warm(candles[:lb])
    for c in candles[lb:]:
        engine.on_closed_candle(c)
    return {"broker": broker, "trades": broker.trades, "blocked": broker.risk.blocked, "open_position": broker.position()}


def summarize(trades: list, max_dd: float | None = None) -> dict:
    net = sum(t["pnl"] for t in trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gross_loss = -sum(losses)
    # drawdown on closed-trade equity (used for in/out-of-sample splits)
    peak = cum = dd = 0.0
    for t in trades:
        cum += t["pnl"]
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {
        "trades": len(trades),
        "net": round(net, 4),
        "win_rate": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "profit_factor": round(sum(wins) / gross_loss, 3) if gross_loss > 0 else (999.0 if wins else 0.0),
        "avg_trade": round(net / len(trades), 4) if trades else 0.0,
        "max_drawdown": round(max_dd if max_dd is not None else dd, 4),
        "fees": round(sum(t["fees"] for t in trades), 4),
        "stop_losses": sum(1 for t in trades if t["reason"] == "stop-loss"),
        "take_profits": sum(1 for t in trades if t["reason"] == "take-profit"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bot_dir")
    ap.add_argument("--months", type=float)
    a = ap.parse_args()
    cfg = load_bot_config(a.bot_dir)
    candles, src = load_candles(cfg, a.months)
    res = run(a.bot_dir, cfg, candles)
    print(f"Data: {src}, {len(candles)} candles")
    print(json.dumps(summarize(res["trades"], res["broker"].max_dd), indent=2))


if __name__ == "__main__":
    main()
