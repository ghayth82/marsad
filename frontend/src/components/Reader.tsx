// قارئ المادة الموحّد: لوحة جانبية تُوسَّع بالسحب، وملء الشاشة، وصفحة أو نافذة مستقلة.
// يُفتح من أي شاشة (الرصد، القصص، الكيانات) بإضافة ?item=رقم إلى العنوان، فزر الرجوع يغلقه.
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { fmtPublished, fmtTime } from "../lib/time";

type Full = {
  id: number; url: string; title: string; text: string; source_title: string; author: string; status: string;
  published_at: string | null; published_date_only?: boolean; captured_at: string; story_id: number | null;
  versions: { version: number; change: string; title: string; captured_at: string; archived: boolean; archive_sha256: string }[];
  diffs: { from: number; to: number; title_changed: boolean; title_before: string; title_after: string; text: { op: string; before: string; after: string }[] }[];
};

const CH: Record<string, string> = { new: "كما نُشر أول مرة", edit: "عدّله الموقع", delete: "حذفه الموقع", restore: "أعاده الموقع" };
const W_KEY = "marsad.reader.width";
const readW = () => { try { return Math.max(360, Number(localStorage.getItem(W_KEY)) || 560); } catch { return 560; } };

/** فتح مادة في القارئ من أي شاشة: يضيف ?item= إلى العنوان (خطوة في سجل الرجوع). */
export function useReader() {
  const [params, setParams] = useSearchParams();
  const loc = useLocation();
  const nav = useNavigate();
  const id = Number(params.get("item")) || null;
  const open = useCallback((itemId: number) => {
    const p = new URLSearchParams(params);
    p.set("item", String(itemId));
    // مادة أخرى والقارئ مفتوح: تُستبدل الخطوة، فالرجوع يعود للقائمة لا يمر بكل مادة
    setParams(p, { replace: !!id, state: { reader: true } });
  }, [params, setParams, id]);
  const close = useCallback(() => {
    if ((loc.state as { reader?: boolean } | null)?.reader) nav(-1);
    else { const p = new URLSearchParams(params); p.delete("item"); setParams(p, { replace: true }); }
  }, [loc.state, nav, params, setParams]);
  return { id, open, close };
}

/** نافذة مستقلة: في برنامج الجهاز نافذة جديدة منه، وفي المتصفح لسان جديد. */
export async function openItemWindow(id: number) {
  const url = `${location.origin}/item/${id}`;
  const tauri = (window as unknown as { __TAURI__?: { webviewWindow?: { WebviewWindow: new (label: string, o: object) => { once: (e: string, f: () => void) => void } } } }).__TAURI__;
  if (tauri?.webviewWindow) {
    try {
      const w = new tauri.webviewWindow.WebviewWindow(`item-${id}-${Date.now()}`, { url, title: "مرصد التحقق — مادة", width: 900, height: 900 });
      w.once("tauri://error", () => window.open(url, "_blank", "noopener"));
      return;
    } catch { /* يُفتح في لسان */ }
  }
  window.open(url, "_blank", "noopener");
}

export function ItemView({ id, compact }: { id: number; compact?: boolean }) {
  const [it, setIt] = useState<Full | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { setIt(null); setErr(""); api<Full>(`/api/items/${id}`).then(setIt).catch((e) => setErr(e.message)); }, [id]);
  if (err) return <div className="msg err">{err}</div>;
  if (!it) return <span className="mu">يُحمَّل…</span>;
  return (
    <article className="reader-body">
      <h2 className="reader-title">{it.title || "(دون عنوان)"}</h2>
      <span className="mu">
        {it.source_title}{it.author ? ` · ${it.author}` : ""} · رُصد {fmtTime(it.captured_at)}
        {it.published_at ? ` · نُشر ${fmtPublished(it.published_at, it.published_date_only)}` : ""} ·{" "}
        <a href={it.url} target="_blank" rel="noreferrer noopener">الرابط الأصلي</a>
      </span>
      {it.status === "deleted" && <div className="msg err">حذف الموقع هذه المادة. ما تراه آخر نسخة رصدناها قبل الحذف.</div>}
      {it.diffs.map((d) => (
        <div key={d.to} className="msg warn" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <b>عدّل الموقع الخبر بعد نشره (من النسخة {d.from} إلى {d.to})</b>
          {d.title_changed && <span>العنوان: <del>{d.title_before}</del> ← <ins>{d.title_after}</ins></span>}
          {d.text.map((x, k) => <span key={k}>{x.before && <del>{x.before}</del>}{x.before && x.after && " ← "}{x.after && <ins>{x.after}</ins>}</span>)}
        </div>
      ))}
      <div className="reader-text">{it.text || "لا نص محفوظ لهذه المادة؛ افتح الرابط الأصلي."}</div>
      <section className="reader-versions" aria-labelledby={`v-${it.id}`}>
        <h3 id={`v-${it.id}`}>تعديلات الخبر</h3>
        <span className="mu">يحفظ البرنامج الخبر كما نُشر، وكل تعديل يجريه الموقع عليه لاحقًا، فيبقى الأصل دليلًا حتى لو غُيّر أو حُذف.{!compact && " «النسخة المحفوظة» تفتح الصفحة كما كانت لحظة الرصد."}</span>
        {it.versions.map((v) => (
          <div key={v.version} className="row">
            <span className="f">النسخة {v.version}: {CH[v.change] ?? v.change} · {fmtTime(v.captured_at)}</span>
            {v.archived && <a className="btn sm" href={`/api/items/${it.id}/archive/${v.version}`} target="_blank" rel="noreferrer" title={`بصمة SHA-256: ${v.archive_sha256}`}>النسخة المحفوظة</a>}
          </div>
        ))}
      </section>
    </article>
  );
}

/** اللوحة الجانبية: تُوسَّع بسحب حافتها، وزر ملء الشاشة، ونافذة مستقلة، وEsc يغلقها. */
export function ReaderDrawer() {
  const { id, close } = useReader();
  const nav = useNavigate();
  const [w, setW] = useState(readW);
  const [full, setFull] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!id) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [id, close]);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => { scroller.current?.scrollTo({ top: 0 }); }, [id]);
  if (!id) return null;
  const drag = (e: React.PointerEvent) => {
    e.preventDefault();
    const box = ref.current!.getBoundingClientRect();
    const fromLeft = box.left < innerWidth / 2;  // اللوحة على يسار الشاشة في الواجهة العربية
    const move = (m: PointerEvent) => setW(Math.min(innerWidth - 80, Math.max(360, fromLeft ? m.clientX - box.left : box.right - m.clientX)));
    const up = () => {
      removeEventListener("pointermove", move); removeEventListener("pointerup", up);
      setW((x) => { try { localStorage.setItem(W_KEY, String(x)); } catch { /* */ } return x; });
    };
    addEventListener("pointermove", move); addEventListener("pointerup", up);
  };
  return (
    <aside ref={ref} className={`reader-drawer${full ? " full" : ""}`} style={full ? undefined : { width: w }} aria-label="قارئ المادة">
      {!full && <div className="reader-grip" onPointerDown={drag} role="separator" aria-orientation="vertical" aria-label="اسحب لتغيير عرض اللوحة" title="اسحب لتوسيع اللوحة أو تضييقها" />}
      <div className="reader-scroll" ref={scroller}>
        <div className="reader-bar">
          <button className="btn sm" onClick={() => setFull(!full)} aria-pressed={full}>{full ? "تصغير" : "ملء الشاشة"}</button>
          <button className="btn sm" onClick={() => nav(`/item/${id}`)}>صفحة مستقلة</button>
          <button className="btn sm" onClick={() => openItemWindow(id)}>نافذة مستقلة</button>
          <span style={{ flex: 1 }} />
          <button className="btn sm" onClick={close} aria-label="إغلاق (Esc)" title="إغلاق (Esc)">✕ إغلاق</button>
        </div>
        <ItemView id={id} />
      </div>
    </aside>
  );
}

/** صفحة مستقلة للمادة (للقراءة الطويلة، أو في نافذة ثانية للمقارنة). */
export function ItemPage() {
  const { id } = useParams();
  return (
    <section className="card reader-page">
      <div className="reader-bar">
        <button className="btn sm" onClick={() => openItemWindow(Number(id))}>نافذة مستقلة</button>
      </div>
      <ItemView id={Number(id)} />
    </section>
  );
}
