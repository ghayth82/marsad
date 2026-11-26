// الشاشة 7: مختبر الصور والفيديو.
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { Checks, fileUrl, fmt, gradePill, gradeText, mmss, type Media, type Recent, UploadForm, Verdict } from "./common";

export function MediaLab() {
  const { id } = useParams();
  const nav = useNavigate();
  const [m, setM] = useState<Media | null>(null);
  const [recent, setRecent] = useState<Recent[]>([]);
  const [heat, setHeat] = useState(false);
  useEffect(() => { api<Recent[]>("/api/labs/media").then((r) => setRecent(r.filter((x) => x.kind !== "audio"))).catch(() => {}); }, [m?.id]);
  useEffect(() => { if (id) api<Media>(`/api/labs/media/${id}`).then(setM).catch(() => setM(null)); else setM(null); }, [id]);
  const check = (k: string) => m?.checks.find((c) => c.check === k);
  const ela = check("ela"), kf = check("keyframes"), arch = check("archive"), ocr = check("ocr"), exif = check("exif");

  return (
    <div className="cols">
      <div className="grow">
        {!m && <UploadForm accept="image/*,video/*" label="افحص صورة أو فيديو" sample onDone={(x) => nav(`/media-lab/${x.id}`)} />}
        {m && (
          <>
            <section className="card">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <h2 style={{ flex: 1 }}>{m.filename || (m.kind === "video" ? "فيديو" : "صورة")}</h2>
                <button className="btn sm" onClick={() => nav("/media-lab")}>ملف جديد</button>
              </div>
              {m.kind === "image" && (
                <div style={{ position: "relative" }}>
                  <img src={heat && ela?.result.heatmap ? fileUrl(ela.result.heatmap) : fileUrl(m.sha256)} alt="معاينة الملف"
                       style={{ maxWidth: "100%", maxHeight: 420, borderRadius: 8, display: "block" }} />
                </div>
              )}
              {m.kind === "video" && <video src={fileUrl(m.sha256)} controls style={{ maxWidth: "100%", maxHeight: 420 }} />}
              <p className="mu" style={{ fontSize: 12 }}>
                {m.kind === "video" ? `${mmss(m.duration)} · ` : ""}{m.width}×{m.height} · البصمة: <span dir="ltr">{m.sha256.slice(0, 4)}…{m.sha256.slice(-3)}</span> · أُرشف {fmt(m.seen_at)}
                {m.url ? <> · المصدر: <a href={m.url} target="_blank" rel="noreferrer noopener">رابط</a></> : " · رفع يدوي"}
              </p>
              {ela?.result.heatmap && <label style={{ fontSize: 13 }}><input type="checkbox" checked={heat} onChange={(e) => setHeat(e.target.checked)} /> اعرض خريطة تحليل الضغط</label>}
            </section>
            {(kf?.result.frames?.length ?? 0) > 0 && (
              <section className="card">
                <h2>اللقطات المفتاحية</h2>
                <span className="mu" style={{ fontSize: 12 }}>تُطابق كل لقطة مع الأرشيف بالبصمة الإدراكية.</span>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {kf!.result.frames.map((f: { id: number; t: number }) => <span key={f.id} className="pill p-n">{mmss(f.t)}</span>)}
                </div>
              </section>
            )}
            <Checks m={m} />
            {(arch?.result.matches?.length ?? 0) > 0 && (
              <section className="card">
                <h2>النسخ في الأرشيف</h2>
                {arch!.result.matches.map((x: { media_id: number; seen_at: string; distance: number; url: string; exact: boolean }) => (
                  <div key={x.media_id} className="row">
                    <span className="f">رُصدت {fmt(x.seen_at)} · {x.exact ? "مطابقة تامة" : `فرق البصمة ${x.distance}/64`}</span>
                    <button className="btn sm" onClick={() => nav(`/media-lab/${x.media_id}`)}>افتح</button>
                  </div>
                ))}
              </section>
            )}
            {(ocr?.result.text || Object.keys(exif?.result.tags ?? {}).length > 0) && (
              <section className="card">
                {ocr?.result.text && <><h2>النص في الصورة</h2><p style={{ whiteSpace: "pre-wrap" }}>{ocr.result.text}</p></>}
                {Object.keys(exif?.result.tags ?? {}).length > 0 && (
                  <><h2>البيانات الوصفية</h2>{Object.entries(exif!.result.tags).map(([k, v]) => <div key={k} className="row"><span className="f mu" dir="ltr">{k}</span><span dir="ltr">{String(v)}</span></div>)}</>
                )}
              </section>
            )}
          </>
        )}
      </div>
      <div className="side">
        {m && <Verdict m={m} />}
        {m && (
          <section className="card">
            <h2>بحث عكسي خارجي</h2>
            {m.reverse_links.length ? m.reverse_links.map((l) => <a key={l.name} className="btn sm" href={l.url} target="_blank" rel="noreferrer noopener">{l.name}</a>)
              : <span className="mu">للملفات المرفوعة: نزّلها وارفعها يدويًا في محرك البحث العكسي، فلا يُرسل البرنامج ملفاتك لأي جهة.</span>}
            <a className="btn sm" href="https://deepmind.google/technologies/synthid/" target="_blank" rel="noreferrer noopener">فحص SynthID (خارجي)</a>
          </section>
        )}
        <SunCard />
        <section className="card">
          <h2>آخر الفحوص</h2>
          {!recent.length && <span className="mu">لا فحوص بعد. ارفع ملفًا، أو اضغط «جرّب بمثال» لترى كيف تظهر النتائج.</span>}
          {recent.map((r) => (
            <div key={r.id} className="row">
              <span className="f">{r.filename || r.kind}<br /><span className="mu">{fmt(r.seen_at)}</span></span>
              <span className={`pill ${gradePill(r.grade)}`}>{gradeText(r.grade)}</span>
              <button className="btn sm" onClick={() => nav(`/media-lab/${r.id}`)}>افتح</button>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

type Sun = { sun: { elevation: number; azimuth: number; shadow_azimuth: number; shadow_per_meter: number | null; daylight: boolean }; notes: string[]; consistent: boolean };

function SunCard() {
  const [f, setF] = useState({ lat: "31.95", lon: "35.93", when: "", az: "", ratio: "" });
  const [r, setR] = useState<Sun | null>(null);
  const [err, setErr] = useState("");
  const go = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try {
      setR(await api<Sun>("/api/labs/sun", { method: "POST", body: { lat: Number(f.lat), lon: Number(f.lon), when: new Date(f.when).toISOString(),
        shadow_azimuth: f.az ? Number(f.az) : null, shadow_ratio: f.ratio ? Number(f.ratio) : null } }));
    } catch (x) { setErr((x as Error).message); }
  };
  return (
    <form className="card" onSubmit={go} style={{ display: "flex", flexDirection: "column", gap: 6 }} aria-label="حاسبة الشمس">
      <h2>الشمس والظل</h2>
      <span className="mu">أين يجب أن يقع الظل في هذا المكان والوقت؟ قارن النتيجة بالظل الظاهر في الصورة.</span>
      <div style={{ display: "flex", gap: 6 }}>
        <label className="fld" style={{ flex: 1 }} data-hint="خط العرض للمكان. انسخه من خرائط Google: اضغط المكان بالزر الأيمن فيظهر رقمان، الأول خط العرض. المثال: عمّان.">خط العرض
          <input className="inp" dir="ltr" value={f.lat} onChange={(e) => setF({ ...f, lat: e.target.value })} aria-label="خط العرض" placeholder="31.95" /></label>
        <label className="fld" style={{ flex: 1 }} data-hint="خط الطول للمكان: الرقم الثاني في خرائط Google. المثال: عمّان.">خط الطول
          <input className="inp" dir="ltr" value={f.lon} onChange={(e) => setF({ ...f, lon: e.target.value })} aria-label="خط الطول" placeholder="35.93" /></label>
      </div>
      <label className="fld" data-hint="اليوم والساعة التي يُقال إن الصورة التُقطت فيها.">وقت الصورة المدّعى
        <input className="inp" type="datetime-local" value={f.when} onChange={(e) => setF({ ...f, when: e.target.value })} aria-label="وقت الصورة المدّعى" /></label>
      <div style={{ display: "flex", gap: 6 }}>
        <label className="fld" style={{ flex: 1 }} data-hint="اختياري. اتجاه الظل في الصورة بالدرجات من الشمال: 0 شمال، 90 شرق، 180 جنوب، 270 غرب.">اتجاه الظل في الصورة (اختياري)
          <input className="inp" value={f.az} onChange={(e) => setF({ ...f, az: e.target.value })} placeholder="مثال: 90 = شرق" aria-label="اتجاه الظل" /></label>
        <label className="fld" style={{ flex: 1 }} data-hint="اختياري. طول الظل مقسومًا على طول الشيء. ظل بطول الشخص = 1، وضعف طوله = 2.">طول الظل ÷ طول الشيء (اختياري)
          <input className="inp" value={f.ratio} onChange={(e) => setF({ ...f, ratio: e.target.value })} placeholder="مثال: 2" aria-label="نسبة الظل" /></label>
      </div>
      <button className="btn" disabled={!f.when}>احسب</button>
      {err && <div className="msg err">{err}</div>}
      {r && (
        <div role="status" style={{ fontSize: 13 }}>
          {r.sun.daylight ? <>ارتفاع الشمس {r.sun.elevation}°، الظل باتجاه {r.sun.shadow_azimuth}° وطوله {r.sun.shadow_per_meter} لكل متر.</> : "الشمس تحت الأفق في هذا الوقت."}
          {r.notes.map((n) => <div key={n} className="msg err">{n}</div>)}
          {r.consistent && (f.az || f.ratio) && <div className="msg">الظل يتفق مع الوقت المدّعى.</div>}
        </div>
      )}
    </form>
  );
}
