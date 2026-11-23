import { useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";
import { Rumors, STATUS, labelPill, type ClaimRow } from "./Rumors";

type V = { id: number; label: string; evidence_grade: string; explanation: string; status: string; author_id: number; approved_at: string | null; created_at: string };
type Node = { item_id: number; parent_item_id: number | null; title: string; outlet: string; url: string; time: string; kind: string; source_kind: string };
type Ev = { id: number; kind: string; title: string; url: string; sha256: string; grade: string; note: string; is_conclusive: boolean; added_at: string };
type Full = ClaimRow & { speaker: string; first_item: { id: number; title: string; url: string; outlet: string } | null;
  official_item: { id: number; title: string; url: string } | null; official_suggestions: { item_id: number; title: string; outlet: string; denial: boolean; url: string }[];
  spread: { nodes: Node[]; coordination: { start: string; outlets: string[]; note: string }[] }; evidence: Ev[]; history: V[]; claimreview: object | null };

const LABELS = ["صحيح", "صحيح جزئيًا", "مضلل", "مفبرك", "غير مؤكد"];
const GRADES = ["قاطع", "مؤشر قوي", "لا يكفي"];
const fmt = (iso: string) => new Date(iso).toLocaleString("ar", { dateStyle: "short", timeStyle: "short" });

export function Claims() {
  return (
    <Routes>
      <Route index element={<Rumors />} />
      <Route path=":id" element={<Card />} />
    </Routes>
  );
}

function Card() {
  const { id } = useParams();
  const can = useCan();
  const nav = useNavigate();
  const [c, setC] = useState<Full | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [ev, setEv] = useState({ kind: "link", title: "", url: "", grade: "", note: "", is_conclusive: false });
  const [vf, setVf] = useState({ label: "", evidence_grade: "", explanation: "" });
  const load = () => api<Full>(`/api/claims/${id}`).then(setC);
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); await load(); setMsg({ kind: "ok", text: ok }); } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  if (!c) return null;
  const cur = c.history.at(-1);
  const pending = cur?.status === "proposed";

  return (
    <div className="cols">
      <div className="grow">
        <section className="card">
          <span className="mu">الشائعات › ادّعاء #{c.id}</span>
          <h2 style={{ fontSize: 18 }}>«{c.text}»</h2>
          <div className="tabs">
            <span className={`pill ${STATUS[c.status]?.[0]}`}>{STATUS[c.status]?.[1]}</span>
            {c.verdict && <span className={`pill ${labelPill(c.verdict.label)}`}>{c.verdict.label} · {c.verdict.evidence_grade}{c.verdict.status === "proposed" ? " (مقترح)" : ""}</span>}
            <span className="pill p-n">{c.appearances} ظهور</span>{c.returns > 0 && <span className="pill p-bad">عاد {c.returns} مرة</span>}
          </div>
          {c.first_item && <span className="mu">أول ظهور: <a href={c.first_item.url} target="_blank" rel="noreferrer noopener">{c.first_item.outlet}</a>{c.first_seen_at && ` · ${fmt(c.first_seen_at)}`}</span>}
          {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}
        </section>

        <section className="card">
          <h2>شجرة الانتشار</h2>
          {c.spread.coordination.map((x, k) => <div key={k} className="msg warn">مؤشر تنسيق: {x.note} ({x.outlets.join("، ")}). مؤشر لا حكم.</div>)}
          {!c.spread.nodes.length && <span className="mu">لا ظهورات مرصودة بعد.</span>}
          {c.spread.nodes.map((n) => {
            const depth = depthOf(c.spread.nodes, n);
            return (
              <div key={n.item_id} className="row" style={{ paddingInlineStart: depth * 22 }}>
                <span className="f">{depth > 0 && "↳ "}<b>{n.outlet}</b> · {fmt(n.time)}<br /><a href={n.url} target="_blank" rel="noreferrer noopener" className="mu">{n.title}</a></span>
                {n.kind === "first" && <span className="pill p-ok">الأصل</span>}{n.kind === "return" && <span className="pill p-bad">عودة</span>}
              </div>
            );
          })}
        </section>

        <section className="card">
          <h2>الأدلة</h2>
          {c.evidence.map((e) => (
            <div key={e.id} className="row"><span className="f"><b>{e.title || e.kind}</b>{e.url && <> · <a href={e.url} target="_blank" rel="noreferrer noopener">الرابط</a></>}
              {e.note && <><br /><span className="mu">{e.note}</span></>}{e.sha256 && <><br /><span className="mu" dir="ltr">SHA-256 {e.sha256.slice(0, 16)}…</span></>}</span>
              {e.grade && <span className={`pill ${e.grade === "قاطع" ? "p-ok" : "p-n"}`}>{e.grade}</span>}</div>
          ))}
          {can("claims.create") && (
            <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={(x) => { x.preventDefault(); run(() => api(`/api/claims/${c.id}/evidence`, { method: "POST", body: ev }), "أُضيف الدليل.").then(() => setEv({ ...ev, title: "", url: "", note: "" })); }}>
              <div className="g4" style={{ gridTemplateColumns: "140px 1fr" }}>
                <select className="inp" value={ev.kind} onChange={(x) => setEv({ ...ev, kind: x.target.value })} aria-label="نوع الدليل">
                  <option value="link">رابط</option><option value="check">نتيجة فحص</option><option value="official">بيان رسمي</option>
                </select>
                <input className="inp" value={ev.title} onChange={(x) => setEv({ ...ev, title: x.target.value })} placeholder="ما الذي يثبته الدليل" aria-label="عنوان الدليل" />
              </div>
              <input className="inp" dir="ltr" value={ev.url} onChange={(x) => setEv({ ...ev, url: x.target.value })} placeholder="https://…" aria-label="رابط الدليل" />
              <div className="tabs">
                <select className="inp" style={{ width: 160 }} value={ev.grade} onChange={(x) => setEv({ ...ev, grade: x.target.value })} aria-label="درجة الدليل">
                  <option value="">درجة الدليل…</option>{GRADES.map((g) => <option key={g}>{g}</option>)}
                </select>
                <label className="chk"><input type="checkbox" checked={ev.is_conclusive} disabled={ev.kind === "link" || ev.kind === "official"} onChange={(x) => setEv({ ...ev, is_conclusive: x.target.checked })} />دليل قاطع (نتيجة فحص)</label>
                <button className="btn" disabled={!ev.title.trim()}>إضافة دليل</button>
              </div>
            </form>
          )}
        </section>
      </div>

      <div className="side">
        <section className="card">
          <h2>قرار الصحفي</h2>
          <span className="mu">الاقتراحات للاستئناس. الحكم لك، ويعتمده محرّر.</span>
          {can("engines.use") && can("claims.create") && (
            <button className="btn" onClick={() => run(async () => { const r = await api<{ batch_id: number }>(`/api/claims/${c.id}/engines`, { method: "POST", body: {} }); nav(`/engines/batch/${r.batch_id}`); }, "")}>اقتراح حكم بالمحركات</button>
          )}
          {can("verdicts.propose") && (
            <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={(x) => { x.preventDefault(); run(() => api(`/api/claims/${c.id}/verdict`, { method: "POST", body: vf }), "اقتُرح الحكم، وينتظر اعتماد محرّر."); }}>
              <label className="fld">الحكم<select className="inp" value={vf.label} onChange={(x) => setVf({ ...vf, label: x.target.value })}><option value="">اختر…</option>{LABELS.map((l) => <option key={l}>{l}</option>)}</select></label>
              <label className="fld">درجة الدليل<select className="inp" value={vf.evidence_grade} onChange={(x) => setVf({ ...vf, evidence_grade: x.target.value })}><option value="">اختر…</option>{GRADES.map((g) => <option key={g}>{g}</option>)}</select></label>
              <label className="fld">الشرح<textarea className="inp" rows={4} style={{ height: "auto", padding: 10 }} value={vf.explanation} onChange={(x) => setVf({ ...vf, explanation: x.target.value })} /></label>
              <button className="btn pri" disabled={!vf.label || !vf.evidence_grade}>اقتراح الحكم</button>
            </form>
          )}
          {pending && can("verdicts.approve") && (
            <div className="msg warn" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span>بانتظار الاعتماد: <b>{cur!.label}</b> ({cur!.evidence_grade}) — {cur!.explanation}</span>
              <div className="tabs">
                <button className="btn sm pri" onClick={() => run(() => api(`/api/claims/${c.id}/approve`, { method: "POST", body: { approve: true } }), "اعتُمد الحكم وسُجّل اسمك ووقته.")}>اعتماد</button>
                <button className="btn sm" onClick={() => run(() => api(`/api/claims/${c.id}/approve`, { method: "POST", body: { approve: false } }), "رُفض الحكم المقترح.")}>رفض</button>
              </div>
            </div>
          )}
        </section>
        <section className="card">
          <h2>البيان الرسمي</h2>
          {c.official_item ? <a href={c.official_item.url} target="_blank" rel="noreferrer noopener">{c.official_item.title}</a> : <span className="mu">لم يُربط بيان.</span>}
          {c.official_suggestions.map((s) => (
            <div key={s.item_id} className="row"><span className="f">{s.title}<br /><span className="mu">{s.outlet}{s.denial ? " · ينفي" : ""}</span></span>
              {can("claims.create") && <button className="btn sm" onClick={() => run(() => api(`/api/claims/${c.id}`, { method: "PUT", body: { official_item_id: s.item_id } }), "رُبط البيان.")}>ربط</button>}</div>
          ))}
        </section>
        <section className="card">
          <h2>سجل الحكم</h2>
          {c.history.map((v) => <div key={v.id} className="row"><span className="f">{v.label} · {v.evidence_grade}<br /><span className="mu">{fmt(v.created_at)}</span></span><span className="pill p-n">{v.status === "approved" ? "معتمد" : v.status === "rejected" ? "مرفوض" : "مقترح"}</span></div>)}
          {!c.history.length && <span className="mu">لا أحكام بعد.</span>}
          {c.claimreview && <details><summary className="mu">ClaimReview</summary><code className="blk">{JSON.stringify(c.claimreview, null, 1)}</code></details>}
        </section>
        <Link className="btn" to="/claims">كل الادّعاءات</Link>
      </div>
    </div>
  );
}

function depthOf(nodes: Node[], n: Node): number {
  let d = 0, cur: Node | undefined = n;
  while (cur?.parent_item_id && d < 8) { cur = nodes.find((x) => x.item_id === cur!.parent_item_id); d++; }
  return d;
}
