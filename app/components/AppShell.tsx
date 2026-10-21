import Link from "next/link";
import type { SessionUser } from "@/app/auth";
import type { Dict, Lang } from "@/lib/i18n";
import { BrandMark, Branch, Gear, Home } from "./icons";
import LangToggle from "./LangToggle";
import LogoutButton from "./LogoutButton";

type Section = "workspace" | "admin";

export default function AppShell({
  user, t, lang, active, title, actions, children,
}: { user: SessionUser; t: Dict; lang: Lang; active: Section; title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  const items = [
    { key: "workspace", href: "/workspace", label: t.navWorkspace, icon: <Branch size={20} /> },
    ...(user.isAdmin ? [{ key: "admin", href: "/admin", label: t.navAdmin, icon: <Gear size={20} /> }] : []),
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <BrandMark />
          <span><strong>{t.brand}</strong><small>{t.brandSub}</small></span>
        </Link>
        <nav>
          {items.map((i) => (
            <Link key={i.key} href={i.href} className={active === i.key ? "on" : ""}>{i.icon}{i.label}</Link>
          ))}
        </nav>
        <div className="me">
          <b>{user.displayName}</b>
          <small>{user.email}</small>
          <div className="row" style={{ marginTop: 12 }}>
            <LangToggle lang={lang} />
            <LogoutButton label={t.signOut} />
          </div>
        </div>
      </aside>
      <main className="main">
        <div className="topbar">
          <h1>{title}</h1>
          <span className="spacer" />
          {actions}
          <span className="mobile-only-lang"><LangToggle lang={lang} /></span>
        </div>
        {children}
      </main>
      <nav className="mobile-nav">
        <Link href="/"><Home size={20} />{t.navHome}</Link>
        {items.map((i) => (
          <Link key={i.key} href={i.href} className={active === i.key ? "on" : ""}>{i.icon}{i.label}</Link>
        ))}
      </nav>
    </div>
  );
}
