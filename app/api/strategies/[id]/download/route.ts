import { apiUser } from "@/app/auth";
import { buildDeployZip, GitHubError, repoName } from "@/lib/github";
import { fail } from "@/lib/http";
import { loadStrategy } from "@/lib/strategies";

export const maxDuration = 120;

/**
 * Deployable zip of the committed version: engine/, bots/<slug>/, run_bot.py,
 * requirements.txt, .env.example, DEPLOY.md and BOT.txt. Owners need passed
 * gates; admins can download any committed version.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  const row = await loadStrategy((await params).id, user);
  if (row instanceof Response) return row;
  if (!row.commitSha) return fail("errNotCommitted", 409);
  if (row.gateStatus !== "pass" && !user.isAdmin) return fail("errNotPassed", 409);

  const info = [
    `bot: ${row.slug}`,
    `name: ${row.name}`,
    `repo: ${repoName()}`,
    `branch: ${row.branch}`,
    `commit: ${row.commitSha}`,
    `gates: ${row.gateStatus || "not run"}`,
    `status: ${row.status}`,
    `built: ${new Date().toISOString()} by ${user.email}`,
    "",
    `Start (paper): python run_bot.py bots/${row.slug}`,
    "See DEPLOY.md before going live.",
    "",
  ].join("\n");
  try {
    const zip = await buildDeployZip(row.commitSha, row.slug, info);
    return new Response(zip as unknown as BodyInit, {
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": `attachment; filename="${row.slug}-${row.commitSha.slice(0, 7)}.zip"`,
        "Cache-Control": "no-store",
      },
    });
  } catch (e) {
    console.error("[api/download] failed:", e);
    return fail("errGithub", 502, { message: e instanceof GitHubError ? e.message : "" });
  }
}
