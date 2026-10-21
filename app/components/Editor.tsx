"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmt, type Dict, type Lang } from "@/lib/i18n";
import {
  dataFileName,
  EXCHANGES,
  hypothesisMarkdown,
  parseConfig,
  quickCheck,
  TIMEFRAMES,
  type BotConfig,
  type GateReport,
  type Hypothesis,
  type Summary,
} from "@/lib/pipeline";
import type { PublicStrategy } from "@/lib/strategies";
import { apiErr, postJson } from "./client-utils";
import { Branch, Check, Code, Cross, Doc, Download, Flask, Rocket, Shield, Sparkle, Trash, Upload } from "./icons";
import { STATUS_PILL } from "./WorkspaceList";

type Props = {
  t: Dict;
  lang: Lang;
  initial: PublicStrategy;
  isAdmin: boolean;
  geminiReady: boolean;
  openrouterReady: boolean;
  models: string[];
  branchUrl: string;
  commitUrlBase: string;
  baseBranch: string;
};

type Draft = { name: string; hypothesis: Hypothesis; spec: string; code: string; config: string };
const snapshot = (d: Draft) => JSON.stringify(d);
const MAINT = 0.5; // % maintenance margin used by the risk gate
const LIQ_BUFFER = 0.8;

async function send(method: string, url: string, body?: unknown) {
  try {
    const res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    return res.ok ? { ok: true, data } : { ok: false, error: String(data.error ?? "errGeneric"), data };
  } catch {
    return { ok: false, error: "errGeneric", data: {} as Record<string, unknown> };
  }
}

export default function Editor(p: Props) {
  const { t } = p;
  const router = useRouter();
  const [s, setS] = useState<PublicStrategy>(p.initial);
  const [draft, setDraft] = useState<Draft>({
    name: p.initial.name,
    hypothesis: p.initial.hypothesis,
    spec: p.initial.spec,
    code: p.initial.code,
    config: p.initial.config,
  });
  const [saved, setSaved] = useState(snapshot(draft));
  const unsaved = snapshot(draft) !== saved;
  const [busy, setBusy] = useState<"" | "save" | "beautify" | "generate" | "commit" | "submit" | "delete">("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string; where: string } | null>(null);
  const [questions, setQuestions] = useState<string[]>([]);
  const [gen, setGen] = useState({ model: p.models[0] ?? "", instructions: "", mode: "new" as "new" | "revise", useReport: false });
  const [aiNotes, setAiNotes] = useState("");
  const [serverProblems, setServerProblems] = useState<string[]>([]);
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [commitMsg, setCommitMsg] = useState("");
  const [rawConfig, setRawConfig] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const parsed = useMemo(() => parseConfig(draft.config), [draft.config]);
  const cfg = parsed.cfg;
  const problems = useMemo(() => quickCheck(draft.code), [draft.code]);
  const report = s.report as GateReport | null;
  const committedDirty = s.dirty || unsaved;

  const flash = (kind: "ok" | "err", text: string, where: string) => setMsg({ kind, text, where });
  const setH = (k: keyof Hypothesis, v: string) => setDraft((d) => ({ ...d, hypothesis: { ...d.hypothesis, [k]: v } }));

  const patchConfig = (fn: (c: BotConfig) => void) => {
    if (!cfg) return;
    const c = JSON.parse(JSON.stringify(cfg)) as BotConfig;
    fn(c);
    setDraft((d) => ({ ...d, config: JSON.stringify(c, null, 2) }));
  };

  // Poll while GitHub is working on something.
  const waiting = s.status === "testing" || s.status === "submitted";
  const refresh = useCallback(async () => {
    const r = await send("GET", `/api/strategies/${s.id}`);
    if (r.ok) setS(r.data.strategy as PublicStrategy);
  }, [s.id]);
  useEffect(() => {
    if (!waiting) return;
    const h = setInterval(refresh, s.status === "testing" ? 12_000 : 30_000);
    return () => clearInterval(h);
  }, [waiting, refresh, s.status]);

  // Warn before leaving with unsaved edits.
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => {
      if (unsaved) e.preventDefault();
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [unsaved]);

  async function save(quiet = false): Promise<boolean> {
    setBusy("save");
    const r = await send("PATCH", `/api/strategies/${s.id}`, draft);
    setBusy("");
    if (!r.ok) {
      flash("err", apiErr(t, r), "save");
      return false;
    }
    setS(r.data.strategy as PublicStrategy);
    setSaved(snapshot(draft));
    if (!quiet) flash("ok", t.saved, "save");
    return true;
  }

  async function beautify() {
    setBusy("beautify");
    setMsg(null);
    const r = await postJson(`/api/strategies/${s.id}/beautify`, { hypothesis: draft.hypothesis, config: draft.config, lang: p.lang });
    setBusy("");
    if (!r.ok) return flash("err", apiErr(t, r), "hyp");
    const h = r.data?.hypothesis as Hypothesis;
    setDraft((d) => ({ ...d, hypothesis: h, spec: String(r.data?.markdown ?? "") }));
    setQuestions((r.data?.questions as string[]) ?? []);
    flash("ok", t.beautifyDone, "hyp");
  }

  async function generate() {
    setBusy("generate");
    setMsg(null);
    setServerProblems([]);
    const r = await postJson(`/api/strategies/${s.id}/generate`, { ...gen, hypothesis: draft.hypothesis, spec: draft.spec, code: draft.code, config: draft.config });
    setBusy("");
    if (!r.ok) return flash("err", apiErr(t, r), "code");
    const d = r.data ?? {};
    const params = d.params as Record<string, unknown> | null;
    const risk = d.risk as Partial<BotConfig["risk"]> | null;
    setDraft((cur) => {
      let config = cur.config;
      const pc = parseConfig(cur.config).cfg;
      if (pc && (params || risk)) {
        if (params) pc.params = { ...pc.params, ...params };
        if (risk) pc.risk = { ...pc.risk, ...risk };
        config = JSON.stringify(pc, null, 2);
      }
      return { ...cur, code: String(d.code ?? cur.code), config };
    });
    setAiNotes([String(d.notes ?? ""), d.model ? `(${d.model})` : ""].filter(Boolean).join(" "));
    flash("ok", t.unsaved, "code");
  }

  async function onFiles(files: FileList | null) {
    if (!files) return;
    for (const f of Array.from(files)) {
      const name = f.name.toLowerCase();
      if (name.endsWith(".csv")) {
        setDataFile(f);
        continue;
      }
      if (f.size > 200_000) continue;
      const text = await f.text();
      if (name.endsWith(".py")) setDraft((d) => ({ ...d, code: text }));
      else if (name.endsWith(".json")) setDraft((d) => ({ ...d, config: text }));
      else if (name.endsWith(".md") || name.endsWith(".txt")) setDraft((d) => ({ ...d, spec: text }));
    }
    if (fileInput.current) fileInput.current.value = "";
  }

  async function commit() {
    setMsg(null);
    setServerProblems([]);
    if (unsaved && !(await save(true))) return;
    setBusy("commit");
    const form = new FormData();
    form.set("message", commitMsg);
    if (dataFile) form.set("data", dataFile);
    try {
      const res = await fetch(`/api/strategies/${s.id}/commit`, { method: "POST", body: form });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        setServerProblems((data.problems as string[]) ?? []);
        flash("err", apiErr(t, { error: String(data.error ?? "errGeneric"), data }), "commit");
      } else {
        setS(data.strategy as PublicStrategy);
        setDataFile(null);
        setCommitMsg("");
      }
    } catch {
      flash("err", t.errGeneric, "commit");
    }
    setBusy("");
  }

  async function submit() {
    setBusy("submit");
    setMsg(null);
    const r = await postJson(`/api/strategies/${s.id}/submit`);
    setBusy("");
    if (!r.ok) return flash("err", apiErr(t, r), "review");
    setS(r.data?.strategy as PublicStrategy);
  }

  async function remove() {
    if (!window.confirm(t.deleteConfirm)) return;
    setBusy("delete");
    const r = await send("DELETE", `/api/strategies/${s.id}`);
    setBusy("");
    if (!r.ok) return flash("err", apiErr(t, r), "delete");
    router.push("/workspace");
    router.refresh();
  }

  const liq = cfg ? (100 / cfg.leverage - MAINT) : 0;
  const steps = [
    { label: t.step1, done: !!(draft.hypothesis.idea.trim() && draft.hypothesis.rules.trim()) },
    { label: t.step2, done: problems.length === 0 },
    { label: t.step3, done: !!cfg && cfg.risk.stop_loss_pct > 0 && cfg.risk.stop_loss_pct <= liq * LIQ_BUFFER },
    { label: t.step4, done: s.gateStatus === "pass" },
    { label: t.step5, done: s.status === "submitted" || s.status === "merged" },
    { label: t.step6, done: s.gateStatus === "pass" && !!s.commitSha },
  ];
  const Msg = ({ where }: { where: string }) =>
    msg && msg.where === where ? <p className={msg.kind === "ok" ? "ok-text" : "error-text"}>{msg.text}</p> : null;
  const lineCount = draft.code.split("\n").length;

  return (
    <>
      <div className="editor-head card">
        <div className="row" style={{ flexWrap: "wrap", gap: 10 }}>
          <span className={`pill ${STATUS_PILL[s.status] ?? ""}`}>{t[`st_${s.status}` as keyof Dict]}</span>
          <a className="mono small" href={p.branchUrl} target="_blank" rel="noreferrer"><Branch size={14} /> {s.branch}</a>
          {s.commitSha && (
            <a className="mono small muted" href={p.commitUrlBase + s.commitSha} target="_blank" rel="noreferrer">{t.commitLabel} {s.commitSha.slice(0, 7)}</a>
          )}
          <span className="spacer" />
          {unsaved && <span className="pill warn">{t.unsaved}</span>}
          <button className="btn btn-ghost btn-sm" onClick={() => save()} disabled={!!busy || !unsaved}>{busy === "save" ? t.saving : t.save}</button>
        </div>
        <ol className="workflow" style={{ margin: "14px 0 0" }}>
          {steps.map((st) => <li key={st.label} className={st.done ? "done" : ""}>{st.label}</li>)}
        </ol>
        <Msg where="save" />
      </div>

      <div className="editor-grid">
        {/* ---------- 1 · Hypothesis ---------- */}
        <section className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}><Doc size={18} /> {t.hypothesisTitle}</h2>
            <span className="spacer" />
            <button className="btn btn-accent btn-sm" onClick={beautify} disabled={!!busy || !p.geminiReady} title={p.geminiReady ? "" : t.errGeminiMissing}>
              <Sparkle size={16} />{busy === "beautify" ? t.beautifying : t.beautify}
            </button>
          </div>
          {!p.geminiReady && <p className="help">{t.errGeminiMissing}</p>}
          <label className="field">{t.strategyName}<input value={draft.name} maxLength={80} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} /></label>
          {([
            ["idea", t.hypIdea, t.hypIdeaPh, 3],
            ["expected", t.hypExpected, t.hypExpectedPh, 3],
            ["invalidation", t.hypInvalid, t.hypInvalidPh, 3],
            ["rules", t.hypRules, t.hypRulesPh, 6],
            ["notes", t.hypNotes, "", 2],
          ] as const).map(([k, label, ph, rows]) => (
            <label className="field" key={k}>
              {label}
              <textarea className="short" rows={rows} value={draft.hypothesis[k]} placeholder={ph} onChange={(e) => setH(k, e.target.value)} />
            </label>
          ))}
          {questions.length > 0 && (
            <div className="note-box">
              <b>{t.questions}</b>
              <ul>{questions.map((q) => <li key={q}>{q}</li>)}</ul>
            </div>
          )}
          <Msg where="hyp" />
          <details className="sub" open={!!draft.spec}>
            <summary>{t.specTitle}</summary>
            <p className="help">{t.specHelp}</p>
            <textarea
              className="code small-code"
              rows={10}
              value={draft.spec}
              placeholder={hypothesisMarkdown(draft.name, draft.hypothesis)}
              onChange={(e) => setDraft((d) => ({ ...d, spec: e.target.value }))}
            />
            <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={() => setDraft((d) => ({ ...d, spec: hypothesisMarkdown(d.name, d.hypothesis) }))}>
              {t.rebuildSpec}
            </button>
          </details>
        </section>

        {/* ---------- 2 · Code ---------- */}
        <section className="card">
          <div className="row" style={{ flexWrap: "wrap" }}>
            <h2 style={{ margin: 0 }}><Code size={18} /> {t.codeTitle}</h2>
            <span className="muted small">{lineCount} {t.lines}</span>
            <span className="spacer" />
            <input ref={fileInput} type="file" multiple accept=".py,.json,.md,.txt,.csv" hidden onChange={(e) => onFiles(e.target.files)} />
            <button className="btn btn-ghost btn-sm" onClick={() => fileInput.current?.click()} title={t.uploadHelp}><Upload size={16} />{t.uploadFiles}</button>
          </div>
          <div className="gen-box">
            <div className="form-grid">
              <label className="field">
                {t.model}
                <select value={gen.model} onChange={(e) => setGen((g) => ({ ...g, model: e.target.value }))}>
                  {p.models.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </label>
              <div className="field">
                &nbsp;
                <div className="seg" style={{ marginTop: 6 }}>
                  <button type="button" className={gen.mode === "new" ? "on" : ""} onClick={() => setGen((g) => ({ ...g, mode: "new" }))}>{t.generate}</button>
                  <button type="button" className={gen.mode === "revise" ? "on" : ""} onClick={() => setGen((g) => ({ ...g, mode: "revise" }))}>{t.revise}</button>
                </div>
              </div>
            </div>
            <label className="field">
              {t.instructions}
              <input value={gen.instructions} maxLength={4000} placeholder={t.instructionsPh} onChange={(e) => setGen((g) => ({ ...g, instructions: e.target.value }))} />
            </label>
            {report && !report.ok && (
              <label className="check">
                <input type="checkbox" checked={gen.useReport} onChange={(e) => setGen((g) => ({ ...g, useReport: e.target.checked }))} />
                <span>{t.useReport}</span>
              </label>
            )}
            <button className="btn btn-accent btn-sm" style={{ marginTop: 12 }} onClick={generate} disabled={!!busy || !p.openrouterReady}>
              <Sparkle size={16} />{busy === "generate" ? t.generating : gen.mode === "revise" ? t.revise : t.generate}
            </button>
            {!p.openrouterReady && <p className="help">{t.errOpenrouterMissing}</p>}
            {aiNotes && <p className="help"><b>{t.aiNotes}:</b> {aiNotes}</p>}
            <Msg where="code" />
          </div>
          <textarea
            className="code"
            spellCheck={false}
            value={draft.code}
            onChange={(e) => setDraft((d) => ({ ...d, code: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key !== "Tab") return;
              e.preventDefault();
              const el = e.currentTarget;
              const { selectionStart: a, selectionEnd: b } = el;
              const v = el.value.slice(0, a) + "    " + el.value.slice(b);
              setDraft((d) => ({ ...d, code: v }));
              requestAnimationFrame(() => el.setSelectionRange(a + 4, a + 4));
            }}
          />
          {problems.length === 0 && serverProblems.length === 0 ? (
            <p className="ok-text"><Check size={14} /> {t.checkOk}</p>
          ) : (
            <div className="note-box bad">
              <b>{t.checkProblems}</b>
              <ul>{[...new Set([...problems, ...serverProblems])].map((x) => <li key={x} className="mono">{x}</li>)}</ul>
            </div>
          )}
        </section>

        {/* ---------- 3 · Risk ---------- */}
        <section className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}><Shield size={18} /> {t.riskTitle}</h2>
            <span className="spacer" />
            <button className="btn btn-ghost btn-sm" onClick={() => setRawConfig((v) => !v)}>{t.rawConfig}</button>
          </div>
          {parsed.error && <p className="error-text">{parsed.error}</p>}
          {cfg && !rawConfig && (
            <>
              <div className="form-grid three">
                <label className="field">{t.exchange}
                  <select value={cfg.exchange} onChange={(e) => patchConfig((c) => { c.exchange = e.target.value; })}>
                    {EXCHANGES.map((x) => <option key={x}>{x}</option>)}
                  </select>
                </label>
                <label className="field">{t.symbol}
                  <input value={cfg.symbol} onChange={(e) => patchConfig((c) => { c.symbol = e.target.value.toUpperCase(); })} />
                </label>
                <label className="field">{t.timeframe}
                  <select value={cfg.timeframe} onChange={(e) => patchConfig((c) => { c.timeframe = e.target.value; })}>
                    {TIMEFRAMES.map((x) => <option key={x}>{x}</option>)}
                  </select>
                </label>
                <NumField label={t.leverage} value={cfg.leverage} step={1} onChange={(v) => patchConfig((c) => { c.leverage = v; })} />
                <NumField label={t.lookback} value={cfg.lookback} step={50} onChange={(v) => patchConfig((c) => { c.lookback = v; })} />
                <NumField label={t.qty} value={Number(cfg.params.qty ?? 0)} step={0.001} onChange={(v) => patchConfig((c) => { c.params.qty = v; })} />
                <NumField label={t.stopLoss} value={cfg.risk.stop_loss_pct} step={0.1} onChange={(v) => patchConfig((c) => { c.risk.stop_loss_pct = v; })} />
                <NumField label={t.maxQty} value={cfg.risk.max_position_qty} step={0.001} onChange={(v) => patchConfig((c) => { c.risk.max_position_qty = v; })} />
                <NumField label={t.maxEntries} value={cfg.risk.max_entries} step={1} onChange={(v) => patchConfig((c) => { c.risk.max_entries = v; })} />
                <NumField label={t.dailyLoss} value={cfg.risk.daily_loss_limit_usdt} step={1} onChange={(v) => patchConfig((c) => { c.risk.daily_loss_limit_usdt = v; })} />
                <NumField label={t.fee} value={cfg.costs.taker_fee_pct} step={0.01} onChange={(v) => patchConfig((c) => { c.costs.taker_fee_pct = v; })} />
                <NumField label={t.slippage} value={cfg.costs.slippage_pct} step={0.01} onChange={(v) => patchConfig((c) => { c.costs.slippage_pct = v; })} />
                <NumField label={t.months} value={cfg.backtest.months} step={1} onChange={(v) => patchConfig((c) => { c.backtest.months = v; })} />
              </div>
              <p className={`help ${cfg.risk.stop_loss_pct > liq * LIQ_BUFFER || cfg.risk.stop_loss_pct <= 0 ? "warn-text" : ""}`}>
                {fmt(t.liqNote, { l: liq.toFixed(1), x: cfg.leverage, b: (liq * LIQ_BUFFER).toFixed(1) })}
              </p>
              <ParamsField
                label={t.params}
                value={cfg.params}
                onChange={(v) => patchConfig((c) => { c.params = { ...v, qty: c.params.qty }; })}
              />
            </>
          )}
          {(rawConfig || !cfg) && (
            <textarea className="code small-code" rows={18} spellCheck={false} value={draft.config} onChange={(e) => setDraft((d) => ({ ...d, config: e.target.value }))} />
          )}
          <div className="field">
            {t.dataFile}
            <div className="row" style={{ marginTop: 6, flexWrap: "wrap" }}>
              <label className="btn btn-ghost btn-sm">
                <Upload size={16} />.csv
                <input type="file" accept=".csv" hidden onChange={(e) => setDataFile(e.target.files?.[0] ?? null)} />
              </label>
              {dataFile && (
                <span className="small">
                  {dataFile.name} · {(dataFile.size / 1024 / 1024).toFixed(1)} MB{" "}
                  <button className="link-btn" onClick={() => setDataFile(null)}>×</button>
                </span>
              )}
            </div>
            <span className="help">{fmt(t.dataHelp, { f: cfg ? dataFileName(cfg) : "data/…csv" })}</span>
          </div>
        </section>

        {/* ---------- 4 · Gates ---------- */}
        <section className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}><Flask size={18} /> {t.gatesTitle}</h2>
            <span className="spacer" />
            {s.runUrl && <a className="btn btn-ghost btn-sm" href={s.runUrl} target="_blank" rel="noreferrer">{t.openRun}</a>}
          </div>
          <div className="commit-box">
            {committedDirty && s.commitSha && <p className="help warn-text">{t.dirtyNote}</p>}
            <label className="field">
              {t.commitMsg}
              <input value={commitMsg} maxLength={200} placeholder={t.commitMsgPh} onChange={(e) => setCommitMsg(e.target.value)} />
            </label>
            <button
              className="btn btn-accent"
              style={{ marginTop: 12 }}
              onClick={commit}
              disabled={!!busy || problems.length > 0 || !cfg || s.status === "merged" || (!committedDirty && !dataFile && !!s.commitSha && s.status !== "failed")}
            >
              <Branch size={18} />{busy === "commit" ? t.committing : t.commit}
            </button>
            <Msg where="commit" />
          </div>
          <GateView t={t} s={s} report={report} />
        </section>

        {/* ---------- 5 · Review & 6 · Deploy ---------- */}
        <section className="card">
          <h2><Check size={18} /> {t.reviewTitle}</h2>
          <p className="muted small" style={{ marginTop: 0 }}>{t.reviewLead} ({s.branch} → {p.baseBranch})</p>
          {s.status === "merged" ? (
            <p className="ok-text">{t.mergedNote} {s.prUrl && <a href={s.prUrl} target="_blank" rel="noreferrer">#{s.prNumber}</a>}</p>
          ) : s.prUrl ? (
            <a className="btn btn-ghost" href={s.prUrl} target="_blank" rel="noreferrer">{t.openPr} #{s.prNumber}</a>
          ) : (
            <>
              <button className="btn btn-accent" onClick={submit} disabled={!!busy || s.status !== "passed" || committedDirty}>
                {busy === "submit" ? t.submitting : t.submit}
              </button>
              {(s.status !== "passed" || committedDirty) && <p className="help">{t.reviewWaiting}</p>}
            </>
          )}
          <Msg where="review" />

          <h2 style={{ marginTop: 26 }}><Rocket size={18} /> {t.deployTitle}</h2>
          <p className="muted small" style={{ marginTop: 0 }}>{t.deployLead}</p>
          {s.commitSha && (s.gateStatus === "pass" || p.isAdmin) ? (
            <a className="btn btn-accent" href={`/api/strategies/${s.id}/download`}><Download size={18} />{t.download}</a>
          ) : (
            <p className="help">{t.deployWaiting}</p>
          )}
          <p className="help mono" style={{ marginTop: 12 }}>{fmt(t.deploySteps, { s: s.slug })}</p>

          <hr className="sep" />
          <button className="btn btn-danger btn-sm" onClick={remove} disabled={!!busy}><Trash size={16} />{t.deleteStrategy}</button>
          <Msg where="delete" />
        </section>
      </div>
    </>
  );
}

function NumField({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (v: number) => void }) {
  const [text, setText] = useState(String(value ?? ""));
  useEffect(() => setText(String(value ?? "")), [value]);
  return (
    <label className="field">
      {label}
      <input
        type="number"
        step={step}
        min={0}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value !== "" && Number.isFinite(n)) onChange(n);
        }}
      />
    </label>
  );
}

function ParamsField({ label, value, onChange }: { label: string; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const shown = useMemo(() => {
    const rest = { ...value };
    delete rest.qty;
    return JSON.stringify(rest, null, 2);
  }, [value]);
  const [text, setText] = useState(shown);
  const [bad, setBad] = useState(false);
  useEffect(() => setText(shown), [shown]);
  return (
    <label className="field">
      {label}
      <textarea
        className={`code small-code ${bad ? "invalid" : ""}`}
        rows={6}
        spellCheck={false}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const v = JSON.parse(e.target.value);
            if (v && typeof v === "object" && !Array.isArray(v)) {
              setBad(false);
              onChange(v);
            } else setBad(true);
          } catch {
            setBad(true);
          }
        }}
      />
    </label>
  );
}

function money(v: number | undefined) {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
}

function SummaryCol({ title, x, t }: { title: string; x?: Summary; t: Dict }) {
  if (!x) return null;
  return (
    <div className="sum-col">
      <h4>{title}</h4>
      <dl>
        <dt>{t.net}</dt><dd className={x.net > 0 ? "pos" : "neg-strong"}>{money(x.net)}</dd>
        <dt>{t.trades}</dt><dd>{x.trades}</dd>
        <dt>{t.winRate}</dt><dd>{x.win_rate}%</dd>
        <dt>{t.pf}</dt><dd>{x.profit_factor >= 999 ? "∞" : x.profit_factor}</dd>
        <dt>{t.dd}</dt><dd>{x.max_drawdown.toFixed(2)}</dd>
        <dt>{t.fees}</dt><dd>{x.fees.toFixed(2)}</dd>
      </dl>
    </div>
  );
}

function Equity({ points, split }: { points: [number, number][]; split?: number }) {
  if (points.length < 2) return null;
  const xs = points.map((p) => p[0]);
  const ys = [0, ...points.map((p) => p[1])];
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const W = 600, H = 150;
  const X = (x: number) => ((x - x0) / Math.max(1, x1 - x0)) * W;
  const Y = (y: number) => H - 8 - ((y - y0) / Math.max(1e-9, y1 - y0)) * (H - 16);
  const line = points.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="equity" preserveAspectRatio="none" role="img" aria-label="equity curve">
      <line x1={0} x2={W} y1={Y(0)} y2={Y(0)} stroke="var(--border)" strokeDasharray="4 4" />
      {split && split > x0 && split < x1 && (
        <>
          <rect x={X(split)} y={0} width={W - X(split)} height={H} fill="rgba(193,250,116,.06)" />
          <line x1={X(split)} x2={X(split)} y1={0} y2={H} stroke="var(--accent)" strokeOpacity=".5" strokeDasharray="3 3" />
        </>
      )}
      <polyline points={line} fill="none" stroke="var(--accent)" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

function GateView({ t, s, report }: { t: Dict; s: PublicStrategy; report: GateReport | null }) {
  const day = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  if (!s.commitSha) return <p className="muted small">{t.gatesNone}</p>;
  if (s.status === "testing") {
    return (
      <div className="gate-wait">
        <div className="spin" />
        <span>{s.gateStatus === "running" ? t.gatesRunning : t.gatesQueued}</span>
      </div>
    );
  }
  return (
    <div>
      <p className={s.gateStatus === "pass" ? "ok-text" : "error-text"}>
        <b>{s.gateStatus === "pass" ? t.gatesPass : s.gateStatus === "error" ? t.gatesError : t.gatesFail}</b>
        {s.error && <> — {s.error}</>}
      </p>
      {report && (
        <>
          <ul className="gate-list">
            {report.gates.map((g) => (
              <li key={g.id} className={g.status}>
                {g.status === "pass" ? <Check size={16} /> : g.status === "fail" ? <Cross size={16} /> : <span className="dot">·</span>}
                <span><b>{g.label}</b> <small>{g.detail}</small></span>
              </li>
            ))}
          </ul>
          {report.warnings?.length > 0 && (
            <div className="note-box">{report.warnings.map((w) => <p key={w}>⚠️ {w}</p>)}</div>
          )}
          {report.equity && report.equity.length > 1 && (
            <>
              <h4 className="mini-h">{t.equityCurve}</h4>
              <Equity points={report.equity} split={report.oos_from} />
            </>
          )}
          <div className="sum-grid">
            <SummaryCol title={t.overall} x={report.overall} t={t} />
            <SummaryCol title={t.inSample} x={report.in_sample} t={t} />
            <SummaryCol title={t.outSample} x={report.out_of_sample} t={t} />
          </div>
          <dl className="kv small">
            {report.overall?.peak_margin != null && (<><dt>{t.peakMargin}</dt><dd>{report.overall.peak_margin.toFixed(2)} USDT · {t.roMargin} {report.overall.return_on_peak_margin_pct}%</dd></>)}
            {report.data && (<><dt>{t.dataUsed}</dt><dd>{report.data.candles.toLocaleString()} · {day(report.data.from)} → {day(report.data.to)}</dd></>)}
            {report.costs_used && (<><dt>{t.costsUsed}</dt><dd>{report.costs_used.taker_fee_pct}% + {report.costs_used.slippage_pct}%</dd></>)}
            {report.blocked && Object.keys(report.blocked).length > 0 && (
              <><dt>{t.blocked}</dt><dd>{Object.entries(report.blocked).map(([k, v]) => `${k}: ${v}`).join(", ")}</dd></>
            )}
          </dl>
          {report.last_trades && report.last_trades.length > 0 && (
            <details className="sub">
              <summary>{t.lastTrades} ({report.last_trades.length})</summary>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>{t.side}</th><th>{t.entry}</th><th>{t.exit}</th><th className="r">{t.pnl}</th><th>{t.reason}</th></tr></thead>
                  <tbody>
                    {[...report.last_trades].reverse().map((x) => (
                      <tr key={`${x.entry_time}-${x.exit_time}`}>
                        <td>{x.side} ×{x.entries}</td>
                        <td className="small">{new Date(x.entry_time).toISOString().slice(0, 16).replace("T", " ")}</td>
                        <td className="small">{new Date(x.exit_time).toISOString().slice(0, 16).replace("T", " ")}</td>
                        <td className={`r num ${x.pnl > 0 ? "pos" : "neg-strong"}`}>{money(x.pnl)}</td>
                        <td className="small">{x.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}
