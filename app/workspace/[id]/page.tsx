import { eq } from "drizzle-orm";
import { notFound } from "next/navigation";
import { requireSessionUser } from "@/app/auth";
import AppShell from "@/app/components/AppShell";
import Editor from "@/app/components/Editor";
import { getDb } from "@/db";
import { strategies } from "@/db/schema";
import { geminiConfigured } from "@/lib/gemini";
import { baseBranch, githubConfigured, repoUrl } from "@/lib/github";
import { getDict } from "@/lib/lang-server";
import { openrouterConfigured, openrouterModels } from "@/lib/openrouter";
import { refreshFromGitHub, toPublic } from "@/lib/strategies";

export const dynamic = "force-dynamic";

export default async function StrategyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: idRaw } = await params;
  const user = await requireSessionUser(`/workspace/${idRaw}`);
  const { t, lang } = await getDict();
  const id = Number(idRaw);
  if (!Number.isSafeInteger(id)) notFound();
  const [row] = await getDb().select().from(strategies).where(eq(strategies.id, id)).limit(1);
  if (!row || row.status === "archived" || (row.userId !== user.id && !user.isAdmin)) notFound();
  const s = toPublic(githubConfigured() ? await refreshFromGitHub(row) : row);

  return (
    <AppShell user={user} t={t} lang={lang} active="workspace" title={s.name}>
      <Editor
        t={t}
        lang={lang}
        initial={s}
        isAdmin={user.isAdmin}
        geminiReady={geminiConfigured()}
        openrouterReady={openrouterConfigured()}
        models={openrouterModels()}
        branchUrl={repoUrl(`/tree/${s.branch}`)}
        commitUrlBase={repoUrl("/commit/")}
        baseBranch={baseBranch()}
      />
    </AppShell>
  );
}
