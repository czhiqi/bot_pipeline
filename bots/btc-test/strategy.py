from engine import Order, Strategy


class FlipToFlip(Strategy):
    """
    'Flip to Flip': always-in-market stop-and-reverse.
    A fast/slow EMA crossover is a 'flip'. On a bullish flip go long
    (closing any short). On a bearish flip go short (closing any long).
    Each position is held from one flip to the next.
    """

    default_params = {
        "qty": 0.02,
        "fast": 20,
        "slow": 50,
    }

    def warmup(self) -> int:
        slow = int(self.params.get("slow", 50))
        return min(max(slow * 3, 60), 1000)

    def on_candle(self, ctx) -> list:
        p = ctx.params
        qty = float(p.get("qty", 0.02))
        fast = int(p.get("fast", 20))
        slow = int(p.get("slow", 50))

        f = ctx.ema(fast)
        s = ctx.ema(slow)
        fp = ctx.ema_prev(fast, back=1)
        sp = ctx.ema_prev(slow, back=1)
        if f is None or s is None or fp is None or sp is None:
            return []

        cross_up = fp <= sp and f > s
        cross_down = fp >= sp and f < s

        pos = ctx.position
        orders = []

        if cross_up:
            if pos.side != "long":
                orders.append(Order("buy", qty, reason="flip up: fast EMA crossed above slow"))
            ctx.state["last_flip"] = "up"
        elif cross_down:
            if pos.side != "short":
                orders.append(Order("sell", qty, reason="flip down: fast EMA crossed below slow"))
            ctx.state["last_flip"] = "down"

        return orders
