import "server-only";
import JSZip from "jszip";

/**
 * GitHub REST client for the one strategy repo (GITHUB_REPO = owner/repo).
 * GITHUB_TOKEN is a fine-grained token limited to that repo with
 * Contents: read & write, Pull requests: read & write, Actions: read.
 * It never reaches the browser.
 */

export class GitHubError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function githubConfigured(): boolean {
  return !!process.env.GITHUB_TOKEN && /^[\w.-]+\/[\w.-]+$/.test(process.env.GITHUB_REPO ?? "");
}

export function repoName(): string {
  return process.env.GITHUB_REPO ?? "";
}

export function baseBranch(): string {
  return process.env.GITHUB_BASE_BRANCH || "main";
}

function api(): string {
  return (process.env.GITHUB_API_URL || "https://api.github.com").replace(/\/$/, "");
}

export function repoUrl(path = ""): string {
  return `https://github.com/${repoName()}${path}`;
}

async function gh<T = unknown>(path: string, init: RequestInit & { raw?: boolean } = {}): Promise<T> {
  if (!githubConfigured()) throw new GitHubError(500, "GitHub is not configured (GITHUB_TOKEN / GITHUB_REPO).");
  const res = await fetch(`${api()}/repos/${repoName()}${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "forge-strategy-pipeline",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
    cache: "no-store",
    signal: init.signal ?? AbortSignal.timeout(60_000),
  });
  if (init.raw) {
    if (!res.ok) throw new GitHubError(res.status, `GitHub ${res.status} on ${path}`);
    return res as unknown as T;
  }
  if (res.status === 204) return undefined as T;
  const body = (await res.json().catch(() => ({}))) as { message?: string };
  if (!res.ok) {
    if (res.status === 409 && /empty/i.test(body.message ?? "")) {
      throw new GitHubError(409, `Repository ${repoName()} is empty. Push the repo-template folder to the ${baseBranch()} branch first (SETUP.md step 1).`);
    }
    throw new GitHubError(res.status, `GitHub ${res.status}: ${body.message ?? "request failed"}`);
  }
  return body as T;
}

const enc = (s: string) => s.split("/").map(encodeURIComponent).join("/");

// ---------- branches ----------

export async function branchSha(branch: string): Promise<string | null> {
  try {
    const ref = await gh<{ object: { sha: string } }>(`/git/ref/heads/${enc(branch)}`);
    return ref.object.sha;
  } catch (e) {
    if (e instanceof GitHubError && (e.status === 404 || e.status === 409)) return null;
    throw e;
  }
}

export async function createBranch(branch: string): Promise<string> {
  const base = await branchSha(baseBranch());
  if (!base) throw new GitHubError(404, `Branch ${baseBranch()} not found in ${repoName()}. If the repository is new, push the repo-template folder to ${baseBranch()} first (SETUP.md step 1).`);
  await gh(`/git/refs`, { method: "POST", body: JSON.stringify({ ref: `refs/heads/${branch}`, sha: base }) });
  return base;
}

export async function deleteBranch(branch: string): Promise<void> {
  try {
    await gh(`/git/refs/heads/${enc(branch)}`, { method: "DELETE" });
  } catch (e) {
    if (!(e instanceof GitHubError && (e.status === 404 || e.status === 422))) throw e;
  }
}

// ---------- files ----------

export type RepoFile = { path: string; content: string | Uint8Array };

/** One commit with several files (creates the branch from the base if it's gone). */
export async function commitFiles(branch: string, files: RepoFile[], message: string): Promise<string> {
  let parent = await branchSha(branch);
  if (!parent) parent = await createBranch(branch);
  const parentCommit = await gh<{ tree: { sha: string } }>(`/git/commits/${parent}`);
  const tree: { path: string; mode: string; type: string; sha: string }[] = [];
  for (const f of files) {
    const isText = typeof f.content === "string";
    const blob = await gh<{ sha: string }>(`/git/blobs`, {
      method: "POST",
      body: JSON.stringify(
        isText
          ? { content: f.content, encoding: "utf-8" }
          : { content: Buffer.from(f.content as Uint8Array).toString("base64"), encoding: "base64" }
      ),
    });
    tree.push({ path: f.path, mode: "100644", type: "blob", sha: blob.sha });
  }
  const newTree = await gh<{ sha: string }>(`/git/trees`, {
    method: "POST",
    body: JSON.stringify({ base_tree: parentCommit.tree.sha, tree }),
  });
  const commit = await gh<{ sha: string }>(`/git/commits`, {
    method: "POST",
    body: JSON.stringify({ message, tree: newTree.sha, parents: [parent] }),
  });
  await gh(`/git/refs/heads/${enc(branch)}`, { method: "PATCH", body: JSON.stringify({ sha: commit.sha, force: false }) });
  return commit.sha;
}

export async function readFile(ref: string, path: string): Promise<string | null> {
  try {
    const f = await gh<{ content?: string; encoding?: string; type?: string }>(`/contents/${enc(path)}?ref=${encodeURIComponent(ref)}`);
    if (f.type !== "file" || f.content == null) return null;
    return Buffer.from(f.content, (f.encoding as BufferEncoding) || "base64").toString("utf-8");
  } catch (e) {
    if (e instanceof GitHubError && e.status === 404) return null;
    throw e;
  }
}

/** Bot folders on a ref (bots/<name>/ that contain strategy.py). */
export async function listBots(ref = baseBranch()): Promise<string[]> {
  try {
    const items = await gh<{ name: string; type: string }[]>(`/contents/bots?ref=${encodeURIComponent(ref)}`);
    return items.filter((i) => i.type === "dir" && !i.name.startsWith("_")).map((i) => i.name);
  } catch (e) {
    if (e instanceof GitHubError && e.status === 404) return [];
    throw e;
  }
}

// ---------- actions ----------

export type RunInfo = { id: number; status: string; conclusion: string | null; url: string; sha: string };

export async function runForCommit(branch: string, sha: string): Promise<RunInfo | null> {
  const r = await gh<{ workflow_runs: { id: number; status: string; conclusion: string | null; html_url: string; head_sha: string; name: string; event: string }[] }>(
    `/actions/runs?branch=${encodeURIComponent(branch)}&head_sha=${sha}&per_page=10`
  );
  const run = r.workflow_runs.find((w) => w.head_sha === sha && w.event === "push") ?? r.workflow_runs.find((w) => w.head_sha === sha);
  return run ? { id: run.id, status: run.status, conclusion: run.conclusion, url: run.html_url, sha: run.head_sha } : null;
}

/** reports/<slug>/report.json from the run's "pipeline-report" artifact. */
export async function runReport(runId: number, slug: string): Promise<unknown | null> {
  const arts = await gh<{ artifacts: { id: number; name: string; expired: boolean }[] }>(`/actions/runs/${runId}/artifacts`);
  const art = arts.artifacts.find((a) => a.name === "pipeline-report" && !a.expired);
  if (!art) return null;
  const res = await gh<Response>(`/actions/artifacts/${art.id}/zip`, { raw: true });
  const zip = await JSZip.loadAsync(await res.arrayBuffer());
  const key = Object.keys(zip.files).find((k) => k.replace(/^reports\//, "") === `${slug}/report.json`);
  return key ? JSON.parse(await zip.files[key].async("string")) : null;
}

// ---------- pull requests ----------

export async function openPullRequest(branch: string, title: string, body: string): Promise<{ number: number; url: string }> {
  try {
    const pr = await gh<{ number: number; html_url: string }>(`/pulls`, {
      method: "POST",
      body: JSON.stringify({ title, body, head: branch, base: baseBranch() }),
    });
    return { number: pr.number, url: pr.html_url };
  } catch (e) {
    if (!(e instanceof GitHubError && e.status === 422)) throw e;
    const owner = repoName().split("/")[0];
    const open = await gh<{ number: number; html_url: string }[]>(`/pulls?head=${encodeURIComponent(`${owner}:${branch}`)}&state=open`);
    if (!open[0]) throw e;
    return { number: open[0].number, url: open[0].html_url };
  }
}

export async function pullState(num: number): Promise<{ state: string; merged: boolean }> {
  const pr = await gh<{ state: string; merged: boolean }>(`/pulls/${num}`);
  return { state: pr.state, merged: !!pr.merged };
}

// ---------- deploy zip ----------

const DEPLOY_ROOT_FILES = ["run_bot.py", "requirements.txt", ".env.example", "DEPLOY.md", "README.md"];

/** A zip with engine/, bots/<slug>/ and the run files, from one commit. */
export async function buildDeployZip(sha: string, slug: string, info: string): Promise<Uint8Array> {
  const res = await gh<Response>(`/zipball/${sha}`, { raw: true, signal: AbortSignal.timeout(120_000) });
  return repackForDeploy(await res.arrayBuffer(), slug, info, sha);
}

/** Keeps engine/, bots/<slug>/ and the run files from a GitHub zipball, under one <slug>/ folder. */
export async function repackForDeploy(zipball: ArrayBuffer | Uint8Array, slug: string, info: string, sha = ""): Promise<Uint8Array> {
  const src = await JSZip.loadAsync(zipball);
  const out = new JSZip();
  const top = `${slug}/`;
  let hasStrategy = false;
  for (const entry of Object.values(src.files)) {
    if (entry.dir) continue;
    const rel = entry.name.replace(/^[^/]+\//, ""); // drop GitHub's "<owner>-<repo>-<sha>/" folder
    if (!rel || rel.includes("__pycache__")) continue;
    const keep =
      rel.startsWith("engine/") || rel.startsWith(`bots/${slug}/`) || DEPLOY_ROOT_FILES.includes(rel) || rel === "pipeline.json";
    if (!keep) continue;
    if (rel === `bots/${slug}/strategy.py`) hasStrategy = true;
    out.file(top + rel, await entry.async("uint8array"));
  }
  if (!hasStrategy) throw new GitHubError(404, `bots/${slug}/strategy.py is not in commit ${sha.slice(0, 7) || "?"}.`);
  out.file(`${top}BOT.txt`, info);
  return out.generateAsync({ type: "uint8array", compression: "DEFLATE", compressionOptions: { level: 6 } });
}

/** Admin check: token works, base branch exists, the workflow file is there. */
export async function healthCheck(): Promise<{ ok: boolean; items: { label: string; ok: boolean; detail: string }[] }> {
  const items: { label: string; ok: boolean; detail: string }[] = [];
  try {
    const repo = await gh<{ full_name: string; permissions?: { push?: boolean } }>(``);
    items.push({ label: "Repository", ok: true, detail: repo.full_name });
    items.push({ label: "Write access", ok: !!repo.permissions?.push, detail: repo.permissions?.push ? "token can push" : "token is read-only" });
    const base = await branchSha(baseBranch());
    items.push({ label: `Base branch ${baseBranch()}`, ok: !!base, detail: base ? base.slice(0, 7) : "missing: push repo-template to this branch (SETUP.md step 1)" });
    const wf = base ? await readFile(baseBranch(), ".github/workflows/pipeline.yml") : null;
    items.push({ label: "Pipeline workflow", ok: !!wf, detail: wf ? ".github/workflows/pipeline.yml" : "copy repo-template/ into the repo" });
    const eng = base ? await readFile(baseBranch(), "engine/strategy.py") : null;
    items.push({ label: "Engine", ok: !!eng, detail: eng ? "engine/strategy.py" : "missing" });
  } catch (e) {
    items.push({ label: "Connection", ok: false, detail: e instanceof Error ? e.message : String(e) });
  }
  return { ok: items.every((i) => i.ok), items };
}
