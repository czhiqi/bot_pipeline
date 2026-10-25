"""Bot config (bots/<name>/config.json) and repo-wide pipeline rules (pipeline.json)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .timeframes import tf_ms

BOT_DEFAULTS = {
    "name": "",
    "exchange": "bitget",  # bitget | binance
    "symbol": "ETH/USDT:USDT",  # ccxt unified perpetual symbol
    "timeframe": "1h",
    "lookback": 1000,  # candles the strategy sees; the live bot fetches the same number
    "leverage": 3,
    "margin_mode": "isolated",
    "params": {"qty": 0.02},
    "risk": {
        "stop_loss_pct": 4.0,  # % price move against the average entry; 0 = none (fails the gate)
        "take_profit_pct": 0,  # % price move in favour of the average entry; 0 = none
        "max_position_qty": 0.1,  # hard cap on position size, base units
        "max_entries": 3,  # first entry + adds
        "daily_loss_limit_usdt": 0,  # 0 = off; blocks new entries for the rest of the UTC day
    },
    "costs": {"taker_fee_pct": 0.06, "slippage_pct": 0.05},
    "backtest": {"months": 24, "start_equity": 1000},
    "live": {"poll_seconds": 10},
}

PIPELINE_DEFAULTS = {
    "oos_fraction": 0.33,  # last third of the data is out-of-sample
    "min_months": 6,
    "min_trades": 30,
    "min_trades_oos": 8,
    "min_profit_factor_oos": 1.05,
    "require_oos_profit": True,
    "max_dd_pct_of_peak_margin": 60,  # worst drawdown vs the most margin the bot ever used
    "max_leverage": 5,
    "require_stop_loss": True,
    "liq_buffer": 0.8,  # stop must sit within 80% of the distance to liquidation
    "min_slippage_pct": 0.03,  # costs below these floors are raised before testing
    "min_taker_fee_pct": 0.04,
    "parity_candles": 1500,
    "allowed_exchanges": ["bitget", "binance"],
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_bot_config(bot_dir: str | Path) -> dict:
    bot_dir = Path(bot_dir)
    raw = json.loads((bot_dir / "config.json").read_text(encoding="utf-8"))
    cfg = _merge(BOT_DEFAULTS, raw)
    if not cfg["name"]:
        cfg["name"] = bot_dir.name
    validate_bot_config(cfg)
    return cfg


def validate_bot_config(cfg: dict) -> None:
    tf_ms(cfg["timeframe"])
    if cfg["exchange"] not in ("bitget", "binance"):
        raise ValueError("exchange must be bitget or binance")
    if ":" not in cfg["symbol"]:
        raise ValueError("symbol must be a ccxt perpetual symbol such as ETH/USDT:USDT")
    if not (1 <= float(cfg["leverage"]) <= 125):
        raise ValueError("leverage must be between 1 and 125")
    if int(cfg["lookback"]) < 100:
        raise ValueError("lookback must be at least 100 candles")
    if float(cfg["params"].get("qty", 0)) <= 0:
        raise ValueError("params.qty must be > 0")
    if float(cfg["risk"]["max_position_qty"]) <= 0:
        raise ValueError("risk.max_position_qty must be > 0")


def load_pipeline_rules(repo_root: str | Path = ".") -> dict:
    p = Path(repo_root) / "pipeline.json"
    raw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _merge(PIPELINE_DEFAULTS, raw)
