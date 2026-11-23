// الشاشة 10: غرفة التحقيق.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, apiForm } from "../../api";
import { useCan } from "../../session";

type Doc = { id: number; number: number; filename: string; kind: string; size: number; sha256: string; status: string; method: string;
  pages: number; error: string; added_at: string; entities: { name: string; kind: string; count: number }[]; entity_count: number; text?: string[] };
type Overview = { id: number; title: string; status: string; summary: string; access: string; members: { user_id: number; email: string; name: string; access: string }[];
  documents: Doc[]; counts: Record<string, number>; open_tasks: number; custody: { ok: boolean; entries: number; note: string };
  drafts: { id: number; title: string; status: string; updated_at: string }[] };
type Rec = { id: number; kind: string; status: string; date: string | null; amount: number | null; doc: number | null; [k: string]: any };
type Graph = { nodes: { id: string; name: string; kind: string; degree: number }[]; edges: { id: number; a: string; b: string; relation: string; status: string; sources: { doc: number; page: number; snippet: string }[] }[] };

const KIND_AR: Record<string, string> = { pdf: "PDF", docx: "Word", xlsx: "Excel", image: "صورة", audio: "تسجيل", text: "نص" };
const METHOD_AR: Record<string, string> = { text: "نص مباشر", ocr: "مسح ضوئي · استُخرج النص", mixed: "نص ومسح ضوئي", sawti: "تفريغ «صوتي»" };
const fmtD = (s: string) => new Date(s).toLocaleDateString("ar");

export function Cases() {
  return (
    <Routes>
      <Route index element={<CaseList />} />
      <Route path=":id/*" element={<Room />} />
    </Routes>
  );
}

function CaseList() {
  const can = useCan();
  const nav = useNavigate();
  const [rows, setRows] = useState<{ id: number; title: string; status: string; access: string; documents: number; updated_at: string; private: boolean }[]>([]);
  const [f, setF] = useState({ title: "", summary: "" });
  const [err, setErr] = useState("");
  useEffect(() => { api<typeof rows>("/api/cases").then(setRows).catch(() => {}); }, []);
  const create = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try { const r = await api<{ id: number }>("/api/cases", { method: "POST", body: f }); nav(`/cases/${r.id}`); } catch (x) { setErr((x as Error).message); }
  };
  return (
    <div className="cols">
      <section className="card grow">
        <h2>القضايا</h2>
        <span className="mu" style={{ fontSize: 12 }}>ترى القضايا التي أنت عضو فيها فقط. محتوى كل قضية مشفّر بمفتاح خاص بها.</span>
        {!rows.length && <span className="mu">لا قضايا بعد.</span>}
        {rows.map((c) => (
          <div key={c.id} className="row">
            <span className="f"><Link to={`/cases/${c.id}`}><b>قضية #{c.id}: {c.title}</b></Link><br />
              <span className="mu" style={{ fontSize: 12 }}>{c.documents} وثيقة · {c.private ? "خاصة بك" : "فريق"} · {c.access === "owner" ? "مالك" : c.access === "edit" ? "تعديل" : "قراءة"} · {fmtD(c.updated_at)}</span></span>
            <span className={`pill ${c.status === "open" ? "p-ac" : "p-n"}`}>{c.status === "open" ? "مفتوحة" : "مغلقة"}</span>
          </div>
        ))}
      </section>
      {can("cases.create") && (
        <form className="card side" onSubmit={create} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h2>قضية جديدة</h2>
          <label className="fld">العنوان<input className="inp" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
          <label className="fld">الملخص<textarea className="inp" rows={3} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} /></label>
          {err && <div className="msg err">{err}</div>}
          <button className="btn pri" disabled={!f.title.trim()}>إنشاء</button>
        </form>
      )}
    </div>
  );
}

const TABS: [string, string][] = [["", "خريطة العلاقات"], ["docs", "الوثائق"], ["timeline", "الخط الزمني"], ["money", "تتبّع المال"], ["tasks", "المهام"],
  ["notes", "الملاحظات"], ["sanctions", "العقوبات"], ["team", "الفريق"], ["custody", "سلسلة الحفظ"]];

function Room() {
  const { id } = useParams();
  const nav = useNavigate();
  const loc = useLocation();
  const can = useCan();
  const [o, setO] = useState<Overview | null>(null);
  const [err, setErr] = useState("");
  const load = () => api<Overview>(`/api/cases/${id}`).then(setO).catch((x) => setErr((x as Error).message));
  useEffect(() => { load(); }, [id]);
  useEffect(() => { // الوثائق قيد الاستخراج: تحديث تلقائي
    if (!o?.documents.some((d) => d.status === "processing")) return;
    const t = setTimeout(load, 2500); return () => clearTimeout(t);
  }, [o]);
  if (err) return <div className="msg err">{err}</div>;
  if (!o) return null;
  const tab = loc.pathname.split("/")[3] ?? "";
  const edit = o.access !== "view";
  const newDraft = async () => { const d = await api<{ id: number }>(`/api/cases/${o.id}/drafts`, { method: "POST", body: {} }); nav(`/story-builder/${d.id}`); };
  return (
    <>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <span className="mu"><Link to="/cases">القضايا</Link> › قضية #{o.id} · {o.members.length === 1 ? "خاصة بك" : `${o.members.length} أعضاء`}</span>
        <h2 style={{ flex: 1, margin: 0 }}>غرفة التحقيق: {o.title}</h2>
        <span className={`pill ${o.custody.ok ? "p-ok" : "p-bad"}`} title={o.custody.note}>{o.custody.ok ? "سلسلة الحفظ سليمة" : "سلسلة الحفظ مكسورة"}</span>
        {can("stories.write") && edit && <button className="btn pri" onClick={newDraft}>ابنِ القصة من الأدلة</button>}
      </div>
      <nav className="tabs" role="tablist" style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {TABS.map(([k, label]) => (
          <Link key={k} role="tab" aria-selected={tab === k} className={`btn sm ${tab === k ? "pri" : ""}`} to={`/cases/${o.id}${k ? "/" + k : ""}`}>
            {label}{k === "docs" ? ` (${o.documents.length})` : k === "tasks" ? ` (${o.open_tasks})` : ""}
          </Link>
        ))}
      </nav>
      <Routes>
        <Route index element={<MapTab o={o} edit={edit} />} />
        <Route path="docs/:num?" element={<DocsTab o={o} edit={edit} reload={load} />} />
        <Route path="timeline" element={<RecordsTab o={o} kind="event" edit={edit} />} />
        <Route path="money" element={<MoneyTab o={o} edit={edit} />} />
        <Route path="tasks" element={<RecordsTab o={o} kind="task" edit={edit} />} />
        <Route path="notes" element={<RecordsTab o={o} kind="note" edit={edit} />} />
        <Route path="sanctions" element={<SanctionsTab o={o} />} />
        <Route path="team" element={<TeamTab o={o} reload={load} />} />
        <Route path="custody" element={<CustodyTab o={o} />} />
      </Routes>
      {o.drafts.length > 0 && (
        <section className="card" style={{ marginTop: 12 }}>
          <h2>المسودات</h2>
          {o.drafts.map((d) => <div key={d.id} className="row"><Link className="f" to={`/story-builder/${d.id}`}>{d.title}</Link><span className="pill p-n">{d.status === "approved" ? "معتمدة" : "مسودة"}</span></div>)}
        </section>
      )}
    </>
  );
}

function useRecords(caseId: number, kind: string) {
  const [rows, setRows] = useState<Rec[]>([]);
  const load = () => api<Rec[]>(`/api/cases/${caseId}/records?kind=${kind}`).then(setRows).catch(() => {});
  useEffect(() => { load(); }, [caseId, kind]);
  const patch = async (r: Rec, body: object) => { await api(`/api/cases/${caseId}/records/${r.id}`, { method: "PATCH", body: { kind: r.kind, ...body } }); load(); };
  return { rows, load, patch };
}

function MapTab({ o, edit }: { o: Overview; edit: boolean }) {
  const [g, setG] = useState<Graph | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [f, setF] = useState({ a: "", b: "", relation: "" });
  const load = () => api<Graph>(`/api/cases/${o.id}/graph`).then(setG);
  useEffect(() => { load(); }, [o.id, o.documents.length]);
  const pos = useMemo(() => {
    const p: Record<string, [number, number]> = {};
    const n = g?.nodes.length ?? 0;
    g?.nodes.forEach((x, i) => { const a = (2 * Math.PI * i) / Math.max(n, 1); const r = i === 0 && n > 6 ? 0 : 200; p[x.id] = [330 + r * Math.cos(a), 240 + r * Math.sin(a)]; });
    return p;
  }, [g]);
  if (!g) return null;
  const edge = g.edges.find((e) => e.id === sel);
  const name = (id: string) => g.nodes.find((n) => n.id === id)?.name ?? id;
  const decide = async (status: string) => { await api(`/api/cases/${o.id}/records/${sel}`, { method: "PATCH", body: { kind: "link", status } }); setSel(null); load(); };
  const add = async (e: React.FormEvent) => { e.preventDefault(); await api(`/api/cases/${o.id}/records`, { method: "POST", body: { kind: "link", data: f } }); setF({ a: "", b: "", relation: "" }); load(); };
  const color = (k: string) => (k === "person" ? "var(--ac)" : k === "org" ? "var(--warn)" : "var(--mu)");
  return (
    <div className="cols">
      <section className="card grow">
        <h2>خريطة العلاقات</h2>
        {!g.nodes.length && <span className="mu">تظهر الكيانات والصلات بعد رفع الوثائق، أو أضف صلة يدويًا.</span>}
        {g.nodes.length > 0 && (
          <svg viewBox="0 0 660 480" style={{ width: "100%", maxHeight: 520 }} role="img" aria-label="خريطة العلاقات">
            {g.edges.map((e) => (
              <line key={e.id} x1={pos[e.a][0]} y1={pos[e.a][1]} x2={pos[e.b][0]} y2={pos[e.b][1]} onClick={() => setSel(e.id)} style={{ cursor: "pointer" }}
                    stroke={e.id === sel ? "var(--act)" : e.status === "confirmed" ? "var(--tx)" : "var(--mu)"} strokeWidth={e.id === sel ? 4 : e.status === "confirmed" ? 2 : 1.2}
                    strokeDasharray={e.status === "suggested" ? "5 4" : undefined} />
            ))}
            {g.nodes.map((n) => (
              <g key={n.id}>
                <circle cx={pos[n.id][0]} cy={pos[n.id][1]} r={7 + Math.min(n.degree, 8)} fill={color(n.kind)} />
                <text x={pos[n.id][0]} y={pos[n.id][1] - 14 - Math.min(n.degree, 8)} textAnchor="middle" fontSize="12" fill="var(--tx)">{n.name}</text>
              </g>
            ))}
          </svg>
        )}
        <span className="mu" style={{ fontSize: 12 }}>الخط المتقطع: صلة مقترحة من الوثائق تحتاج تأكيدك. انقر الخط لرؤية مصدره.</span>
      </section>
      <div className="side">
        {edge && (
          <section className="card" aria-label="الصلة المختارة">
            <h2>{name(edge.a)} ↔ {name(edge.b)}</h2>
            <p>{edge.relation}{edge.status === "suggested" ? " · صلة مقترحة تحتاج تأكيدك" : ""}</p>
            {edge.sources.map((s, i) => <div key={i} className="row"><span className="f mu" style={{ fontSize: 12 }}>وثيقة {s.doc} ص {s.page}: «{s.snippet}»</span></div>)}
            {edit && edge.status !== "confirmed" && <button className="btn" onClick={() => decide("confirmed")}>تأكيد الصلة</button>}
            {edit && edge.status !== "rejected" && <button className="btn" onClick={() => decide("rejected")}>رفض</button>}
          </section>
        )}
        {edit && (
          <form className="card" onSubmit={add} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <h2>صلة جديدة</h2>
            <input className="inp" value={f.a} onChange={(e) => setF({ ...f, a: e.target.value })} placeholder="الطرف الأول" aria-label="الطرف الأول" />
            <input className="inp" value={f.relation} onChange={(e) => setF({ ...f, relation: e.target.value })} placeholder="الصلة (مدير، شريك، عقد…)" aria-label="الصلة" />
            <input className="inp" value={f.b} onChange={(e) => setF({ ...f, b: e.target.value })} placeholder="الطرف الثاني" aria-label="الطرف الثاني" />
            <button className="btn" disabled={!f.a.trim() || !f.b.trim()}>إضافة</button>
          </form>
        )}
      </div>
    </div>
  );
}

function DocsTab({ o, edit, reload }: { o: Overview; edit: boolean; reload: () => void }) {
  const { num } = useParams();
  const nav = useNavigate();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [msg, setMsg] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { setDoc(null); if (num) api<Doc>(`/api/cases/${o.id}/documents/${num}`).then(setDoc).catch(() => {}); }, [num, o.id]);
  const up = async () => {
    const files = input.current?.files; if (!files?.length) return;
    const f = new FormData(); Array.from(files).forEach((x) => f.append("files", x));
    setMsg("يجري الرفع…");
    try { const r = await apiForm<{ added: unknown[]; errors: { file: string; error: string }[] }>(`/api/cases/${o.id}/documents`, f);
      setMsg(`أُضيفت ${r.added.length} وثيقة${r.errors.length ? ` · ${r.errors.map((e) => `${e.file}: ${e.error}`).join("، ")}` : ""}`); input.current!.value = ""; reload(); }
    catch (x) { setMsg((x as Error).message); }
  };
  return (
    <div className="cols">
      <section className="card grow">
        <h2>الوثائق ({o.documents.length})</h2>
        {o.documents.map((d) => (
          <div key={d.id} className="row" data-doc={d.number}>
            <span className="f"><Link to={`/cases/${o.id}/docs/${d.number}`}><b>وثيقة {d.number}: {d.filename}</b></Link><br />
              <span className="mu" style={{ fontSize: 12 }}>{KIND_AR[d.kind]} · {d.status === "processing" ? "يجري استخراج النص…" : d.status === "failed" ? d.error : `${METHOD_AR[d.method] ?? ""} · ${d.pages} صفحة`} · <span dir="ltr">{d.sha256.slice(0, 8)}…</span></span></span>
            {d.status === "ready" && <span className="pill p-n">{d.entity_count} كيانًا</span>}
          </div>
        ))}
        {edit && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            <input ref={input} type="file" multiple accept=".pdf,.docx,.xlsx,.txt,.csv,image/*,audio/*" aria-label="رفع وثائق" />
            <button className="btn" onClick={up}>رفع</button>
          </div>
        )}
        {msg && <div className="msg" role="status">{msg}</div>}
        <span className="mu" style={{ fontSize: 12 }}>PDF (ونص الممسوح ضوئيًا)، Word، Excel، صور، تسجيلات عبر «صوتي». كل ملف يُشفّر ويُحفظ ببصمته، وكل فتح وتنزيل يُسجَّل.</span>
      </section>
      {doc && (
        <section className="card side" style={{ maxWidth: 560 }} aria-label="نص الوثيقة">
          <div style={{ display: "flex", gap: 6 }}>
            <h2 style={{ flex: 1 }}>وثيقة {doc.number}</h2>
            <a className="btn sm" href={`/api/cases/${o.id}/documents/${doc.number}/file`}>تنزيل الأصل</a>
            <button className="btn sm" onClick={() => nav(`/cases/${o.id}/docs`)}>إغلاق</button>
          </div>
          <span className="mu" dir="ltr" style={{ fontSize: 11, wordBreak: "break-all" }}>SHA-256 {doc.sha256}</span>
          {doc.entities.length > 0 && <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>{doc.entities.map((e) => <span key={e.name} className="pill p-n">{e.name}</span>)}</div>}
          {(doc.text ?? []).map((t, i) => <div key={i}><b className="mu" style={{ fontSize: 12 }}>ص {i + 1}</b><p style={{ whiteSpace: "pre-wrap", margin: "4px 0 10px" }}>{t}</p></div>)}
        </section>
      )}
    </div>
  );
}

function RecordsTab({ o, kind, edit }: { o: Overview; kind: "event" | "task" | "note"; edit: boolean }) {
  const { rows, load, patch } = useRecords(o.id, kind);
  const [f, setF] = useState({ title: "", date: "", text: "" });
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    await api(`/api/cases/${o.id}/records`, { method: "POST", body: { kind, date: f.date || null, data: kind === "note" ? { text: f.text } : { title: f.title } } });
    setF({ title: "", date: "", text: "" }); load();
  };
  const title = kind === "event" ? "الخط الزمني" : kind === "task" ? "المهام" : "الملاحظات";
  const shown = kind === "event" ? rows.filter((r) => r.status !== "rejected") : rows;
  return (
    <section className="card">
      <h2>{title}</h2>
      {kind === "event" && <span className="mu" style={{ fontSize: 12 }}>التواريخ المستخرجة من الوثائق مقترحة؛ أكّد ما يخص القضية ليدخل هيكل القصة.</span>}
      {!shown.length && <span className="mu">لا شيء بعد.</span>}
      {shown.map((r) => (
        <div key={r.id} className="row">
          {kind === "event" && <b style={{ width: 96 }} dir="ltr">{r.date}</b>}
          {kind === "task" && <input type="checkbox" checked={r.status === "done"} disabled={!edit} aria-label={r.title} onChange={(e) => patch(r, { status: e.target.checked ? "done" : "open" })} />}
          <span className="f">{kind === "note" ? <span style={{ whiteSpace: "pre-wrap" }}>{r.text}</span> : r.title}
            {r.doc && <span className="mu" style={{ fontSize: 12 }}> · <Link to={`/cases/${o.id}/docs/${r.doc}`}>وثيقة {r.doc}</Link>{r.page ? ` ص ${r.page}` : ""}</span>}</span>
          {kind === "event" && (r.status === "suggested" ? (edit && <><button className="btn sm" onClick={() => patch(r, { status: "confirmed" })}>تأكيد</button><button className="btn sm" onClick={() => patch(r, { status: "rejected" })}>استبعاد</button></>) : <span className="pill p-ok">مؤكد</span>)}
          {kind === "task" && <span className={`pill ${r.status === "done" ? "p-ok" : "p-warn"}`}>{r.status === "done" ? "منجزة" : "مفتوحة"}</span>}
        </div>
      ))}
      {edit && (
        <form onSubmit={add} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          {kind === "event" && <input className="inp" type="date" style={{ width: 160 }} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} aria-label="التاريخ" />}
          {kind === "note" ? <textarea className="inp" rows={2} style={{ flex: 1 }} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} aria-label="ملاحظة" />
            : <input className="inp" style={{ flex: 1 }} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} aria-label={kind === "task" ? "مهمة جديدة" : "الحدث"} />}
          <button className="btn" disabled={kind === "note" ? !f.text.trim() : !f.title.trim()}>إضافة</button>
        </form>
      )}
    </section>
  );
}

function MoneyTab({ o, edit }: { o: Overview; edit: boolean }) {
  const [d, setD] = useState<{ rows: Rec[]; flows: { from: string; to: string; currency: string; total: number; count: number; docs: number[] }[] } | null>(null);
  const [f, setF] = useState({ from: "", to: "", amount: "", currency: "دينار", date: "", doc: "" });
  const load = () => api<typeof d>(`/api/cases/${o.id}/money`).then(setD);
  useEffect(() => { load(); }, [o.id]);
  const patch = async (r: Rec, status: string) => { await api(`/api/cases/${o.id}/records/${r.id}`, { method: "PATCH", body: { kind: "money", status } }); load(); };
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    await api(`/api/cases/${o.id}/records`, { method: "POST", body: { kind: "money", amount: Number(f.amount), date: f.date || null, doc: f.doc ? Number(f.doc) : null, data: { from: f.from, to: f.to, currency: f.currency } } });
    setF({ ...f, from: "", to: "", amount: "", doc: "" }); load();
  };
  if (!d) return null;
  return (
    <div className="cols">
      <section className="card grow">
        <h2>تتبّع المال</h2>
        <h3 style={{ fontSize: 14 }}>التدفقات المؤكدة</h3>
        {!d.flows.length && <span className="mu">أكّد الحركات المقترحة أو أضف حركة.</span>}
        {d.flows.map((x, i) => <div key={i} className="row"><span className="f"><b>{x.from || "؟"}</b> ← <b>{x.to || "؟"}</b> · {x.count} حركة{x.docs.length ? ` · وثائق ${x.docs.join("، ")}` : ""}</span><b>{x.total.toLocaleString("ar")} {x.currency}</b></div>)}
        <h3 style={{ fontSize: 14 }}>كل الحركات</h3>
        {d.rows.filter((r) => r.status !== "rejected").map((r) => (
          <div key={r.id} className="row">
            <span className="f">{r.from || "؟"} ← {r.to || "؟"} · {r.amount?.toLocaleString("ar")} {r.currency}{r.date ? ` · ${r.date}` : ""}{r.doc ? ` · وثيقة ${r.doc}` : ""}<br /><span className="mu" style={{ fontSize: 12 }}>{r.purpose}</span></span>
            {r.status === "suggested" ? (edit && <><button className="btn sm" onClick={() => patch(r, "confirmed")}>تأكيد</button><button className="btn sm" onClick={() => patch(r, "rejected")}>استبعاد</button></>) : <span className="pill p-ok">مؤكدة</span>}
          </div>
        ))}
      </section>
      {edit && (
        <form className="card side" onSubmit={add} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h2>حركة مال</h2>
          <input className="inp" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} placeholder="من" aria-label="من" />
          <input className="inp" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} placeholder="إلى" aria-label="إلى" />
          <div style={{ display: "flex", gap: 6 }}>
            <input className="inp" inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} placeholder="المبلغ" aria-label="المبلغ" />
            <input className="inp" style={{ width: 90 }} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })} aria-label="العملة" />
          </div>
          <input className="inp" type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} aria-label="تاريخ الحركة" />
          <input className="inp" inputMode="numeric" value={f.doc} onChange={(e) => setF({ ...f, doc: e.target.value })} placeholder="رقم الوثيقة المصدر" aria-label="رقم الوثيقة المصدر" />
          <button className="btn" disabled={!f.amount || isNaN(Number(f.amount))}>إضافة</button>
        </form>
      )}
    </div>
  );
}

function SanctionsTab({ o }: { o: Overview }) {
  const [d, setD] = useState<{ lists: { name: string; entries: number }[]; checked: number; matches: { name: string; match: string; list: string; score: number; countries: string; programs: string; pep: boolean }[]; note: string } | null>(null);
  useEffect(() => { api<typeof d>(`/api/cases/${o.id}/sanctions`).then(setD); }, [o.id]);
  if (!d) return null;
  return (
    <section className="card">
      <h2>مطابقة العقوبات والأشخاص ذوي النفوذ</h2>
      {!d.lists.length ? <p className="mu">لم تُستورد قوائم بعد. يستوردها المدير من «الإدارة» (ملف OpenSanctions أو قائمة CSV).</p>
        : <p className="mu" style={{ fontSize: 12 }}>فُحص {d.checked} اسمًا مقابل: {d.lists.map((l) => `${l.name} (${l.entries})`).join("، ")}</p>}
      <div className="msg" role="note">{d.note}</div>
      {d.matches.map((m, i) => (
        <div key={i} className="row"><span className="f"><b>{m.name}</b> ≈ {m.match} {m.pep && <span className="pill p-warn">شخص ذو نفوذ</span>}<br />
          <span className="mu" style={{ fontSize: 12 }}>{m.list} · {m.countries} · {m.programs}</span></span><span className="pill p-warn">تطابق {Math.round(m.score * 100)}٪</span></div>
      ))}
      {d.lists.length > 0 && !d.matches.length && <span className="mu">لا تطابق.</span>}
    </section>
  );
}

function TeamTab({ o, reload }: { o: Overview; reload: () => void }) {
  const [f, setF] = useState({ email: "", access: "edit" });
  const [msg, setMsg] = useState("");
  const set = async (email: string, access: string | null) => {
    setMsg("");
    try { await api(`/api/cases/${o.id}/members`, { method: "POST", body: { email, access } }); reload(); setF({ email: "", access: "edit" }); }
    catch (x) { setMsg((x as Error).message); }
  };
  const owner = o.access === "owner";
  return (
    <section className="card">
      <h2>الفريق</h2>
      {o.members.map((m) => (
        <div key={m.user_id} className="row"><span className="f">{m.name || m.email}<br /><span className="mu" style={{ fontSize: 12 }}>{m.email}</span></span>
          {owner ? <select className="inp" style={{ width: 130 }} value={m.access} onChange={(e) => set(m.email, e.target.value)} aria-label={`وصول ${m.email}`}>
            <option value="owner">مالك</option><option value="edit">تعديل</option><option value="view">قراءة</option></select> : <span className="pill p-n">{m.access}</span>}
          {owner && <button className="btn sm" onClick={() => set(m.email, null)}>إزالة</button>}
        </div>
      ))}
      {owner && (
        <form onSubmit={(e) => { e.preventDefault(); set(f.email, f.access); }} style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <input className="inp" dir="ltr" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} placeholder="البريد" aria-label="بريد العضو" />
          <select className="inp" style={{ width: 130 }} value={f.access} onChange={(e) => setF({ ...f, access: e.target.value })} aria-label="مستوى الوصول"><option value="edit">تعديل</option><option value="view">قراءة</option></select>
          <button className="btn" disabled={!f.email.includes("@")}>إضافة</button>
        </form>
      )}
      {msg && <div className="msg err">{msg}</div>}
      <span className="mu" style={{ fontSize: 12 }}>القضية لأعضائها فقط، ولو كان المستخدم مديرًا للنظام.</span>
    </section>
  );
}

function CustodyTab({ o }: { o: Overview }) {
  const [d, setD] = useState<{ verify: { ok: boolean; note: string; entries: number }; rows: { at: string; user: string; action: string; detail: string; sha256: string }[] } | null>(null);
  useEffect(() => { api<typeof d>(`/api/cases/${o.id}/custody`).then(setD); }, [o.id]);
  if (!d) return null;
  return (
    <section className="card">
      <h2>سلسلة الحفظ</h2>
      <div className={`msg ${d.verify.ok ? "" : "err"}`} role="status">{d.verify.note} · {d.verify.entries} قيدًا</div>
      {d.rows.map((r, i) => <div key={i} className="row"><span className="mu" style={{ width: 150, fontSize: 12 }}>{new Date(r.at).toLocaleString("ar")}</span><span className="f">{r.user} · {r.detail || r.action}</span>{r.sha256 && <span className="mu" dir="ltr" style={{ fontSize: 11 }}>{r.sha256.slice(0, 10)}…</span>}</div>)}
    </section>
  );
}
