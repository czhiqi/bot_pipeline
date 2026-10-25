# Strategy pipeline repo

One shared engine, one folder per bot. Every strategy goes through the same path:

**Hypothesis → strategy code → gates (CI) → review (pull request) → paper → live**

```
engine/            shared engine (admin-owned, protected by CODEOWNERS)
  strategy.py      Strategy / Order / Context interface
  indicators.py    incremental EMA / RSI / ATR, higher-timeframe resampling
  core.py          Engine loop, RiskGuard, SimBroker (backtest + paper)
  live.py          LiveRunner (paper + live), CcxtBroker (real orders)
  backtest.py      python -m engine.backtest bots/<name>
  pipeline.py      the gates; writes reports/<name>/report.json
  data.py          candles: data/*.csv or ccxt download
  sandbox_check.py static check for submitted code
  signal_adapter.py research-lab strategies (build_signal) as bots
  lab/             vendored lab primitives, templates and signal code
bots/<name>/       strategy.py · config.json · hypothesis.md
pipeline.json      gate thresholds (admin-owned)
run_bot.py         python run_bot.py bots/<name>
```

## The gates

| Gate | Passes when |
|---|---|
| Only bots/ changed | the branch touches nothing outside `bots/` and `data/` |
| Required files | `strategy.py`, `config.json`, `hypothesis.md` exist |
| Config valid | exchange, symbol, timeframe, size, leverage make sense |
| Code check | no imports beyond math/collections/etc., no file, network, eval or dunder access |
| Risk settings | leverage ≤ cap; stop-loss set and inside 80% of the liquidation distance |
| Enough data | at least `min_months` of candles |
| Backtest runs | no errors over the whole history |
| Enough trades | `min_trades` overall, `min_trades_oos` in the last third |
| Out-of-sample | out-of-sample net > 0 and profit factor ≥ `min_profit_factor_oos` |
| Drawdown vs margin | worst drawdown ≤ `max_dd_pct_of_peak_margin` of the most margin used |
| Live = backtest | the live runner, fed the same candles poll by poll, makes identical trades |

Fees and slippage are raised to the `pipeline.json` floors before testing, so a bot can't pass by assuming free fills.

### Why backtest and live match by construction
- One `Engine.on_closed_candle()` for both. Orders decided on a close fill at the next open.
- Both start with exactly `lookback` candles of history (default 1000). The live bot fetches the same number, so indicators are seeded the same way. (A 200-candle EMA150 read was 4% off live on ZEC.)
- Indicators are incremental and higher timeframes are built from the bot's own closed candles.
- The parity gate replays the runner with forming candles, repeated polls and multi-candle catch-ups.

Still not modelled: funding, partial fills, and moves inside a candle. Strategies that add or exit within a candle should be judged on 1m data. On ZEC, 15m replay overstated profit about 6x.

## Writing a strategy

```python
from engine import Order, Strategy

class MyIdea(Strategy):
    default_params = {"qty": 0.02, "fast": 50, "slow": 150}

    def warmup(self):
        return self.params["slow"] + 5

    def on_candle(self, ctx):
        fast, slow = ctx.ema(self.params["fast"]), ctx.ema(self.params["slow"])
        trend_4h = ctx.ema(150, "4h")
        if ctx.position.is_flat and fast > slow:
            return [Order("buy", self.params["qty"], "fast above slow")]
        if not ctx.position.is_flat and fast < slow:
            return [Order("close", reason="fast below slow")]
        return []
```

`ctx` gives `candles` (closed, oldest first, at most `lookback`), `position` (side, qty, avg_price, entries, `pnl_pct(price)`), `params`, `equity`, `state` (your scratch dict, saved across restarts), and `ema/ema_prev/rsi/atr(period, tf)`.

Stops, size caps, max entries, the daily loss limit and the kill switch come from `config.json` → `risk`. The engine enforces them, so the strategy doesn't have to.

## Research-lab strategies (from the Research tab)

A strategy researched in the lab (`/lab` in the web app) is deployed **unchanged**: its file goes into `bots/<name>/strategy.py` and the loader wraps it in `engine/signal_adapter.py`. Its `from tool.engine import ...` line resolves to `engine/lab/`, the lab's primitives, templates and signal code copied verbatim.

- Every closed candle, the lab's own signal code turns the candle window into its target position (+1 / -1 / 0), including warmup gating, the forward-filled state machine and the `build_regime` overlay. `lag` works as in the lab.
- `risk.stop_loss_pct` / `risk.take_profit_pct` and `params.signal.max_hold` exit like the lab's `_apply_stops()`: stop wins over target in the same candle, and after any of them the bot stays out until the signal changes.
- `tests/test_signal_adapter.py` checks bar by bar that the bot holds the same position the lab's engine computes, for long-only, long/short, edge-form, regime, stop, target and max-hold cases.
- The backtest computes the signal once over the whole history; the live bot recomputes it on its `lookback` window. **Live = backtest** therefore also catches look-ahead (e.g. `.shift(-1)`) and strategies that depend on all history (`.expanding()`); raise `lookback` for the latter.
- Only `DATASET = []` strategies can be deployed: a bot only gets exchange OHLCV, not the lab's feature datasets.
- Not identical to the lab's report numbers: Forge fills at the next open with its own fees and slippage on the exchange's perpetual market, where the lab books closes on its uploaded (usually spot) data. The gates re-test it on Forge's terms.

```json
"params": {"qty": 0.001, "mode": "long_short", "lag": 1, "on_missing_data": "hold",
           "signal": {"window": 20, "threshold": 1.0, "max_hold": 0},
           "regime": {"regime_window": 60}}
```

## Local commands

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m engine.data fetch --exchange bitget --symbol BTC/USDT:USDT --tf 4h --months 60
python -m engine.backtest bots/example-ema-flip
python -m engine.pipeline --bots example-ema-flip --out reports
python run_bot.py bots/example-ema-flip            # paper
```

## Porting the existing bots
The snowball bots (ETH, XRP, CL, ZEC) add and move stops inside a candle, while this engine decides on candle closes. Port them in this order:
1. **Flip-style bots (BTC flip):** port now. The example bot is the BTC 4H EMA50/150 flip.
2. **Snowball bots:** run them on a 1m timeframe with `lookback` 1000 and keep the add/lock logic in `on_candle`. This engine decides on 1m closes, while the old bots react to ticks, so results will differ. Compare every port against the old 1m backtest before trusting it.
3. Exchange extras (post-only maker adds, stop-limit no-loss floors) are not in `CcxtBroker` yet. Keep those bots on their current code until those are added to the engine and covered by the parity tests.

See DEPLOY.md for repository setup and manual deployment.
