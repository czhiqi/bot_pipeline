import { apiUser } from "@/app/auth";
import { getDb } from "@/db";
import { aiCallsLastHour, limits, logAiCall } from "@/db/queries";
import { fail, readJson } from "@/lib/http";
import { generateStrategy, openrouterConfigured, openrouterModels } from "@/lib/openrouter";
import { EMPTY_HYPOTHESIS, parseConfig, type GateReport, type Hypothesis } from "@/lib/pipeline";
import { loadStrategy, parseHypothesis, reportFeedback } from "@/lib/strategies";

export const maxDuration = 300;

/** OpenRouter writes (or revises) strategy.py. Returns the result; the page decides to keep it. */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  const row = await loadStrategy((await params).id, user);
  if (row instanceof Response) return row;
  const body = await readJson<{
    mode?: string;
    model?: string;
    instructions?: string;
    useReport?: boolean;
    hypothesis?: Partial<Hypothesis>;
    spec?: string;
    code?: string;
    config?: string;
  }>(request);
  if (body instanceof Response) return body;
  if (!openrouterConfigured()) return fail("errOpenrouterMissing", 503);

  const models = openrouterModels();
  const model = models.includes(String(body.model)) ? String(body.model) : models[0];
  const parsed = parseConfig(body.config ?? row.config);
  if (!parsed.cfg) return fail("errConfig", 400, { message: parsed.error });

  const db = getDb();
  if (!user.isAdmin && (await aiCallsLastHour(db, user.id)) >= limits().aiPerHour) return fail("errAiLimit", 429);

  const h: Hypothesis = { ...EMPTY_HYPOTHESIS, ...parseHypothesis(row.hypothesis), ...(body.hypothesis ?? {}) };
  const spec = typeof body.spec === "string" ? body.spec : row.spec;
  if (!h.idea.trim() && !h.rules.trim() && !spec.trim()) return fail("errHypothesisEmpty");
  let report: GateReport | null = null;
  try {
    report = body.useReport && row.gateReport ? (JSON.parse(row.gateReport) as GateReport) : null;
  } catch {
    report = null;
  }

  try {
    const out = await generateStrategy(
      {
        name: row.name,
        config: parsed.cfg,
        hypothesis: h,
        spec,
        currentCode: typeof body.code === "string" ? body.code : row.code,
        instructions: String(body.instructions ?? "").slice(0, 4000),
        mode: body.mode === "revise" ? "revise" : "new",
        gateFeedback: reportFeedback(report),
      },
      model
    );
    await logAiCall(db, { userId: user.id, kind: "generate", model: out.model, ok: true, tokens: out.tokens });
    return Response.json(out);
  } catch (e) {
    await logAiCall(db, { userId: user.id, kind: "generate", model, ok: false });
    console.error("[api/generate] failed:", e);
    return fail("errAi", 502, { message: e instanceof Error ? e.message.slice(0, 300) : "" });
  }
}
