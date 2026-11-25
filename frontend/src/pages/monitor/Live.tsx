import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fmtPublished } from "../../lib/time";
import { useReader } from "../../components/Reader";
import { api } from "../../api";

type It = { id: number; url: string; title: string; excerpt: string; source_title: string; source_kind: string; published_at: string | null; published_date_only?: boolean; published_tz?: string; published_tz_label?: string; published_tz_assumed?: boolean;
  captured_at: string; status: "live" | "edited" | "deleted"; version: number; media: { type: string; url: string }[]; author: string };
type Status = { sources: number; ok: number; error: number; items_24h: number; edited_24h: number; deleted_24h: number; items_total: number };

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ar", { dateStyle: "short", timeStyle: "short" }) : "—");

export function Live() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [data, setData] = useState<{ total: number; engine: string; items: It[] } | null>(null);
  const [st, setSt] = useState<Status | null>(null);
  const reader = useReader();
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
            <div key={i.id} className={`row clickable${reader.id === i.id ? " on" : ""}`}
              onClick={() => reader.open(i.id)} onKeyDown={(e) => e.key === "Enter" && reader.open(i.id)} tabIndex={0} role="button" aria-pressed={reader.id === i.id}>
              <span className="f"><b>{i.title || "(دون عنوان)"}</b><br /><span className="mu">{i.source_title} · رُصد {fmt(i.captured_at)}{i.published_at ? ` · نُشر ${fmtPublished(i.published_at, i.published_date_only, i, true)}` : ""}</span></span>
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
      </div>
    </div>
  );
}
