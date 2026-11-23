// الشاشة 14 (جزء): الوضع التدريبي.
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";

type Ex = { id: number; title: string; level: string; instructions: string; material: { text?: string; url?: string }; labels: string[]; grades: string[];
  answer?: { label: string; grade: string; key_points: string[]; explanation: string }; submissions: Sub[] };
type Sub = { id: number; attempt: number; response: { label: string; grade: string; reasoning: string }; score: number; final_score: number;
  feedback: { label: string; grade: string; reasoning: string; missed: string[] }; trainer_score: number | null; trainer_note: string; user?: string };

export function Training() {
  const { id } = useParams();
  return id ? <Exercise id={Number(id)} /> : <List />;
}

function List() {
  const can = useCan();
  const nav = useNavigate();
  const [rows, setRows] = useState<{ id: number; title: string; level: string; published: boolean; my_score: number | null }[]>([]);
  useEffect(() => { api<typeof rows>("/api/training").then(setRows).catch(() => {}); }, []);
  return (
    <div className="cols">
      <section className="card grow">
        <h2>تمارين التحقق</h2>
        <span className="mu" style={{ fontSize: 13 }}>اقرأ المادة، احكم عليها، واختر درجة الدليل، واكتب تعليلك. يُصحَّح التمرين فورًا ويظهر الحل النموذجي بعد إجابتك.</span>
        {rows.map((e) => (
          <div key={e.id} className="row">
            <span className="f"><Link to={`/training/${e.id}`}><b>{e.title}</b></Link><br /><span className="mu" style={{ fontSize: 12 }}>{e.level}{!e.published ? " · غير منشور" : ""}</span></span>
            {e.my_score != null ? <span className={`pill ${e.my_score >= 75 ? "p-ok" : e.my_score >= 50 ? "p-warn" : "p-bad"}`}>{Math.round(e.my_score)} / 100</span> : <span className="pill p-n">لم يُحل</span>}
          </div>
        ))}
      </section>
      {can("training.manage") && <NewExercise onDone={(id) => nav(`/training/${id}`)} />}
    </div>
  );
}

function Exercise({ id }: { id: number }) {
  const can = useCan();
  const [e, setE] = useState<Ex | null>(null);
  const [f, setF] = useState({ label: "", grade: "", reasoning: "" });
  const [res, setRes] = useState<Sub | null>(null);
  const load = () => api<Ex>(`/api/training/${id}`).then((x) => { setE(x); setRes(x.submissions[x.submissions.length - 1] ?? null); });
  useEffect(() => { load(); }, [id]);
  if (!e) return null;
  const submit = async (ev: React.FormEvent) => { ev.preventDefault(); await api(`/api/training/${id}/submit`, { method: "POST", body: f }); await load(); };
  return (
    <div className="cols">
      <div className="grow">
        <section className="card">
          <span className="mu"><Link to="/training">التمارين</Link> › {e.level}</span>
          <h2>{e.title}</h2>
          <p>{e.instructions}</p>
          <div className="card" style={{ background: "var(--sf2)", whiteSpace: "pre-wrap" }} aria-label="مادة التمرين">{e.material.text}</div>
          {e.material.url && <a href={e.material.url} target="_blank" rel="noreferrer noopener">المادة الأصلية</a>}
        </section>
        <form className="card" onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h2>{res ? `محاولة جديدة (${res.attempt + 1})` : "إجابتك"}</h2>
          <label className="fld">الحكم<select className="inp" value={f.label} onChange={(x) => setF({ ...f, label: x.target.value })}><option value="">اختر…</option>{e.labels.map((l) => <option key={l}>{l}</option>)}</select></label>
          <label className="fld">درجة الدليل<select className="inp" value={f.grade} onChange={(x) => setF({ ...f, grade: x.target.value })}><option value="">اختر…</option>{e.grades.map((l) => <option key={l}>{l}</option>)}</select></label>
          <label className="fld">التعليل<textarea className="inp" rows={4} value={f.reasoning} onChange={(x) => setF({ ...f, reasoning: x.target.value })} /></label>
          <button className="btn pri" disabled={!f.label || !f.grade}>تسليم</button>
        </form>
      </div>
      <div className="side">
        {res && (
          <section className="card" aria-label="النتيجة">
            <h2>النتيجة: {Math.round(res.final_score)} / 100</h2>
            <div className="row"><span className="f">{res.feedback.label}</span></div>
            <div className="row"><span className="f">{res.feedback.grade}</span></div>
            <div className="row"><span className="f">{res.feedback.reasoning}{res.feedback.missed.length ? ` فاتك: ${res.feedback.missed.join("، ")}` : ""}</span></div>
            {res.trainer_score != null && <div className="msg">تصحيح المدرّب: {res.trainer_score}{res.trainer_note ? ` — ${res.trainer_note}` : ""}</div>}
          </section>
        )}
        {e.answer && (
          <section className="card" aria-label="الحل النموذجي">
            <h2>الحل النموذجي</h2>
            <p><b>{e.answer.label}</b> · درجة الدليل: <b>{e.answer.grade}</b></p>
            <p>{e.answer.explanation}</p>
          </section>
        )}
        {can("training.manage") && <Submissions id={id} />}
      </div>
    </div>
  );
}

function Submissions({ id }: { id: number }) {
  const [rows, setRows] = useState<Sub[]>([]);
  const load = () => api<Sub[]>(`/api/training/${id}/submissions`).then(setRows);
  useEffect(() => { load(); }, [id]);
  return (
    <section className="card">
      <h2>إجابات المتدربين ({rows.length})</h2>
      {rows.map((s) => <Regrade key={s.id} s={s} onDone={load} />)}
    </section>
  );
}

function Regrade({ s, onDone }: { s: Sub; onDone: () => void }) {
  const [score, setScore] = useState(String(s.final_score));
  const [note, setNote] = useState(s.trainer_note);
  return (
    <div className="row" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <span><b>{s.user}</b> · {s.response.label} / {s.response.grade} · آلي {s.score}</span>
      <span className="mu" style={{ fontSize: 12 }}>{s.response.reasoning}</span>
      <div style={{ display: "flex", gap: 6 }}>
        <input className="inp" style={{ width: 80 }} value={score} onChange={(e) => setScore(e.target.value)} aria-label="درجة المدرّب" />
        <input className="inp" value={note} onChange={(e) => setNote(e.target.value)} placeholder="ملاحظة" aria-label="ملاحظة المدرّب" />
        <button className="btn sm" onClick={() => api(`/api/training/submissions/${s.id}/grade`, { method: "POST", body: { score: Number(score), note } }).then(onDone)}>حفظ</button>
      </div>
    </div>
  );
}

function NewExercise({ onDone }: { onDone: (id: number) => void }) {
  const [f, setF] = useState({ title: "", level: "مبتدئ", instructions: "", text: "", label: "", grade: "", key_points: "", explanation: "" });
  const [err, setErr] = useState("");
  const go = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try {
      const r = await api<{ id: number }>("/api/training", { method: "POST", body: { title: f.title, level: f.level, instructions: f.instructions, material: { text: f.text },
        answer: { label: f.label, grade: f.grade, key_points: f.key_points.split("\n"), explanation: f.explanation } } });
      onDone(r.id);
    } catch (x) { setErr((x as Error).message); }
  };
  const L = ["صحيح", "صحيح جزئيًا", "مضلل", "مفبرك", "غير مؤكد"], G = ["قاطع", "مؤشر قوي", "لا يكفي"];
  return (
    <form className="card side" onSubmit={go} style={{ display: "flex", flexDirection: "column", gap: 6 }} aria-label="تمرين جديد">
      <h2>تمرين جديد</h2>
      <label className="fld">العنوان<input className="inp" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
      <label className="fld">المستوى<select className="inp" value={f.level} onChange={(e) => setF({ ...f, level: e.target.value })}><option>مبتدئ</option><option>متوسط</option><option>متقدم</option></select></label>
      <label className="fld">التعليمات<input className="inp" value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} /></label>
      <label className="fld">المادة<textarea className="inp" rows={4} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></label>
      <label className="fld">الحكم الصحيح<select className="inp" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })}><option value="">اختر…</option>{L.map((x) => <option key={x}>{x}</option>)}</select></label>
      <label className="fld">درجة الدليل<select className="inp" value={f.grade} onChange={(e) => setF({ ...f, grade: e.target.value })}><option value="">اختر…</option>{G.map((x) => <option key={x}>{x}</option>)}</select></label>
      <label className="fld">النقاط الأساسية في التعليل (سطر لكل نقطة، والبدائل بـ |)<textarea className="inp" rows={3} value={f.key_points} onChange={(e) => setF({ ...f, key_points: e.target.value })} /></label>
      <label className="fld">الحل النموذجي<textarea className="inp" rows={3} value={f.explanation} onChange={(e) => setF({ ...f, explanation: e.target.value })} /></label>
      {err && <div className="msg err">{err}</div>}
      <button className="btn pri" disabled={!f.title || !f.label || !f.grade}>إنشاء</button>
    </form>
  );
}
