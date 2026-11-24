import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fmtPublished } from "../../lib/time";
import { api } from "../../api";

type It = { id: number; url: string; title: string; excerpt: string; source_title: string; source_kind: string; published_at: string | null; published_date_only?: boolean;
  captured_at: string; status: "live" | "edited" | "deleted"; version: number; media: { type: string; url: string }[]; author: string };
type Full = It & { text: string; versions: { version: number; change: string; title: string; captured_at: string; archived: boolean; archive_sha256: string }[];
  diffs: { from: number; to: number; title_changed: boolean; title_before: string; title_after: string; text: { op: string; before: string; after: string }[] }[] };
type Status = { sources: number; ok: number; error: number; items_24h: number; edited_24h: number; deleted_24h: number; items_total: number };

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ar", { dateStyle: "short", timeStyle: "short" }) : "—");
const CH: Record<string, string> = { new: "رُصد", edit: "عُدّل", delete: "حُذف", restore: "عاد" };

export function Live() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [data, setData] = useState<{ total: number; engine: string; items: It[] } | null>(null);
  const [st, setSt] = useState<Status | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [ms, setMs] = useState(0);
  const load = useCallback(async () => {
    const t0 = performance.now();
    const p = new URLSearchParams({ limit: "60" });
    if (params.get("q")) p.set("q", params.get("q")!);
    if (params.get("status")) p.set("status", params.get("status")!);
    setData(await api(`/api/items?${p}`));
    setMs(Math.round(performance.now() - t0));
    api<Status>("/api/monitor/status").then(setSt).catch(() => {});
  }, [params]);
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); }, [load]);

  return (
    <div className="cols">
      <div className="grow">
        <form className="card" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center" }}
          onSubmit={(e) => { e.preventDefault(); const p = new URLSearchParams(); if (q) p.set("q", q); if (status) p.set("status", status); setParams(p); }}>
          <input className="inp" style={{ flex: "1 1 280px" }} type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="ابحث في كل ما رُصد (كل أشكال الكلمة)" aria-label="بحث في المواد" />
          <select className="inp" style={{ width: 150 }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="الحالة">
            <option value="">كل المواد</option><option value="edited">عُدّلت بعد النشر</option><option value="deleted">حُذفت</option>
          </select>
          <button className="btn pri">بحث</button>
          {data && <span className="mu">{data.total} مادة · {ms} مللي ثانية</span>}
        </form>
        <section className="card">
          <h2>تدفّق المواد</h2>
          {data && !data.items.length && <span className="mu">لا مواد بعد. أضف مصادر من شاشة المصادر.</span>}
          {data?.items.map((i) => (
            <div key={i.id} className="row" style={{ cursor: "pointer", background: sel === i.id ? "var(--acs)" : undefined, borderRadius: 8, padding: "8px 6px" }}
              onClick={() => setSel(i.id)} onKeyDown={(e) => e.key === "Enter" && setSel(i.id)} tabIndex={0} role="button" aria-pressed={sel === i.id}>
              <span className="f"><b>{i.title || "(دون عنوان)"}</b><br /><span className="mu">{i.source_title} · رُصد {fmt(i.captured_at)}{i.published_at ? ` · نُشر ${fmtPublished(i.published_at, i.published_date_only)}` : ""}</span></span>
              {i.status === "edited" && <span className="pill p-warn">عُدّل ({i.version - 1})</span>}
              {i.status === "deleted" && <span className="pill p-bad">محذوف</span>}
              {i.media.some((m) => m.type === "video") && <span className="pill p-n">فيديو</span>}
            </div>
          ))}
        </section>
      </div>
      <div className="side" style={{ maxWidth: 520 }}>
        {st && (
          <section className="card">
            <h2>آخر 24 ساعة</h2>
            <div className="row"><span className="f">مواد جديدة</span><b>{st.items_24h}</b></div>
            <div className="row"><span className="f">عُدّلت</span><b>{st.edited_24h}</b></div>
            <div className="row"><span className="f">حُذفت</span><b>{st.deleted_24h}</b></div>
            <div className="row"><span className="f">مصادر تعمل</span><span className={`pill ${st.error ? "p-bad" : "p-ok"}`}>{st.ok} من {st.sources}{st.error ? ` · ${st.error} بخطأ` : ""}</span></div>
          </section>
        )}
        {sel && <Preview id={sel} />}
      </div>
    </div>
  );
}

function Preview({ id }: { id: number }) {
  const [it, setIt] = useState<Full | null>(null);
  useEffect(() => { setIt(null); api<Full>(`/api/items/${id}`).then(setIt); }, [id]);
  if (!it) return null;
  return (
    <section className="card">
      <h2>{it.title}</h2>
      <span className="mu">{it.source_title}{it.author ? ` · ${it.author}` : ""} · <a href={it.url} target="_blank" rel="noreferrer noopener">الرابط الأصلي</a></span>
      {it.status === "deleted" && <div className="msg err">حُذفت هذه المادة من موقعها. ما تراه هو آخر نسخة رصدناها.</div>}
      {it.diffs.map((d) => (
        <div key={d.to} className="msg warn" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <b>تعديل بين النسختين {d.from} و{d.to}</b>
          {d.title_changed && <span>العنوان: <del>{d.title_before}</del> ← <ins>{d.title_after}</ins></span>}
          {d.text.map((x, k) => <span key={k}>{x.before && <del>{x.before}</del>}{x.before && x.after && " ← "}{x.after && <ins>{x.after}</ins>}</span>)}
        </div>
      ))}
      <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.9, fontSize: 14, maxHeight: 360, overflowY: "auto" }}>{it.text || "لا نص."}</div>
      <h3>النسخ</h3>
      {it.versions.map((v) => (
        <div key={v.version} className="row">
          <span className="f">{v.version}. {CH[v.change] ?? v.change} · {fmt(v.captured_at)}</span>
          {v.archived && <a className="btn sm" href={`/api/items/${it.id}/archive/${v.version}`} target="_blank" rel="noreferrer" title={`SHA-256: ${v.archive_sha256}`}>النسخة المؤرشفة</a>}
        </div>
      ))}
    </section>
  );
}
