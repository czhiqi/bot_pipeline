import { apiUser } from "@/app/auth";
import { getDb } from "@/db";
import { aiCallsLastHour, limits, logAiCall } from "@/db/queries";
import { geminiBeautify, geminiConfigured, geminiModel } from "@/lib/gemini";
import { fail, readJson } from "@/lib/http";
import { normalizeLang } from "@/lib/i18n";
import { EMPTY_HYPOTHESIS, hypothesisMarkdown, parseConfig, type Hypothesis } from "@/lib/pipeline";
import { loadStrategy, parseHypothesis } from "@/lib/strategies";

/** Gemini rewrites the rough hypothesis into a clear, testable one. Returns it; the page decides to keep it. */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  const row = await loadStrategy((await params).id, user);
  if (row instanceof Response) return row;
  const body = await readJson<{ hypothesis?: Partial<Hypothesis>; config?: string; lang?: string }>(request);
  if (body instanceof Response) return body;
  if (!geminiConfigured()) return fail("errGeminiMissing", 503);

  const db = getDb();
  if (!user.isAdmin && (await aiCallsLastHour(db, user.id)) >= limits().aiPerHour) return fail("errAiLimit", 429);

  const h: Hypothesis = { ...EMPTY_HYPOTHESIS, ...parseHypothesis(row.hypothesis), ...(body.hypothesis ?? {}) };
  if (!h.idea.trim() && !h.rules.trim()) return fail("errHypothesisEmpty");
  const cfg = parseConfig(body.config ?? row.config).cfg;

  try {
    const out = await geminiBeautify(
      { name: row.name, exchange: cfg?.exchange ?? "?", symbol: cfg?.symbol ?? "?", timeframe: cfg?.timeframe ?? "?", hypothesis: h },
      normalizeLang(body.lang)
    );
    await logAiCall(db, { userId: user.id, kind: "beautify", model: geminiModel(), ok: true });
    return Response.json({ hypothesis: out.hypothesis, questions: out.questions, markdown: hypothesisMarkdown(row.name, out.hypothesis) });
  } catch (e) {
    await logAiCall(db, { userId: user.id, kind: "beautify", model: geminiModel(), ok: false });
    console.error("[api/beautify] failed:", e);
    return fail("errAi", 502, { message: e instanceof Error ? e.message.slice(0, 300) : "" });
  }
}
