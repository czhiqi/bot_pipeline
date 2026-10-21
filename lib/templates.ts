// Starter code and the strategy guide given to the code-writing model.

export const BLANK_CODE = `from engine import Order, Strategy


class MyStrategy(Strategy):
    """Describe the rule in one or two lines."""

    default_params = {
        "qty": 0.02,
        "fast": 50,
        "slow": 150,
    }

    def warmup(self):
        return self.params["slow"] + 5

    def on_candle(self, ctx):
        fast = ctx.ema(self.params["fast"])
        slow = ctx.ema(self.params["slow"])
        if fast is None or slow is None:
            return []
        if ctx.position.is_flat and fast > slow:
            return [Order("buy", self.params["qty"], "fast above slow")]
        if ctx.position.side == "long" and fast < slow:
            return [Order("close", reason="fast below slow")]
        return []
`;

export const STRATEGY_GUIDE = `You write trading strategies for a shared Python engine. Output ONE file, strategy.py.

## Interface (engine/strategy.py — already exists, do not redefine it)
from engine import Order, Strategy

class Strategy:
    default_params: dict = {}          # merged with config.json "params"; self.params holds the result
    def warmup(self) -> int            # closed candles needed before on_candle is first called (<= lookback, default lookback 1000)
    def on_candle(self, ctx) -> list   # called once per CLOSED candle; return a list of Order (may be empty)

Order("buy", qty, reason="")   # open/add long; while short it closes the short and opens a long
Order("sell", qty, reason="")  # open/add short; while long it closes the long and opens a short
Order("close", reason="")      # close the whole position
qty is in base units (ETH, BTC...). Use self.params["qty"].

ctx.candles     list of closed candles, oldest first, dicts with t (ms), o, h, l, c, v; at most lookback candles
ctx.close, ctx.time, ctx.candle, ctx.closes(n=None)
ctx.position    side ("long"|"short"|"flat"), qty, avg_price, entries, opened_at, is_flat, pnl_pct(price) (% price move from avg entry, + = profit)
ctx.params      dict of params; ctx.equity float
ctx.state       dict you may read/write; persisted between candles and across bot restarts (JSON values only)
ctx.ema(period, tf=None) / ctx.ema_prev(period, tf=None, back=1) / ctx.rsi(period=14, tf=None) / ctx.atr(period=14, tf=None)
    -> float or None while warming up. tf may be a HIGHER timeframe such as "4h" (must be a multiple of the bot timeframe);
       its value only changes when that higher candle closes. ema_prev(back=n) gives the value n closed candles ago (n <= 49).

## Execution model
- Orders returned on a candle close fill at market at the next candle's open, with fees and slippage.
- The ENGINE (not the strategy) applies config.json "risk": stop_loss_pct from the average entry, max_position_qty,
  max_entries, daily_loss_limit_usdt and a kill switch. Do not implement your own stop-loss unless it is part of the idea
  (e.g. a trailing exit), in which case use Order("close").
- Never enter on the very first reading after start: compare with ctx.state or ema_prev so entries happen on a change.
- No intrabar logic: you only see closed candles.

## Hard rules (CI rejects the file otherwise)
- Allowed imports ONLY: math, statistics, dataclasses, typing, collections, itertools, functools, enum, engine.
- No eval/exec/compile/open/__import__/getattr/setattr/globals/locals/vars/input, no dunder attributes, no global/nonlocal.
- Exactly ONE class that subclasses Strategy. No file, network, time or random access. Deterministic.
- Keep indicator periods <= lookback/6 (<= 160 with lookback 1000).
- Use only the API above. Guard against None from indicators.

## Output format
First a \`\`\`python block with the complete strategy.py.
Then a \`\`\`json block: {"params": {...default params incl. qty...}, "risk": {"stop_loss_pct": n, "max_position_qty": n, "max_entries": n}, "notes": "one short paragraph: what the code does and any assumption you made"}.
Nothing else.`;
