import { Fragment, useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { fmtPublished } from "../../lib/time";
import { useReader } from "../../components/Reader";
import { api } from "../../api";
import { useCan } from "../../session";

type S = { id: number; title: string; item_count: number; source_count: number; updated_at: string };
type TL = { item_id: number; title: string; outlet: string; url: string; time: string; basis: string; published_at: string | null; published_date_only?: boolean; captured_at: string; published_tz?: string; published_tz_label?: string; published_tz_assumed?: boolean; archive_sha256: string; status: string };
type Rel = { item_id: number; outlet: string; kind: string; from_outlet: string | null; similarity: number; adds: string[] };
type View = { story: S & { locked: boolean }; first: TL | null; timeline: TL[]; relations: Rel[];
  comparison: { numbers: { unit: string; values: { value: string; outlets: string[] }[]; agreed: boolean }[];
    names: { name: string; outlets: string[]; share: string }[]; attributions: { outlet: string; attributed_to: string }[];
    anonymous_sources: string[]; disagreements: unknown[] } };

const fmt = (iso: string) => new Date(iso).toLocaleString("ar", { dateStyle: "short", timeStyle: "short" });
const REL: Record<string, string> = { "نقل مع نسبة": "p-ok", "نسخ دون نسبة": "p-bad", "ينسب لمصدر آخر": "p-n", "تغطية خاصة": "p-ac", "من الموقع نفسه": "p-n" };

export function Stories() {
  return (
    <Routes>
      <Route index element={<List />} />
      <Route path=":id" element={<StoryPage />} />
    </Routes>
  );
}

function List() {
  const [rows, setRows] = useState<S[]>([]);
  const [multi, setMulti] = useState(true);
  useEffect(() => { api<S[]>(`/api/stories?min_sources=${multi ? 2 : 1}`).then(setRows); }, [multi]);
  return (
    <section className="card">
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <h2 style={{ flex: 1 }}>القصص</h2>
        <label className="chk"><input type="checkbox" checked={multi} onChange={(e) => setMulti(e.target.checked)} />التي نشرها أكثر من مصدر فقط</label>
      </div>
      {!rows.length && <span className="mu">{multi ? "لا قصة نشرتها جهتان أو أكثر بعد. أزل علامة «أكثر من مصدر» لترى كل القصص، ومنها قصص المصدر الواحد." : "لا قصص بعد. تتكوّن تلقائيًا من المواد المرصودة."}</span>}
      {rows.map((s) => (
        <div key={s.id} className="row">
          <span className="f"><Link to={`/stories/${s.id}`}>{s.title}</Link><br /><span className="mu">آخر تحديث {fmt(s.updated_at)}</span></span>
          <span className="pill p-ac">{s.item_count} مادة · {s.source_count} مصدر</span>
        </div>
      ))}
    </section>
  );
}

function StoryPage() {
  const { id } = useParams();
  const can = useCan();
  const nav = useNavigate();
  const [v, setV] = useState<View | null>(null);
  const [msg, setMsg] = useState("");
  const [undo, setUndo] = useState<(() => Promise<unknown>) | null>(null);
  const [picker, setPicker] = useState<{ mode: "merge" } | { mode: "move"; itemId: number } | null>(null);
  const reader = useReader();
  const load = () => api<View>(`/api/stories/${id}`).then(setV);
  const done = (text: string, back: (() => Promise<unknown>) | null) => { setMsg(text); setUndo(() => back); setPicker(null); load(); };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!v) return null;
  const rel = Object.fromEntries(v.relations.map((r) => [r.item_id, r]));
  const moveItem = async (itemId: number, to: number | null, label: string) => {
    const r = await api<{ story_id: number; from_story_id: number | null }>(`/api/items/${itemId}/story`, { method: "PUT", body: { story_id: to } });
    done(to === null ? `فُصلت المادة إلى قصة مستقلة. سُجّل التعديل.` : `نُقلت المادة إلى «${label}». سُجّل التعديل.`,
      r.from_story_id ? () => api(`/api/items/${itemId}/story`, { method: "PUT", body: { story_id: r.from_story_id } }) : null);
  };
  const merge = async (other: S) => {
    if (!confirm(`ستنتقل مواد القصة «${other.title}» (${other.item_count} مادة) إلى هذه القصة «${v.story.title}»، وتبقيان قصة واحدة.\nيمكنك التراجع بعدها مباشرة. متابعة؟`)) return;
    const r = await api<{ moved: number[]; from_story_id: number }>(`/api/stories/${id}/merge`, { method: "POST", body: { other_id: other.id } });
    done(`دُمجت «${other.title}» في هذه القصة (${r.moved.length} مادة). سُجّل التعديل.`,
      () => api("/api/stories/move-items", { method: "POST", body: { item_ids: r.moved, story_id: r.from_story_id } }));
  };
  return (
    <div className="cols">
      <div className="grow">
        <section className="card">
          <h2>{v.story.title}</h2>
          <div className="tabs"><span className="pill p-ac">{v.story.item_count} مادة</span><span className="pill p-n">{v.story.source_count} مصدر</span>
            {v.story.locked && <span className="pill p-warn">عدّلها صحفي يدويًا</span>}</div>
          {v.first && (
            <div className="msg ok">
              <b>أول ناشر: {v.first.outlet}</b> · {fmt(v.first.time)} ({v.first.basis})
              <br /><span className="mu">رُصدت {fmt(v.first.captured_at)}{v.first.published_at ? ` · المعلن ${fmtPublished(v.first.published_at, v.first.published_date_only, v.first)}` : ""}{v.first.archive_sha256 && ` · بصمة النسخة المؤرشفة ${v.first.archive_sha256.slice(0, 12)}…`}</span>
            </div>
          )}
          {msg && (
            <div className="msg ok" role="status" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ flex: 1 }}>{msg}</span>
              {undo && <button className="btn sm" onClick={async () => { await undo(); setUndo(null); setMsg("تُراجع عن آخر تعديل. سُجّل في سجل التدقيق."); load(); }}>تراجع</button>}
            </div>
          )}
          {can("claims.create") && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button className="btn sm" onClick={() => setPicker(picker?.mode === "merge" ? null : { mode: "merge" })} aria-expanded={picker?.mode === "merge"}>ادمج معها قصة أخرى</button>
            </div>
          )}
          {picker?.mode === "merge" && <StoryPicker exclude={Number(id)} hint="ابحث عن القصة التي تتحدث عن الحدث نفسه، فتنتقل موادها إلى هذه القصة." onPick={merge} onCancel={() => setPicker(null)} />}
        </section>
        <section className="card">
          <h2>الخط الزمني: من نشر أولًا ومن نقل عن من</h2>
          {v.timeline.map((t, k) => (
            <Fragment key={t.item_id}>
            <div className={`row${reader.id === t.item_id ? " on" : ""}`}>
              <span className="pill p-n">{k + 1}</span>
              <span className="f"><b>{t.outlet}</b> · {t.basis.startsWith("وقت النشر") ? fmtPublished(t.time, false, t, true) : fmt(t.time)} <span className="mu">({t.basis})</span><br />
                <button className="linkish" onClick={() => reader.open(t.item_id)} title="اقرأ المادة في لوحة جانبية">{t.title}</button>
                {" "}<a href={t.url} target="_blank" rel="noreferrer noopener" className="mu" title="افتح الخبر في موقعه">↗</a>
                {rel[t.item_id]?.adds.length ? <><br /><span className="mu">أضاف: {rel[t.item_id].adds[0].slice(0, 140)}…</span></> : null}</span>
              {k === 0 ? <span className="pill p-ok">الأول</span> : rel[t.item_id] &&
                <span className={`pill ${REL[rel[t.item_id].kind] ?? "p-n"}`}>{rel[t.item_id].kind}{rel[t.item_id].from_outlet ? ` عن ${rel[t.item_id].from_outlet}` : ""}</span>}
              {t.status === "deleted" && <span className="pill p-bad">حُذفت</span>}
              {can("claims.create") && <>
                <button className="btn sm" onClick={() => setPicker(picker?.mode === "move" && picker.itemId === t.item_id ? null : { mode: "move", itemId: t.item_id })} title="المادة عن حدث في قصة أخرى">انقل إلى قصة…</button>
                <button className="btn sm" onClick={() => moveItem(t.item_id, null, "")} title="ليست عن الحدث نفسه ولا عن قصة موجودة">فصل</button>
              </>}
            </div>
            {picker?.mode === "move" && picker.itemId === t.item_id && (
              <StoryPicker exclude={Number(id)} hint="اختر القصة التي تنتمي إليها هذه المادة." onPick={(st) => moveItem(t.item_id, st.id, st.title)} onCancel={() => setPicker(null)} />
            )}
            </Fragment>
          ))}
        </section>
      </div>
      <div className="side">
        <section className="card">
          <h2>مقارنة الروايات</h2>
          {v.comparison.numbers.length === 0 && <span className="mu">لا أرقام للمقارنة.</span>}
          {v.comparison.numbers.map((n) => (
            <div key={n.unit} className="row">
              <span className="f"><b>{n.unit}</b>{n.values.map((x) => <div key={x.value} className="mu">{x.value} — {x.outlets.join("، ")}</div>)}</span>
              <span className={`pill ${n.agreed ? "p-ok" : "p-bad"}`}>{n.agreed ? "متفق" : "مختلف"}</span>
            </div>
          ))}
          {!!v.comparison.anonymous_sources.length && <div className="msg warn">مصادر مجهولة لدى: {v.comparison.anonymous_sources.join("، ")}</div>}
        </section>
        <section className="card">
          <h2>الأسماء الواردة</h2>
          {v.comparison.names.slice(0, 12).map((n) => (
            <div key={n.name} className="row"><span className="f">{n.name}</span><span className="pill p-n">{n.share}</span></div>
          ))}
          <button className="btn sm" onClick={() => nav("/entities")}>كل الكيانات</button>
        </section>
      </div>
    </div>
  );
}

/** اختيار قصة بالبحث في عنوانها (للدمج أو النقل). */
function StoryPicker({ exclude, hint, onPick, onCancel }: { exclude: number; hint: string; onPick: (s: S) => void; onCancel: () => void }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<S[]>([]);
  useEffect(() => {
    const t = setTimeout(() => {
      const p = new URLSearchParams({ exclude: String(exclude), limit: "15" });
      if (q.trim()) p.set("q", q.trim());
      api<S[]>(`/api/stories?${p}`).then(setRows).catch(() => setRows([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q, exclude]);
  return (
    <div className="card" style={{ background: "var(--sf2)", gap: 8 }}>
      <span className="mu">{hint}</span>
      <div style={{ display: "flex", gap: 6 }}>
        <input className="inp" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="ابحث بكلمة من عنوان القصة" aria-label="بحث عن قصة" />
        <button className="btn sm" onClick={onCancel}>إلغاء</button>
      </div>
      {!rows.length && <span className="mu">لا قصص مطابقة.</span>}
      {rows.map((r) => (
        <div key={r.id} className="row clickable" role="button" tabIndex={0} onClick={() => onPick(r)} onKeyDown={(e) => e.key === "Enter" && onPick(r)}>
          <span className="f">{r.title}<br /><span className="mu">{r.item_count} مادة · {r.source_count} مصدر · آخر تحديث {fmt(r.updated_at)}</span></span>
          <span className="btn sm">اختر</span>
        </div>
      ))}
    </div>
  );
}
