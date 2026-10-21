from engine import Order, Strategy


class EmaFlip(Strategy):
    """Trend flip on closed candles.

    UP   = close > slow EMA, fast EMA > slow EMA, slow EMA rising vs `slope_bars` ago
    DOWN = all three reversed. A mixed reading keeps the last state.
    Enter only on the candle where the state flips; exit at the next flip.
    Optional higher-timeframe filter: only trade in the direction of the trend_tf EMAs.
    """

    name = "ema-flip"
    default_params = {
        "qty": 0.02,
        "fast": 50,
        "slow": 150,
        "slope_bars": 5,
        "direction": "long",  # long | short | auto
        "trend_tf": "",  # e.g. "4h"; empty = no filter
    }

    def warmup(self) -> int:
        return self.params["slow"] + self.params["slope_bars"] + 1

    def _state(self, ctx, back: int) -> str:
        p = self.params
        fast = ctx.ema_prev(p["fast"], back=back)
        slow = ctx.ema_prev(p["slow"], back=back)
        slow_then = ctx.ema_prev(p["slow"], back=back + p["slope_bars"])
        if None in (fast, slow, slow_then):
            return "none"
        close = ctx.candles[-1 - back]["c"]
        if close > slow and fast > slow and slow > slow_then:
            return "up"
        if close < slow and fast < slow and slow < slow_then:
            return "down"
        return "mixed"

    def _trend_ok(self, ctx, side: str) -> bool:
        tf = self.params["trend_tf"]
        if not tf:
            return True
        fast, slow = ctx.ema(self.params["fast"], tf), ctx.ema(self.params["slow"], tf)
        if fast is None or slow is None:
            return False
        return fast > slow if side == "long" else fast < slow

    def on_candle(self, ctx):
        now = self._state(ctx, 0)
        if now in ("none", "mixed"):
            return []
        prev = ctx.state.get("last", "none")
        ctx.state["last"] = now
        if prev == now or prev == "none":
            return []  # no flip (and never enter mid-trend on the first reading)

        p, pos, out = self.params, ctx.position, []
        want = "long" if now == "up" else "short"
        if not pos.is_flat and pos.side != want:
            out.append(Order("close", reason=f"flip {now}"))
        allowed = p["direction"] == "auto" or p["direction"] == want
        if allowed and (pos.is_flat or pos.side != want) and self._trend_ok(ctx, want):
            out.append(Order("buy" if want == "long" else "sell", p["qty"], reason=f"flip {now}"))
        return out
