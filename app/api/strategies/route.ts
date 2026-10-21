import { and, desc, eq, ne, sql } from "drizzle-orm";
import { apiUser } from "@/app/auth";
import { getDb } from "@/db";
import { limits } from "@/db/queries";
import { strategies } from "@/db/schema";
import { branchSha, createBranch, GitHubError, githubConfigured, readFile } from "@/lib/github";
import { fail, readJson } from "@/lib/http";
import { defaultConfig, EMPTY_HYPOTHESIS, EXCHANGES, slugify, TIMEFRAMES } from "@/lib/pipeline";
import { toPublic } from "@/lib/strategies";
import { BLANK_CODE } from "@/lib/templates";

/** The user's strategies (admins: ?all=1 for everyone's). */
export async function GET(request: Request) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  const all = user.isAdmin && new URL(request.url).searchParams.get("all") === "1";
  const rows = await getDb()
    .select()
    .from(strategies)
    .where(all ? ne(strategies.status, "archived") : and(eq(strategies.userId, user.id), ne(strategies.status, "archived")))
    .orderBy(desc(strategies.updatedAt))
    .limit(200);
  return Response.json({ strategies: rows.map(toPublic) });
}

/** Creates a strategy and its branch strategy/<slug> from the base branch. */
export async function POST(request: Request) {
  const user = await apiUser();
  if (user instanceof Response) return user;
  const body = await readJson<{ name?: string; exchange?: string; symbol?: string; timeframe?: string; start?: string }>(request);
  if (body instanceof Response) return body;
  if (!githubConfigured()) return fail("errGithubMissing", 503);

  const name = String(body.name ?? "").trim().slice(0, 80);
  if (name.length < 3) return fail("errName3");
  const exchange = EXCHANGES.includes(body.exchange as never) ? String(body.exchange) : "bitget";
  const timeframe = TIMEFRAMES.includes(body.timeframe as never) ? String(body.timeframe) : "1h";
  const symbol = String(body.symbol ?? "").trim().toUpperCase() || "ETH/USDT:USDT";
  if (!/^[A-Z0-9]+\/[A-Z0-9]+:[A-Z0-9]+$/.test(symbol)) return fail("errSymbol");
  const start = String(body.start ?? "blank");

  const db = getDb();
  const lim = limits();
  if (!user.isAdmin && lim.strategiesPerUser > 0) {
    const [row] = await db
      .select({ n: sql<number>`count(*)` })
      .from(strategies)
      .where(and(eq(strategies.userId, user.id), ne(strategies.status, "archived")));
    if (Number(row?.n ?? 0) >= lim.strategiesPerUser) return fail("errTooMany", 429);
  }

  // Unique slug = bot folder name = branch suffix. Also avoid branches that already exist.
  const baseSlug = slugify(name);
  let slug = baseSlug;
  for (let i = 2; ; i++) {
    const [taken] = await db.select({ id: strategies.id }).from(strategies).where(eq(strategies.slug, slug)).limit(1);
    if (!taken && !(await branchSha(`strategy/${slug}`))) break;
    if (i > 50) return fail("errGeneric", 500);
    slug = `${baseSlug}-${i}`.slice(0, 60);
  }
  const branch = `strategy/${slug}`;

  let code = BLANK_CODE;
  let config = defaultConfig(slug, exchange, symbol, timeframe);
  let spec = "";
  try {
    if (start.startsWith("repo:")) {
      const from = start.slice(5).replace(/[^\w.-]/g, "");
      const [src, cfg, md] = await Promise.all([
        readFile(process.env.GITHUB_BASE_BRANCH || "main", `bots/${from}/strategy.py`),
        readFile(process.env.GITHUB_BASE_BRANCH || "main", `bots/${from}/config.json`),
        readFile(process.env.GITHUB_BASE_BRANCH || "main", `bots/${from}/hypothesis.md`),
      ]);
      if (!src) return fail("errNotFound", 404);
      code = src;
      spec = md ?? "";
      if (cfg) {
        try {
          // Keep the source bot's settings, but use the market the user picked.
          config = { ...config, ...JSON.parse(cfg), name: slug, exchange, symbol, timeframe };
        } catch {
          /* keep defaults */
        }
      }
    }
    await createBranch(branch);
  } catch (e) {
    console.error("[api/strategies] create failed:", e);
    return fail("errGithub", 502, { message: e instanceof GitHubError ? e.message : "" });
  }

  const [res] = await db.insert(strategies).values({
    userId: user.id,
    name,
    slug,
    branch,
    hypothesis: JSON.stringify(EMPTY_HYPOTHESIS),
    spec,
    code,
    config: JSON.stringify(config, null, 2),
  });
  return Response.json({ id: res.insertId, slug, branch }, { status: 201 });
}
