import { and, desc, eq, ne } from "drizzle-orm";
import { requireSessionUser } from "@/app/auth";
import AppShell from "@/app/components/AppShell";
import WorkspaceList from "@/app/components/WorkspaceList";
import { getDb } from "@/db";
import { strategies, users } from "@/db/schema";
import { githubConfigured, listBots, repoName } from "@/lib/github";
import { getDict } from "@/lib/lang-server";
import { toPublic } from "@/lib/strategies";

export const dynamic = "force-dynamic";

export default async function WorkspacePage({ searchParams }: { searchParams: Promise<{ all?: string }> }) {
  const user = await requireSessionUser("/workspace");
  const { t, lang } = await getDict();
  const all = user.isAdmin && (await searchParams).all === "1";
  const rows = await getDb()
    .select({ s: strategies, email: users.email })
    .from(strategies)
    .leftJoin(users, eq(users.id, strategies.userId))
    .where(all ? ne(strategies.status, "archived") : and(eq(strategies.userId, user.id), ne(strategies.status, "archived")))
    .orderBy(desc(strategies.updatedAt))
    .limit(200);

  const gh = githubConfigured();
  let repoBots: string[] = [];
  if (gh) {
    try {
      repoBots = await listBots();
    } catch (e) {
      console.error("[workspace] listBots failed:", e);
    }
  }

  return (
    <AppShell user={user} t={t} lang={lang} active="workspace" title={t.workspaceTitle}>
      <WorkspaceList
        t={t}
        isAdmin={user.isAdmin}
        showAll={all}
        githubReady={gh}
        repo={repoName()}
        repoBots={repoBots}
        items={rows.map(({ s, email }) => {
          const p = toPublic(s);
          return {
            id: p.id,
            name: p.name,
            slug: p.slug,
            branch: p.branch,
            status: p.status,
            dirty: p.dirty,
            gateStatus: p.gateStatus,
            oosNet: p.report?.out_of_sample?.net ?? null,
            config: p.config,
            owner: email ?? "",
            updatedAt: p.updatedAt,
          };
        })}
      />
    </AppShell>
  );
}
