import Link from "next/link";
import { getSessionUser } from "@/app/auth";
import { getDict } from "@/lib/lang-server";
import SiteHeader from "./components/SiteHeader";
import { Branch, Check, Code, Doc, Flask, Rocket, Sparkle } from "./components/icons";

export const dynamic = "force-dynamic";

const DEMO_GATES = ["Code check", "Risk settings", "Backtest runs", "Out-of-sample", "Drawdown vs margin", "Live = backtest"];
const DEMO_EQUITY = [0, 2, 1, 4, 6, 5, 9, 8, 12, 11, 15, 18, 16, 21, 24, 23, 27];

export default async function Landing() {
  const [{ t, lang }, user] = await Promise.all([getDict(), getSessionUser().catch(() => null)]);

  const features = [
    { icon: <Doc size={30} />, title: t.feat1, text: t.feat1d },
    { icon: <Sparkle size={30} />, title: t.feat2, text: t.feat2d },
    { icon: <Code size={30} />, title: t.feat3, text: t.feat3d },
    { icon: <Flask size={30} />, title: t.feat4, text: t.feat4d },
    { icon: <Rocket size={30} />, title: t.feat5, text: t.feat5d },
  ];
  const ctaHref = user ? "/workspace" : "/register";
  const max = Math.max(...DEMO_EQUITY);
  const pts = DEMO_EQUITY.map((v, i) => `${(i / (DEMO_EQUITY.length - 1)) * 260},${80 - (v / max) * 70}`).join(" ");

  return (
    <>
      <SiteHeader t={t} lang={lang} signedIn={!!user} />
      <main className="wrap">
        <section className="hero">
          <div>
            <span className="eyebrow">{t.heroEyebrow}</span>
            <h1>
              {t.heroTitle1}
              <span className="accent">{t.heroTitle2}</span>
            </h1>
            <p className="lead">{t.heroLead}</p>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <Link href={ctaHref} className="btn btn-accent btn-lg"><Branch size={20} />{t.heroCta}</Link>
              <a href="#how" className="btn btn-ghost btn-lg">{t.heroCta2}</a>
            </div>
          </div>

          <div className="hero-visual" aria-hidden>
            <div className="float-tag a"><Branch size={18} />strategy/eth-ema-flip</div>
            <div className="float-tag b"><Rocket size={18} />{lang === "zh" ? "下载机器人 · .zip" : "Download bot · .zip"}</div>
            <div className="demo-card card">
              <div className="row" style={{ marginBottom: 12 }}>
                <span className="pill ok">{t.gatesPass}</span>
                <span className="spacer" />
                <span className="mono muted">a1c9e42</span>
              </div>
              <ul className="gate-list">
                {DEMO_GATES.map((g) => (
                  <li key={g} className="pass"><Check size={16} />{g}</li>
                ))}
              </ul>
              <svg viewBox="0 0 260 84" className="demo-curve">
                <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinejoin="round" />
              </svg>
              <div className="demo-stats">
                <span><small>{t.outSample}</small><b className="pos">+22.1</b></span>
                <span><small>{t.pf}</small><b>1.84</b></span>
                <span><small>{t.dd}</small><b>9.6</b></span>
              </div>
            </div>
          </div>
        </section>

        <section className="features">
          {features.map((f) => (
            <div className="card feature" key={f.title}>
              <div className="ico">{f.icon}</div>
              <b>{f.title}</b>
              <p>{f.text}</p>
            </div>
          ))}
        </section>

        <section className="section" id="how">
          <span className="eyebrow">01 · 02 · 03</span>
          <h2>{t.howTitle}</h2>
          <div className="steps">
            {[[t.how1, t.how1d], [t.how2, t.how2d], [t.how3, t.how3d]].map(([h, d], i) => (
              <div className="card step" key={h}>
                <div className="step-n">{i + 1}</div>
                <h3>{h}</h3>
                <p>{d}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="section" id="rules">
          <span className="eyebrow">{t.heroEyebrow}</span>
          <h2>{t.rulesTitle}</h2>
          <div className="rules">
            {[[t.rule1, t.rule1d], [t.rule2, t.rule2d], [t.rule3, t.rule3d], [t.rule4, t.rule4d]].map(([h, d]) => (
              <div className="card" key={h}>
                <b>{h}</b>
                <p>{d}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="section faq" id="faq">
          <h2>{t.faqTitle}</h2>
          {[[t.faq1q, t.faq1a], [t.faq2q, t.faq2a], [t.faq3q, t.faq3a]].map(([q, a]) => (
            <details key={q}>
              <summary>{q}</summary>
              <p>{a}</p>
            </details>
          ))}
        </section>
      </main>
      <footer className="site-footer">© {new Date().getFullYear()} {t.brand} · {t.footer}</footer>
    </>
  );
}
