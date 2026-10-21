"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fmt, type Dict } from "@/lib/i18n";
import { EXCHANGES, TIMEFRAMES } from "@/lib/pipeline";
import { apiErr, postJson } from "./client-utils";
import { Branch } from "./icons";

export type ListItem = {
  id: number;
  name: string;
  slug: string;
  branch: string;
  status: string;
  dirty: boolean;
  gateStatus: string;
  oosNet: number | null;
  config: string;
  owner: string;
  updatedAt: number;
};

export const STATUS_PILL: Record<string, string> = {
  draft: "",
  testing: "info",
  passed: "ok",
  failed: "bad",
  submitted: "warn",
  merged: "ok",
};

function market(config: string): string {
  try {
    const c = JSON.parse(config) as { exchange?: string; symbol?: string; timeframe?: string };
    return [c.exchange, c.symbol, c.timeframe].filter(Boolean).join(" · ");
  } catch {
    return "";
  }
}

export default function WorkspaceList({
  t, items, isAdmin, showAll, githubReady, repo, repoBots,
}: { t: Dict; items: ListItem[]; isAdmin: boolean; showAll: boolean; githubReady: boolean; repo: string; repoBots: string[] }) {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", exchange: "bitget", symbol: "ETH/USDT:USDT", timeframe: "1h", start: "blank" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const r = await postJson("/api/strategies", form);
    setBusy(false);
    if (!r.ok) return setError(apiErr(t, r));
    router.push(`/workspace/${r.data?.id}`);
  }

  return (
    <div className="ws-grid">
      <form className="card" onSubmit={create}>
        <h2>{t.newStrategy}</h2>
        <p className="muted small" style={{ margin: 0 }}>{t.newLead}</p>
        {!githubReady && <p className="error-text">{t.githubMissingNote}</p>}
        <label className="field">
          {t.strategyName}
          <input required minLength={3} maxLength={80} value={form.name} placeholder={t.strategyNamePh} onChange={(e) => set("name", e.target.value)} />
        </label>
        <div className="form-grid">
          <label className="field">
            {t.exchange}
            <select value={form.exchange} onChange={(e) => set("exchange", e.target.value)}>
              {EXCHANGES.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
          </label>
          <label className="field">
            {t.timeframe}
            <select value={form.timeframe} onChange={(e) => set("timeframe", e.target.value)}>
              {TIMEFRAMES.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
          </label>
        </div>
        <label className="field">
          {t.symbol}
          <input required value={form.symbol} onChange={(e) => set("symbol", e.target.value.toUpperCase())} placeholder="ETH/USDT:USDT" />
        </label>
        <label className="field">
          {t.startFrom}
          <select value={form.start} onChange={(e) => set("start", e.target.value)}>
            <option value="blank">{t.startBlank}</option>
            {repoBots.map((b) => <option key={b} value={`repo:${b}`}>{fmt(t.startRepo, { b })}</option>)}
          </select>
        </label>
        {form.name.trim().length >= 3 && (
          <p className="help mono">{repo}: strategy/{form.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40)}</p>
        )}
        {error && <p className="error-text">{error}</p>}
        <button className="btn btn-accent" style={{ marginTop: 16, width: "100%" }} disabled={busy || !githubReady}>
          <Branch size={18} />{busy ? t.creating : t.create}
        </button>
      </form>

      <div className="card">
        <div className="row" style={{ marginBottom: 6 }}>
          <h2 style={{ margin: 0 }}>{showAll ? t.allUsers : t.mine}</h2>
          <span className="spacer" />
          {isAdmin && (
            <Link className="btn btn-ghost btn-sm" href={showAll ? "/workspace" : "/workspace?all=1"}>{showAll ? t.mine : t.allUsers}</Link>
          )}
        </div>
        {items.length === 0 ? (
          <p className="muted">{t.noStrategies}</p>
        ) : (
          <ul className="strat-list">
            {items.map((s) => (
              <li key={s.id}>
                <Link href={`/workspace/${s.id}`}>
                  <div className="grow">
                    <b>{s.name}</b>
                    <div className="meta">
                      <span className="mono">{s.branch}</span>
                      <span>{market(s.config)}</span>
                      {showAll && <span>{s.owner}</span>}
                    </div>
                  </div>
                  <div className="right">
                    <span className={`pill ${STATUS_PILL[s.status] ?? ""}`}>{t[`st_${s.status}` as keyof Dict]}</span>
                    {s.oosNet != null && (
                      <small className={s.oosNet > 0 ? "pos" : "neg"}>{t.outSample} {s.oosNet > 0 ? "+" : ""}{s.oosNet.toFixed(2)}</small>
                    )}
                    {s.dirty && s.status !== "draft" && <small className="muted">{t.unsaved}</small>}
                    <small className="muted">{new Date(s.updatedAt).toLocaleString()}</small>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
