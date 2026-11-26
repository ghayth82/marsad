import { useEffect, useState } from "react";
import { Link, Route, Routes, useParams } from "react-router-dom";
import { useReader } from "../../components/Reader";
import { api } from "../../api";
import { useCan } from "../../session";

type E = { id: number; name: string; kind: string; mentions: number; aliases: string[] };
type St = { id: number; quote: string; said_at: string | null; is_promise: boolean; item_id: number; item_title: string; url: string };
type Full = E & { tone_by_outlet: { outlet: string; mentions: number; tone: number }[]; statements: St[]; promises: number;
  contradictions: { reason: string; a: St; b: St }[]; recent_items: { id: number; title: string; outlet: string; captured_at: string }[] };

const KIND: Record<string, string> = { person: "شخص أو منصب", org: "مؤسسة", place: "مكان" };
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("ar") : "—");

export function Entities() {
  return (
    <Routes>
      <Route index element={<List />} />
      <Route path=":id" element={<EntityPage />} />
    </Routes>
  );
}

function List() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [rows, setRows] = useState<E[]>([]);
  useEffect(() => {
    const t = setTimeout(() => api<E[]>(`/api/entities?${new URLSearchParams({ q, ...(kind ? { kind } : {}) })}`).then(setRows), 250);
    return () => clearTimeout(t);
  }, [q, kind]);
  return (
    <section className="card">
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="inp" style={{ flex: "1 1 240px" }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="ابحث عن شخص أو مؤسسة أو مكان" aria-label="بحث في الكيانات" />
        <select className="inp" style={{ width: 160 }} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="النوع">
          <option value="">كل الأنواع</option>{Object.entries(KIND).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
      {rows.map((e) => (
        <div key={e.id} className="row"><span className="f"><Link to={`/entities/${e.id}`}>{e.name}</Link> <span className="mu">· {KIND[e.kind]}</span></span>
          <span className="pill p-n">{e.mentions} مادة</span></div>
      ))}
      {!rows.length && <div className="empty"><span>لا أسماء بعد. يستخرج البرنامج أسماء الأشخاص والجهات تلقائيًا من الأخبار المرصودة.</span><Link className="btn pri" to="/sources">أضف مصدرًا</Link></div>}
    </section>
  );
}

const toneWord = (x: number) => (x > 0.5 ? "إيجابية واضحة" : x > 0.2 ? "إيجابية غالبًا" : x < -0.5 ? "سلبية واضحة" : x < -0.2 ? "سلبية غالبًا" : "محايدة أو مختلطة");
const toneCls = (x: number) => (x > 0.2 ? "p-ok" : x < -0.2 ? "p-bad" : "p-n");

function EntityPage() {
  const { id } = useParams();
  const [e, setE] = useState<Full | null>(null);
  const [alias, setAlias] = useState("");
  const [tracked, setTracked] = useState<{ id: number; text: string; status_ar: string; due_at: string | null; overdue: boolean; statement_id: number | null }[]>([]);
  const [track, setTrack] = useState<{ sid: number; due: string } | null>(null);
  const can = useCan();
  const reader = useReader();
  const load = () => {
    api<Full>(`/api/entities/${id}`).then(setE);
    api<{ promises: typeof tracked }>(`/api/promises?entity_id=${id}`).then((r) => setTracked(r.promises)).catch(() => setTracked([]));
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!e) return null;
  return (
    <div className="cols">
      <div className="grow">
        <section className="card">
          <h2>{e.name} <span className="mu">· {KIND[e.kind]}</span></h2>
          <div className="tabs"><span className="pill p-n">{e.mentions} مادة</span><span className="pill p-n">{e.statements.length} تصريح</span>
            {e.promises > 0 && <span className="pill p-ac">{e.promises} وعد</span>}{e.contradictions.length > 0 && <span className="pill p-bad">{e.contradictions.length} تناقض محتمل</span>}</div>
          {!!e.aliases.length && <span className="mu">يُكتب أيضًا: {e.aliases.join("، ")}</span>}
        </section>
        <section className="card">
          <h2>المواد التي ذُكر فيها <span className="mu">({e.mentions})</span></h2>
          <span className="mu">اضغط المادة لتقرأها في لوحة جانبية، ومنها تفتحها في صفحة أو نافذة مستقلة.</span>
          {!e.recent_items.length && <span className="mu">لا مواد بعد.</span>}
          {e.recent_items.map((i) => (
            <div key={i.id} className={`row clickable${reader.id === i.id ? " on" : ""}`} role="button" tabIndex={0}
              onClick={() => reader.open(i.id)} onKeyDown={(k) => k.key === "Enter" && reader.open(i.id)}>
              <span className="f"><b>{i.title}</b><br /><span className="mu">{i.outlet} · {day(i.captured_at)}</span></span>
            </div>
          ))}
        </section>
        {e.contradictions.map((c, k) => (
          <section key={k} className="card" style={{ borderColor: "var(--bad)" }}>
            <h3>تناقض محتمل: {c.reason}</h3>
            <span className="mu">للمراجعة: قد يكون تغيّرًا مبرّرًا في الموقف.</span>
            <div className="g4" style={{ gridTemplateColumns: "1fr 1fr" }}>
              {[c.a, c.b].map((s) => <div key={s.id} className="msg warn"><b>{day(s.said_at)}</b><br />«{s.quote}»</div>)}
            </div>
          </section>
        ))}
        <section className="card">
          <h2>التصريحات</h2>
          {e.statements.map((s) => (
            <div key={s.id} className="row"><span className="f">«{s.quote}»<br /><span className="mu">{day(s.said_at)} · <a href={s.url} target="_blank" rel="noreferrer noopener">{s.item_title}</a></span></span>
              {s.is_promise && <span className="pill p-ac">وعد</span>}
              {can("claims.create") && !tracked.some((t) => t.statement_id === s.id) && (track?.sid === s.id ? (
                <span style={{ display: "flex", gap: 6 }}>
                  <input className="inp" type="date" style={{ width: 150 }} value={track.due} onChange={(x) => setTrack({ ...track, due: x.target.value })} aria-label="موعد الوفاء" />
                  <button className="btn sm pri" onClick={async () => { await api("/api/promises", { method: "POST", body: { statement_id: s.id, due_at: track.due || null } }); setTrack(null); load(); }}>تتبّع</button>
                </span>) : <button className="btn sm" onClick={() => setTrack({ sid: s.id, due: "" })}>تتبّع كوعد</button>)}</div>
          ))}
          {!e.statements.length && <span className="mu">لا تصريحات منسوبة بعد.</span>}
        </section>
      </div>
      <div className="side">
        <section className="card">
          <h2>الوعود المتابَعة</h2>
          {!tracked.length && <span className="mu">لا وعود تُتابع لهذا الكيان.</span>}
          {tracked.map((t) => <div key={t.id} className="row"><Link className="f" to="/tools/promises">«{t.text}»</Link><span className={`pill ${t.overdue ? "p-bad" : "p-n"}`}>{t.overdue ? "حان موعده" : t.status_ar}</span></div>)}
        </section>
        <section className="card">
          <h2>نبرة التغطية حسب الموقع</h2>
          <span className="mu">كيف تتحدث كل جهة عن هذا الكيان، بحسب الكلمات الإيجابية والسلبية حول اسمه. مؤشر آلي للاستئناس لا حكم.</span>
          {e.tone_by_outlet.map((t) => (
            <div key={t.outlet} className="row"><span className="f">{t.outlet}<br /><span className="mu">مبنية على {t.mentions} {t.mentions === 1 ? "مادة" : "مواد"}{t.mentions < 3 ? " — عدد قليل لا يكفي للحكم" : ""}</span></span>
              <span className={`pill ${toneCls(t.tone)}`} title={`المؤشر ${t.tone > 0 ? "+" : ""}${t.tone} من −1 إلى +1`}>{toneWord(t.tone)}</span></div>
          ))}
        </section>
        <section className="card">
          <h2>أسماء بديلة</h2>
          <form style={{ display: "flex", gap: 6 }} onSubmit={async (ev) => { ev.preventDefault(); await api(`/api/entities/${e.id}`, { method: "PUT", body: { aliases: [...e.aliases, alias] } }); setAlias(""); load(); }}>
            <input className="inp" value={alias} onChange={(x) => setAlias(x.target.value)} placeholder="كتابة أخرى للاسم" aria-label="اسم بديل" />
            <button className="btn" disabled={!alias.trim()}>إضافة</button>
          </form>
        </section>
      </div>
    </div>
  );
}
