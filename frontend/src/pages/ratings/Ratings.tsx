// الشاشة 12: تقييم المواقع — داخلي فقط.
import { useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";

type Ind = { key?: string; ar: string; how?: string; value: number | null; ci: [number, number] | null; sample: number; min_sample: number;
  enough: boolean; good: number; bad: number; examples_bad?: Ex[]; examples_good?: Ex[]; anonymous?: number; anonymous_share?: number | null;
  first_count?: number; kappa_machine_human?: number | null; reviewed?: number; items?: { key: string; ar: string; declared: boolean; detail: string }[] };
type Ex = { item_id: number; title: string; url: string; time: string; note: string };
type Row = { outlet: { id: number; name: string; kind: string }; items: number; composite: number | null; indicators: Record<string, Ind>;
  methodology_version: number; missing: string[] };
type Card = Row & { period: { start: string; end: string; days: number }; evolution: { end: string; composite: number | null }[];
  replies: Reply[]; snapshots: { id: number; end: string; composite: number | null; status: string; methodology_version: number }[]; composite_basis: string[] };
type Reply = { id: number; item_id: number | null; indicator: string; text: string; channel: string; status: string; resolution: string; received_at: string };
type Meth = { current: { version: number; weights: Record<string, number>; min_sample: number; period_days: number; note: string; created_at: string };
  history: { version: number; note: string; created_at: string; weights: Record<string, number> }[];
  indicators: Record<string, { ar: string; how: string }>; rules: string[]; references: { name: string; url: string }[] };

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}٪`);
const COLS = ["accuracy", "attribution", "corrections", "sensational"];
const NOTICE = "داخلي فقط · لا يُنشر قبل المراجعة القانونية";

export function Ratings() {
  return (
    <>
      <div className="msg" role="note" style={{ fontWeight: 600 }}>{NOTICE}</div>
      <Routes>
        <Route index element={<Ranking />} />
        <Route path="outlets/:id" element={<OutletCard />} />
        <Route path="methodology" element={<Methodology />} />
        <Route path="review" element={<Review />} />
      </Routes>
    </>
  );
}

function Ranking() {
  const [d, setD] = useState<{ rows: Row[]; indicators: Record<string, string>; period_days: number; methodology_version: number } | null>(null);
  const nav = useNavigate();
  useEffect(() => { api<typeof d>("/api/ratings").then(setD).catch(() => {}); }, []);
  if (!d) return <p className="mu">يجري الحساب…</p>;
  return (
    <div className="cols">
      <section className="card grow">
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <h2 style={{ flex: 1 }}>الترتيب · آخر {d.period_days} يومًا</h2>
          <Link className="btn sm" to="methodology">المنهجية (الإصدار {d.methodology_version})</Link>
          <Link className="btn sm" to="review">المراجعة البشرية</Link>
        </div>
        <p className="mu" style={{ fontSize: 13 }}>كل رقم يمكن تتبّعه إلى الأخبار التي حُسب منها. «—» يعني أن العيّنة أقل من الحد الأدنى فلا يُعرض رقم.</p>
        {!d.rows.length && <span className="mu">لا جهات لها مواد في الفترة بعد.</span>}
        <div style={{ overflowX: "auto" }}>
          <table className="tbl" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={{ textAlign: "start" }}>الجهة</th>{COLS.map((k) => <th key={k}>{d.indicators[k]}</th>)}<th>المواد</th><th>المؤشر</th></tr></thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.outlet.id} className="clickable" onClick={() => nav(`outlets/${r.outlet.id}`)} style={{ cursor: "pointer", borderTop: "1px solid var(--bd)" }}>
                  <td style={{ padding: "8px 4px" }}><Link to={`outlets/${r.outlet.id}`}>{r.outlet.name}</Link></td>
                  {COLS.map((k) => <td key={k} style={{ textAlign: "center" }}>{pct(r.indicators[k]?.value)}</td>)}
                  <td style={{ textAlign: "center" }}>{r.items}</td>
                  <td style={{ textAlign: "center" }}><b>{r.composite ?? "—"}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function OutletCard() {
  const { id } = useParams();
  const can = useCan();
  const [c, setC] = useState<Card | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [full, setFull] = useState<Ind | null>(null);
  const [reply, setReply] = useState({ item_id: "", indicator: "", text: "", channel: "" });
  const [msg, setMsg] = useState("");
  const load = () => api<Card>(`/api/ratings/outlets/${id}`).then(setC).catch(() => {});
  useEffect(() => { load(); }, [id]);
  useEffect(() => { setFull(null); if (open) api<Ind>(`/api/ratings/outlets/${id}/indicators/${open}`).then(setFull).catch(() => {}); }, [open, id]);
  if (!c) return <p className="mu">يجري الحساب…</p>;
  const run = async (f: () => Promise<unknown>, ok: string) => { setMsg(""); try { await f(); setMsg(ok); load(); } catch (x) { setMsg((x as Error).message); } };
  const max = Math.max(1, ...c.evolution.map((e) => e.composite ?? 0));
  return (
    <div className="cols">
      <div className="grow">
        <section className="card">
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <h2 style={{ flex: 1 }}>بطاقة: {c.outlet.name}</h2>
            <span className="pill p-ac" style={{ fontSize: 15, height: 30 }}>المؤشر {c.composite ?? "—"}</span>
          </div>
          <p className="mu" style={{ fontSize: 12 }}>{c.items} مادة · {new Date(c.period.start).toLocaleDateString("ar")} – {new Date(c.period.end).toLocaleDateString("ar")} · المنهجية الإصدار {c.methodology_version}
            {c.composite == null ? " · المؤشر المركّب يحتاج 4 مؤشرات بعيّنة كافية" : ` · مبني على: ${c.composite_basis.map((k) => c.indicators[k].ar).join("، ")}`}</p>
          {Object.entries(c.indicators).map(([k, v]) => (
            <div key={k} className="row" data-indicator={k}>
              <button className="btn sm" aria-expanded={open === k} onClick={() => setOpen(open === k ? null : k)} aria-label={`أمثلة ${v.ar}`}>{open === k ? "إخفاء" : "الأمثلة"}</button>
              <span className="f"><b>{v.ar}</b>{v.how && <><br /><span className="mu" style={{ fontSize: 12 }}>{v.how}</span></>}</span>
              <span style={{ minWidth: 150, textAlign: "end" }}>
                <b style={{ fontSize: 17 }}>{pct(v.value)}</b>
                <br /><span className="mu" style={{ fontSize: 12 }}>
                  {v.enough ? (v.ci ? `هامش الثقة ${pct(v.ci[0])}–${pct(v.ci[1])} · ${v.sample} مادة` : `${v.good} من ${v.sample}`) : `عيّنة ${v.sample} من ${v.min_sample} المطلوبة`}
                </span>
              </span>
            </div>
          ))}
        </section>
        {open && (
          <section className="card" aria-label="المواد خلف الرقم">
            <h2>{c.indicators[open].ar}: المواد التي بُني عليها الرقم</h2>
            {!full && <span className="mu">يجري التحميل…</span>}
            {full?.items && full.items.map((x) => <div key={x.key} className="row"><span className="f">{x.ar}{x.detail ? `: ${x.detail}` : ""}</span><span className={`pill ${x.declared ? "p-ok" : "p-n"}`}>{x.declared ? "معلن" : "غير معلن"}</span></div>)}
            {full && !full.items && (
              <>
                <h3 style={{ fontSize: 14 }}>تخفض المؤشر ({full.bad})</h3>
                {full.examples_bad!.map((x) => <ExRow key={`b${x.item_id}${x.note}`} x={x} />)}
                <h3 style={{ fontSize: 14 }}>ترفع المؤشر ({full.good})</h3>
                {full.examples_good!.slice(0, 30).map((x) => <ExRow key={`g${x.item_id}${x.note}`} x={x} />)}
                {full.good > 30 && <span className="mu">و{full.good - 30} مادة أخرى.</span>}
              </>
            )}
          </section>
        )}
        <section className="card">
          <h2>التطوّر عبر الزمن</h2>
          <svg viewBox="0 0 300 80" style={{ width: "100%", height: 100 }} role="img" aria-label="تطوّر المؤشر">
            {c.evolution.map((e, i) => (
              <g key={e.end}>
                <rect x={i * 50 + 10} y={70 - ((e.composite ?? 0) / max) * 60} width={30} height={((e.composite ?? 0) / max) * 60} fill={e.composite == null ? "var(--bd)" : "var(--ac)"} />
                <text x={i * 50 + 25} y={78} fontSize="7" textAnchor="middle" fill="var(--mu)">{new Date(e.end).toLocaleDateString("ar", { month: "short" })}</text>
                <text x={i * 50 + 25} y={66 - ((e.composite ?? 0) / max) * 60} fontSize="8" textAnchor="middle" fill="var(--tx)">{e.composite ?? "—"}</text>
              </g>
            ))}
          </svg>
        </section>
      </div>
      <div className="side">
        <section className="card" aria-label="حق الرد">
          <h2>حق الرد</h2>
          <span className="mu" style={{ fontSize: 12 }}>سجّل اعتراض الجهة على مادة محددة؛ المحرّر يقبله أو يرفضه بسبب مكتوب، والرد المقبول يُخرج المادة من المؤشر.</span>
          <form style={{ display: "flex", flexDirection: "column", gap: 6 }} onSubmit={(e) => { e.preventDefault(); run(() => api("/api/ratings/replies", { method: "POST", body: { outlet_id: c.outlet.id, item_id: reply.item_id ? Number(reply.item_id) : null, indicator: reply.indicator, text: reply.text, channel: reply.channel } }), "سُجّل الرد.").then(() => setReply({ item_id: "", indicator: "", text: "", channel: "" })); }}>
            <select className="inp" value={reply.indicator} onChange={(e) => setReply({ ...reply, indicator: e.target.value })} aria-label="المؤشر المعترض عليه">
              <option value="">كل المؤشرات</option>{Object.entries(c.indicators).map(([k, v]) => <option key={k} value={k}>{v.ar}</option>)}
            </select>
            <input className="inp" inputMode="numeric" value={reply.item_id} onChange={(e) => setReply({ ...reply, item_id: e.target.value.replace(/\D/g, "") })} placeholder="رقم المادة" aria-label="رقم المادة" />
            <input className="inp" value={reply.channel} onChange={(e) => setReply({ ...reply, channel: e.target.value })} placeholder="وصل عبر (بريد، رسالة رسمية…)" aria-label="قناة الرد" />
            <textarea className="inp" rows={3} value={reply.text} onChange={(e) => setReply({ ...reply, text: e.target.value })} placeholder="نص الاعتراض كما وصل" aria-label="نص الاعتراض" />
            <button className="btn" disabled={!reply.text.trim()}>تسجيل الرد</button>
          </form>
          {c.replies.map((r) => <ReplyRow key={r.id} r={r} canDecide={can("ratings.approve")} onDecide={(status, resolution) => run(() => api(`/api/ratings/replies/${r.id}/decide`, { method: "POST", body: { status, resolution } }), "سُجّل القرار.")} />)}
          {msg && <div className="msg" role="status">{msg}</div>}
        </section>
        <section className="card">
          <h2>اللقطات المحفوظة</h2>
          <button className="btn sm" onClick={() => run(() => api(`/api/ratings/outlets/${c.outlet.id}/snapshot`, { method: "POST" }), "حُفظت لقطة.")}>احفظ لقطة الآن</button>
          {c.snapshots.map((s) => (
            <div key={s.id} className="row"><span className="f">{new Date(s.end).toLocaleDateString("ar")} · الإصدار {s.methodology_version} · {s.composite ?? "—"}</span>
              {s.status === "approved" ? <span className="pill p-ok">معتمد داخليًا</span> : can("ratings.approve") && <button className="btn sm" onClick={() => run(() => api(`/api/ratings/scores/${s.id}/approve`, { method: "POST" }), "اعتُمدت داخليًا.")}>اعتماد</button>}
            </div>
          ))}
          <span className="mu" style={{ fontSize: 12 }}>الاعتماد داخلي. النشر العلني ممنوع حتى المراجعة القانونية.</span>
        </section>
      </div>
    </div>
  );
}

function ExRow({ x }: { x: Ex }) {
  return <div className="row"><span className="f"><a href={x.url} target="_blank" rel="noreferrer noopener">{x.title || `مادة #${x.item_id}`}</a><br /><span className="mu" style={{ fontSize: 12 }}>#{x.item_id} · {new Date(x.time).toLocaleDateString("ar")}{x.note ? ` · ${x.note}` : ""}</span></span></div>;
}

function ReplyRow({ r, canDecide, onDecide }: { r: Reply; canDecide: boolean; onDecide: (s: string, why: string) => void }) {
  const [why, setWhy] = useState("");
  return (
    <div className="row" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <span>{r.text}<br /><span className="mu" style={{ fontSize: 12 }}>{r.item_id ? `المادة #${r.item_id} · ` : ""}{r.channel} · {new Date(r.received_at).toLocaleDateString("ar")}</span></span>
      {r.status === "open" ? (canDecide ? (
        <div style={{ display: "flex", gap: 6 }}>
          <input className="inp" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="سبب القرار" aria-label="سبب القرار" />
          <button className="btn sm" disabled={!why.trim()} onClick={() => onDecide("accepted", why)}>قبول</button>
          <button className="btn sm" disabled={!why.trim()} onClick={() => onDecide("rejected", why)}>رفض</button>
        </div>) : <span className="pill p-warn">بانتظار المحرّر</span>)
        : <span><span className={`pill ${r.status === "accepted" ? "p-ok" : "p-n"}`}>{r.status === "accepted" ? "مقبول" : "مرفوض"}</span> <span className="mu">{r.resolution}</span></span>}
    </div>
  );
}

function Methodology() {
  const can = useCan();
  const [m, setM] = useState<Meth | null>(null);
  const [w, setW] = useState<Record<string, number>>({});
  const [f, setF] = useState({ min_sample: 30, period_days: 90, note: "" });
  const [msg, setMsg] = useState("");
  const load = () => api<Meth>("/api/ratings/methodology").then((x) => { setM(x); setW(x.current.weights); setF({ min_sample: x.current.min_sample, period_days: x.current.period_days, note: "" }); });
  useEffect(() => { load().catch(() => {}); }, []);
  if (!m) return null;
  const total = Object.values(w).reduce((a, b) => a + b, 0) || 1;
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setMsg("");
    try { const r = await api<{ version: number }>("/api/ratings/methodology", { method: "POST", body: { weights: w, ...f } }); setMsg(`حُفظ الإصدار ${r.version}.`); load(); }
    catch (x) { setMsg((x as Error).message); }
  };
  return (
    <div className="cols">
      <section className="card grow">
        <h2>المنهجية · الإصدار {m.current.version}</h2>
        <p>التقييم يُحسب من الأخبار والعناوين المنشورة فعلًا، لا من رأي أو سمعة.</p>
        <ol>{m.rules.map((r) => <li key={r}>{r}</li>)}</ol>
        <form onSubmit={save}>
          {Object.entries(m.indicators).map(([k, v]) => (
            <div key={k} className="row">
              <span className="f"><b>{v.ar}</b><br /><span className="mu" style={{ fontSize: 12 }}>{v.how}</span></span>
              <input className="inp" type="number" min={0} style={{ width: 80 }} disabled={!can("ratings.configure")} value={w[k] ?? 0} aria-label={`وزن ${v.ar}`}
                     onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} />
              <span className="mu" style={{ width: 44 }}>{Math.round(((w[k] ?? 0) / total) * 100)}٪</span>
            </div>
          ))}
          {can("ratings.configure") && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
              <label className="fld">الحد الأدنى للعيّنة<input className="inp" type="number" value={f.min_sample} onChange={(e) => setF({ ...f, min_sample: Number(e.target.value) })} /></label>
              <label className="fld">الفترة (يوم)<input className="inp" type="number" value={f.period_days} onChange={(e) => setF({ ...f, period_days: Number(e.target.value) })} /></label>
              <label className="fld" style={{ flex: 1 }}>سبب التغيير<input className="inp" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
              <button className="btn pri" disabled={!f.note.trim()}>حفظ إصدار جديد</button>
            </div>
          )}
        </form>
        {msg && <div className="msg" role="status">{msg}</div>}
      </section>
      <div className="side">
        <section className="card">
          <h2>سجل الإصدارات</h2>
          {m.history.map((h) => <div key={h.version} className="row"><span className="f"><b>الإصدار {h.version}</b> · {new Date(h.created_at).toLocaleDateString("ar")}<br /><span className="mu">{h.note}</span></span></div>)}
        </section>
        <section className="card">
          <h2>المرجعيات</h2>
          {m.references.map((r) => <a key={r.url} href={r.url} target="_blank" rel="noreferrer noopener">{r.name}</a>)}
          <span className="mu" style={{ fontSize: 12 }}>يُقترح عرض المنهجية والأوزان على لجنة مراجعة من أكاديميين وصحفيين قبل اعتماد أي تقييم، ومراجعتها سنويًا.</span>
        </section>
      </div>
    </div>
  );
}

type Agree = Record<string, { ar: string; reviewed_items: number; kappa_machine_human: number | null; kappa_human_human: number | null; reading: string }>;

function Review() {
  const [ind, setInd] = useState("sensational");
  const [q, setQ] = useState<{ question: string; items: { item_id: number; title: string; text: string; url: string }[] } | null>(null);
  const [ag, setAg] = useState<Agree | null>(null);
  const load = () => { api<typeof q>(`/api/ratings/review/${ind}`).then(setQ); api<Agree>("/api/ratings/agreement").then(setAg); };
  useEffect(() => { load(); }, [ind]);
  const answer = async (item_id: number, value: boolean) => {
    await api("/api/ratings/review", { method: "POST", body: { item_id, indicator: ind, value } });
    setQ((x) => x && { ...x, items: x.items.filter((i) => i.item_id !== item_id) });
    api<Agree>("/api/ratings/agreement").then(setAg);
  };
  const it = q?.items[0];
  return (
    <div className="cols">
      <section className="card grow">
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <h2 style={{ flex: 1 }}>المراجعة البشرية</h2>
          <select className="inp" style={{ width: 220 }} value={ind} onChange={(e) => setInd(e.target.value)} aria-label="المؤشر">
            {ag && Object.entries(ag).map(([k, v]) => <option key={k} value={k}>{v.ar}</option>)}
          </select>
        </div>
        <span className="mu" style={{ fontSize: 12 }}>لا يُعرض الحكم الآلي كي لا يؤثر في حكمك. تُقارن أحكامك بالآلة وبالمراجعين الآخرين.</span>
        {!it && <p className="mu">لا مواد للمراجعة الآن.</p>}
        {it && (
          <div>
            <p><b>{q!.question}</b></p>
            <h3>{it.title}</h3>
            <p style={{ whiteSpace: "pre-wrap", maxHeight: 260, overflow: "auto" }}>{it.text}</p>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" onClick={() => answer(it.item_id, true)}>نعم</button>
              <button className="btn" onClick={() => answer(it.item_id, false)}>لا</button>
              <span className="mu">بقي {q!.items.length}</span>
            </div>
          </div>
        )}
      </section>
      <section className="card side" aria-label="الاتفاق">
        <h2>نسبة الاتفاق (كوهين كابا)</h2>
        {ag && Object.entries(ag).map(([k, v]) => (
          <div key={k} className="row"><span className="f"><b>{v.ar}</b><br /><span className="mu" style={{ fontSize: 12 }}>{v.reading} · {v.reviewed_items} مادة</span></span>
            <span>الآلة/الإنسان {v.kappa_machine_human ?? "—"}<br />بين المراجعين {v.kappa_human_human ?? "—"}</span></div>
        ))}
      </section>
    </div>
  );
}
