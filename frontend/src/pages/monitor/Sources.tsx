import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useCan } from "../../session";

type Src = { id: number; url: string; kind: string; kind_ar: string; read_url: string; title: string; tags: string[]; check_minutes: number;
  active: boolean; status: "new" | "ok" | "error" | "paused"; last_checked_at: string | null; last_item_at: string | null; last_error: string; silent: boolean; checking?: boolean };
type Outlet = { id: number; name: string; kind: string; country: string; website: string; logo_url: string; tags: string[]; items: number; sources: Src[] };
// بلد الموقع يحدد توقيت وقت النشر الظاهر في صفحاته («21:45 بتوقيت مصر»)
const COUNTRY_BY_TLD: Record<string, string> = { eg: "مصر", sa: "السعودية", ae: "الإمارات", qa: "قطر", kw: "الكويت", bh: "البحرين", om: "عمان",
  iq: "العراق", lb: "لبنان", sy: "سوريا", ps: "فلسطين", tr: "تركيا", ma: "المغرب", dz: "الجزائر", tn: "تونس", ly: "ليبيا", sd: "السودان" };
const COUNTRIES = ["الأردن", "السعودية", "الإمارات", "قطر", "الكويت", "البحرين", "عمان", "العراق", "اليمن", "مصر", "لبنان",
  "سوريا", "فلسطين", "تركيا", "المغرب", "الجزائر", "تونس", "ليبيا", "السودان", "بريطانيا", "فرنسا", "ألمانيا", "روسيا", "الولايات المتحدة"];

type Disc = { url: string; kind: string; read_url: string; title: string; outlet_name: string; logo_url: string; social: { platform: string; url: string }[]; note?: string };

const STATUS: Record<Src["status"], [string, string]> = { ok: ["p-ok", "يعمل"], error: ["p-bad", "خطأ"], paused: ["p-n", "متوقف"], new: ["p-warn", "بانتظار أول فحص"] };
const PLATFORM: Record<string, string> = { facebook: "فيسبوك", instagram: "إنستغرام", x: "X", tiktok: "تيك توك", telegram: "تيليغرام", youtube: "يوتيوب" };
const ago = (iso: string | null) => {
  if (!iso) return "—";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "الآن" : m < 60 ? `قبل ${m} د` : m < 1440 ? `قبل ${Math.round(m / 60)} س` : `قبل ${Math.round(m / 1440)} يوم`;
};

export function Sources() {
  const can = useCan();
  const manage = can("sources.manage");
  const [outlets, setOutlets] = useState<Outlet[]>([]);
  const [filter, setFilter] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err" | "warn"; text: string } | null>(null);
  const load = useCallback(() => api<Outlet[]>("/api/outlets").then(setOutlets).catch((e) => setMsg({ kind: "err", text: e.message })), []);
  useEffect(() => { load(); }, [load]);
  // ما دام مصدر يُفحص: تحديث كل 4 ثوانٍ فتظهر المواد والحالة تباعًا
  const anyChecking = outlets.some((o) => o.sources.some((s) => s.checking));
  useEffect(() => {
    if (!anyChecking) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [anyChecking, load]);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); await load(); setMsg({ kind: "ok", text: ok }); } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const all = outlets.flatMap((o) => o.sources);
  const shown = outlets.filter((o) => !filter || o.name.includes(filter) || o.tags.some((t) => t.includes(filter)) || o.sources.some((s) => s.url.includes(filter)));

  return (
    <div className="cols">
      <div className="grow">
        {manage && <PasteLink onAdded={(t) => { load(); setMsg({ kind: "ok", text: t }); }} />}
        {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}
        <section className="card">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
            <h2 style={{ flex: 1 }}>الجهات ومصادرها ({outlets.length} جهة · {all.length} مصدر)</h2>
            <input className="inp" style={{ width: 220, height: 36 }} placeholder="تصفية بالاسم أو الوسم" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="تصفية" />
          </div>
          {!outlets.length && <span className="mu">لا توجد مصادر بعد. الصق رابطًا أعلاه، أو أضف القائمة المقترحة.</span>}
          {shown.map((o) => (
            <details key={o.id} className="row" style={{ display: "block" }}>
              <summary style={{ cursor: "pointer", display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <b>{o.name}</b>
                {o.country ? <span className="mu">{o.country}</span> : <span className="pill p-warn" title="يُفترض توقيت الأردن لوقت النشر">البلد غير محدد</span>}
                {o.tags.map((t) => <span key={t} className="pill p-n">{t}</span>)}
                <span className="mu">· {o.items} مادة</span>
                {o.sources.map((s) => <span key={s.id} className={`pill ${STATUS[s.status][0]}`} title={s.kind_ar}>{s.kind_ar}</span>)}
              </summary>
              {manage && (
                <label className="fld" style={{ maxWidth: 360, marginTop: 8 }}>بلد الموقع: يُقرأ وقت النشر الظاهر في صفحاته بتوقيته
                  <select className="inp" aria-label={`بلد ${o.name}`} value={o.country || ""} onChange={(e) => run(() => api(`/api/outlets/${o.id}`, { method: "PUT", body: { name: o.name, kind: o.kind, country: e.target.value, website: o.website, tags: o.tags } }), `حُفظ بلد «${o.name}»: ${e.target.value || "غير محدد"}.`)}>
                    <option value="">غير محدد (يُفترض توقيت الأردن)</option>
                    {COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
                    <option value="دولي">دولي</option>
                  </select>
                </label>
              )}
              <div className="tw" style={{ marginTop: 8 }}>
                <table>
                  <thead><tr><th>المصدر</th><th>الحالة</th><th>آخر فحص</th><th>آخر مادة</th><th>التواتر</th>{manage && <th></th>}</tr></thead>
                  <tbody>{o.sources.map((s) => (
                    <tr key={s.id}>
                      <td>{s.kind_ar}<br /><a href={s.url} target="_blank" rel="noreferrer noopener" dir="ltr" className="mu">{s.url.length > 60 ? s.url.slice(0, 60) + "…" : s.url}</a></td>
                      <td>{s.checking ? <span className="pill p-warn">جارٍ الفحص…</span> : <span className={`pill ${STATUS[s.status][0]}`}>{STATUS[s.status][1]}</span>}
                        {s.silent && <><br /><span className="pill p-warn">لا مواد جديدة منذ مدة</span></>}
                        {s.last_error && <><br /><span className="mu" style={{ color: "var(--bad)" }}>{s.last_error}</span></>}</td>
                      <td>{ago(s.last_checked_at)}</td>
                      <td>{ago(s.last_item_at)}</td>
                      <td>{manage ? (
                        <select className="inp" style={{ height: 30, width: 110 }} value={s.check_minutes} aria-label="تواتر الفحص"
                          onChange={(e) => run(() => api(`/api/sources/${s.id}`, { method: "PUT", body: { check_minutes: Number(e.target.value) } }), "حُفظ التواتر.")}>
                          {[5, 15, 30, 60, 180, 720, 1440].map((m) => <option key={m} value={m}>{m < 60 ? `${m} دقيقة` : `${m / 60} ساعة`}</option>)}
                        </select>) : `${s.check_minutes} د`}</td>
                      {manage && <td style={{ whiteSpace: "nowrap" }}>
                        <button className="btn sm" disabled={s.checking} onClick={() => run(async () => {
                          const r = await api<{ already?: boolean }>(`/api/sources/${s.id}/check`, { method: "POST" });
                          return r;
                        }, "بدأ الفحص. قد يستغرق فحص موقع كامل بضع دقائق، وتظهر المواد هنا وفي الرصد المباشر تباعًا.")}>{s.checking ? "يُفحص…" : "افحص الآن"}</button>{" "}
                        {s.active ? <button className="btn sm" onClick={() => run(() => api(`/api/sources/${s.id}`, { method: "DELETE" }), "أُوقف رصد المصدر؛ المواد المرصودة باقية.")}>إيقاف</button>
                          : <button className="btn sm" onClick={() => run(() => api(`/api/sources/${s.id}`, { method: "PUT", body: { active: true } }), "استؤنف الرصد.")}>استئناف</button>}
                      </td>}
                    </tr>))}
                  </tbody>
                </table>
              </div>
            </details>
          ))}
        </section>
      </div>
      <div className="side">
        <section className="card">
          <h2>حالة الرصد</h2>
          {(["ok", "error", "new", "paused"] as const).map((k) => (
            <div key={k} className="row"><span className="f">{STATUS[k][1]}</span><span className={`pill ${STATUS[k][0]}`}>{all.filter((s) => s.status === k).length}</span></div>
          ))}
        </section>
        {manage && <ImportExport onDone={(t) => { load(); setMsg({ kind: "ok", text: t }); }} />}
      </div>
    </div>
  );
}

function PasteLink({ onAdded }: { onAdded: (t: string) => void }) {
  const [url, setUrl] = useState("");
  const [d, setD] = useState<Disc | null>(null);
  const [name, setName] = useState("");
  const [country, setCountry] = useState("الأردن");
  const [tags, setTags] = useState("");
  const [also, setAlso] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const check = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setD(null); setBusy(true);
    try {
      const x = await api<Disc>("/api/sources/discover", { method: "POST", body: { url } });
      setD(x); setName(x.outlet_name); setCountry(COUNTRY_BY_TLD[new URL(x.url).hostname.split(".").pop() ?? ""] ?? "الأردن"); setAlso(x.social.filter((s) => s.platform === "telegram" || s.platform === "youtube").map((s) => s.url));
    } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  };
  const add = async () => {
    if (!d) return;
    setErr(""); setBusy(true);
    try {
      const r = await api<{ also: unknown[]; skipped?: { url: string; reason: string }[] }>("/api/sources", { method: "POST", body: { url: d.url, outlet_name: name, country, tags: tags.split(/[،,]/).map((t) => t.trim()).filter(Boolean), also } });
      setD(null); setUrl(""); setTags("");
      onAdded(`أُضيف المصدر${r.also.length ? ` و${r.also.length} من صفحاته` : ""}، وبدأ رصده الآن.` +
        (r.skipped?.length ? ` لم تُضف ${r.skipped.length} صفحة: ${r.skipped.map((x) => `${x.url} (${x.reason})`).join("، ")}` : ""));
    } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  };
  return (
    <section className="card">
      <h2>الصق الرابط</h2>
      <form onSubmit={check} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="inp" style={{ flex: "1 1 320px" }} dir="ltr" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="رابط المصدر"
          placeholder="الصق هنا رابط موقع إخباري أو قناة تيليغرام أو يوتيوب" />
        <button className="btn pri" disabled={!url.trim() || busy}>{busy && !d ? "جارٍ الفحص…" : "افحص الرابط"}</button>
      </form>
      {err && <div className="msg err">{err}</div>}
      {d && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="row">
            {d.logo_url && <img src={d.logo_url} alt="" width={40} height={40} style={{ borderRadius: 8, objectFit: "contain", background: "#fff" }} />}
            <span className="f"><b>{d.title}</b><br /><span className="mu">طريقة القراءة: {d.kind === "rss" ? "خلاصة RSS" : d.kind === "sitemap" ? "خريطة الموقع" : d.kind === "page" ? "الصفحة العامة" : d.kind}</span></span>
          </div>
          {d.note && <div className="msg warn">{d.note}</div>}
          <label className="fld">اسم الجهة<input className="inp" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="fld">بلد الموقع (لقراءة وقت النشر بتوقيته)
            <select className="inp" aria-label="بلد الموقع" value={country} onChange={(e) => setCountry(e.target.value)}>
              {COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
              <option value="دولي">دولي أو غير محدد (يُفترض توقيت الأردن)</option>
            </select>
          </label>
          <label className="fld">وسوم (مفصولة بفاصلة)<input className="inp" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="محلي، رسمي" /></label>
          {!!d.social.length && (
            <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
              <legend className="mu">صفحات الجهة المكتشفة: أضفها للجهة نفسها</legend>
              <div className="tabs">{d.social.map((s) => (
                <label key={s.url} className="chk"><input type="checkbox" checked={also.includes(s.url)} onChange={(e) => setAlso(e.target.checked ? [...also, s.url] : also.filter((x) => x !== s.url))} />
                  {PLATFORM[s.platform] ?? s.platform} <bdi className="mu" dir="ltr">{s.url.replace(/^https:\/\/[^/]+/, "")}</bdi>{["facebook", "instagram", "x", "tiktok"].includes(s.platform) && <span className="mu"> (تنتظر المزوّد)</span>}</label>
              ))}</div>
            </fieldset>
          )}
          <div><button className="btn pri" disabled={busy} onClick={add}>إضافة وبدء الرصد</button></div>
        </div>
      )}
    </section>
  );
}

function ImportExport({ onDone }: { onDone: (t: string) => void }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async (fn: () => Promise<{ added: number; skipped: number; errors: unknown[] }>) => {
    setErr(""); setBusy(true);
    try { const r = await fn(); onDone(`أُضيف ${r.added}، وتُخطّي ${r.skipped} موجود${r.errors.length ? `، و${r.errors.length} لم يُضف` : ""}.`); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <section className="card">
      <h2>استيراد وتصدير</h2>
      <button className="btn" disabled={busy} onClick={() => go(() => api("/api/sources/seed", { method: "POST" }))}>إضافة القائمة المقترحة (50 مصدرًا)</button>
      <span className="mu">أردنية وعربية ودولية ومنصات تحقق وGDELT. تعدّلها أو توقف ما لا تريده.</span>
      <label className="btn" style={{ cursor: "pointer" }}>استيراد ملف CSV
        <input type="file" accept=".csv,text/csv" className="sr" onChange={async (e) => {
          const f = e.target.files?.[0]; if (!f) return;
          const text = await f.text();
          go(() => api("/api/sources/import", { method: "POST", body: { csv: text, discover: false } }));
        }} />
      </label>
      <a className="btn" href="/api/sources/export">تصدير القائمة CSV</a>
      <span className="mu">أعمدة CSV: outlet، url، kind، tags (الوسوم مفصولة بـ |).</span>
      {err && <div className="msg err">{err}</div>}
    </section>
  );
}
