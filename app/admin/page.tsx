import Link from "next/link";
import { desc, eq, gte, inArray, ne, sql } from "drizzle-orm";
import { requireAdminPage } from "@/app/auth";
import AppShell from "@/app/components/AppShell";
import { Bars, Branch, Check, Sparkle } from "@/app/components/icons";
import { STATUS_PILL } from "@/app/components/WorkspaceList";
import { getDb } from "@/db";
import { limits } from "@/db/queries";
import { aiCalls, strategies, users } from "@/db/schema";
import { geminiConfigured, geminiModel } from "@/lib/gemini";
import { githubConfigured, healthCheck, repoName } from "@/lib/github";
import { fmt, type Dict } from "@/lib/i18n";
import { getDict } from "@/lib/lang-server";
import { openrouterConfigured, openrouterModels } from "@/lib/openrouter";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const user = await requireAdminPage();
  const { t, lang } = await getDict();
  const db = getDb();
  const day = new Date(Date.now() - 24 * 3600 * 1000);

  const [[u], [st], [passed], [ai], recent, gh] = await Promise.all([
    db.select({ n: sql<number>`count(*)` }).from(users),
    db.select({ n: sql<number>`count(*)` }).from(strategies).where(ne(strategies.status, "archived")),
    db.select({ n: sql<number>`count(*)` }).from(strategies).where(inArray(strategies.status, ["passed", "submitted", "merged"])),
    db.select({ n: sql<number>`count(*)` }).from(aiCalls).where(gte(aiCalls.createdAt, day)),
    db
      .select({ s: strategies, email: users.email })
      .from(strategies)
      .leftJoin(users, eq(users.id, strategies.userId))
      .where(ne(strategies.status, "archived"))
      .orderBy(desc(strategies.updatedAt))
      .limit(100),
    githubConfigured() ? healthCheck() : Promise.resolve({ ok: false, items: [{ label: "GitHub", ok: false, detail: "Set GITHUB_TOKEN and GITHUB_REPO" }] }),
  ]);
  const lim = limits();
  const stats = [
    { icon: <Bars />, label: t.users, value: Number(u?.n ?? 0) },
    { icon: <Branch />, label: t.strategiesCount, value: Number(st?.n ?? 0) },
    { icon: <Check />, label: t.passedCount, value: Number(passed?.n ?? 0) },
    { icon: <Sparkle />, label: t.aiCalls24, value: Number(ai?.n ?? 0) },
  ];

  return (
    <AppShell user={user} t={t} lang={lang} active="admin" title={t.adminTitle}>
      <section className="stats">
        {stats.map((s) => (
          <div className="card stat" key={s.label}>
            <div className="ico">{s.icon}</div>
            <div><small>{s.label}</small><b className="num">{s.value.toLocaleString()}</b></div>
          </div>
        ))}
      </section>

      <div className="card" style={{ marginBottom: 18 }}>
        <h2>{t.connections}</h2>
        <ul className="gate-list">
          <li className={gh.ok ? "pass" : "fail"}><b>GitHub</b>&nbsp;<small className="mono">{repoName() || "—"}</small></li>
          {gh.items.map((i) => (
            <li key={i.label} className={i.ok ? "pass" : "fail"} style={{ paddingLeft: 22 }}><span><b>{i.label}</b> <small>{i.detail}</small></span></li>
          ))}
          <li className={geminiConfigured() ? "pass" : "fail"}><span><b>Gemini</b> <small>{geminiConfigured() ? geminiModel() : `${t.missing} — GEMINI_API_KEY`}</small></span></li>
          <li className={openrouterConfigured() ? "pass" : "fail"}><span><b>OpenRouter</b> <small>{openrouterConfigured() ? openrouterModels().join(", ") : `${t.missing} — OPENROUTER_API_KEY`}</small></span></li>
        </ul>
        <p className="muted small">{fmt(t.limitsNote, { a: lim.aiPerHour || "∞", s: lim.strategiesPerUser || "∞", c: lim.commitsPerHour || "∞" })}</p>
      </div>

      <div className="card">
        <h2>{t.recentStrategies}</h2>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>#</th><th>{t.strategyName}</th><th>{t.owner}</th><th>{t.branch}</th><th>{t.status}</th><th className="r">{t.outSample}</th><th>{t.updated}</th></tr>
            </thead>
            <tbody>
              {recent.map(({ s, email }) => {
                let oos: number | null = null;
                try {
                  oos = s.gateReport ? (JSON.parse(s.gateReport).out_of_sample?.net ?? null) : null;
                } catch {
                  oos = null;
                }
                return (
                  <tr key={s.id}>
                    <td className="num">{s.id}</td>
                    <td><Link href={`/workspace/${s.id}`}>{s.name}</Link></td>
                    <td className="small">{email ?? "—"}</td>
                    <td className="small mono">{s.branch}</td>
                    <td>
                      <span className={`pill ${STATUS_PILL[s.status] ?? ""}`}>{t[`st_${s.status}` as keyof Dict]}</span>
                      {s.prUrl && <a className="small" style={{ marginLeft: 8 }} href={s.prUrl} target="_blank" rel="noreferrer">PR #{s.prNumber}</a>}
                    </td>
                    <td className={`r num ${oos != null && oos > 0 ? "pos" : ""}`}>{oos == null ? "—" : `${oos > 0 ? "+" : ""}${oos.toFixed(2)}`}</td>
                    <td className="small muted">{new Date(s.updatedAt).toISOString().slice(0, 16).replace("T", " ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
