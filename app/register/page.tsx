import Link from "next/link";
import { Suspense } from "react";
import AuthForm from "@/app/components/AuthForm";
import { BrandMark } from "@/app/components/icons";
import LangToggle from "@/app/components/LangToggle";
import { getDict } from "@/lib/lang-server";

export default async function Page() {
  const { t, lang } = await getDict();
  return (
    <main className="auth">
      <div style={{ width: "min(440px, 100%)" }}>
        <div className="row" style={{ marginBottom: 18 }}>
          <Link href="/" className="brand"><BrandMark /><span><strong>{t.brand}</strong><small>{t.brandSub}</small></span></Link>
          <span className="spacer" />
          <LangToggle lang={lang} />
        </div>
        <Suspense fallback={null}>
          <AuthForm mode="register" t={t} />
        </Suspense>
      </div>
    </main>
  );
}
