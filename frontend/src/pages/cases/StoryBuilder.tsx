// الشاشة 11: بناء القصة.
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";

type Draft = { id: number; case_id: number; case_title: string; title: string; status: string; version: number; angle?: string; body?: string; questions?: string[];
  check: { sentences: { text: string; sourced: boolean; needs_source: boolean }[]; unsourced: string[]; broken_refs: string[]; all_sourced: boolean };
  checklist: { key: string; label: string; mode: string; done: boolean }[]; ready: boolean; sources: { doc: number; filename: string; sha256: string; method: string }[] };

export function StoryBuilder() {
  const { id } = useParams();
  return id ? <Builder id={Number(id)} /> : <DraftList />;
}

function DraftList() {
  const [rows, setRows] = useState<{ id: number; title: string; status: string; case_id: number; case_title: string; updated_at: string }[]>([]);
  useEffect(() => { api<typeof rows>("/api/drafts").then(setRows).catch(() => {}); }, []);
  return (
    <section className="card">
      <h2>المسودات</h2>
      {!rows.length && <span className="mu">لا مسودات. افتح قضية واضغط «ابنِ القصة من الأدلة».</span>}
      {rows.map((d) => (
        <div key={d.id} className="row"><span className="f"><Link to={`/story-builder/${d.id}`}><b>{d.title}</b></Link><br /><span className="mu" style={{ fontSize: 12 }}>قضية #{d.case_id}: {d.case_title}</span></span>
          <span className={`pill ${d.status === "approved" ? "p-ok" : "p-n"}`}>{d.status === "approved" ? "معتمدة" : "مسودة"}</span></div>
      ))}
    </section>
  );
}

function Builder({ id }: { id: number }) {
  const can = useCan();
  const nav = useNavigate();
  const [d, setD] = useState<Draft | null>(null);
  const [f, setF] = useState({ title: "", angle: "", body: "", questions: "" });
  const [msg, setMsg] = useState<{ text: string; err?: boolean } | null>(null);
  const [dirty, setDirty] = useState(false);
  const take = (x: Draft) => { setD(x); setF({ title: x.title, angle: x.angle ?? "", body: x.body ?? "", questions: (x.questions ?? []).join("\n") }); setDirty(false); };
  useEffect(() => { api<Draft>(`/api/drafts/${id}`).then(take).catch((x) => setMsg({ text: (x as Error).message, err: true })); }, [id]);
  if (!d) return msg ? <div className="msg err">{msg.text}</div> : null;
  const run = async (fn: () => Promise<Draft>, ok: string) => { setMsg(null); try { take(await fn()); setMsg({ text: ok }); } catch (x) { setMsg({ text: (x as Error).message, err: true }); } };
  const save = () => run(() => api<Draft>(`/api/drafts/${id}`, { method: "PUT", body: { title: f.title, angle: f.angle, body: f.body, questions: f.questions.split("\n").filter((q) => q.trim()), version: d.version } }), "حُفظت المسودة.");
  const editable = can("stories.write");
  return (
    <div className="cols">
      <div className="grow">
        <span className="mu"><Link to="/cases">القضايا</Link> › <Link to={`/cases/${d.case_id}`}>قضية #{d.case_id}</Link> › المسودة</span>
        <section className="card">
          <label className="fld">العنوان<input className="inp" value={f.title} disabled={!editable} onChange={(e) => { setF({ ...f, title: e.target.value }); setDirty(true); }} /></label>
          <label className="fld">الزاوية<input className="inp" value={f.angle} disabled={!editable} onChange={(e) => { setF({ ...f, angle: e.target.value }); setDirty(true); }} /></label>
          <label className="fld">المسودة
            <textarea className="inp" rows={12} aria-label="نص المسودة" value={f.body} disabled={!editable} onChange={(e) => { setF({ ...f, body: e.target.value }); setDirty(true); }} style={{ lineHeight: 1.9 }} />
          </label>
          <span className="mu" style={{ fontSize: 12 }}>اربط كل معلومة بدليلها: [وثيقة 3] أو [وثيقة 3 ص 2]، أو [مادة 120] لخبر مرصود، أو [دليل 7] لدليل في بطاقة ادّعاء.</span>
          <label className="fld">أسئلة مفتوحة (سطر لكل سؤال)<textarea className="inp" rows={3} value={f.questions} disabled={!editable} onChange={(e) => { setF({ ...f, questions: e.target.value }); setDirty(true); }} /></label>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            {editable && <button className="btn pri" disabled={!dirty} onClick={save}>حفظ وفحص المصادر</button>}
            <a className="btn" href={`/api/drafts/${id}/export.docx`}>تصدير Word</a>
            {msg && <div className={`msg ${msg.err ? "err" : ""}`} role="status" style={{ margin: 0 }}>{msg.text}{msg.err && msg.text.includes("زميل") && <button className="btn sm" onClick={() => api<Draft>(`/api/drafts/${id}`).then(take)}>حمّل الأحدث</button>}</div>}
          </div>
        </section>
        <section className="card" aria-label="المسودة مع المصادر">
          <h2>المسودة كما تُقرأ</h2>
          <span className="mu" style={{ fontSize: 12 }}>كل جملة فيها معلومة مرتبطة بدليلها. الجملة بلا دليل تظهر بخط تحتها.</span>
          <p style={{ lineHeight: 2 }}>
            {d.check.sentences.map((s, i) => (
              <span key={i} data-unsourced={!s.sourced || undefined} style={!s.sourced ? { textDecoration: "underline wavy var(--bad)", textUnderlineOffset: 5 } : undefined}>{s.text} </span>
            ))}
          </p>
          {d.check.broken_refs.length > 0 && <div className="msg err">إحالات إلى أدلة غير موجودة: {d.check.broken_refs.join("، ")}</div>}
        </section>
      </div>
      <div className="side">
        <section className="card" aria-label="المصادر">
          <h2>المصادر بجانب النص</h2>
          {!d.sources.length && <span className="mu">لا إحالات إلى وثائق بعد.</span>}
          {d.sources.map((s) => (
            <div key={s.doc} className="row"><span className="f"><Link to={`/cases/${d.case_id}/docs/${s.doc}`}>وثيقة {s.doc} · {s.filename}</Link><br /><span className="mu" dir="ltr" style={{ fontSize: 11 }}>{s.sha256.slice(0, 16)}…</span></span><span className="pill p-ok">مؤكد</span></div>
          ))}
        </section>
        <section className="card" aria-label="قبل النشر">
          <h2>قبل النشر</h2>
          {d.checklist.map((c) => (
            <label key={c.key} className="row" style={{ cursor: c.mode === "manual" && editable ? "pointer" : "default" }}>
              <input type="checkbox" checked={c.done} disabled={c.mode !== "manual" || !editable}
                     onChange={(e) => run(() => api<Draft>(`/api/drafts/${id}/checklist`, { method: "POST", body: { key: c.key, done: e.target.checked } }), "حُدّثت القائمة.")} />
              <span className="f">{c.label}{c.mode === "auto" ? " (يُحسب تلقائيًا)" : c.mode === "approve" ? " (محرّر آخر)" : ""}</span>
            </label>
          ))}
          {can("stories.approve") && d.status !== "approved" && <button className="btn pri" onClick={() => run(() => api<Draft>(`/api/drafts/${id}/approve`, { method: "POST" }), "اعتُمدت المسودة.")}>اعتماد</button>}
          {d.status === "approved" && <span className="pill p-ok">معتمدة · الإصدار {d.version}</span>}
          <button className="btn sm" onClick={() => nav(`/cases/${d.case_id}`)}>العودة إلى القضية</button>
        </section>
      </div>
    </div>
  );
}
