// البند 14: الواجهة البرمجية — رموز الوصول بصلاحيات وتاريخ انتهاء، إشعارات Webhook موقّعة، وتوثيق المسارات.
import { useEffect, useState } from "react";
import { api } from "../../api";

type Token = { id: number; name: string; prefix: string; scopes: string[]; expires_at: string | null; revoked: boolean; expired: boolean; last_used_at: string | null; uses: number };
type Hook = { id: number; url: string; events: string[]; active: boolean; deliveries: { id: number; event: string; status: string; attempts: number; last_code: number; last_error: string; created_at: string }[] };
type Data = { tokens: Token[]; webhooks: Hook[]; scopes: Record<string, string>; events: Record<string, string> };
type Spec = { paths: Record<string, Record<string, { summary?: string }>> };

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("ar") : "—");

export function ApiAccess() {
  const [d, setD] = useState<Data | null>(null);
  const [spec, setSpec] = useState<Spec | null>(null);
  const [tk, setTk] = useState({ name: "", scopes: ["verdicts.read"] as string[], expires_days: 365 });
  const [hk, setHk] = useState({ url: "", events: ["verdict.approved", "verdict.corrected"] as string[] });
  const [shown, setShown] = useState<{ title: string; value: string } | null>(null);
  const [err, setErr] = useState("");
  const load = () => api<Data>("/api/api-access").then(setD);
  useEffect(() => { load(); api<Spec>("/api/api-access/openapi.json").then(setSpec); }, []);
  if (!d) return null;
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  return (
    <div className="cols">
      <div className="grow">
        {shown && (
          <section className="card" style={{ borderColor: "var(--ac)" }}>
            <h2>{shown.title}</h2>
            <span className="mu">انسخه الآن واحفظه في النظام الآخر؛ لن يظهر مرة أخرى.</span>
            <code className="blk">{shown.value}</code>
            <div style={{ display: "flex", gap: 6 }}>
              <button className="btn sm" onClick={() => navigator.clipboard?.writeText(shown.value)}>نسخ</button>
              <button className="btn sm" onClick={() => setShown(null)}>نسختُه</button>
            </div>
          </section>
        )}
        {err && <div className="msg err">{err}</div>}
        <section className="card">
          <h2>رموز الوصول</h2>
          {!d.tokens.length && <span className="mu">لا رموز بعد.</span>}
          {d.tokens.map((t) => (
            <div key={t.id} className="row">
              <span className="f"><b>{t.name}</b> <span className="mu" dir="ltr">{t.prefix}…</span><br />
                <span className="mu">{t.scopes.map((s) => d.scopes[s] ?? s).join("، ")} · ينتهي {fmt(t.expires_at)} · آخر استعمال {fmt(t.last_used_at)} ({t.uses})</span></span>
              <span className={`pill ${t.revoked || t.expired ? "p-n" : "p-ok"}`}>{t.revoked ? "مسحوب" : t.expired ? "منتهٍ" : "فعّال"}</span>
              {!t.revoked && <button className="btn sm danger" onClick={async () => { if (confirm(`سحب الرمز «${t.name}»؟ يتوقف النظام الذي يستعمله فورًا.`)) { await api(`/api/api-access/tokens/${t.id}`, { method: "DELETE" }); load(); } }}>سحب</button>}
            </div>
          ))}
        </section>
        <section className="card">
          <h2>إشعارات Webhook</h2>
          <span className="mu">عند اعتماد حكم أو تصحيحه يُرسل البرنامج طلب POST موقّعًا: <code dir="ltr">X-Marsad-Signature: sha256=HMAC(السر، الطابع.الجسم)</code> والطابع في <code dir="ltr">X-Marsad-Timestamp</code>. يُعاد الإرسال عند الفشل حتى 6 مرات.</span>
          {!d.webhooks.filter((w) => w.active).length && <span className="mu">لا إشعارات بعد.</span>}
          {d.webhooks.filter((w) => w.active).map((w) => (
            <div key={w.id} className="card" style={{ padding: 10 }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <code dir="ltr" style={{ flex: 1 }}>{w.url}</code>
                <button className="btn sm" onClick={async () => { await api(`/api/api-access/webhooks/${w.id}/test`, { method: "POST" }); load(); }}>اختبار</button>
                <button className="btn sm danger" onClick={async () => { await api(`/api/api-access/webhooks/${w.id}`, { method: "DELETE" }); load(); }}>إيقاف</button>
              </div>
              <span className="mu">{w.events.map((e) => d.events[e] ?? e).join("، ")}</span>
              {w.deliveries.slice(0, 5).map((x) => (
                <div key={x.id} className="row" style={{ fontSize: 12 }}>
                  <span className="f">{x.event} · {new Date(x.created_at).toLocaleString("ar")}{x.last_error ? ` · ${x.last_error}` : ""}</span>
                  <span className={`pill ${x.status === "sent" ? "p-ok" : x.status === "failed" ? "p-bad" : "p-warn"}`}>{x.status === "sent" ? "أُرسل" : x.status === "failed" ? "فشل" : `محاولة ${x.attempts}`}{x.last_code ? ` (${x.last_code})` : ""}</span>
                </div>
              ))}
            </div>
          ))}
        </section>
        <section className="card">
          <h2>التوثيق</h2>
          <span className="mu">كل طلب يحمل <code dir="ltr">Authorization: Bearer &lt;الرمز&gt;</code>. الأحكام دون أسماء الصحفيين. <a href="/api/api-access/openapi.json" target="_blank" rel="noreferrer">مواصفة OpenAPI</a></span>
          {spec && Object.entries(spec.paths).flatMap(([path, ms]) => Object.entries(ms).map(([m, op]) => (
            <div key={m + path} className="row"><code dir="ltr" style={{ minWidth: 220 }}><b>{m.toUpperCase()}</b> {path}</code><span className="f">{op.summary}</span></div>
          )))}
        </section>
      </div>
      <div className="side">
        <section className="card">
          <h2>رمز جديد</h2>
          <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={async (e) => {
            e.preventDefault(); setErr("");
            try { const r = await api<{ token: string; name: string }>("/api/api-access/tokens", { method: "POST", body: tk }); setShown({ title: `الرمز «${r.name}»`, value: r.token }); setTk({ ...tk, name: "" }); load(); }
            catch (x) { setErr((x as Error).message); }
          }}>
            <label className="fld">الاسم<input className="inp" required value={tk.name} onChange={(e) => setTk({ ...tk, name: e.target.value })} placeholder="نظام النشر" /></label>
            {Object.entries(d.scopes).map(([k, ar]) => <label key={k} className="chk"><input type="checkbox" checked={tk.scopes.includes(k)} onChange={() => setTk({ ...tk, scopes: toggle(tk.scopes, k) })} />{ar}</label>)}
            <label className="fld">ينتهي بعد (يوم)<input className="inp" type="number" min={1} max={3650} value={tk.expires_days} onChange={(e) => setTk({ ...tk, expires_days: Number(e.target.value) })} /></label>
            <button className="btn sm pri">إنشاء</button>
          </form>
        </section>
        <section className="card">
          <h2>Webhook جديد</h2>
          <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={async (e) => {
            e.preventDefault(); setErr("");
            try { const r = await api<{ secret: string }>("/api/api-access/webhooks", { method: "POST", body: hk }); setShown({ title: "سر التوقيع", value: r.secret }); setHk({ ...hk, url: "" }); load(); }
            catch (x) { setErr((x as Error).message); }
          }}>
            <label className="fld">الرابط<input className="inp" dir="ltr" required value={hk.url} onChange={(e) => setHk({ ...hk, url: e.target.value })} placeholder="https://cms.example.com/hooks/marsad" /></label>
            {Object.entries(d.events).map(([k, ar]) => <label key={k} className="chk"><input type="checkbox" checked={hk.events.includes(k)} onChange={() => setHk({ ...hk, events: toggle(hk.events, k) })} />{ar}</label>)}
            <button className="btn sm pri">إضافة</button>
          </form>
        </section>
      </div>
    </div>
  );
}
