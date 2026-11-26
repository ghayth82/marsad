// البند 13: «أدوات التحقق» — البلاغات، الأرقام الرسمية، الوعود، تفريغ التسجيلات، الأرشفة الفورية.
import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, apiForm } from "../../api";
import { useCan } from "../../session";

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ar", { dateStyle: "short", timeStyle: "short" }) : "—");

export function Tools() {
  const can = useCan();
  const work = can("claims.create") || can("verdicts.propose") || can("verdicts.approve");
  const tabs = [
    { to: "workflow", ar: "سير العمل", ok: work },
    { to: "tips", ar: "البلاغات", ok: can("claims.create") },
    { to: "figures", ar: "الأرقام الرسمية", ok: can("monitor.view") || can("claims.create") },
    { to: "promises", ar: "الوعود", ok: can("monitor.view") || can("claims.create") },
    { to: "transcripts", ar: "تفريغ التسجيلات", ok: can("labs.use") },
    { to: "archive", ar: "الأرشفة الفورية", ok: can("monitor.view") || can("claims.create") || can("cases.create") },
    { to: "corrections", ar: "سجل التصحيحات", ok: work },
  ].filter((t) => t.ok);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <nav className="tabs" aria-label="الأدوات">{tabs.map((t) => <NavLink key={t.to} to={`/tools/${t.to}`} className={({ isActive }) => (isActive ? "on" : "")}>{t.ar}</NavLink>)}</nav>
      <Routes>
        <Route index element={tabs[0] ? <Navigate to={tabs[0].to} replace /> : null} />
        <Route path="workflow" element={<Board />} />
        <Route path="corrections" element={<Corrections />} />
        <Route path="tips" element={<Tips />} />
        <Route path="figures" element={<Figures />} />
        <Route path="promises" element={<Promises />} />
        <Route path="transcripts/:id?" element={<Transcripts />} />
        <Route path="archive" element={<Archive />} />
      </Routes>
    </div>
  );
}

function Msg({ m }: { m: { k: string; t: string } | null }) { return m ? <div className={`msg ${m.k}`}>{m.t}</div> : null; }

// ---------- البلاغات ----------

type Tip = { id: number; code: string; text: string; urls: string[]; media_id: number | null; media_kind: string; status: string;
  claim_id: number | null; replied_at: string | null; reply_text: string; note: string; can_reply: boolean; received_at: string };
const TIP_ST: Record<string, string> = { new: "جديد", claim: "صار ادّعاءً", answered: "رُدّ عليه", rejected: "مرفوض" };

function Tips() {
  const nav = useNavigate();
  const [st, setSt] = useState("new");
  const [d, setD] = useState<{ tips: Tip[]; counts: Record<string, number>; bot: { configured: boolean; username: string | null } } | null>(null);
  const [m, setM] = useState<{ k: string; t: string } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [form, setForm] = useState({ text: "", reply: true, note: "", reply_text: "" });
  const load = () => api<typeof d>(`/api/tips?status=${st}`).then(setD);
  useEffect(() => { load(); }, [st]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return null;
  return (
    <div className="cols">
      <section className="card grow">
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <h2 style={{ flex: 1 }}>بلاغات الجمهور</h2>
          <div className="seg">{Object.entries(TIP_ST).map(([k, ar]) => <button key={k} className={st === k ? "on" : ""} onClick={() => setSt(k)}>{ar} ({d.counts[k] ?? 0})</button>)}</div>
          <button className="btn sm" onClick={async () => { const r = await api<{ tips: number }>("/api/tips/poll", { method: "POST" }); setM({ k: "ok", t: `${r.tips} بلاغ جديد` }); load(); }} disabled={!d.bot.configured}>افحص الآن</button>
        </div>
        <Msg m={m} />
        {!d.tips.length && <span className="mu">لا بلاغات هنا.</span>}
        {d.tips.map((t) => (
          <div key={t.id} className="row" style={{ alignItems: "flex-start" }}>
            <span className="f">
              <b>{t.code}</b> <span className="mu">· {fmt(t.received_at)}</span><br />
              <span style={{ whiteSpace: "pre-wrap" }}>{t.text || <span className="mu">بلا نص</span>}</span>
              {t.urls.map((u) => <div key={u}><a dir="ltr" href={u} target="_blank" rel="noreferrer noopener">{u}</a></div>)}
              {t.media_id && <div><Link to={`/${t.media_kind === "audio" ? "audio-lab" : "media-lab"}/${t.media_id}`}>افتح المرفق في المختبر ({t.media_kind === "image" ? "صورة" : t.media_kind === "video" ? "فيديو" : "صوت"})</Link></div>}
              {t.note && <div className="mu">{t.note}</div>}
              {t.claim_id && <div><Link to={`/claims/${t.claim_id}`}>بطاقة الادّعاء</Link>{t.replied_at ? ` · رُدّ عليه ${fmt(t.replied_at)}` : ""}</div>}
              {open === t.id && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                  <label className="fld">نص الادّعاء<textarea className="inp" rows={2} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} /></label>
                  <label className="chk"><input type="checkbox" checked={form.reply} disabled={!t.can_reply} onChange={(e) => setForm({ ...form, reply: e.target.checked })} />أرسل النتيجة لصاحب البلاغ حين يُعتمد الحكم</label>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button className="btn sm pri" onClick={async () => { try { const r = await api<{ claim_id: number }>(`/api/tips/${t.id}/claim`, { method: "POST", body: { text: form.text, reply: form.reply } }); nav(`/claims/${r.claim_id}`); } catch (e) { setM({ k: "err", t: (e as Error).message }); } }}>حوّله إلى ادّعاء</button>
                  </div>
                  <label className="fld">أو ارفضه — سبب داخلي<input className="inp" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></label>
                  <label className="fld">رد لصاحب البلاغ (اختياري)<input className="inp" value={form.reply_text} disabled={!t.can_reply} onChange={(e) => setForm({ ...form, reply_text: e.target.value })} /></label>
                  <button className="btn sm danger" onClick={async () => { await api(`/api/tips/${t.id}/reject`, { method: "POST", body: { note: form.note, reply_text: form.reply_text } }); setOpen(null); load(); }}>رفض</button>
                </div>
              )}
            </span>
            <span className="pill p-n">{TIP_ST[t.status]}</span>
            {t.status === "new" && open !== t.id && <button className="btn sm" onClick={() => { setOpen(t.id); setForm({ text: t.text.replace(/https?:\/\/\S+/g, "").trim(), reply: t.can_reply, note: "", reply_text: "" }); }}>معالجة</button>}
          </div>
        ))}
      </section>
      <section className="card side">
        <h2>كيف يعمل</h2>
        {d.bot.configured
          ? <span>يرسل الجمهور إلى البوت <b dir="ltr">@{d.bot.username}</b> نصًا أو رابطًا أو صورة أو تسجيلًا، فيصلهم رقم متابعة. شارك رابط البوت <a dir="ltr" href={`https://t.me/${d.bot.username}`} target="_blank" rel="noreferrer">t.me/{d.bot.username}</a>.</span>
          : <div className="msg warn">لم يُضف بوت تيليغرام بعد. يضيفه المدير من الإدارة ← التخزين والإعدادات.</div>}
        <span className="mu">لا يُحفظ من المُبلِّغ إلا معرّف المحادثة لإرسال النتيجة، ويُمحى بعد 90 يومًا. يُفحص البوت كل دقيقة.</span>
      </section>
    </div>
  );
}

// ---------- الأرقام الرسمية ----------

type Fig = { id: number; indicator: string; value: number; unit: string; as_of: string; agency: string; url: string; keywords: string[]; note: string };

function Figures() {
  const can = useCan();
  const [rows, setRows] = useState<Fig[]>([]);
  const [f, setF] = useState({ indicator: "", value: "", unit: "", as_of: "", agency: "", url: "", keywords: "" });
  const [m, setM] = useState<{ k: string; t: string } | null>(null);
  const [test, setTest] = useState("");
  const [hits, setHits] = useState<{ indicator: string; claimed: number; official: number; diff_pct: number | null; same: boolean }[] | null>(null);
  const load = () => api<{ figures: Fig[] }>("/api/figures").then((r) => setRows(r.figures));
  useEffect(() => { load(); }, []);
  const manage = can("figures.manage");
  return (
    <div className="cols">
      <section className="card grow">
        <h2>جدول الأرقام الرسمية</h2>
        <span className="mu">كل رقم في ادّعاء أو مادة يُقارن بآخر قيمة للمؤشر نفسه هنا. المقارنة دليل يقرّه الصحفي، لا حكم.</span>
        <div className="tw"><table>
          <thead><tr><th>المؤشر</th><th>القيمة</th><th>التاريخ</th><th>الجهة</th><th>الكلمات</th>{manage && <th />}</tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}><td>{r.url ? <a href={r.url} target="_blank" rel="noreferrer noopener">{r.indicator}</a> : r.indicator}</td>
              <td>{r.value} {r.unit}</td><td>{r.as_of}</td><td>{r.agency}</td><td className="mu">{r.keywords.join("، ")}</td>
              {manage && <td><button className="btn sm" onClick={async () => { if (confirm(`حذف «${r.indicator}» بتاريخ ${r.as_of}؟`)) { await api(`/api/figures/${r.id}`, { method: "DELETE" }); load(); } }}>حذف</button></td>}</tr>))}</tbody>
        </table></div>
        {!rows.length && <span className="mu">الجدول فارغ.</span>}
      </section>
      <div className="side">
        {manage && (
          <section className="card">
            <h2>إضافة رقم</h2>
            <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={async (e) => {
              e.preventDefault(); setM(null);
              try { await api("/api/figures", { method: "POST", body: f }); setF({ indicator: "", value: "", unit: "", as_of: "", agency: "", url: "", keywords: "" }); load(); setM({ k: "ok", t: "أُضيف." }); }
              catch (x) { setM({ k: "err", t: (x as Error).message }); }
            }}>
              <label className="fld">المؤشر<input className="inp" required value={f.indicator} onChange={(e) => setF({ ...f, indicator: e.target.value })} placeholder="معدل البطالة" /></label>
              <div style={{ display: "flex", gap: 6 }}>
                <label className="fld" style={{ flex: 1 }}>القيمة<input className="inp" required value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} /></label>
                <label className="fld" style={{ flex: 1 }}>الوحدة<input className="inp" value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} placeholder="٪" /></label>
              </div>
              <label className="fld">التاريخ<input className="inp" required value={f.as_of} onChange={(e) => setF({ ...f, as_of: e.target.value })} placeholder="2026-09 أو 2026" /></label>
              <label className="fld">الجهة<input className="inp" value={f.agency} onChange={(e) => setF({ ...f, agency: e.target.value })} /></label>
              <label className="fld">الرابط<input className="inp" dir="ltr" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></label>
              <label className="fld">كلمات تدل عليه في الأخبار (بفواصل)<input className="inp" value={f.keywords} onChange={(e) => setF({ ...f, keywords: e.target.value })} placeholder="البطالة، العاطلين عن العمل" /></label>
              <button className="btn sm pri">إضافة</button>
            </form>
            <Msg m={m} />
            <label className="fld">أو استورد CSV (المؤشر، القيمة، الوحدة، التاريخ، الجهة، الرابط، الكلمات)
              <input type="file" accept=".csv,text/csv" onChange={async (e) => {
                const file = e.target.files?.[0]; if (!file) return;
                const fd = new FormData(); fd.append("file", file);
                try { const r = await apiForm<{ added: number; errors: string[] }>("/api/figures/import", fd); setM({ k: r.errors.length ? "warn" : "ok", t: `أُضيف ${r.added}. ${r.errors.join(" · ")}` }); load(); }
                catch (x) { setM({ k: "err", t: (x as Error).message }); }
                e.target.value = "";
              }} /></label>
          </section>
        )}
        <section className="card">
          <h2>جرّب نصًا</h2>
          <textarea className="inp" rows={3} value={test} onChange={(e) => setTest(e.target.value)} placeholder="ارتفعت نسبة البطالة إلى 30٪" aria-label="نص للتجربة" />
          <button className="btn sm" onClick={async () => setHits((await api<{ matches: NonNullable<typeof hits> }>("/api/figures/match", { method: "POST", body: { text: test } })).matches)}>قارن</button>
          {hits && (hits.length ? hits.map((h, i) => <div key={i} className="row"><span className="f">{h.indicator}: {h.claimed} مقابل {h.official}</span><span className={`pill ${h.same ? "p-ok" : "p-warn"}`}>{h.same ? "مطابق" : `فرق ${h.diff_pct}٪`}</span></div>) : <span className="mu">لا رقم قرب كلمة مؤشر معروف.</span>)}
        </section>
      </div>
    </div>
  );
}

// ---------- الوعود ----------

type Prom = { id: number; entity_id: number; entity: string; text: string; said_at: string | null; source_url: string; due_at: string | null;
  status: string; status_ar: string; evidence_url: string; evidence_note: string; overdue: boolean; history: { at: string; status: string; note: string; url?: string }[] };

function Promises() {
  const can = useCan();
  const [d, setD] = useState<{ promises: Prom[]; statuses: Record<string, string> } | null>(null);
  const [st, setSt] = useState("");
  const [f, setF] = useState({ entity_name: "", text: "", said_at: "", due_at: "", source_url: "" });
  const [m, setM] = useState<{ k: string; t: string } | null>(null);
  const [upd, setUpd] = useState<{ id: number; status: string; evidence_url: string; evidence_note: string } | null>(null);
  const load = () => api<typeof d>(`/api/promises${st ? `?status=${st}` : ""}`).then(setD);
  useEffect(() => { load(); }, [st]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return null;
  return (
    <div className="cols">
      <section className="card grow">
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <h2 style={{ flex: 1 }}>الوعود والتصريحات</h2>
          <select className="inp" style={{ width: 170 }} value={st} onChange={(e) => setSt(e.target.value)} aria-label="الحالة">
            <option value="">كل الحالات</option>{Object.entries(d.statuses).map(([k, ar]) => <option key={k} value={k}>{ar}</option>)}
          </select>
        </div>
        <Msg m={m} />
        {!d.promises.length && <span className="mu">لا وعود تُتابع. أضف وعدًا، أو اضغط «تتبّع كوعد» على تصريح في صفحة الكيان.</span>}
        {d.promises.map((p) => (
          <div key={p.id} className="row" style={{ alignItems: "flex-start" }}>
            <span className="f">
              <Link to={`/entities/${p.entity_id}`}><b>{p.entity}</b></Link>: «{p.text}»<br />
              <span className="mu">قاله {p.said_at ? fmt(p.said_at) : "—"}{p.source_url && <> · <a href={p.source_url} target="_blank" rel="noreferrer noopener">المصدر</a></>} · الموعد {p.due_at ? fmt(p.due_at) : "غير محدد"}</span>
              {p.evidence_note && <div className="mu">الدليل: {p.evidence_note} {p.evidence_url && <a href={p.evidence_url} target="_blank" rel="noreferrer noopener">رابط</a>}</div>}
              {upd?.id === p.id && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                  <select className="inp" value={upd.status} onChange={(e) => setUpd({ ...upd, status: e.target.value })} aria-label="الحالة الجديدة">
                    {Object.entries(d.statuses).map(([k, ar]) => <option key={k} value={k}>{ar}</option>)}</select>
                  <input className="inp" dir="ltr" placeholder="رابط الدليل" value={upd.evidence_url} onChange={(e) => setUpd({ ...upd, evidence_url: e.target.value })} />
                  <input className="inp" placeholder="ملاحظة الدليل" value={upd.evidence_note} onChange={(e) => setUpd({ ...upd, evidence_note: e.target.value })} />
                  <button className="btn sm pri" onClick={async () => { try { await api(`/api/promises/${p.id}`, { method: "PATCH", body: upd }); setUpd(null); load(); } catch (x) { setM({ k: "err", t: (x as Error).message }); } }}>حفظ</button>
                </div>
              )}
            </span>
            <span className={`pill ${p.overdue ? "p-bad" : p.status === "kept" ? "p-ok" : p.status === "broken" ? "p-bad" : p.status === "partial" ? "p-warn" : "p-n"}`}>{p.overdue ? "حان موعده" : p.status_ar}</span>
            {can("claims.create") && upd?.id !== p.id && <button className="btn sm" onClick={() => setUpd({ id: p.id, status: p.status, evidence_url: p.evidence_url, evidence_note: "" })}>تحديث</button>}
          </div>
        ))}
      </section>
      {can("claims.create") && (
        <section className="card side">
          <h2>تتبّع وعد</h2>
          <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={async (e) => {
            e.preventDefault(); setM(null);
            try { await api("/api/promises", { method: "POST", body: { ...f, said_at: f.said_at || null, due_at: f.due_at || null } }); setF({ entity_name: "", text: "", said_at: "", due_at: "", source_url: "" }); load(); setM({ k: "ok", t: "بدأت المتابعة. سيصلك تذكير حين يحين الموعد." }); }
            catch (x) { setM({ k: "err", t: (x as Error).message }); }
          }}>
            <label className="fld">صاحب الوعد<input className="inp" required value={f.entity_name} onChange={(e) => setF({ ...f, entity_name: e.target.value })} placeholder="وزير الأشغال" /></label>
            <label className="fld">نص الوعد<textarea className="inp" required rows={2} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></label>
            <label className="fld">تاريخ التصريح<input className="inp" type="date" value={f.said_at} onChange={(e) => setF({ ...f, said_at: e.target.value })} /></label>
            <label className="fld">موعد الوفاء<input className="inp" type="date" value={f.due_at} onChange={(e) => setF({ ...f, due_at: e.target.value })} /></label>
            <label className="fld">رابط المصدر<input className="inp" dir="ltr" value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} /></label>
            <button className="btn sm pri">ابدأ المتابعة</button>
          </form>
        </section>
      )}
    </div>
  );
}

// ---------- تفريغ التسجيلات ----------

type Seg = { i: number; start: number; end: number; speaker: string; text: string; reasons: string[] };
const ts = (s: number) => { const x = Math.floor(s || 0); return `${String(Math.floor(x / 60)).padStart(2, "0")}:${String(x % 60).padStart(2, "0")}`; };

function Transcripts() {
  const can = useCan();
  const nav = useNavigate();
  const [list, setList] = useState<{ media_id: number; kind: string; filename: string; available: boolean; summary: string; checkable: number }[]>([]);
  const [cur, setCur] = useState<{ media_id: number; filename: string; available: boolean; summary: string; segments: Seg[]; checkable: number } | null>(null);
  const [only, setOnly] = useState(true);
  const [busy, setBusy] = useState(false);
  const [m, setM] = useState<{ k: string; t: string } | null>(null);
  const loadList = () => api<{ media: typeof list }>("/api/transcripts").then((r) => setList(r.media));
  useEffect(() => { loadList(); }, []);
  const open = async (id: number) => { setM(null); setCur(await api(`/api/transcripts/${id}`)); };
  const run = async (id: number) => { setBusy(true); setM(null); try { setCur(await api(`/api/transcripts/${id}`, { method: "POST" })); loadList(); } catch (x) { setM({ k: "err", t: (x as Error).message }); } finally { setBusy(false); } };
  const segs = cur ? cur.segments.filter((s) => !only || s.reasons.length) : [];
  return (
    <div className="cols">
      <section className="card grow">
        {!cur ? <span className="mu">اختر تسجيلًا من القائمة، أو ارفع تسجيل مؤتمر من <Link to="/audio-lab">مختبر الصوت</Link> أو فيديو من <Link to="/media-lab">مختبر الصور والفيديو</Link>.</span> : (<>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <h2 style={{ flex: 1 }}>{cur.filename || `تسجيل #${cur.media_id}`}</h2>
            <label className="chk"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} />الجمل القابلة للتحقق فقط ({cur.checkable})</label>
            {!cur.available && <button className="btn sm pri" disabled={busy} onClick={() => run(cur.media_id)}>{busy ? "يفرّغ…" : "فرّغ الآن"}</button>}
          </div>
          <span className="mu">{cur.summary}. الإبراز بقواعد ثابتة: أرقام، نسب، مقارنات، أعداد، «الأول أو الأكبر»، وقائع منسوبة، تواريخ.</span>
          <Msg m={m} />
          {segs.map((s) => (
            <div key={s.i} className="row" style={{ alignItems: "flex-start", background: s.reasons.length ? "var(--acs)" : undefined, borderRadius: 8, padding: 8 }}>
              <span className="mu" dir="ltr" style={{ minWidth: 44 }}>{ts(s.start)}</span>
              <span className="f">{s.speaker && <b>{s.speaker}: </b>}{s.text}
                {s.reasons.length > 0 && <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>{s.reasons.map((r) => <span key={r} className="pill p-ac">{r}</span>)}</div>}</span>
              {can("claims.create") && <button className="btn sm" onClick={async () => { const r = await api<{ claim_id: number }>(`/api/transcripts/${cur.media_id}/claim`, { method: "POST", body: { i: s.i } }); nav(`/claims/${r.claim_id}`); }}>حوّلها إلى ادّعاء</button>}
            </div>
          ))}
        </>)}
      </section>
      <section className="card side">
        <h2>التسجيلات</h2>
        {!list.length && <span className="mu">لا تسجيلات صوت أو فيديو بعد.</span>}
        {list.map((x) => (
          <button key={x.media_id} type="button" className="row" onClick={() => open(x.media_id)}
            style={{ border: "none", borderBottom: "1px solid var(--bd)", background: cur?.media_id === x.media_id ? "var(--acs)" : "none", textAlign: "start", fontFamily: "inherit", color: "var(--tx)", cursor: "pointer" }}>
            <span className="f">{x.filename || `#${x.media_id}`}<br /><span className="mu">{x.kind === "video" ? "فيديو" : "صوت"} · {x.available ? `${x.checkable} جملة قابلة للتحقق` : "لم يُفرَّغ"}</span></span>
          </button>
        ))}
        <span className="mu">التفريغ بمحركات «صوتي». البث المباشر غير مشمول.</span>
      </section>
    </div>
  );
}

// ---------- الأرشفة الفورية ----------

type Snap = { id: number; url: string; title: string; sha256: string; status: string; error: string; has_screenshot: boolean; wayback_status: string; wayback_url: string; created_at: string; claim_id: number | null };

function Archive() {
  const [rows, setRows] = useState<Snap[]>([]);
  const [url, setUrl] = useState("");
  const [wb, setWb] = useState(false);
  const [busy, setBusy] = useState(false);
  const [m, setM] = useState<{ k: string; t: string } | null>(null);
  const load = () => api<{ snapshots: Snap[] }>("/api/snapshots").then((r) => setRows(r.snapshots));
  useEffect(() => { load(); }, []);
  return (
    <div className="cols">
      <section className="card grow">
        <h2>الأرشيف الفوري</h2>
        {!rows.length && <span className="mu">لم يُؤرشف رابط بعد.</span>}
        {rows.map((s) => (
          <div key={s.id} className="row">
            <span className="f"><a href={s.url} target="_blank" rel="noreferrer noopener">{s.title || s.url}</a><br />
              <span className="mu" dir="ltr" style={{ fontSize: 11 }}>SHA-256 {s.sha256 ? s.sha256.slice(0, 24) + "…" : "—"}</span>
              <span className="mu"> · {fmt(s.created_at)}{s.claim_id ? <> · <Link to={`/claims/${s.claim_id}`}>الادّعاء</Link></> : null}</span>
              {s.status !== "ok" && <div className="msg err" style={{ marginTop: 4 }}>{s.error}</div>}</span>
            {s.status === "ok" && <a className="btn sm" href={`/api/snapshots/${s.id}/html`}>النسخة</a>}
            {s.has_screenshot && <a className="btn sm" href={`/api/snapshots/${s.id}/screenshot`} target="_blank" rel="noreferrer">اللقطة</a>}
            {s.wayback_url && <a className="btn sm" href={s.wayback_url} target="_blank" rel="noreferrer noopener">Wayback</a>}
          </div>
        ))}
      </section>
      <section className="card side">
        <h2>أرشف رابطًا</h2>
        <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={async (e) => {
          e.preventDefault(); setBusy(true); setM(null);
          try { const s = await api<Snap>("/api/snapshots", { method: "POST", body: { url, wayback: wb } }); setM(s.status === "ok" ? { k: "ok", t: "أُرشف." } : { k: "err", t: s.error }); setUrl(""); load(); }
          catch (x) { setM({ k: "err", t: (x as Error).message }); } finally { setBusy(false); }
        }}>
          <input className="inp" dir="ltr" placeholder="https://" required value={url} onChange={(e) => setUrl(e.target.value)} aria-label="الرابط" />
          <label className="chk"><input type="checkbox" checked={wb} onChange={(e) => setWb(e.target.checked)} />اطلب حفظه في Wayback Machine أيضًا (يُرسل الرابط إلى جهة خارجية)</label>
          <button className="btn sm pri" disabled={busy}>{busy ? "يؤرشف…" : "أرشف الآن"}</button>
        </form>
        <Msg m={m} />
        <span className="mu">تُحفظ الصفحة كما وصلت ونصها وبصمتها، ولقطة كاملة إن توفّر متصفح على الجهاز. الروابط في مسودات القصص تُؤرشف تلقائيًا داخل قضيتها.</span>
      </section>
    </div>
  );
}

// ---------- سير العمل (البند 14) ----------

type WClaim = { id: number; text: string; state_ar: string; priority: string; priority_ar: string; assignee: string; due_at: string | null; overdue: boolean };

function Board() {
  const can = useCan();
  const [d, setD] = useState<{ columns: { key: string; title: string; claims: WClaim[] }[]; sla: Record<string, number>; priorities: Record<string, string> } | null>(null);
  const [sla, setSla] = useState<Record<string, number> | null>(null);
  const [m, setM] = useState<{ k: string; t: string } | null>(null);
  const load = () => api<NonNullable<typeof d>>("/api/workflow/board").then((r) => { setD(r); setSla(r.sla); });
  useEffect(() => { load(); }, []);
  if (!d || !sla) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 12 }}>
        {d.columns.map((col) => (
          <section key={col.key} className="card" aria-label={col.title}>
            <h2>{col.title} <span className="mu">({col.claims.length})</span></h2>
            {!col.claims.length && <span className="mu">لا شيء.</span>}
            {col.claims.map((c) => (
              <Link key={c.id} to={`/claims/${c.id}`} className="card" style={{ padding: 10, gap: 4, textDecoration: "none", color: "var(--tx)", borderColor: c.overdue ? "var(--bad)" : undefined }}>
                <span style={{ fontSize: 13 }}>{c.text}</span>
                <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  <span className={`pill ${c.priority === "urgent" ? "p-bad" : c.priority === "high" ? "p-warn" : "p-n"}`}>{c.priority_ar}</span>
                  {c.assignee && <span className="pill p-n">{c.assignee}</span>}
                  {c.overdue && <span className="pill p-bad">تجاوز المهلة</span>}
                </span>
                {c.due_at && <span className="mu" style={{ fontSize: 11 }}>المهلة {fmt(c.due_at)}</span>}
              </Link>
            ))}
          </section>
        ))}
      </div>
      <section className="card adv">
        <h2>المهل بالساعات</h2>
        <span className="mu">تبدأ المهلة من الإسناد. يصل المُسند إليه تنبيه حين يبقى ربعها، ويصله مع المحرّرين تنبيه حين تُتجاوز.</span>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
          {Object.entries(d.priorities).map(([k, ar]) => (
            <label key={k} className="fld" style={{ width: 120 }}>{ar}<input className="inp" type="number" min={0.25} step={0.25} value={sla[k]} disabled={!can("system.manage")}
              onChange={(e) => setSla({ ...sla, [k]: Number(e.target.value) })} /></label>
          ))}
          {can("system.manage") && <button className="btn sm" onClick={async () => { try { await api("/api/workflow/sla", { method: "PUT", body: sla }); setM({ k: "ok", t: "حُفظت المهل." }); } catch (x) { setM({ k: "err", t: (x as Error).message }); } }}>حفظ</button>}
        </div>
        <Msg m={m} />
      </section>
    </div>
  );
}

// ---------- سجل التصحيحات ----------

type Corr = { id: number; claim_id: number; claim: string; before: { label: string; grade: string }; after: { label: string; grade: string }; reason: string; at: string; public: boolean };

function Corrections() {
  const can = useCan();
  const [d, setD] = useState<{ corrections: Corr[]; public: boolean } | null>(null);
  const load = () => api<NonNullable<typeof d>>("/api/corrections").then(setD);
  useEffect(() => { load(); }, []);
  if (!d) return null;
  return (
    <div className="cols">
      <section className="card grow">
        <h2>سجل التصحيحات</h2>
        <span className="mu">كل تعديل لحكم معتمد يُسجَّل هنا بما كان وما صار وسببه.</span>
        {!d.corrections.length && <span className="mu">لا تصحيحات بعد.</span>}
        {d.corrections.map((k) => (
          <div key={k.id} className="row" style={{ alignItems: "flex-start" }}>
            <span className="f"><Link to={`/claims/${k.claim_id}`}>{k.claim}</Link><br />
              <span>كان: <b>{k.before.label}</b> ← صار: <b>{k.after.label}</b></span><br />
              <span className="mu">السبب: {k.reason || "—"} · {fmt(k.at)}</span></span>
            {can("verdicts.approve") && <label className="chk"><input type="checkbox" checked={k.public} onChange={async (e) => { await api(`/api/corrections/${k.id}`, { method: "PUT", body: { public: e.target.checked } }); load(); }} />في الصفحة العامة</label>}
          </div>
        ))}
      </section>
      <section className="card side">
        <h2>الصفحة العامة</h2>
        <span>{d.public ? "مفعّلة" : "مطفأة"}: تُفتح دون دخول على <a dir="ltr" href="/public/corrections" target="_blank" rel="noreferrer">/public/corrections</a>، وتعرض الأحكام المصحّحة فقط، دون أسماء الصحفيين ودون أي تقييم للمواقع.</span>
        {can("system.manage") && <button className={`btn sm ${d.public ? "" : "pri"}`} onClick={async () => { await api("/api/corrections/public", { method: "PUT", body: { public: !d.public } }); load(); }}>{d.public ? "أطفئ الصفحة العامة" : "فعّل الصفحة العامة"}</button>}
      </section>
    </div>
  );
}
