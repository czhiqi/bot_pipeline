import Link from "next/link";
import type { Dict, Lang } from "@/lib/i18n";
import { BrandMark } from "./icons";
import LangToggle from "./LangToggle";

export default function SiteHeader({ t, lang, signedIn }: { t: Dict; lang: Lang; signedIn: boolean }) {
  return (
    <header className="site-header">
      <Link href="/" className="brand">
        <BrandMark />
        <span><strong>{t.brand}</strong><small>{t.brandSub}</small></span>
      </Link>
      <nav>
        <a href="#how">{t.howTitle}</a>
        <a href="#rules">{t.rulesTitle}</a>
        <a href="#faq">{t.faqTitle}</a>
      </nav>
      <span className="spacer" />
      <LangToggle lang={lang} />
      {signedIn ? (
        <Link className="btn btn-accent btn-sm" href="/workspace">{t.navWorkspace}</Link>
      ) : (
        <Link className="btn btn-ghost btn-sm" href="/login">{t.signIn}</Link>
      )}
    </header>
  );
}
