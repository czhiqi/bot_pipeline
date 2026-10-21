import { eq } from "drizzle-orm";
import { apiUser } from "@/app/auth";
import { getDb } from "@/db";
import { strategies } from "@/db/schema";
import { GitHubError, openPullRequest } from "@/lib/github";
import { fail, sameOrigin } from "@/lib/http";
import { parseConfig, type GateReport } from "@/lib/pipeline";
import { filesHash, loadStrategy, toPublic } from "@/lib/strategies";

/** Opens a pull request strategy/<slug> → base for review. Only after the gates passed. */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  if (!sameOrigin(request, true)) return fail("bad_origin", 403);
  const row = await loadStrategy((await params).id, user);
  if (row instanceof Response) return row;
  if (row.status !== "passed" || row.gateStatus !== "pass") return fail("errNotPassed", 409);
  if (row.committedHash !== filesHash(row)) return fail("errDirty", 409);

  let report: GateReport | null = null;
  try {
    report = row.gateReport ? (JSON.parse(row.gateReport) as GateReport) : null;
  } catch {
    report = null;
  }
  const cfg = parseConfig(row.config).cfg;
  const s = (x?: { net: number; trades: number; profit_factor: number; max_drawdown: number }) =>
    x ? `net ${x.net >= 0 ? "+" : ""}${x.net.toFixed(2)} USDT · ${x.trades} trades · PF ${x.profit_factor} · DD ${x.max_drawdown.toFixed(2)}` : "—";
  const body = [
    `**${row.name}** · \`bots/${row.slug}/\` · ${cfg ? `${cfg.exchange} ${cfg.symbol} ${cfg.timeframe}, ${cfg.leverage}x, stop ${cfg.risk.stop_loss_pct}%` : ""}`,
    "",
    `Submitted by ${user.displayName} (${user.email}) from the strategy workspace. Commit ${row.commitSha.slice(0, 7)}.`,
    "",
    "### Gates",
    ...(report?.gates ?? []).map((g) => `- ${g.status === "pass" ? "✅" : g.status === "fail" ? "❌" : "⏭️"} ${g.label}: ${g.detail}`),
    "",
    `- Overall: ${s(report?.overall)}`,
    `- In-sample: ${s(report?.in_sample)}`,
    `- Out-of-sample: ${s(report?.out_of_sample)}`,
    ...(report?.warnings ?? []).map((w) => `- ⚠️ ${w}`),
    "",
    "### Reviewer checklist",
    "- [ ] Code does what hypothesis.md says, nothing else",
    "- [ ] Risk settings fit the account (size, leverage, stop)",
    "- [ ] Paper-trade period agreed before live keys",
  ].join("\n");

  try {
    const pr = await openPullRequest(row.branch, `Strategy: ${row.name}`, body);
    const patch = { status: "submitted" as const, prNumber: pr.number, prUrl: pr.url, error: "" };
    await getDb().update(strategies).set(patch).where(eq(strategies.id, row.id));
    return Response.json({ strategy: toPublic({ ...row, ...patch } as typeof row) });
  } catch (e) {
    console.error("[api/submit] failed:", e);
    return fail("errGithub", 502, { message: e instanceof GitHubError ? e.message : "" });
  }
}
