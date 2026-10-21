import { eq } from "drizzle-orm";
import { apiUser } from "@/app/auth";
import { getDb } from "@/db";
import { strategies } from "@/db/schema";
import { deleteBranch } from "@/lib/github";
import { fail, readJson, sameOrigin } from "@/lib/http";
import type { Hypothesis } from "@/lib/pipeline";
import { loadStrategy, refreshFromGitHub, toPublic } from "@/lib/strategies";

type Ctx = { params: Promise<{ id: string }> };

/** The strategy, after checking GitHub for a finished gate run or merged PR. */
export async function GET(_request: Request, { params }: Ctx) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  const row = await loadStrategy((await params).id, user);
  if (row instanceof Response) return row;
  return Response.json({ strategy: toPublic(await refreshFromGitHub(row)) });
}

/** Saves the draft. Nothing reaches GitHub until "Commit & run gates". */
export async function PATCH(request: Request, { params }: Ctx) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  const row = await loadStrategy((await params).id, user);
  if (row instanceof Response) return row;
  const body = await readJson<{ name?: string; hypothesis?: Partial<Hypothesis>; spec?: string; code?: string; config?: string }>(request);
  if (body instanceof Response) return body;

  const patch: Partial<typeof strategies.$inferInsert> = {};
  if (typeof body.name === "string" && body.name.trim().length >= 3) patch.name = body.name.trim().slice(0, 80);
  if (body.hypothesis && typeof body.hypothesis === "object") {
    const h = body.hypothesis;
    const s = (v: unknown, max: number) => (typeof v === "string" ? v.slice(0, max) : "");
    patch.hypothesis = JSON.stringify({ idea: s(h.idea, 4000), expected: s(h.expected, 4000), invalidation: s(h.invalidation, 4000), rules: s(h.rules, 8000), notes: s(h.notes, 4000) });
  }
  if (typeof body.spec === "string") patch.spec = body.spec.slice(0, 30_000);
  if (typeof body.code === "string") {
    if (body.code.length > 100_000) return fail("errCodeSize", 413);
    patch.code = body.code;
  }
  if (typeof body.config === "string") {
    if (body.config.length > 20_000) return fail("errConfigSize", 413);
    patch.config = body.config;
  }
  if (Object.keys(patch).length === 0) return Response.json({ strategy: toPublic(row) });
  await getDb().update(strategies).set(patch).where(eq(strategies.id, row.id));
  return Response.json({ strategy: toPublic({ ...row, ...patch, updatedAt: new Date() } as typeof row) });
}

/** Archives the strategy and deletes its branch (merged code stays on the base branch). */
export async function DELETE(request: Request, { params }: Ctx) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  if (!sameOrigin(request, true)) return fail("bad_origin", 403);
  const row = await loadStrategy((await params).id, user);
  if (row instanceof Response) return row;
  try {
    await deleteBranch(row.branch);
  } catch (e) {
    console.error("[api/strategies] delete branch failed:", e);
  }
  // Free the slug so the name can be reused.
  await getDb()
    .update(strategies)
    .set({ status: "archived", slug: `${row.slug}~${row.id}`.slice(0, 60) })
    .where(eq(strategies.id, row.id));
  return Response.json({ ok: true });
}
