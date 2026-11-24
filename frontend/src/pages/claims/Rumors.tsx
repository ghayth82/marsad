import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";

export type ClaimRow = { id: number; text: string; status: string; origin: string; first_seen_at: string | null; appearances: number; returns: number;
  verdict: { label: string; evidence_grade: string; status: string } | null };
type Radar = { term: string; count: number; expected: number; score: number; samples: string[] };
type Alert = { id: number; text: string; created_at: string; read: boolean };

export const STATUS: Record<string, [string, string]> = {
  new: ["p-warn", "جديد"], assigned: ["p-n", "مُسند"], investigating: ["p-ac", "قيد التحقق"], proposed: ["p-warn", "حكم مقترح"], verdict: ["p-ok", "حكم معتمد"], dismissed: ["p-n", "مرفوض"], archived: ["p-n", "مؤرشف"] };
export const labelPill = (l?: string) => (l === "صحيح" ? "p-ok" : l === "مضلل" || l === "مفبرك" ? "p-bad" : l ? "p-warn" : "p-n");

export function Rumors() {
  const can = useCan();
  const nav = useNavigate();
  const [radar, setRadar] = useState<Radar[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [claims, setClaims] = useState<ClaimRow[]>([]);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Radar[]>("/api/rumors/radar").then(setRadar).catch(() => {});
    api<Alert[]>("/api/rumors/alerts").then(setAlerts).catch(() => {});
  }, []);
  useEffect(() => {
    const t = setTimeout(() => api<ClaimRow[]>(`/api/claims?${new URLSearchParams({ q, ...(status ? { status } : {}) })}`).then(setClaims), 250);
    return () => clearTimeout(t);
  }, [q, status]);
  const add = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try { const c = await api<ClaimRow>("/api/claims", { method: "POST", body: { text } }); nav(`/claims/${c.id}`); }
    catch (x) { setErr((x as Error).message); }
  };
  return (
    <div className="cols">
      <div className="grow">
        {alerts.filter((a) => !a.read).slice(0, 5).map((a) => {
          const m = a.text.match(/\/claims\/(\d+)/);
          return (
            <div key={a.id} className="msg err" role="alert" style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span style={{ flex: 1 }}>{a.text.replace(/التحقق السابق: \/claims\/\d+/, "")}</span>
              {m && <Link className="btn sm" to={`/claims/${m[1]}`}>التحقق السابق</Link>}
            </div>
          );
        })}
        <section className="card">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <h2 style={{ flex: 1 }}>سجل الادّعاءات</h2>
            <input className="inp" style={{ width: 220, height: 36 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="بحث" aria-label="بحث في الادّعاءات" />
            <select className="inp" style={{ width: 150, height: 36 }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="الحالة">
              <option value="">كل الحالات</option>{Object.entries(STATUS).map(([k, [, l]]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </div>
          {!claims.length && <span className="mu">لا ادّعاءات. تُسجَّل تلقائيًا من مواد الشائعات، أو أضف ادّعاءً.</span>}
          {claims.map((c) => (
            <div key={c.id} className="row">
              <span className="f"><Link to={`/claims/${c.id}`}>{c.text}</Link><br />
                <span className="mu">{c.appearances} ظهور{c.returns ? ` · عاد ${c.returns} مرة` : ""}{c.origin === "auto" ? " · رُصد تلقائيًا" : ""}</span></span>
              {c.verdict && <span className={`pill ${labelPill(c.verdict.label)}`}>{c.verdict.label}</span>}
              <span className={`pill ${STATUS[c.status]?.[0] ?? "p-n"}`}>{STATUS[c.status]?.[1] ?? c.status}</span>
            </div>
          ))}
        </section>
      </div>
      <div className="side">
        <Campaigns />
        {can("claims.create") && (
          <form className="card" onSubmit={add}>
            <h2>ادّعاء جديد</h2>
            <textarea className="inp" rows={3} style={{ height: "auto", padding: 10 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="الجملة القابلة للتحقق كما وردت" aria-label="نص الادّعاء" />
            {err && <div className="msg err">{err}</div>}
            <button className="btn pri" disabled={text.trim().length < 10}>تسجيل وفتح البطاقة</button>
          </form>
        )}
        <section className="card">
          <h2>الرادار: مواضيع تتصاعد الآن</h2>
          <span className="mu">آخر 3 ساعات مقارنة بمعدل الأسبوع.</span>
          {!radar.length && <span className="mu">لا تصاعد غير معتاد.</span>}
          {radar.map((r) => (
            <div key={r.term} className="row"><span className="f"><Link to={`/live?q=${encodeURIComponent(r.term)}`}><b>{r.term}</b></Link><br /><span className="mu">{r.samples[0]}</span></span>
              <span className="pill p-warn">{r.count} مقابل {r.expected}</span></div>
          ))}
        </section>
        <a className="btn" href="/api/claims/export/claimreview">تصدير ClaimReview</a>
        <a className="btn" href="/api/claims/export/csv">تصدير CSV</a>
      </div>
    </div>
  );
}

type Cluster = { kind: string; accounts: string[]; count: number; start: string; span_minutes: number; score: number; note: string;
  items: { id: number; author: string; url: string; title: string; time: string }[] };

/** مؤشرات الحملات المنسّقة على المنصات وتيليغرام. */
export function Campaigns() {
  const [d, setD] = useState<{ clusters: Cluster[]; items: number; note: string } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { api<typeof d>("/api/social/campaigns?hours=24").then(setD).catch(() => {}); }, []);
  if (!d) return null;
  return (
    <section className="card" aria-label="الحملات المنسّقة">
      <h2>مؤشرات الحملات المنسّقة · 24 ساعة</h2>
      <span className="mu" style={{ fontSize: 12 }}>{d.note}</span>
      {!d.clusters.length && <span className="mu">لا مؤشرات في {d.items} منشورًا من المنصات وتيليغرام.</span>}
      {d.clusters.map((c, i) => (
        <div key={i} className="row" style={{ flexDirection: "column", alignItems: "stretch" }}>
          <button className="btn sm" style={{ justifyContent: "space-between", display: "flex" }} onClick={() => setOpen(open === i ? null : i)}>
            <span>{c.kind}</span><span className="pill p-warn">{c.accounts.length} حساب · {Math.round(c.span_minutes)} د</span>
          </button>
          {open === i && <>
            <span className="mu" style={{ fontSize: 12 }}>{c.note}</span>
            {c.items.map((x) => <a key={x.id} href={x.url} target="_blank" rel="noreferrer noopener" style={{ fontSize: 13 }}>@{x.author}: {x.title}</a>)}
          </>}
        </div>
      ))}
    </section>
  );
}
