"""The gates every bot must pass before it can be merged and deployed.

  python -m engine.pipeline --bots "example-ema-flip" --out reports

Gates, in order (a failed early gate skips the later ones):
  scope       the branch only changed files under bots/
  files       strategy.py, config.json and hypothesis.md exist
  config      config.json is valid
  code        static check of strategy.py (engine/sandbox_check.py)
  risk        leverage cap, stop-loss present and inside the liquidation distance
  data        enough history
  backtest    the strategy runs on the whole history without errors
  trades      enough trades overall and out-of-sample
  oos         out-of-sample profit and profit factor
  drawdown    worst drawdown vs the most margin the bot used
  parity      the live runner, replaying the same candles poll by poll, makes identical trades

Thresholds come from pipeline.json at the repo root (admin-owned), never from the bot.
Costs below the pipeline floors are raised before testing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

from . import __version__
from .backtest import run as run_backtest
from .backtest import summarize
from .config import load_bot_config, load_pipeline_rules
from .core import RiskGuard, SimBroker
from .data import coverage, load_candles
from .live import LiveRunner
from .sandbox_check import check_source
from .timeframes import tf_ms

MAINT_MARGIN = 0.005  # rough maintenance margin for the liquidation estimate


class Report:
    def __init__(self, bot: str):
        self.d = {"bot": bot, "ok": False, "engine": __version__, "generated_at": int(time.time() * 1000), "gates": [], "warnings": []}
        self.failed = False

    def gate(self, gid: str, label: str, ok: bool, detail: str = "", value=None, limit=None) -> bool:
        self.d["gates"].append({"id": gid, "label": label, "status": "pass" if ok else "fail", "detail": detail, "value": value, "limit": limit})
        if not ok:
            self.failed = True
        _progress(gid, "pass" if ok else "fail")
        return ok

    def skip(self, gid: str, label: str) -> None:
        self.d["gates"].append({"id": gid, "label": label, "status": "skip", "detail": "skipped after an earlier failure"})
        _progress(gid, "skip")


def _progress(gid: str, status: str) -> None:
    """One line per finished gate on stderr, so a caller can show live progress."""
    print(f"::gate::{gid}::{status}", file=sys.stderr, flush=True)


GATE_ORDER = [
    ("scope", "Only bots/ changed"),
    ("files", "Required files"),
    ("config", "Config valid"),
    ("code", "Code check"),
    ("risk", "Risk settings"),
    ("data", "Enough data"),
    ("backtest", "Backtest runs"),
    ("trades", "Enough trades"),
    ("oos", "Out-of-sample result"),
    ("drawdown", "Drawdown vs margin"),
    ("parity", "Live = backtest"),
]


def evaluate(bot_dir: Path, rules: dict, outside: list, allow_download: bool = True, data_root: Path | None = None) -> dict:
    rep = Report(bot_dir.name)
    done = set()

    def finish():
        for gid, label in GATE_ORDER:
            if gid not in done:
                rep.skip(gid, label)
        rep.d["ok"] = not rep.failed
        return rep.d

    def g(gid, ok, detail="", value=None, limit=None):
        done.add(gid)
        return rep.gate(gid, dict(GATE_ORDER)[gid], ok, detail, value, limit)

    if not g("scope", not outside, "Changed outside bots/: " + ", ".join(outside[:10]) if outside else "OK"):
        return finish()

    missing = [f for f in ("strategy.py", "config.json", "hypothesis.md") if not (bot_dir / f).exists()]
    if not g("files", not missing, "Missing: " + ", ".join(missing) if missing else "OK"):
        return finish()

    try:
        cfg = load_bot_config(bot_dir)
    except Exception as e:
        g("config", False, str(e))
        return finish()
    g("config", True, f"{cfg['exchange']} {cfg['symbol']} {cfg['timeframe']}, lookback {cfg['lookback']}")
    rep.d["config"] = {k: cfg[k] for k in ("name", "exchange", "symbol", "timeframe", "lookback", "leverage", "margin_mode", "params", "risk")}

    problems = check_source((bot_dir / "strategy.py").read_text(encoding="utf-8"))
    if not g("code", not problems, "; ".join(problems[:8]) if problems else "OK"):
        return finish()

    lev = float(cfg["leverage"])
    sl = float(cfg["risk"].get("stop_loss_pct") or 0)
    liq = (1 / lev - MAINT_MARGIN) * 100
    risk_issues = []
    if cfg["exchange"] not in rules["allowed_exchanges"]:
        risk_issues.append(f"exchange {cfg['exchange']} not allowed")
    if lev > rules["max_leverage"]:
        risk_issues.append(f"leverage {lev:g}x is above the {rules['max_leverage']}x cap")
    if rules["require_stop_loss"] and sl <= 0:
        risk_issues.append("risk.stop_loss_pct must be set")
    if sl > 0 and sl > liq * rules["liq_buffer"]:
        risk_issues.append(f"stop {sl:g}% is beyond {rules['liq_buffer']:.0%} of the liquidation distance (~{liq:.1f}% at {lev:g}x)")
    if not g("risk", not risk_issues, "; ".join(risk_issues) or f"stop {sl:g}%, liquidation ~{liq:.1f}% away at {lev:g}x", sl, round(liq * rules["liq_buffer"], 2)):
        return finish()

    try:
        candles, source = load_candles(cfg, allow_download=allow_download, **({"root": data_root} if data_root else {}))
    except Exception as e:
        g("data", False, f"Could not load candles: {e}. Commit data/ with `python -m engine.data fetch`.")
        return finish()
    lb = int(cfg["lookback"])
    span_months = (candles[-1]["t"] - candles[0]["t"]) / (30.44 * 86_400_000) if candles else 0
    rep.d["data"] = {"source": source, "candles": len(candles), "from": candles[0]["t"] if candles else None, "to": candles[-1]["t"] if candles else None, "months": round(span_months, 1)}
    cov = coverage(candles, cfg["timeframe"])
    rep.d["data"]["coverage"] = round(cov, 4)
    min_cov = float(rules.get("min_data_coverage", 0.98))
    detail = f"{len(candles)} candles, {span_months:.1f} months ({source})"
    if cov < min_cov:
        detail = (f"{len(candles)} candles over {span_months:.1f} months is only {cov:.0%} of the {round(len(candles) / cov):,} expected: "
                  f"the data has gaps. Download it again or upload a complete CSV ({source})")
    if not g("data", len(candles) > lb + 50 and span_months >= rules["min_months"] and cov >= min_cov, detail, round(span_months, 1), rules["min_months"]):
        return finish()

    costs = {
        "taker_fee_pct": max(float(cfg["costs"]["taker_fee_pct"]), rules["min_taker_fee_pct"]),
        "slippage_pct": max(float(cfg["costs"]["slippage_pct"]), rules["min_slippage_pct"]),
    }
    rep.d["costs_used"] = costs
    try:
        res = run_backtest(str(bot_dir), cfg, candles, costs)
    except Exception as e:
        g("backtest", False, f"{type(e).__name__}: {e} | " + traceback.format_exc().strip().splitlines()[-1])
        return finish()
    broker = res["broker"]
    trades = res["trades"]
    g("backtest", True, f"{len(trades)} trades")

    t0, t1 = candles[lb]["t"], candles[-1]["t"]
    cut = t0 + (1 - rules["oos_fraction"]) * (t1 - t0)
    ins = [t for t in trades if t["entry_time"] < cut]
    oos = [t for t in trades if t["entry_time"] >= cut]
    overall = summarize(trades, broker.max_dd)
    overall["peak_margin"] = round(broker.peak_margin, 4)
    overall["return_on_peak_margin_pct"] = round(100 * overall["net"] / broker.peak_margin, 1) if broker.peak_margin else 0.0
    rep.d["overall"] = overall
    rep.d["in_sample"] = summarize(ins)
    rep.d["out_of_sample"] = summarize(oos)
    rep.d["oos_from"] = int(cut)
    rep.d["blocked"] = _count(r for _, r in res["blocked"])
    rep.d["open_position"] = res["open_position"].__dict__
    rep.d["last_trades"] = trades[-25:]
    rep.d["equity"] = _equity_points(trades)

    g("trades", len(trades) >= rules["min_trades"] and len(oos) >= rules["min_trades_oos"], f"{len(trades)} total, {len(oos)} out-of-sample", len(trades), rules["min_trades"])
    o = rep.d["out_of_sample"]
    oos_ok = (o["net"] > 0 or not rules["require_oos_profit"]) and o["profit_factor"] >= rules["min_profit_factor_oos"]
    g("oos", oos_ok, f"net {o['net']:+.2f}, profit factor {o['profit_factor']}, drawdown {o['max_drawdown']:.2f}", o["profit_factor"], rules["min_profit_factor_oos"])
    if o["net"] > 0 and o["max_drawdown"] > o["net"]:
        rep.d["warnings"].append("Out-of-sample drawdown is larger than out-of-sample profit.")
    dd_pct = 100 * broker.max_dd / broker.peak_margin if broker.peak_margin else 0.0
    g("drawdown", dd_pct <= rules["max_dd_pct_of_peak_margin"], f"max drawdown {broker.max_dd:.2f} = {dd_pct:.0f}% of peak margin {broker.peak_margin:.2f}", round(dd_pct, 1), rules["max_dd_pct_of_peak_margin"])

    try:
        same, detail = parity(bot_dir, cfg, candles[-(lb + int(rules["parity_candles"])) :], costs)
    except Exception as e:
        same, detail = False, f"{type(e).__name__}: {e}"
    g("parity", same, detail)
    if tf_ms(cfg["timeframe"]) >= tf_ms("15m"):
        rep.d["warnings"].append("Fills are simulated at the next candle open. Strategies that add or exit inside a candle need 1m data to judge (15m replay overstated ZEC about 6x).")
    return finish()


def parity(bot_dir: Path, cfg: dict, candles: list, costs: dict) -> tuple:
    """Backtest vs the live runner fed poll by poll (forming candles, repeats and
    multi-candle catch-ups included). Trades must match exactly."""
    lb = int(cfg["lookback"])
    bt = run_backtest(str(bot_dir), cfg, candles, costs)["trades"]
    step = tf_ms(cfg["timeframe"])
    broker = SimBroker(costs, RiskGuard(cfg["risk"]), cfg["leverage"], cfg["backtest"]["start_equity"])
    runner = LiveRunner(bot_dir, cfg, broker, persist=False)
    i = lb + 1  # first poll sees lookback history + the first tradable candle
    pattern = [1, 0, 1, 2, 1, 1, 3, 1]  # candles revealed per poll
    k = 0
    while i <= len(candles):
        visible = candles[max(0, i - lb - 2) : i]
        forming = None
        if i < len(candles):
            nxt = candles[i]
            forming = {**nxt, "c": nxt["o"]}  # the forming candle is filtered out by time
        now = visible[-1]["t"] + step + 1
        runner.poll(visible + ([forming] if forming else []), now)
        if i == len(candles):
            break
        i = min(len(candles), i + pattern[k % len(pattern)])
        k += 1
    lv = broker.trades

    def key(t):
        return (t["side"], t["entry_time"], t["exit_time"], round(t["qty"], 8), t["entries"], round(t["pnl"], 6))

    a, b = [key(t) for t in bt], [key(t) for t in lv]
    if a == b:
        return True, f"{len(a)} trades identical over {len(candles) - lb} candles"
    first = next((n for n, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return False, f"backtest {len(a)} trades vs live replay {len(b)}; first difference at trade #{first + 1}"


def _count(items) -> dict:
    out: dict = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out


def _equity_points(trades: list, max_points: int = 300) -> list:
    pts, cum = [], 0.0
    for t in trades:
        cum += t["pnl"]
        pts.append([t["exit_time"], round(cum, 4)])
    if len(pts) > max_points:
        stride = len(pts) / max_points
        pts = [pts[int(i * stride)] for i in range(max_points)] + [pts[-1]]
    return pts


def to_markdown(r: dict) -> str:
    icon = {"pass": "✅", "fail": "❌", "skip": "⏭️"}
    lines = [f"## {'✅' if r['ok'] else '❌'} {r['bot']}", "", "| Gate | Result | Detail |", "|---|---|---|"]
    for gt in r["gates"]:
        lines.append(f"| {gt['label']} | {icon[gt['status']]} | {gt['detail']} |")
    for name in ("overall", "in_sample", "out_of_sample"):
        if name in r:
            s = r[name]
            lines.append(f"\n**{name.replace('_', ' ')}**: net {s['net']:+.2f}, {s['trades']} trades, PF {s['profit_factor']}, DD {s['max_drawdown']:.2f}")
    for w in r.get("warnings", []):
        lines.append(f"\n> ⚠️ {w}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", default="", help="space-separated bot folder names; empty = all")
    ap.add_argument("--outside", default="", help="space-separated changed paths outside bots/")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args()
    rules = load_pipeline_rules(".")
    names = a.bots.split() or sorted(p.name for p in Path("bots").iterdir() if p.is_dir() and not p.name.startswith("_"))
    outside = a.outside.split()
    all_ok = True
    summary = []
    for name in names:
        bot_dir = Path("bots") / name
        if not bot_dir.is_dir():
            continue
        r = evaluate(bot_dir, rules, outside, allow_download=not a.no_download)
        out = Path(a.out) / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
        md = to_markdown(r)
        (out / "report.md").write_text(md, encoding="utf-8")
        summary.append(md)
        print(md)
        all_ok &= r["ok"]
    if not names:
        print("No bots to test.")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n".join(summary) or "No bots changed.\n")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
