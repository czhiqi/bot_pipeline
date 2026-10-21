"use client";

import { useRouter } from "next/navigation";
import type { Lang } from "@/lib/i18n";

export default function LangToggle({ lang }: { lang: Lang }) {
  const router = useRouter();
  const set = (l: Lang) => {
    document.cookie = `lang=${l}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  };
  return (
    <div className="lang-toggle" role="group" aria-label="Language">
      <button className={lang === "en" ? "on" : ""} onClick={() => set("en")} aria-pressed={lang === "en"}>EN</button>
      <button className={lang === "zh" ? "on" : ""} onClick={() => set("zh")} aria-pressed={lang === "zh"}>中文</button>
    </div>
  );
}
