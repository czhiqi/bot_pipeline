// Shared by server and browser (no secrets here).

export type Hypothesis = {
  idea: string;
  expected: string;
  invalidation: string;
  rules: string;
  notes: string;
};

export const EMPTY_HYPOTHESIS: Hypothesis = { idea: "", expected: "", invalidation: "", rules: "", notes: "" };

export const EXCHANGES = ["bitget", "binance"] as const;
export const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"] as const;

export type BotConfig = {
  name: string;
  exchange: string;
  symbol: string;
  timeframe: string;
  lookback: number;
  leverage: number;
  margin_mode: string;
  params: Record<string, unknown>;
  risk: { stop_loss_pct: number; max_position_qty: number; max_entries: number; daily_loss_limit_usdt: number };
  costs: { taker_fee_pct: number; slippage_pct: number };
  backtest: { months: number; start_equity: number };
  live: { poll_seconds: number };
};

export function defaultConfig(slug: string, exchange = "bitget", symbol = "ETH/USDT:USDT", timeframe = "1h"): BotConfig {
  return {
    name: slug,
    exchange,
    symbol,
    timeframe,
    lookback: 1000,
    leverage: 3,
    margin_mode: "isolated",
    params: { qty: 0.02 },
    risk: { stop_loss_pct: 4, max_position_qty: 0.1, max_entries: 3, daily_loss_limit_usdt: 0 },
    costs: { taker_fee_pct: 0.06, slippage_pct: 0.05 },
    backtest: { months: 24, start_equity: 1000 },
    live: { poll_seconds: 10 },
  };
}

export function parseConfig(text: string): { cfg?: BotConfig; error?: string } {
  try {
    const cfg = JSON.parse(text) as BotConfig;
    if (!cfg || typeof cfg !== "object") return { error: "config.json must be an object" };
    if (!EXCHANGES.includes(cfg.exchange as (typeof EXCHANGES)[number])) return { error: "exchange must be bitget or binance" };
    if (!TIMEFRAMES.includes(cfg.timeframe as (typeof TIMEFRAMES)[number])) return { error: `timeframe must be one of ${TIMEFRAMES.join(", ")}` };
    if (typeof cfg.symbol !== "string" || !/^[A-Z0-9]+\/[A-Z0-9]+:[A-Z0-9]+$/.test(cfg.symbol)) return { error: "symbol must look like ETH/USDT:USDT" };
    if (!(Number(cfg.leverage) >= 1 && Number(cfg.leverage) <= 125)) return { error: "leverage must be 1–125" };
    if (!(Number(cfg.lookback) >= 100)) return { error: "lookback must be at least 100" };
    if (!(Number(cfg.params?.qty) > 0)) return { error: "params.qty must be > 0" };
    if (!(Number(cfg.risk?.max_position_qty) > 0)) return { error: "risk.max_position_qty must be > 0" };
    return { cfg };
  } catch (e) {
    return { error: `config.json is not valid JSON: ${e instanceof Error ? e.message : e}` };
  }
}

export function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "strategy"
  );
}

/** Data file name the engine looks for (engine/data.py data_path). */
export function dataFileName(cfg: Pick<BotConfig, "exchange" | "symbol" | "timeframe">): string {
  return `data/${cfg.exchange}_${cfg.symbol.replace("/", "").replace(":", "_")}_${cfg.timeframe}.csv`;
}

export function hypothesisMarkdown(name: string, h: Hypothesis): string {
  const sec = (title: string, body: string) => (body.trim() ? `## ${title}\n${body.trim()}\n` : "");
  return [
    `# Hypothesis: ${name}\n`,
    sec("Idea", h.idea),
    sec("Expected effect", h.expected),
    sec("What would prove it wrong", h.invalidation),
    sec("Rules", h.rules),
    sec("Notes", h.notes),
  ]
    .filter(Boolean)
    .join("\n");
}

// ---- static code check (mirror of engine/sandbox_check.py, for instant feedback) ----

const ALLOWED_IMPORTS = new Set(["math", "statistics", "dataclasses", "typing", "collections", "itertools", "functools", "enum", "__future__", "engine", "engine.strategy"]);
const BANNED = ["eval", "exec", "compile", "open", "__import__", "globals", "locals", "vars", "getattr", "setattr", "delattr", "input", "breakpoint", "exit", "quit", "memoryview", "help"];

/** Quick check in the browser and before commit. CI runs the real AST check. */
export function quickCheck(code: string): string[] {
  const problems: string[] = [];
  if (!code.trim()) return ["strategy.py is empty"];
  if (new TextEncoder().encode(code).length > 100_000) return ["strategy.py is larger than 100 KB"];
  // Blank out triple-quoted strings (docstrings) but keep their newlines so line numbers stay right.
  const noDocs = code.replace(/("""|''')[\s\S]*?\1/g, (m) => '""' + m.replace(/[^\n]/g, "").replace(/\n/g, "\n"));
  const lines = noDocs.split("\n");
  let classes = 0;
  lines.forEach((raw, i) => {
    const line = raw.replace(/#.*$/, "").replace(/(["'])(?:\\.|(?!\1).)*\1/g, '""');
    const n = i + 1;
    let m = line.match(/^\s*import\s+(.+)$/);
    if (m) {
      for (const part of m[1].split(",")) {
        const mod = part.trim().split(/\s+/)[0];
        if (mod && !ALLOWED_IMPORTS.has(mod)) problems.push(`line ${n}: import ${mod} is not allowed`);
      }
    }
    m = line.match(/^\s*from\s+(\S+)\s+import\b/);
    if (m && !ALLOWED_IMPORTS.has(m[1])) problems.push(`line ${n}: from ${m[1]} import … is not allowed`);
    for (const b of BANNED) {
      // a bare name (not an attribute like self.open), same as the AST check
      if (new RegExp(`(^|[^\\w.])${b}\\b`).test(line)) problems.push(`line ${n}: ${b} is not allowed`);
    }
    const dunder = line.match(/\.(__\w+__)/);
    if (dunder && dunder[1] !== "__init__") problems.push(`line ${n}: attribute ${dunder[1]} is not allowed`);
    if (/^\s*(global|nonlocal)\s/.test(line)) problems.push(`line ${n}: global/nonlocal is not allowed; use ctx.state`);
    if (/^\s*class\s+\w+\s*\([^)]*\bStrategy\b[^)]*\)\s*:/.test(line)) classes++;
  });
  if (classes !== 1) problems.push(`Define exactly one class that subclasses Strategy (found ${classes})`);
  return [...new Set(problems)];
}

// ---- gate report (written by engine/pipeline.py) ----

export type Gate = { id: string; label: string; status: "pass" | "fail" | "skip"; detail: string; value?: number | null; limit?: number | null };
export type Summary = {
  trades: number;
  net: number;
  win_rate: number;
  profit_factor: number;
  avg_trade: number;
  max_drawdown: number;
  fees: number;
  stop_losses: number;
  peak_margin?: number;
  return_on_peak_margin_pct?: number;
};
export type GateReport = {
  bot: string;
  ok: boolean;
  engine: string;
  generated_at: number;
  gates: Gate[];
  warnings: string[];
  data?: { source: string; candles: number; from: number; to: number; months: number };
  costs_used?: { taker_fee_pct: number; slippage_pct: number };
  overall?: Summary;
  in_sample?: Summary;
  out_of_sample?: Summary;
  oos_from?: number;
  blocked?: Record<string, number>;
  equity?: [number, number][];
  last_trades?: { side: string; entry_time: number; exit_time: number; qty: number; entries: number; avg_entry: number; exit_price: number; pnl: number; reason: string }[];
};
