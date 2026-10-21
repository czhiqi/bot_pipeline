import "server-only";
import type { BotConfig, Hypothesis } from "./pipeline";
import { quickCheck } from "./pipeline";
import { STRATEGY_GUIDE } from "./templates";

/**
 * Bot generation through OpenRouter (server only; OPENROUTER_API_KEY never
 * reaches the browser). The model writes strategy.py against the engine
 * interface; the result is checked before it is shown, and again in CI.
 */

export function openrouterConfigured(): boolean {
  return !!process.env.OPENROUTER_API_KEY;
}

/** Models offered in the UI. The first one is the default. */
export function openrouterModels(): string[] {
  const list = (process.env.OPENROUTER_MODELS || process.env.OPENROUTER_MODEL || "~anthropic/claude-opus-latest")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return list.length ? list : ["~anthropic/claude-opus-latest"];
}

export type GenerateInput = {
  name: string;
  config: BotConfig;
  hypothesis: Hypothesis;
  spec: string;
  currentCode: string;
  instructions: string;
  mode: "new" | "revise";
  gateFeedback: string;
};

export type GenerateResult = {
  code: string;
  params: Record<string, unknown> | null;
  risk: Record<string, number> | null;
  notes: string;
  problems: string[];
  model: string;
  tokens: number | null;
};

function userPrompt(i: GenerateInput): string {
  const c = i.config;
  const parts = [
    `Bot: ${i.name} — ${c.exchange} ${c.symbol} perpetual, ${c.timeframe} candles, lookback ${c.lookback}, leverage ${c.leverage}x ${c.margin_mode}.`,
    `Current params: ${JSON.stringify(c.params)}. Current risk: ${JSON.stringify(c.risk)}.`,
    "",
    "## Hypothesis",
    i.spec.trim() ||
      [
        `Idea: ${i.hypothesis.idea}`,
        `Expected: ${i.hypothesis.expected}`,
        `Proven wrong if: ${i.hypothesis.invalidation}`,
        `Rules: ${i.hypothesis.rules}`,
        `Notes: ${i.hypothesis.notes}`,
      ].join("\n"),
  ];
  if (i.mode === "revise" && i.currentCode.trim()) {
    parts.push("", "## Current strategy.py (revise it; keep what already works)", "```python", i.currentCode.slice(0, 40_000), "```");
  }
  if (i.gateFeedback.trim()) parts.push("", "## Last pipeline result", i.gateFeedback.slice(0, 4000));
  if (i.instructions.trim()) parts.push("", "## Extra instructions from the author", i.instructions.slice(0, 4000));
  parts.push("", "Implement the hypothesis exactly. If a rule is ambiguous, choose the simplest reading and say so in notes.");
  return parts.join("\n");
}

function extract(text: string): { code: string; json: Record<string, unknown> | null } {
  const py = text.match(/```(?:python|py)\s*\n([\s\S]*?)```/i);
  const js = text.match(/```json\s*\n([\s\S]*?)```/i);
  let json: Record<string, unknown> | null = null;
  if (js) {
    try {
      json = JSON.parse(js[1]);
    } catch {
      json = null;
    }
  }
  return { code: (py ? py[1] : "").replace(/\s+$/, "") + "\n", json };
}

function numbers(o: unknown, keys: string[]): Record<string, number> | null {
  if (!o || typeof o !== "object") return null;
  const out: Record<string, number> = {};
  for (const k of keys) {
    const v = Number((o as Record<string, unknown>)[k]);
    if (Number.isFinite(v) && v >= 0) out[k] = v;
  }
  return Object.keys(out).length ? out : null;
}

export async function generateStrategy(input: GenerateInput, model: string): Promise<GenerateResult> {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) throw new Error("OPENROUTER_API_KEY is not set.");
  const base = (process.env.OPENROUTER_BASE_URL || "https://openrouter.ai/api/v1").replace(/\/$/, "");
  const res = await fetch(`${base}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${key}`,
      ...(process.env.APP_URL ? { "HTTP-Referer": process.env.APP_URL } : {}),
      "X-Title": "Forge strategy pipeline",
    },
    body: JSON.stringify({
      model,
      temperature: 0.2,
      max_tokens: Number(process.env.OPENROUTER_MAX_TOKENS) || 8000,
      messages: [
        { role: "system", content: STRATEGY_GUIDE },
        { role: "user", content: userPrompt(input) },
      ],
    }),
    signal: AbortSignal.timeout(180_000),
    cache: "no-store",
  });
  const body = (await res.json().catch(() => ({}))) as {
    error?: { message?: string };
    model?: string;
    usage?: { total_tokens?: number };
    choices?: { message?: { content?: string | { type: string; text?: string }[] } }[];
  };
  if (!res.ok || body.error) throw new Error(`OpenRouter ${res.status}: ${body.error?.message ?? "request failed"}`);
  const content = body.choices?.[0]?.message?.content;
  const text = Array.isArray(content) ? content.map((p) => p.text ?? "").join("") : content ?? "";
  const { code, json } = extract(text);
  if (!code.trim() || !/class\s+\w+\s*\(/.test(code)) throw new Error("The model did not return a strategy.py code block.");
  const params = json && json.params && typeof json.params === "object" ? (json.params as Record<string, unknown>) : null;
  return {
    code,
    params,
    risk: numbers(json?.risk, ["stop_loss_pct", "max_position_qty", "max_entries"]),
    notes: typeof json?.notes === "string" ? json.notes.slice(0, 1500) : "",
    problems: quickCheck(code),
    model: body.model || model,
    tokens: body.usage?.total_tokens ?? null,
  };
}
