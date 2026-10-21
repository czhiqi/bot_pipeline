import "server-only";
import type { Lang } from "./i18n";
import type { Hypothesis } from "./pipeline";

/**
 * "Beautify" with Google Gemini (server only; GEMINI_API_KEY never reaches the
 * browser). Rewrites a rough hypothesis into a clear, testable one. Strict JSON
 * via responseSchema, validated before use.
 */

export function geminiConfigured(): boolean {
  return !!process.env.GEMINI_API_KEY;
}

export function geminiModel(): string {
  return process.env.GEMINI_MODEL || "gemini-3.8-flash";
}

const SCHEMA = {
  type: "OBJECT",
  properties: {
    idea: { type: "STRING", description: "The market behaviour being exploited, 2-4 sentences" },
    expected: { type: "STRING", description: "What results should look like if the idea is right: trade frequency, win/loss shape, which conditions it should work in" },
    invalidation: { type: "STRING", description: "Concrete, checkable conditions that would prove it wrong, as '- ' bullet lines" },
    rules: { type: "STRING", description: "Entry, add, exit and filter rules as precise '- ' bullet lines, with every number the user gave" },
    notes: { type: "STRING", description: "Assumptions you had to make, as '- ' bullet lines; empty if none" },
    questions: { type: "ARRAY", items: { type: "STRING" }, description: "Up to 4 ambiguities the author must decide before coding" },
  },
  required: ["idea", "expected", "invalidation", "rules", "notes", "questions"],
};

export type BeautifyInput = { name: string; exchange: string; symbol: string; timeframe: string; hypothesis: Hypothesis };

function buildPrompt(input: BeautifyInput, lang: Lang): string {
  const language = lang === "zh" ? "Simplified Chinese (简体中文), keeping indicator names such as EMA/RSI in English" : "English";
  const h = input.hypothesis;
  return [
    "You are a quantitative trading reviewer. Rewrite this rough strategy hypothesis so another developer can code and test it.",
    `Strategy: ${input.name} · ${input.exchange} ${input.symbol} perpetual · ${input.timeframe} candles`,
    "",
    `Idea: ${h.idea || "(empty)"}`,
    `Expected effect: ${h.expected || "(empty)"}`,
    `What would prove it wrong: ${h.invalidation || "(empty)"}`,
    `Rules: ${h.rules || "(empty)"}`,
    `Notes: ${h.notes || "(empty)"}`,
    "",
    "Rules for you:",
    "- Keep the author's idea and every number they gave. Do not add new indicators, filters or parameters they did not ask for; put suggestions in questions instead.",
    "- Make rules precise: closed-candle conditions, which timeframe, what triggers entry, adds, exit.",
    "- Invalidation must be checkable from a backtest report (out-of-sample net, profit factor, drawdown, trade count, regime split).",
    "- Never invent backtest results, win rates or profit claims.",
    "- Use plain, short sentences.",
    `Write every field in ${language}.`,
  ].join("\n");
}

function clean(v: unknown, max: number): string {
  return typeof v === "string" ? v.replace(/\r/g, "").replace(/\n{3,}/g, "\n\n").trim().slice(0, max) : "";
}

export async function geminiBeautify(input: BeautifyInput, lang: Lang): Promise<{ hypothesis: Hypothesis; questions: string[] }> {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new Error("GEMINI_API_KEY is not set.");
  const base = (process.env.GEMINI_BASE_URL || "https://generativelanguage.googleapis.com").replace(/\/$/, "");

  const res = await fetch(`${base}/v1beta/models/${encodeURIComponent(geminiModel())}:generateContent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": key },
    body: JSON.stringify({
      contents: [{ role: "user", parts: [{ text: buildPrompt(input, lang) }] }],
      generationConfig: { responseMimeType: "application/json", responseSchema: SCHEMA, temperature: 0.4 },
    }),
    signal: AbortSignal.timeout(60_000),
    cache: "no-store",
  });

  const body = (await res.json().catch(() => ({}))) as {
    error?: { message?: string };
    candidates?: { content?: { parts?: { text?: string }[] } }[];
  };
  if (!res.ok) throw new Error(`Gemini ${res.status}: ${body.error?.message ?? "request failed"}`);

  const text = (body.candidates?.[0]?.content?.parts ?? []).map((p) => p.text ?? "").join("");
  let r: Record<string, unknown>;
  try {
    r = JSON.parse(text);
  } catch {
    throw new Error("Gemini returned no usable JSON.");
  }
  const hypothesis: Hypothesis = {
    idea: clean(r.idea, 2000),
    expected: clean(r.expected, 2000),
    invalidation: clean(r.invalidation, 2000),
    rules: clean(r.rules, 4000),
    notes: clean(r.notes, 2000),
  };
  if (!hypothesis.idea || !hypothesis.rules) throw new Error("Gemini returned an incomplete hypothesis.");
  const questions = Array.isArray(r.questions) ? r.questions.map((q) => clean(q, 300)).filter(Boolean).slice(0, 4) : [];
  return { hypothesis, questions };
}
