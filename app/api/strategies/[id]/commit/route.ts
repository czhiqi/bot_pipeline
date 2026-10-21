import { eq } from "drizzle-orm";
import { apiUser } from "@/app/auth";
import { getDb } from "@/db";
import { limits } from "@/db/queries";
import { strategies } from "@/db/schema";
import { commitFiles, GitHubError, githubConfigured, type RepoFile } from "@/lib/github";
import { fail, sameOrigin } from "@/lib/http";
import { dataFileName, parseConfig, quickCheck } from "@/lib/pipeline";
import { allowCommit, botFiles, filesHash, loadStrategy, toPublic } from "@/lib/strategies";

export const maxDuration = 120;

const MAX_DATA_BYTES = (Number(process.env.MAX_DATA_MB) || 25) * 1024 * 1024;

/**
 * Commits the saved draft (strategy.py, config.json, hypothesis.md) to
 * strategy/<slug>, plus an optional candle CSV for data/. The push starts the
 * GitHub Actions gates. Multipart form: message, data (optional .csv).
 */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  if (!sameOrigin(request, true)) return fail("bad_origin", 403);
  const row = await loadStrategy((await params).id, user);
  if (row instanceof Response) return row;
  if (!githubConfigured()) return fail("errGithubMissing", 503);
  if (row.status === "merged") return fail("errMerged", 409);

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return fail("errGeneric", 400);
  }
  const message = String(form.get("message") ?? "").trim().slice(0, 200);

  const parsed = parseConfig(row.config);
  if (!parsed.cfg) return fail("errConfig", 400, { message: parsed.error });
  const problems = quickCheck(row.code);
  if (problems.length) return fail("errCodeCheck", 422, { problems });

  const files: RepoFile[] = botFiles(row);
  const data = form.get("data");
  if (data instanceof File && data.size > 0) {
    if (data.size > MAX_DATA_BYTES) return fail("errDataSize", 413);
    const text = await data.text();
    const header = text.slice(0, 200).split(/\r?\n/)[0].trim().toLowerCase().replace(/\s/g, "");
    if (header !== "t,o,h,l,c,v") return fail("errDataHeader");
    files.push({ path: dataFileName(parsed.cfg), content: text });
  }

  if (!user.isAdmin && !allowCommit(user.id, limits().commitsPerHour)) return fail("errCommitLimit", 429);

  try {
    const sha = await commitFiles(
      row.branch,
      files,
      `bots/${row.slug}: ${message || "update strategy"}\n\nCommitted from the strategy workspace by ${user.email}.`
    );
    const patch = {
      status: "testing" as const,
      commitSha: sha,
      committedHash: filesHash(row),
      committedAt: new Date(),
      gateStatus: "queued",
      gateReport: null,
      runId: "",
      runUrl: "",
      error: "",
      lastCheckedAt: null,
    };
    await getDb().update(strategies).set(patch).where(eq(strategies.id, row.id));
    return Response.json({ strategy: toPublic({ ...row, ...patch } as typeof row) });
  } catch (e) {
    console.error("[api/commit] failed:", e);
    return fail("errGithub", 502, { message: e instanceof GitHubError ? e.message : "" });
  }
}
