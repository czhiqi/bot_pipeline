"""Candle data: read data/<exchange>_<SYMBOL>_<tf>.csv, or download it with ccxt (public API, no keys).

  python -m engine.data fetch --exchange bitget --symbol ETH/USDT:USDT --tf 1h --months 24

Commit the CSV under data/ if the CI runner can't reach the exchange (Binance
blocks some cloud regions). Columns: t,o,h,l,c,v with t in ms UTC.
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from .timeframes import tf_ms

DATA_DIR = Path("data")


def data_path(exchange: str, symbol: str, tf: str, root: Path = DATA_DIR) -> Path:
    safe = symbol.replace("/", "").replace(":", "_")
    return root / f"{exchange}_{safe}_{tf}.csv"


def read_csv(path: Path) -> list:
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(
                {
                    "t": int(float(row["t"])),
                    "o": float(row["o"]),
                    "h": float(row["h"]),
                    "l": float(row["l"]),
                    "c": float(row["c"]),
                    "v": float(row.get("v") or 0),
                }
            )
    return clean(out)


def write_csv(path: Path, candles: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "o", "h", "l", "c", "v"])
        for c in candles:
            w.writerow([c["t"], c["o"], c["h"], c["l"], c["c"], c["v"]])


def clean(candles: list) -> list:
    """Sort, drop duplicates and zero-price rows."""
    seen = {}
    for c in candles:
        if c["o"] > 0 and c["c"] > 0:
            seen[c["t"]] = c
    return [seen[t] for t in sorted(seen)]


def make_exchange(name: str, keys: dict | None = None):
    try:
        import ccxt  # imported lazily so backtests on local CSVs don't need it
    except ImportError:
        raise SystemExit("ccxt is not installed. Run: pip install -r requirements.txt") from None

    cls = getattr(ccxt, "binanceusdm" if name == "binance" else name)
    opts = {"enableRateLimit": True, **(keys or {})}
    if name == "bitget":
        opts.setdefault("options", {})["defaultType"] = "swap"
    return cls(opts)


def download(exchange: str, symbol: str, tf: str, since_ms: int, until_ms: int | None = None) -> list:
    ex = make_exchange(exchange)
    step = tf_ms(tf)
    until_ms = until_ms or int(time.time() * 1000)
    out = []
    cursor = since_ms
    while cursor < until_ms:
        rows = ex.fetch_ohlcv(symbol, tf, since=cursor, limit=1000)
        if not rows:
            break
        for t, o, h, l, c, v in rows:
            if t + step <= until_ms:  # closed candles only
                out.append({"t": int(t), "o": o, "h": h, "l": l, "c": c, "v": v or 0.0})
        nxt = int(rows[-1][0]) + step
        if nxt <= cursor:
            break
        cursor = nxt
    return clean(out)


def load_candles(cfg: dict, months: float | None = None, root: Path = DATA_DIR, allow_download: bool = True) -> tuple:
    """Returns (candles, source description)."""
    months = float(months or cfg["backtest"]["months"])
    path = data_path(cfg["exchange"], cfg["symbol"], cfg["timeframe"], root)
    now = int(time.time() * 1000)
    since = now - int(months * 30.44 * 86_400_000)
    if path.exists():
        candles = read_csv(path)
        return [c for c in candles if c["t"] >= since] or candles, f"file {path}"
    if not allow_download:
        raise FileNotFoundError(f"No data file {path}")
    candles = download(cfg["exchange"], cfg["symbol"], cfg["timeframe"], since, now)
    if candles:
        write_csv(path, candles)
    return candles, f"downloaded from {cfg['exchange']} ({len(candles)} candles)"


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--exchange", required=True, choices=["bitget", "binance"])
    f.add_argument("--symbol", required=True)
    f.add_argument("--tf", required=True)
    f.add_argument("--months", type=float, default=24)
    a = ap.parse_args()
    now = int(time.time() * 1000)
    candles = download(a.exchange, a.symbol, a.tf, now - int(a.months * 30.44 * 86_400_000), now)
    path = data_path(a.exchange, a.symbol, a.tf)
    write_csv(path, candles)
    print(f"Wrote {len(candles)} candles to {path}")


if __name__ == "__main__":
    main()
