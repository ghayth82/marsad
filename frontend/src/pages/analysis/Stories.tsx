import { useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";

type S = { id: number; title: string; item_count: number; source_count: number; updated_at: string };
type TL = { item_id: number; title: string; outlet: string; url: string; time: string; basis: string; published_at: string | null; captured_at: string; archive_sha256: string; status: string };
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
  const load = () => api<View>(`/api/stories/${id}`).then(setV);
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!v) return null;
  const rel = Object.fromEntries(v.relations.map((r) => [r.item_id, r]));
  const detach = async (itemId: number) => {
    const r = await api<{ story_id: number }>(`/api/items/${itemId}/story`, { method: "PUT", body: { story_id: null } });
    setMsg(`فُصلت المادة إلى قصة مستقلة (#${r.story_id}). سُجّل التعديل.`);
    load();
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
              <br /><span className="mu">رُصدت {fmt(v.first.captured_at)}{v.first.published_at ? ` · المعلن ${fmt(v.first.published_at)}` : ""}{v.first.archive_sha256 && ` · بصمة النسخة المؤرشفة ${v.first.archive_sha256.slice(0, 12)}…`}</span>
            </div>
          )}
          {msg && <div className="msg ok" role="status">{msg}</div>}
        </section>
        <section className="card">
          <h2>الخط الزمني: من نشر أولًا ومن نقل عن من</h2>
          {v.timeline.map((t, k) => (
            <div key={t.item_id} className="row">
              <span className="pill p-n">{k + 1}</span>
              <span className="f"><b>{t.outlet}</b> · {fmt(t.time)} <span className="mu">({t.basis})</span><br />
                <a href={t.url} target="_blank" rel="noreferrer noopener">{t.title}</a>
                {rel[t.item_id]?.adds.length ? <><br /><span className="mu">أضاف: {rel[t.item_id].adds[0].slice(0, 140)}…</span></> : null}</span>
              {k === 0 ? <span className="pill p-ok">الأول</span> : rel[t.item_id] &&
                <span className={`pill ${REL[rel[t.item_id].kind] ?? "p-n"}`}>{rel[t.item_id].kind}{rel[t.item_id].from_outlet ? ` عن ${rel[t.item_id].from_outlet}` : ""}</span>}
              {t.status === "deleted" && <span className="pill p-bad">حُذفت</span>}
              {can("claims.create") && <button className="btn sm" onClick={() => detach(t.item_id)} title="ليست عن الحدث نفسه">فصل</button>}
            </div>
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
