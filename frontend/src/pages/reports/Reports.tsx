// الشاشة 14 (جزء): الموجزات والتقارير.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";

type Row = { id: number; kind: string; local_date: string; created_at: string; auto: boolean; summary: string };
type Content = { items: number; edited_or_deleted: number; top_outlets: { name: string; items: number }[];
  rising_stories: { id: number; title: string; outlets: number; link: string }[];
  claims: { new_count: number; new: { id: number; text: string; link: string }[]; returns: { id: number; text: string; times: number; link: string }[];
    verdicts: { claim_id: number; label: string; grade: string; text: string; link: string }[] };
  sources: { ok: number; error: number; total: number; broken: { id: number; title: string; error: string }[] };
  alerts: { kind: string; text: string; at: string }[]; engine_cost_usd?: number | null };

const KIND = { morning: "الموجز الصباحي", weekly: "التقرير الأسبوعي" } as Record<string, string>;
const DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"];

export function Reports() {
  const { id } = useParams();
  return id ? <ReportView id={Number(id)} /> : <ReportList />;
}

function ReportList() {
  const can = useCan();
  const [d, setD] = useState<{ schedule: { morning: string; weekly: string; weekly_day: number; tz: string }; rows: Row[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => api<typeof d>("/api/reports").then(setD);
  useEffect(() => { load(); }, []);
  const gen = async (k: string) => { setBusy(true); try { await api(`/api/reports/${k}`, { method: "POST" }); await load(); } finally { setBusy(false); } };
  if (!d) return null;
  return (
    <div className="cols">
      <section className="card grow">
        <h2>الموجزات والتقارير</h2>
        <span className="mu" style={{ fontSize: 13 }}>الموجز الصباحي يُنشأ تلقائيًا كل يوم الساعة {d.schedule.morning}، والتقرير الأسبوعي يوم {DAYS[d.schedule.weekly_day]} الساعة {d.schedule.weekly} ({d.schedule.tz}). يصل ملخصهما على تيليغرام لمن ربط حسابه.</span>
        {!d.rows.length && <p className="mu">لا تقارير بعد.</p>}
        {d.rows.map((r) => (
          <div key={r.id} className="row">
            <span className="f"><Link to={`/reports/${r.id}`}><b>{KIND[r.kind]} · {r.local_date}</b></Link><br /><span className="mu" style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{r.summary.split("\n").slice(1, 2).join("")}</span></span>
            <span className="pill p-n">{r.auto ? "تلقائي" : "يدوي"}</span>
          </div>
        ))}
      </section>
      {can("monitor.view") && (
        <section className="card side">
          <h2>إنشاء الآن</h2>
          <button className="btn" disabled={busy} onClick={() => gen("morning")}>موجز آخر 24 ساعة</button>
          <button className="btn" disabled={busy} onClick={() => gen("weekly")}>تقرير آخر 7 أيام</button>
        </section>
      )}
    </div>
  );
}

function ReportView({ id }: { id: number }) {
  const [r, setR] = useState<(Row & { content: Content }) | null>(null);
  useEffect(() => { api<typeof r>(`/api/reports/${id}`).then(setR); }, [id]);
  if (!r) return null;
  const c = r.content;
  const list = (rows: { link: string; text: string }[], empty: string) => rows.length ? rows.map((x, i) => <div key={i} className="row"><Link className="f" to={x.link}>{x.text}</Link></div>) : <span className="mu">{empty}</span>;
  return (
    <div className="cols">
      <div className="grow">
        <section className="card">
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <h2 style={{ flex: 1 }}>{KIND[r.kind]} · {r.local_date}</h2>
            <a className="btn sm" href={`/api/reports/${id}/print`} target="_blank" rel="noreferrer">طباعة أو PDF</a>
            <Link className="btn sm" to="/reports">كل التقارير</Link>
          </div>
          <div className="g4">
            <div><b style={{ fontSize: 22 }}>{c.items}</b><br /><span className="mu">مادة جديدة</span></div>
            <div><b style={{ fontSize: 22 }}>{c.claims.new_count}</b><br /><span className="mu">ادّعاء جديد</span></div>
            <div><b style={{ fontSize: 22 }}>{c.claims.verdicts.length}</b><br /><span className="mu">حكم معتمد</span></div>
            <div><b style={{ fontSize: 22 }}>{c.edited_or_deleted}</b><br /><span className="mu">عُدّلت أو حُذفت</span></div>
          </div>
        </section>
        <section className="card"><h2>القصص الصاعدة</h2>{list(c.rising_stories.map((s) => ({ link: s.link, text: `${s.title} — ${s.outlets} مصادر` })), "لا قصص صاعدة.")}</section>
        <section className="card"><h2>شائعات عادت</h2>{list(c.claims.returns, "لم تعد شائعة مكشوفة.")}</section>
        <section className="card"><h2>أحكام معتمدة</h2>{list(c.claims.verdicts.map((v) => ({ link: v.link, text: `${v.label} (${v.grade}): ${v.text}` })), "لا أحكام جديدة.")}</section>
        <section className="card"><h2>ادّعاءات جديدة</h2>{list(c.claims.new, "لا ادّعاءات جديدة.")}</section>
      </div>
      <div className="side">
        <section className="card"><h2>أكثر الجهات نشرًا</h2>{c.top_outlets.map((o) => <div key={o.name} className="row"><span className="f">{o.name}</span><b>{o.items}</b></div>)}</section>
        <section className="card"><h2>المصادر</h2><span>{c.sources.ok} تعمل · {c.sources.error} متوقفة من {c.sources.total}</span>
          {c.sources.broken.map((s) => <div key={s.id} className="row"><span className="f mu" style={{ fontSize: 12 }}>{s.title}: {s.error}</span></div>)}</section>
        {c.alerts.length > 0 && <section className="card"><h2>تنبيهات عاجلة</h2>{c.alerts.map((a, i) => <div key={i} className="row"><span className="f" style={{ fontSize: 13 }}>{a.text}</span></div>)}</section>}
        {c.engine_cost_usd != null && <section className="card"><h2>كلفة المحركات</h2><b>{c.engine_cost_usd.toFixed(2)} $</b></section>}
      </div>
    </div>
  );
}
