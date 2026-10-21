"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import type { Dict } from "@/lib/i18n";
import { errText, postJson } from "./client-utils";

export default function AuthForm({ mode, t }: { mode: "login" | "register"; t: Dict }) {
  const router = useRouter();
  const params = useSearchParams();
  const rt = params.get("return_to") ?? "";
  const returnTo = rt.startsWith("/") && !rt.startsWith("//") ? rt : "/workspace";

  const [form, setForm] = useState({ email: "", password: "", displayName: "", agreeTerms: false });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const r = await postJson(`/api/auth/${mode}`, form);
    setBusy(false);
    if (!r.ok) return setError(errText(t, r.error));
    router.push(returnTo);
    router.refresh();
  }

  return (
    <form className="card" onSubmit={submit}>
      <h1>{mode === "login" ? t.loginTitle : t.registerTitle}</h1>
      {mode === "register" && (
        <label className="field">
          {t.displayName}
          <input required maxLength={100} value={form.displayName} onChange={(e) => set("displayName", e.target.value)} autoComplete="name" />
        </label>
      )}
      <label className="field">
        {t.email}
        <input type="email" required value={form.email} onChange={(e) => set("email", e.target.value)} autoComplete="email" placeholder="you@example.com" />
      </label>
      <label className="field">
        {t.password}
        <input
          type="password"
          required
          minLength={mode === "register" ? 8 : undefined}
          value={form.password}
          onChange={(e) => set("password", e.target.value)}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
        />
      </label>
      {mode === "register" && (
        <label className="check">
          <input type="checkbox" required checked={form.agreeTerms} onChange={(e) => set("agreeTerms", e.target.checked)} />
          <span>{t.agreeTerms}</span>
        </label>
      )}
      {error && <p className="error-text">{error}</p>}
      <div className="foot">
        <Link href={mode === "login" ? "/register" : "/login"}>{mode === "login" ? t.noAccount : t.haveAccount}</Link>
        <button className="btn btn-accent" disabled={busy}>{busy ? t.working : mode === "login" ? t.signIn : t.signUp}</button>
      </div>
    </form>
  );
}
