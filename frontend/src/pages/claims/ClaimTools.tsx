// البند 13 على بطاقة الادّعاء: التحقق السابق، الأرقام الرسمية، الأرشفة الفورية، وبطاقة النتيجة للنشر.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";

export type FactCheck = { checked_at: string; configured: boolean; error: string; note?: string;
  global: { claim: string; claimant: string; publisher: string; rating: string; date: string; url: string; title: string }[];
  local: { claim_id: number; text: string; label: string; score: number; link: string }[] } | null;

export function FactCheckPanel({ cid, fc, can, onDone }: { cid: number; fc: FactCheck; can: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const go = async () => { setBusy(true); setErr(""); try { await api(`/api/claims/${cid}/factcheck`, { method: "POST" }); onDone(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); } };
  return (
    <section className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h2 style={{ flex: 1 }}>هل تحقق منها أحد قبلي؟</h2>
        {can && <button className="btn sm" disabled={busy} onClick={go}>{busy ? "يبحث…" : fc ? "ابحث مجددًا" : "ابحث الآن"}</button>}
      </div>
      {err && <div className="msg err">{err}</div>}
      {!fc ? <span className="mu">يبحث في قواعد التحقق العالمية (Google Fact Check) وفي سجل البرنامج.</span> : (<>
        {fc.note && <div className="msg warn">{fc.note}</div>}
        {fc.error && <div className="msg err">{fc.error}</div>}
        {fc.configured && !fc.error && !fc.global.length && <span className="mu">لا نتائج في قواعد التحقق العالمية.</span>}
        {fc.global.map((g) => (
          <div key={g.url} className="row">
            <span className="f"><a href={g.url} target="_blank" rel="noreferrer noopener">{g.title || g.claim}</a><br />
              <span className="mu">{g.publisher}{g.date ? ` · ${g.date}` : ""}{g.claimant ? ` · القائل: ${g.claimant}` : ""}</span></span>
            <span className="pill p-warn">{g.rating}</span>
          </div>
        ))}
        <h3>في سجل البرنامج</h3>
        {!fc.local.length && <span className="mu">لا ادّعاء مشابه بحكم معتمد.</span>}
        {fc.local.map((l) => <div key={l.claim_id} className="row"><Link className="f" to={l.link}>{l.text}</Link><span className="pill p-ac">{l.label}</span></div>)}
        <span className="mu" style={{ fontSize: 11 }}>آخر بحث: {new Date(fc.checked_at).toLocaleString("ar")}</span>
      </>)}
    </section>
  );
}

type Match = { figure_id: number; indicator: string; official: number; unit: string; as_of: string; agency: string; url: string;
  claimed: number; diff_pct: number | null; snippet: string; same: boolean };

export function FiguresPanel({ cid }: { cid: number }) {
  const [m, setM] = useState<Match[] | null>(null);
  useEffect(() => { api<{ matches: Match[] }>(`/api/claims/${cid}/figures`).then((r) => setM(r.matches)).catch(() => setM([])); }, [cid]);
  if (!m || !m.length) return null;
  return (
    <section className="card">
      <h2>الأرقام الرسمية</h2>
      <span className="mu">مقارنة آلية بآخر قيمة في جدول الأرقام الرسمية. دليل يقرّه الصحفي، لا حكم.</span>
      {m.map((x) => (
        <div key={x.figure_id} className="row">
          <span className="f"><b>{x.indicator}</b>: في الادّعاء <b>{x.claimed}</b>، والرسمي <b>{x.official}{x.unit ? ` ${x.unit}` : ""}</b> ({x.as_of})<br />
            <span className="mu">{x.agency}{x.url && <> · <a href={x.url} target="_blank" rel="noreferrer noopener">المصدر</a></>}</span></span>
          <span className={`pill ${x.same ? "p-ok" : "p-warn"}`}>{x.same ? "مطابق" : x.diff_pct == null ? "—" : `فرق ${x.diff_pct > 0 ? "+" : ""}${x.diff_pct}٪`}</span>
        </div>
      ))}
    </section>
  );
}

export function ArchivePanel({ cid, onDone }: { cid: number; onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [wb, setWb] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ k: string; t: string } | null>(null);
  return (
    <section className="card">
      <h2>أرشف رابطًا الآن</h2>
      <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={async (e) => {
        e.preventDefault(); setBusy(true); setMsg(null);
        try {
          const s = await api<{ status: string; error: string; sha256: string }>("/api/snapshots", { method: "POST", body: { url, wayback: wb, claim_id: cid } });
          setMsg(s.status === "ok" ? { k: "ok", t: `أُرشف وأُضيف دليلًا. البصمة: ${s.sha256.slice(0, 16)}…` } : { k: "err", t: s.error });
          if (s.status === "ok") { setUrl(""); onDone(); }
        } catch (x) { setMsg({ k: "err", t: (x as Error).message }); } finally { setBusy(false); }
      }}>
        <input className="inp" dir="ltr" placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} required aria-label="الرابط" />
        <label className="chk"><input type="checkbox" checked={wb} onChange={(e) => setWb(e.target.checked)} />اطلب حفظه في Wayback Machine أيضًا (يُرسل الرابط إلى جهة خارجية)</label>
        <button className="btn sm" disabled={busy}>{busy ? "يؤرشف…" : "أرشف"}</button>
      </form>
      {msg && <div className={`msg ${msg.k}`}>{msg.t}</div>}
    </section>
  );
}

type CardData = { claim: string; label: string; grade: string; explanation: string; date: string; org: string };

function wrap(ctx: CanvasRenderingContext2D, text: string, max: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const w of text.split(/\s+/)) {
    const t = line ? `${line} ${w}` : w;
    if (ctx.measureText(t).width > max && line) { out.push(line); line = w; } else line = t;
  }
  if (line) out.push(line);
  return out;
}

function draw(cv: HTMLCanvasElement, d: CardData, link: string, tall: boolean) {
  const W = 1080, H = tall ? 1920 : 1080;
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d")!;
  const css = getComputedStyle(document.querySelector(".app") || document.body);
  const v = (k: string, f: string) => css.getPropertyValue(k).trim() || f;
  const bg = v("--sf", "#ffffff"), tx = v("--tx", "#18202a"), mu = v("--mu", "#5b6673"), ac = v("--ac", "#0f766e"), onac = v("--onac", "#ffffff");
  const font = (w: number, s: number) => `${w} ${s}px "Noto Sans Arabic", "IBM Plex Sans Arabic", sans-serif`;
  ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = ac; ctx.fillRect(0, 0, W, 18);
  ctx.direction = "rtl"; ctx.textAlign = "right";
  const R = W - 80;
  let y = tall ? 260 : 150;
  ctx.fillStyle = mu; ctx.font = font(600, 40); ctx.fillText("نتيجة التحقق", R, y);
  y += 70;
  ctx.fillStyle = tx; ctx.font = font(700, tall ? 64 : 56);
  const lines = wrap(ctx, `«${d.claim}»`, W - 160).slice(0, tall ? 9 : 6);
  for (const l of lines) { y += tall ? 92 : 80; ctx.fillText(l, R, y); }
  y += tall ? 190 : 150;
  ctx.font = font(700, 76);
  const lw = ctx.measureText(d.label).width + 90;
  ctx.fillStyle = ac;
  ctx.beginPath(); ctx.roundRect(R - lw, y - 82, lw, 116, 58); ctx.fill();
  ctx.fillStyle = onac; ctx.fillText(d.label, R - 45, y + 4);
  if (d.explanation) {
    y += 120; ctx.fillStyle = mu; ctx.font = font(400, 38);
    for (const l of wrap(ctx, d.explanation, W - 160).slice(0, tall ? 6 : 3)) { y += 56; ctx.fillText(l, R, y); }
  }
  ctx.fillStyle = mu; ctx.font = font(600, 34);
  ctx.fillText(`${d.org} · ${d.date}`, R, H - 110);
  if (link) { ctx.textAlign = "left"; ctx.direction = "ltr"; ctx.fillText(link, 80, H - 110); }
}

export function ResultCard({ cid }: { cid: number }) {
  const [d, setD] = useState<CardData | null>(null);
  const [tall, setTall] = useState(false);
  const [link, setLink] = useState("");
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => { api<CardData>(`/api/claims/${cid}/card`).then(setD).catch(() => setD(null)); }, [cid]);
  useEffect(() => {
    if (!d || !ref.current) return;
    const cv = ref.current;
    document.fonts.ready.then(() => draw(cv, d, link, tall));
  }, [d, tall, link]);
  if (!d) return null;
  return (
    <section className="card">
      <h2>بطاقة النتيجة للنشر</h2>
      <div className="seg" role="group" aria-label="المقاس">
        <button className={!tall ? "on" : ""} onClick={() => setTall(false)}>مربعة</button>
        <button className={tall ? "on" : ""} onClick={() => setTall(true)}>عمودية</button>
      </div>
      <input className="inp" dir="ltr" placeholder="رابط مختصر لمادتك المنشورة (اختياري)" value={link} onChange={(e) => setLink(e.target.value.slice(0, 40))} aria-label="الرابط على البطاقة" />
      <canvas ref={ref} role="img" aria-label={`بطاقة: ${d.label}`} style={{ width: "100%", maxWidth: tall ? 240 : 360, border: "1px solid var(--bd)", borderRadius: 8, alignSelf: "center" }} />
      <button className="btn sm pri" onClick={() => { const a = document.createElement("a"); a.download = `marsad-${cid}-${tall ? "story" : "square"}.png`; a.href = ref.current!.toDataURL("image/png"); a.click(); }}>تنزيل الصورة</button>
      <span className="mu">بألوان نمطك الحالي. لأحكام الادّعاءات المعتمدة فقط.</span>
    </section>
  );
}

// ---------- سير العمل التحريري (البند 14) ----------

const PRI: Record<string, string> = { urgent: "عاجل", high: "مهم", normal: "عادي" };

export function WorkflowPanel({ c, onDone }: { c: { id: number; status: string; assignee_id: number | null; priority: string; due_at: string | null }; onDone: () => void }) {
  const [people, setPeople] = useState<{ id: number; name: string }[] | null>(null);
  const [msg, setMsg] = useState<{ k: string; t: string } | null>(null);
  const [reason, setReason] = useState("");
  const [me, setMe] = useState<{ id: number; perms: string[] } | null>(null);
  useEffect(() => {
    api<{ people: { id: number; name: string }[] }>("/api/workflow/people").then((r) => setPeople(r.people)).catch(() => setPeople(null));
    api<{ id: number; access: { effective: string[] } }>("/api/me").then((m) => setMe({ id: m.id, perms: m.access.effective }));
  }, []);
  if (!people || !me) return null;
  const editor = me.perms.includes("verdicts.approve");
  const open = ["new", "assigned", "investigating", "proposed"].includes(c.status);
  const act = async (fn: () => Promise<unknown>, ok: string) => { setMsg(null); try { await fn(); setMsg({ k: "ok", t: ok }); onDone(); } catch (e) { setMsg({ k: "err", t: (e as Error).message }); } };
  const put = (body: object) => act(() => api(`/api/claims/${c.id}/workflow`, { method: "PUT", body }), "حُفظ.");
  const overdue = c.due_at && open && new Date(c.due_at) <= new Date();
  return (
    <section className="card" aria-label="سير العمل">
      <h2>سير العمل</h2>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <label className="fld" style={{ flex: "1 1 160px" }}>المُسند إليه
          <select className="inp" value={c.assignee_id ?? ""} disabled={!open} onChange={(e) => e.target.value && put({ assignee_id: Number(e.target.value) })}>
            <option value="">— غير مُسند —</option>
            {people.filter((p) => editor || p.id === me.id || p.id === c.assignee_id).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
        <label className="fld" style={{ flex: "1 1 110px" }}>الأولوية
          <select className="inp" value={c.priority} disabled={!open} onChange={(e) => put({ priority: e.target.value })}>
            {Object.entries(PRI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      </div>
      {c.due_at && <span className={overdue ? "msg err" : "mu"}>المهلة: {new Date(c.due_at).toLocaleString("ar", { dateStyle: "short", timeStyle: "short" })}{overdue ? " — تجاوزها" : ""}</span>}
      {c.assignee_id && <span className="mu">الاعتماد بمراجع ثانٍ غير كاتب الحكم.</span>}
      {["new", "assigned"].includes(c.status) && <button className="btn sm" onClick={() => act(() => api(`/api/claims/${c.id}/workflow/start`, { method: "POST" }), "بدأ التحقق.")}>ابدأ التحقق</button>}
      {editor && open && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <input className="inp" style={{ flex: "1 1 140px" }} placeholder="سبب الرفض" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="سبب رفض الادّعاء" />
          <button className="btn sm danger" style={{ whiteSpace: "nowrap" }} disabled={reason.trim().length < 3} onClick={() => act(() => api(`/api/claims/${c.id}/workflow/dismiss`, { method: "POST", body: { reason } }), "رُفض الادّعاء.")}>رفض الادّعاء</button>
        </div>
      )}
      {msg && <div className={`msg ${msg.k}`}>{msg.t}</div>}
    </section>
  );
}
