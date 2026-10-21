import "server-only";
import { createHash } from "crypto";
import { eq } from "drizzle-orm";
import type { SessionUser } from "@/app/auth";
import { getDb } from "@/db";
import { strategies } from "@/db/schema";
import { GitHubError, pullState, runForCommit, runReport } from "./github";
import { fail } from "./http";
import { EMPTY_HYPOTHESIS, hypothesisMarkdown, type GateReport, type Hypothesis } from "./pipeline";

export type StrategyRow = typeof strategies.$inferSelect;

export function parseHypothesis(text: string): Hypothesis {
  try {
    return { ...EMPTY_HYPOTHESIS, ...(JSON.parse(text) as Partial<Hypothesis>) };
  } catch {
    return { ...EMPTY_HYPOTHESIS };
  }
}

/** The three files committed to bots/<slug>/. */
export function botFiles(row: Pick<StrategyRow, "slug" | "name" | "hypothesis" | "spec" | "code" | "config">) {
  const dir = `bots/${row.slug}`;
  const md = row.spec.trim() ? row.spec : hypothesisMarkdown(row.name, parseHypothesis(row.hypothesis));
  return [
    { path: `${dir}/strategy.py`, content: row.code.endsWith("\n") ? row.code : row.code + "\n" },
    { path: `${dir}/config.json`, content: row.config.endsWith("\n") ? row.config : row.config + "\n" },
    { path: `${dir}/hypothesis.md`, content: md.endsWith("\n") ? md : md + "\n" },
  ];
}

export function filesHash(row: Parameters<typeof botFiles>[0]): string {
  const h = createHash("sha256");
  for (const f of botFiles(row)) h.update(f.path).update("\0").update(f.content).update("\0");
  return h.digest("hex");
}

/** Loads a strategy the user may see (owner or admin), or a 404 Response. */
export async function loadStrategy(idRaw: string, user: SessionUser): Promise<StrategyRow | Response> {
  const id = Number(idRaw);
  if (!Number.isSafeInteger(id)) return fail("errNotFound", 404);
  const [row] = await getDb().select().from(strategies).where(eq(strategies.id, id)).limit(1);
  if (!row || row.status === "archived" || (row.userId !== user.id && !user.isAdmin)) return fail("errNotFound", 404);
  return row;
}

export function toPublic(row: StrategyRow) {
  let report: GateReport | null = null;
  try {
    report = row.gateReport ? (JSON.parse(row.gateReport) as GateReport) : null;
  } catch {
    report = null;
  }
  return {
    id: row.id,
    userId: row.userId,
    name: row.name,
    slug: row.slug,
    branch: row.branch,
    hypothesis: parseHypothesis(row.hypothesis),
    spec: row.spec,
    code: row.code,
    config: row.config,
    status: row.status,
    dirty: !row.commitSha || row.committedHash !== filesHash(row),
    commitSha: row.commitSha,
    committedAt: row.committedAt ? new Date(row.committedAt).getTime() : null,
    gateStatus: row.gateStatus,
    report,
    runUrl: row.runUrl,
    prNumber: row.prNumber,
    prUrl: row.prUrl,
    error: row.error,
    updatedAt: new Date(row.updatedAt).getTime(),
  };
}
export type PublicStrategy = ReturnType<typeof toPublic>;

const CHECK_EVERY_MS = 10_000;
const RUN_START_TIMEOUT_MS = 15 * 60 * 1000;

/** Polls GitHub for the gate run / PR state when the strategy is waiting on them. */
export async function refreshFromGitHub(row: StrategyRow): Promise<StrategyRow> {
  const now = Date.now();
  if (row.lastCheckedAt && now - new Date(row.lastCheckedAt).getTime() < CHECK_EVERY_MS) return row;
  const db = getDb();
  const patch: Partial<StrategyRow> = { lastCheckedAt: new Date(now) };
  try {
    if (row.status === "testing" && row.commitSha) {
      const run = await runForCommit(row.branch, row.commitSha);
      if (!run) {
        const since = row.committedAt ? now - new Date(row.committedAt).getTime() : 0;
        if (since > RUN_START_TIMEOUT_MS) {
          Object.assign(patch, { status: "failed", gateStatus: "error", error: "No GitHub Actions run started for this commit. Check that .github/workflows/pipeline.yml is on the base branch and Actions are enabled." });
        } else {
          patch.gateStatus = "queued";
        }
      } else {
        patch.runId = String(run.id);
        patch.runUrl = run.url;
        if (run.status !== "completed") {
          patch.gateStatus = run.status === "in_progress" ? "running" : "queued";
        } else {
          const report = (await runReport(run.id, row.slug)) as GateReport | null;
          if (report) {
            Object.assign(patch, { gateReport: JSON.stringify(report), gateStatus: report.ok ? "pass" : "fail", status: report.ok ? "passed" : "failed", error: "" });
          } else {
            Object.assign(patch, {
              gateStatus: "error",
              status: "failed",
              error: run.conclusion === "success" ? "The run finished but no report was found for this bot." : `The pipeline run ended with "${run.conclusion}" before writing a report. Open the run log.`,
            });
          }
        }
      }
    } else if (row.status === "submitted" && row.prNumber) {
      const pr = await pullState(row.prNumber);
      if (pr.merged) patch.status = "merged";
      else if (pr.state === "closed") Object.assign(patch, { status: "passed", prNumber: null, prUrl: "" });
    } else {
      return row;
    }
  } catch (e) {
    console.error("[strategies] GitHub refresh failed:", e);
    patch.error = (e instanceof GitHubError ? e.message : "GitHub check failed").slice(0, 500);
  }
  await db.update(strategies).set(patch).where(eq(strategies.id, row.id));
  return { ...row, ...patch } as StrategyRow;
}

// Per-process limiter for commits (each one starts a CI run).
const commitHits = new Map<number, number[]>();
export function allowCommit(userId: number, maxPerHour: number): boolean {
  if (maxPerHour <= 0) return true;
  const now = Date.now();
  const recent = (commitHits.get(userId) ?? []).filter((t) => now - t < 3600_000);
  if (recent.length >= maxPerHour) {
    commitHits.set(userId, recent);
    return false;
  }
  recent.push(now);
  commitHits.set(userId, recent);
  return true;
}

/** Plain-text summary of a failed report, fed back to the code model on "revise". */
export function reportFeedback(report: GateReport | null): string {
  if (!report) return "";
  const lines = report.gates.filter((g) => g.status === "fail").map((g) => `FAILED ${g.label}: ${g.detail}`);
  const o = report.out_of_sample;
  if (o) lines.push(`Out-of-sample: net ${o.net}, ${o.trades} trades, profit factor ${o.profit_factor}, drawdown ${o.max_drawdown}`);
  const a = report.overall;
  if (a) lines.push(`Overall: net ${a.net}, ${a.trades} trades, win rate ${a.win_rate}%, stop-losses ${a.stop_losses}`);
  return lines.join("\n");
}
