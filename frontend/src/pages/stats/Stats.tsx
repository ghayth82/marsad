// البند 12: صفحة «الإحصاءات». كل رقم يُنقر فيفتح الادّعاءات أو المواد التي حُسب منها.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { Bars, Heatmap, Kpi, Timeline, type Drill, type Metric } from "../../components/Charts";
import { useCan } from "../../session";

type Stat = { median: number | null; mean: number | null; count: number };
type Spread = { claim_id: number; text?: string; bucket: string; verdict_at: string | null;
  points: { t: string; items: number; sources: number; ids: number[] }[];
  effect: { hours: number; before: Metric; after: Metric; drop_pct: number | null } | null };
type Data = {
  period: { start: string; end: string };
  can_team: boolean;
  verification: { claims: Metric; decided: Metric; pending: Metric; labels: ({ label: string } & Metric)[];
    time_to_verdict_hours: Stat; by_topic: ({ key: string } & Metric)[]; by_platform: ({ key: string } & Metric)[];
    returns: Metric & { top: { claim_id: number; times: number; text: string }[] } };
  spread: { claims: { claim_id: number; text: string; topic: string; platform: string; appearances: number; verdict: string | null; spread: Spread }[] };
  geography: { governorates: ({ key: string } & Metric)[]; heatmap: ({ day: number; hour: number } & Metric)[] };
  sources: { outlets: { outlet_id: number; name: string; items: Metric; edited: Metric; deleted: Metric; edited_pct: number;
    deleted_pct: number; first: Metric; delay_minutes: Stat; uncredited: Metric }[]; note: string };
  impact: { verified: Metric; not_true: Metric; publisher_corrected: Metric & { pct: number | null; items: Metric };
    spread_measured: Metric; spread_dropped: Metric & { pct: number | null }; method: string };
  team?: { people: { user_id: number; name: string; created: Metric; proposed: Metric; approved: Metric; hours_to_verdict: Stat }[];
    review_acceptance_pct: number | null; reviewed: number; engine_agreement: { pairs: number; kappa: number | null; agree_pct: number | null };
    engine_cost_usd: number; cost_per_verdict_usd: number | null; note: string };
};
type Row = { id: number; title: string; link: string; external: boolean; meta: string; at: string };

const TABS = [["verification", "التحقق"], ["spread", "الانتشار"], ["sources", "المصادر"], ["team", "الفريق"], ["impact", "الأثر"]] as const;
const hrs = (s: Stat) => (s.median == null ? "—" : `${s.median} س`);
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v}٪`);

export function Stats() {
  const can = useCan();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") || "verification";
  const days = sp.get("days") || "30";
  const start = sp.get("start") || "", end = sp.get("end") || "";
  const topic = sp.get("topic") || "", platform = sp.get("platform") || "";
  const [opts, setOpts] = useState<{ topics: string[]; platforms: string[] } | null>(null);
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState("");
  const [drill, setDrill] = useState<{ title: string; d: Drill } | null>(null);
  const qs = useMemo(() => {
    const q = new URLSearchParams();
    if (start) { q.set("start", start); if (end) q.set("end", end); } else q.set("days", days);
    if (topic) q.set("topic", topic);
    if (platform) q.set("platform", platform);
    return q.toString();
  }, [days, start, end, topic, platform]);
  useEffect(() => { api<typeof opts>("/api/stats/options").then(setOpts); }, []);
  useEffect(() => { setErr(""); api<Data>(`/api/stats?${qs}`).then(setD).catch((e) => setErr(e.message)); }, [qs]);
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); if (k === "days") { n.delete("start"); n.delete("end"); } setSp(n, { replace: true }); };
  const pick = (title: string, dd: Drill) => setDrill({ title, d: dd });
  const open = (title: string, m: Metric) => (m.n ? () => pick(title, m.drill) : undefined);
  const tabs = TABS.filter(([k]) => k !== "team" || d?.can_team);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <section className="card" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "end", gap: 10 }} aria-label="الفلاتر">
        <div className="seg" role="group" aria-label="الفترة">
          {["7", "30", "90"].map((x) => <button key={x} className={!start && days === x ? "on" : ""} onClick={() => set("days", x)}>{x} يومًا</button>)}
        </div>
        <label className="fld" style={{ width: 150 }}>من<input className="inp" type="date" value={start} onChange={(e) => set("start", e.target.value)} /></label>
        <label className="fld" style={{ width: 150 }}>إلى<input className="inp" type="date" value={end} onChange={(e) => set("end", e.target.value)} disabled={!start} /></label>
        <label className="fld" style={{ width: 150 }}>الموضوع
          <select className="inp" value={topic} onChange={(e) => set("topic", e.target.value)}>
            <option value="">كل المواضيع</option>{opts?.topics.map((t) => <option key={t}>{t}</option>)}
          </select></label>
        <label className="fld" style={{ width: 170 }}>المنصة
          <select className="inp" value={platform} onChange={(e) => set("platform", e.target.value)}>
            <option value="">كل المنصات</option>{opts?.platforms.map((t) => <option key={t}>{t}</option>)}
          </select></label>
      </section>
      <nav className="tabs" aria-label="اللوحات">
        {tabs.map(([k, ar]) => <a key={k} href={`?${new URLSearchParams({ ...Object.fromEntries(sp), tab: k })}`} className={tab === k ? "on" : ""}
          onClick={(e) => { e.preventDefault(); set("tab", k); }}>{ar}</a>)}
      </nav>
      {err && <div className="msg err">{err}</div>}
      {!d ? <span className="mu">يُحسب…</span> : (
        <>
          {tab === "verification" && <Verification d={d} pick={pick} open={open} />}
          {tab === "spread" && <SpreadTab d={d} pick={pick} />}
          {tab === "sources" && <Sources d={d} pick={pick} />}
          {tab === "team" && d.team && <Team d={d} pick={pick} />}
          {tab === "impact" && <Impact d={d} open={open} qs={qs} canExport={can("data.export")} />}
        </>
      )}
      {drill && <DrillModal title={drill.title} d={drill.d} onClose={() => setDrill(null)} />}
    </div>
  );
}

type P = { d: Data; pick: (t: string, d: Drill) => void };

function Verification({ d, pick, open }: P & { open: (t: string, m: Metric) => (() => void) | undefined }) {
  const v = d.verification;
  return (
    <>
      <div className="g4">
        <Kpi label="ادّعاء ظهر في الفترة" value={v.claims.n} onClick={open("ادّعاءات الفترة", v.claims)} />
        <Kpi label="حُسم بحكم معتمد" value={v.decided.n} sub={`${v.pending.n} بلا حكم بعد`} onClick={open("ادّعاءات محسومة", v.decided)} />
        <Kpi label="وسيط زمن التحقق" value={hrs(v.time_to_verdict_hours)}
          sub={v.time_to_verdict_hours.mean == null ? "من أول ظهور إلى اعتماد الحكم" : `المتوسط ${v.time_to_verdict_hours.mean} س · من أول ظهور إلى الاعتماد`} />
        <Kpi label="شائعة عادت" value={v.returns.n} onClick={open("شائعات عادت", v.returns)} />
      </div>
      <div className="cols">
        <section className="card grow"><h2>توزيع الأحكام</h2>
          <Bars rows={v.labels.map((x) => ({ key: x.label, n: x.n, drill: x.drill }))} onPick={pick} /></section>
        <section className="card side"><h2>حسب المنصة</h2>
          <Bars rows={v.by_platform.map((x) => ({ key: x.key, n: x.n, drill: x.drill }))} onPick={pick} /></section>
      </div>
      <div className="cols">
        <section className="card grow"><h2>حسب الموضوع</h2>
          <span className="mu">تصنيف بكلمات مفتاحية ثابتة؛ وسم الادّعاء اليدوي يسبقه.</span>
          <Bars rows={v.by_topic.map((x) => ({ key: x.key, n: x.n, drill: x.drill }))} onPick={pick} /></section>
        <section className="card side"><h2>الشائعات العائدة</h2>
          {!v.returns.top.length && <span className="mu">لم تعد شائعة في هذه الفترة.</span>}
          {v.returns.top.map((r) => <div key={r.claim_id} className="row"><Link className="f" to={`/claims/${r.claim_id}`}>{r.text}</Link><span className="pill p-warn">عادت {r.times}</span></div>)}
        </section>
      </div>
    </>
  );
}

function SpreadTab({ d, pick }: P) {
  const list = d.spread.claims;
  const [sel, setSel] = useState<number | null>(list[0]?.claim_id ?? null);
  const cur = list.find((c) => c.claim_id === sel);
  return (
    <>
      <div className="cols">
        <section className="card grow"><h2>منحنى الانتشار</h2>
          {!cur ? <span className="mu">لا ادّعاءات في هذه الفترة.</span> : (<>
            <Link to={`/claims/${cur.claim_id}`}><b>{cur.text}</b></Link>
            <Timeline points={cur.spread.points} marker={cur.spread.verdict_at} bucket={cur.spread.bucket} onPick={pick} />
            {cur.spread.effect ? (
              <div className="g4">
                <Kpi label={`مادة في ${cur.spread.effect.hours} ساعات قبل الحكم`} value={cur.spread.effect.before.n} onClick={cur.spread.effect.before.n ? () => pick("قبل الحكم", cur.spread.effect!.before.drill) : undefined} />
                <Kpi label={`مادة في ${cur.spread.effect.hours} ساعات بعده`} value={cur.spread.effect.after.n} onClick={cur.spread.effect.after.n ? () => pick("بعد الحكم", cur.spread.effect!.after.drill) : undefined} />
                <Kpi label="أثر التصحيح" value={cur.spread.effect.drop_pct == null ? "—" : cur.spread.effect.drop_pct >= 0 ? `هبط ${cur.spread.effect.drop_pct}٪` : `زاد ${-cur.spread.effect.drop_pct}٪`}
                  sub={cur.spread.effect.drop_pct == null ? "لا ظهورات قبل الحكم للمقارنة" : undefined} />
              </div>
            ) : <span className="mu">لا حكم معتمد بعد، فلا يُقاس أثر التصحيح.</span>}
          </>)}
        </section>
        <section className="card side"><h2>الأكثر انتشارًا</h2>
          {list.map((c) => (
            <button key={c.claim_id} type="button" onClick={() => setSel(c.claim_id)} className="row"
              style={{ border: "none", borderBottom: "1px solid var(--bd)", background: sel === c.claim_id ? "var(--acs)" : "none", textAlign: "start",
                fontFamily: "inherit", color: "var(--tx)", cursor: "pointer", borderRadius: 8, padding: 8 }}>
              <span className="f" style={{ fontSize: 13 }}>{c.text}<br /><span className="mu">{c.topic} · {c.platform} · {c.appearances} ظهور{c.verdict ? ` · ${c.verdict}` : ""}</span></span>
              <span style={{ width: 90 }}><Timeline points={c.spread.points} marker={c.spread.verdict_at} compact /></span>
            </button>
          ))}
        </section>
      </div>
      <div className="cols">
        <section className="card grow"><h2>ساعات الذروة في النشر</h2><Heatmap cells={d.geography.heatmap} onPick={pick} /></section>
        <section className="card side"><h2>المحافظات</h2>
          <span className="mu">مواد الفترة التي تذكر المحافظة أو مركزها.</span>
          <Bars rows={d.geography.governorates.map((x) => ({ key: x.key, n: x.n, drill: x.drill }))} onPick={pick} /></section>
      </div>
    </>
  );
}

function Num({ m, title, pick, children }: { m: Metric; title: string; pick: P["pick"]; children?: ReactNode }) {
  return m.n ? <button type="button" className="btn sm" style={{ height: 26 }} onClick={() => pick(title, m.drill)}>{children ?? m.n}</button> : <span className="mu">{children ?? 0}</span>;
}

function Sources({ d, pick }: P) {
  const rows = d.sources.outlets;
  return (
    <section className="card"><h2>المصادر</h2>
      <span className="mu">{d.sources.note} «النقل دون نسبة»: مادة في قصة نُشرت بعد الناشر الأول ولا تذكر اسمه ولا رابطه. «التأخر»: الوسيط بالدقائق عن الناشر الأول.</span>
      {!rows.length ? <span className="mu">لا مواد في هذه الفترة.</span> : (
        <div className="tw"><table>
          <thead><tr><th>الجهة</th><th>مواد</th><th>عُدّلت</th><th>حُذفت</th><th>نشر أولًا</th><th>التأخر</th><th>نقل دون نسبة</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.outlet_id}>
              <td>{r.name}</td>
              <td><Num m={r.items} title={`مواد ${r.name}`} pick={pick} /></td>
              <td><Num m={r.edited} title={`معدّلة: ${r.name}`} pick={pick}>{r.edited.n} ({r.edited_pct}٪)</Num></td>
              <td><Num m={r.deleted} title={`محذوفة: ${r.name}`} pick={pick}>{r.deleted.n} ({r.deleted_pct}٪)</Num></td>
              <td><Num m={r.first} title={`نشر أولًا: ${r.name}`} pick={pick} /></td>
              <td>{r.delay_minutes.median == null ? "—" : `${r.delay_minutes.median} د`}</td>
              <td><Num m={r.uncredited} title={`نقل دون نسبة: ${r.name}`} pick={pick} /></td>
            </tr>))}</tbody>
        </table></div>)}
    </section>
  );
}

function Team({ d, pick }: P) {
  const t = d.team!;
  return (
    <>
      <div className="g4">
        <Kpi label="قبول المراجع الثاني" value={pct(t.review_acceptance_pct)} sub={`من ${t.reviewed} اقتراحًا رُوجع`} />
        <Kpi label="اتفاق المحركات مع الحكم النهائي" value={t.engine_agreement.kappa == null ? pct(t.engine_agreement.agree_pct) : `κ ${t.engine_agreement.kappa}`}
          sub={t.engine_agreement.kappa == null ? `${t.engine_agreement.pairs} زوج (كابا يحتاج 5 على الأقل)` : `${t.engine_agreement.agree_pct}٪ تطابق في ${t.engine_agreement.pairs} ادّعاء`} />
        <Kpi label="كلفة المحركات" value={`${t.engine_cost_usd.toFixed(2)} $`} sub={t.cost_per_verdict_usd == null ? "لا أحكام معتمدة" : `${t.cost_per_verdict_usd.toFixed(2)} $ لكل حكم معتمد`} />
      </div>
      <section className="card"><h2>حجم العمل</h2><span className="mu">{t.note}</span>
        <div className="tw"><table>
          <thead><tr><th>المستخدم</th><th>ادّعاءات سجّلها</th><th>أحكام اقترحها</th><th>أحكام اعتمدها</th><th>وسيط الزمن حتى اعتماد أحكامه</th></tr></thead>
          <tbody>{t.people.map((p) => (
            <tr key={p.user_id}><td>{p.name}</td>
              <td><Num m={p.created} title={`سجّلها ${p.name}`} pick={pick} /></td>
              <td><Num m={p.proposed} title={`اقترحها ${p.name}`} pick={pick} /></td>
              <td><Num m={p.approved} title={`اعتمدها ${p.name}`} pick={pick} /></td>
              <td>{hrs(p.hours_to_verdict)}</td></tr>))}</tbody>
        </table></div>
      </section>
    </>
  );
}

function Impact({ d, open, qs, canExport }: { d: Data; open: (t: string, m: Metric) => (() => void) | undefined; qs: string; canExport: boolean }) {
  const i = d.impact;
  return (
    <>
      <section className="card" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
        <h2 style={{ flex: 1 }}>تقرير الأثر · {d.period.start.slice(0, 10)} — {d.period.end.slice(0, 10)}</h2>
        <a className="btn sm" href={`/api/stats/impact/print?${qs}`} target="_blank" rel="noreferrer">طباعة أو PDF</a>
        {canExport && <a className="btn sm" href={`/api/stats/impact.csv?${qs}`}>تصدير CSV</a>}
      </section>
      <div className="g4">
        <Kpi label="تحقق معتمد" value={i.verified.n} onClick={open("تحققات معتمدة", i.verified)} />
        <Kpi label="صحّحه ناشره بعد التحقق" value={pct(i.publisher_corrected.pct)} sub={`${i.publisher_corrected.n} ادّعاء · ${i.publisher_corrected.items.n} مادة عُدّلت أو حُذفت`} onClick={open("صحّحه ناشره", i.publisher_corrected)} />
        <Kpi label="هبط انتشارها بعد التصحيح" value={i.spread_dropped.n} sub={`من ${i.spread_measured.n} قيس انتشارها (${pct(i.spread_dropped.pct)})`} onClick={open("هبط انتشارها", i.spread_dropped)} />
        <Kpi label="حكم غير «صحيح»" value={i.not_true.n} onClick={open("أحكام غير «صحيح»", i.not_true)} />
      </div>
      <section className="card"><h2>الطريقة</h2><span className="mu">{i.method}</span></section>
    </>
  );
}

function DrillModal({ title, d, onClose }: { title: string; d: Drill; onClose: () => void }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  useEffect(() => { api<{ rows: Row[] }>(`/api/stats/rows?kind=${d.kind}&ids=${d.ids.join(",")}`).then((r) => setRows(r.rows)); }, [d]);
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === "Escape" && onClose(); addEventListener("keydown", k); return () => removeEventListener("keydown", k); }, [onClose]);
  return (
    <div role="dialog" aria-modal="true" aria-label={title} onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40, padding: 16 }}>
      <section className="card" onClick={(e) => e.stopPropagation()} style={{ width: "min(720px,100%)", maxHeight: "80vh", overflowY: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h2 style={{ flex: 1 }}>{title} ({d.ids.length})</h2>
          <button className="btn sm" onClick={onClose}>إغلاق</button>
        </div>
        {!rows ? <span className="mu">يُحمَّل…</span> : rows.map((r) => (
          <div key={r.id} className="row">
            <span className="f">{r.external ? <a href={r.link} target="_blank" rel="noreferrer">{r.title}</a> : <Link to={r.link} onClick={onClose}>{r.title}</Link>}
              <br /><span className="mu">{r.meta} · {new Date(r.at).toLocaleString("ar")}</span></span>
          </div>
        ))}
      </section>
    </div>
  );
}
