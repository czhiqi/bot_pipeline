import { cookies } from "next/headers";
import { DICTS, normalizeLang, type Lang } from "./i18n";

/** Language from the `lang` cookie (set by the EN / 中文 toggle). Default: English. */
export async function getLang(): Promise<Lang> {
  return normalizeLang((await cookies()).get("lang")?.value);
}

export async function getDict() {
  const lang = await getLang();
  return { lang, t: DICTS[lang] };
}
