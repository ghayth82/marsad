import { useEffect, useState } from "react";
import { api } from "../../api";
import type { Batch, EngineT, Item, Output, Run } from "./types";
import { money, pct } from "./types";

const LABELS = ["صحيح", "صحيح جزئيًا", "مضلل", "مفبرك", "غير مؤكد"];
const EVIDENCE = ["قاطع", "مؤشر قوي", "لا يكفي"];
const pillFor = (label?: string) =>
  label === "صحيح" ? "p-ok" : label === "مضلل" || label === "مفبرك" ? "p-bad" : label === "صحيح جزئيًا" ? "p-warn" : "p-n";
const STATUS: Record<Run["status"], string> = { ok: "", error: "تعطّل", invalid: "مخرج غير صالح", limit: "بلغ حد الإنفاق" };

function OutputView({ task, out }: { task: string; out: Output }) {
  if (task === "classify_verdict")
    return (
      <>
        <div className="tabs"><span className={`pill ${pillFor(out.label)}`}>{out.label}</span><span className="pill p-n">الدليل: {out.evidence}</span></div>
        <span style={{ fontSize: 13, lineHeight: 1.8 }}>{out.reasoning}</span>
        {!!out.items?.length && <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 12.5 }}>{out.items.map((i, k) => <li key={k}>{i.type}: {i.value}</li>)}</ul>}
      </>
    );
  if (task === "extract_claims")
    return <ol style={{ margin: 0, paddingInlineStart: 18, fontSize: 13, lineHeight: 1.8 }}>{out.claims?.map((c, k) => <li key={k}>{c.text}{c.speaker && <span className="mu"> — {c.speaker}</span>}</li>)}</ol>;
  return (
    <>
      <span style={{ fontSize: 13, lineHeight: 1.8 }}>{out.summary}</span>
      {!!out.points?.length && <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 12.5 }}>{out.points.map((p, k) => <li key={k}>{p}</li>)}</ul>}
    </>
  );
}

export function BatchView({ id, engines }: { id: number; engines: EngineT[] }) {
  const [b, setB] = useState<Batch | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const x = await api<Batch>(`/api/engines/batches/${id}`);
        if (stop) return;
        setB(x);
        if (x.status !== "done") setTimeout(tick, 1500);
      } catch (e) { setErr((e as Error).message); }
    };
    tick();
    return () => { stop = true; };
  }, [id]);

  if (err) return <div className="msg err">{err}</div>;
  if (!b) return null;
  const cmp = b.comparison;
  const running = b.status !== "done";

  return (
    <div className="cols">
      <div className="grow">
        <section className="card">
          <h2>{b.task_name} <span className="mu">· {b.mode === "multi" ? "عدة محركات" : "محرك واحد"} · {money(b.total_cost_usd)}</span></h2>
          {b.input.claim && <div><span className="mu">الادّعاء</span><br /><b>«{b.input.claim}»</b></div>}
          {b.input.text && <details><summary className="mu">النص المحلَّل</summary><p style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{b.input.text}</p></details>}
          {running && <div className="msg warn" role="status">المحركات تعمل الآن…</div>}
          {!running && cmp.votes && (
            <div className="tabs" aria-label="الاتفاق">
              {Object.entries(cmp.votes).map(([k, v]) => <span key={k} className={`pill ${pillFor(k)}`}>{k}: {v}</span>)}
              <span className="pill p-n">الاتفاق {pct(cmp.agreement)}</span>
              {cmp.disagreement === "none" && <span className="pill p-ok">اتفاق في الحكم</span>}
              {cmp.disagreement === "minor" && <span className="pill p-warn">خلاف بسيط</span>}
              {cmp.disagreement === "major" && <span className="pill p-bad">خلاف كبير</span>}
            </div>
          )}
        </section>

        <h2 style={{ margin: "4px 0 0", fontSize: 15 }}>مقارنة جنبًا إلى جنب</h2>
        <div className="g4">
          {b.runs.map((r) => (
            <section key={r.id} className="card">
              <h3>{r.engine}</h3>
              {r.status === "ok" && r.output ? <OutputView task={b.task} out={r.output} /> : <div className="msg err">{STATUS[r.status]}: {r.error}</div>}
              <span className="mu" style={{ fontSize: 11 }}>{r.model_version || r.model} · {r.prompt} · {money(r.cost_usd)} · {(r.duration_ms / 1000).toFixed(1)} ث</span>
            </section>
          ))}
          {b.merges.map((m) => (
            <section key={`m${m.id}`} className="card" style={{ borderColor: "var(--ac)" }}>
              <h3>مسودة الدمج <span className="mu">· {m.engine}</span></h3>
              {m.status === "ok" && m.output ? (
                <>
                  <OutputView task={b.task} out={m.output.final} />
                  {!!m.output.attribution.length && <div className="mu" style={{ fontSize: 12 }}>
                    {m.output.attribution.map((a, k) => <div key={k}>• {a.point} <span className="pill p-ac">{a.engines.join("، ")}</span></div>)}
                  </div>}
                </>
              ) : <div className="msg err">{m.error}</div>}
            </section>
          ))}
        </div>

        {b.merges.some((m) => m.output?.disagreements.length) && (
          <section className="card">
            <h2>الخلافات كما رآها محرك الدمج</h2>
            {b.merges.flatMap((m) => (m.output?.disagreements ?? []).map((d, k) => (
              <div className="row" key={`${m.id}-${k}`}>
                <span className="f"><b>{d.topic}</b><br />{Object.entries(d.positions).map(([e, v]) => <span key={e} className="mu">{e}: {v}<br /></span>)}
                  <span>المقترح: {d.suggested} — {d.why}</span></span>
              </div>
            )))}
          </section>
        )}
        {!running && b.mode === "multi" && <Remerge batch={b} engines={engines} onDone={setB} />}
      </div>
      <div className="side">{!running && <Decision batch={b} onDone={setB} />}</div>
    </div>
  );
}

function Remerge({ batch, engines, onDone }: { batch: Batch; engines: EngineT[]; onDone: (b: Batch) => void }) {
  const [eid, setEid] = useState<number | "">("");
  const [err, setErr] = useState("");
  return (
    <section className="card">
      <h3>إعادة الدمج بمحرك آخر</h3>
      <span className="mu">المخرجات الأصلية محفوظة، وتظهر النتيجتان جنبًا إلى جنب للمقارنة.</span>
      <div className="tabs">
        <select className="inp" style={{ width: "auto" }} value={eid} onChange={(e) => setEid(e.target.value ? Number(e.target.value) : "")} aria-label="محرك الدمج">
          <option value="">اختر محرك الدمج…</option>
          {engines.filter((e) => e.enabled).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
        </select>
        <button className="btn" disabled={!eid} onClick={async () => {
          setErr("");
          try { onDone(await api<Batch>(`/api/engines/batches/${batch.id}/merge`, { method: "POST", body: { merge_engine_id: eid } })); }
          catch (e) { setErr((e as Error).message); }
        }}>دمج</button>
      </div>
      {err && <div className="msg err">{err}</div>}
    </section>
  );
}

function Decision({ batch, onDone }: { batch: Batch; onDone: (b: Batch) => void }) {
  const d = batch.decision?.output;
  const [label, setLabel] = useState(d?.label ?? "");
  const [evidence, setEvidence] = useState(d?.evidence ?? "");
  const [reasoning, setReasoning] = useState(d?.reasoning ?? "");
  const [summary, setSummary] = useState(d?.summary ?? batch.merges.at(-1)?.output?.final.summary ?? "");
  const items: Item[] = batch.comparison.items ?? [];
  const [accepted, setAccepted] = useState<Record<number, boolean | undefined>>({});
  const [note, setNote] = useState(batch.decision?.note ?? "");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);

  const submit = async () => {
    setErr(""); setOk(false);
    let output: Output;
    if (batch.task === "classify_verdict") {
      const kept = items.filter((_, i) => accepted[i]).map((it) => ({ type: it.data.type ?? "", value: it.data.value ?? it.text }));
      output = { label, evidence, reasoning, items: kept };
    } else if (batch.task === "extract_claims") {
      output = { claims: items.filter((_, i) => accepted[i]).map((it) => ({ text: it.text, speaker: it.data.speaker ?? "", type: it.data.type ?? "" })) };
    } else output = { summary, points: batch.merges.at(-1)?.output?.final.points ?? [] };
    try {
      onDone(await api<Batch>(`/api/engines/batches/${batch.id}/decision`, { method: "POST", body: { output, source: "manual", note } }));
      setOk(true);
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <>
      {!!items.length && (
        <section className="card">
          <h2>العناصر المستخرجة — اقبل أو ارفض كل عنصر</h2>
          {items.map((it, i) => (
            <div key={i} className="row">
              <span className="f">{it.text}<br /><span className={`pill ${it.agreed ? "p-ac" : "p-warn"}`}>{it.agreed ? it.share + " محركات" : "محرك واحد: " + it.engines[0]}</span></span>
              <div className="seg" role="group" aria-label={`قرار العنصر ${i + 1}`}>
                <button className={accepted[i] === true ? "on" : ""} aria-pressed={accepted[i] === true} onClick={() => setAccepted({ ...accepted, [i]: true })}>قبول</button>
                <button className={accepted[i] === false ? "on" : ""} aria-pressed={accepted[i] === false} onClick={() => setAccepted({ ...accepted, [i]: false })}>رفض</button>
              </div>
            </div>
          ))}
        </section>
      )}
      <section className="card">
        <h2>قرار الصحفي</h2>
        <span className="mu">الاقتراحات للاستئناس. القرار لك وحدك.</span>
        {batch.task === "classify_verdict" && (
          <>
            <label className="fld">الحكم
              <select className="inp" value={label} onChange={(e) => setLabel(e.target.value)}>
                <option value="">اختر…</option>{LABELS.map((l) => <option key={l}>{l}</option>)}
              </select>
            </label>
            {batch.comparison.suggested && <span className="mu">المرجّح من المحركات: {batch.comparison.suggested} ({pct(batch.comparison.agreement)})</span>}
            <label className="fld">درجة الدليل
              <select className="inp" value={evidence} onChange={(e) => setEvidence(e.target.value)}>
                <option value="">اختر…</option>{EVIDENCE.map((l) => <option key={l}>{l}</option>)}
              </select>
            </label>
            <label className="fld">الشرح<textarea className="inp" rows={4} style={{ height: "auto", padding: 10 }} value={reasoning} onChange={(e) => setReasoning(e.target.value)} /></label>
          </>
        )}
        {batch.task === "summarize" && (
          <label className="fld">الملخص المعتمد<textarea className="inp" rows={6} style={{ height: "auto", padding: 10 }} value={summary} onChange={(e) => setSummary(e.target.value)} /></label>
        )}
        <label className="fld">ملاحظة<input className="inp" value={note} onChange={(e) => setNote(e.target.value)} /></label>
        {err && <div className="msg err">{err}</div>}
        {ok && <div className="msg ok" role="status">اعتُمد، وسُجّل اسمك ووقت الاعتماد في سجل التدقيق.</div>}
        {batch.decision && !ok && <div className="msg ok">معتمد في {batch.decision.decided_at.slice(0, 16).replace("T", " ")}</div>}
        <button className="btn pri" disabled={batch.task === "classify_verdict" && (!label || !evidence)} onClick={submit}>اعتماد</button>
        <span className="mu">سيُسجَّل اسمك ووقت الاعتماد في سجل التدقيق.</span>
      </section>
    </>
  );
}
