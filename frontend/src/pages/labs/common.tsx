import { useState } from "react";
import { api, apiForm } from "../../api";

export type Check = { id: number; check: string; label: string; grade: string; summary: string; result: Record<string, any> };
export type Media = {
  id: number; kind: string; mime: string; filename: string; size: number; sha256: string; phash: string; width: number; height: number;
  duration: number; origin: string; url: string; seen_at: string; overall: { grade: string; because: { check: string; summary: string }[] };
  checks: Check[]; reverse_links: { name: string; url: string }[];
};
export type Recent = { id: number; kind: string; filename: string; seen_at: string; grade: string };

export const gradePill = (g: string) => (g === "قاطع" ? "p-ok" : g === "مؤشر قوي" ? "p-warn" : g === "مؤشر" ? "p-ac" : "p-n");
export const gradeText = (g: string) => (g === "لا يكفي" ? "لا يكفي للحكم" : g === "قاطع" ? "دليل قاطع" : g);
export const fileUrl = (rel: string) => `/api/labs/files/${rel.split("/").pop()!.split(".")[0]}`;
export const fmt = (s: string) => new Date(s).toLocaleString("ar", { dateStyle: "medium", timeStyle: "short" });
export const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

/** نموذج الرفع: ملف أو رابط، مع التاريخ المدّعى (يُقارن به الأرشيف). */
export function UploadForm({ accept, onDone, label }: { accept: string; onDone: (m: Media) => void; label: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [claimed, setClaimed] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setBusy(true);
    const f = new FormData();
    if (file) f.append("file", file); else f.append("url", url.trim());
    if (claimed) f.append("claimed_at", new Date(claimed).toISOString());
    try { onDone(await apiForm<Media>("/api/labs/media", f)); setFile(null); setUrl(""); }
    catch (x) { setErr((x as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <form className="card" onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h2>{label}</h2>
      <label className="fld">الملف<input className="inp" type="file" accept={accept} aria-label="الملف" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      <label className="fld">أو رابط مباشر<input className="inp" dir="ltr" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" aria-label="رابط الملف" /></label>
      <label className="fld">التاريخ المدّعى (اختياري)<input className="inp" type="datetime-local" value={claimed} onChange={(e) => setClaimed(e.target.value)} aria-label="التاريخ المدّعى" /></label>
      {err && <div className="msg err" role="alert">{err}</div>}
      <button className="btn pri" disabled={busy || (!file && !url.trim())}>{busy ? "يجري الفحص…" : "افحص"}</button>
      <span className="mu" style={{ fontSize: 12 }}>يُحفظ الملف في الأرشيف ببصمته SHA-256، ولا يُرسل إلى أي جهة خارجية.</span>
    </form>
  );
}

export function Checks({ m }: { m: Media }) {
  return (
    <section className="card">
      <h2>الفحوص</h2>
      {m.checks.filter((c) => c.check !== "hashes").map((c) => (
        <div key={c.id} className="row" data-check={c.check}>
          <span className="f"><b>{c.label}</b><br /><span className="mu">{c.summary}</span></span>
          {c.grade && c.grade !== "—" && <span className={`pill ${gradePill(c.grade)}`}>{gradeText(c.grade)}</span>}
        </div>
      ))}
    </section>
  );
}

export function Verdict({ m }: { m: Media }) {
  const [claim, setClaim] = useState("");
  const [msg, setMsg] = useState("");
  const attach = async () => {
    setMsg("");
    try { const r = await api<{ grade: string }>(`/api/labs/media/${m.id}/attach`, { method: "POST", body: { claim_id: Number(claim) } }); setMsg(`أُرفق بالادّعاء #${claim} بدرجة «${r.grade}».`); }
    catch (x) { setMsg((x as Error).message); }
  };
  return (
    <section className="card" aria-label="النتيجة">
      <h2>النتيجة بدرجات الدليل</h2>
      <span className={`pill ${gradePill(m.overall.grade)}`} style={{ fontSize: 15, height: 30 }}>{gradeText(m.overall.grade)}</span>
      {m.overall.because.map((b) => <p key={b.check} style={{ margin: "8px 0 0" }}>{b.summary}</p>)}
      <p className="mu" style={{ fontSize: 12 }}>لا تُصدر الأداة حكمًا قاطعًا دون دليل قاطع. تحليل الضغط والبيانات الوصفية مؤشرات فقط.</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="inp" style={{ width: 130 }} inputMode="numeric" value={claim} onChange={(e) => setClaim(e.target.value.replace(/\D/g, ""))} placeholder="رقم الادّعاء" aria-label="رقم الادّعاء" />
        <button className="btn" disabled={!claim} onClick={attach}>أرفق بالادّعاء</button>
        <a className="btn" href={`/api/labs/media/${m.id}/report`} target="_blank" rel="noreferrer">تقرير التحقق</a>
      </div>
      {msg && <div className="msg" role="status">{msg}</div>}
    </section>
  );
}
