import { useEffect, useState } from "react";
import { api, apiForm } from "../../api";
import { useCan } from "../../session";

// داخل برنامج سطح المكتب: نافذة اختيار مجلد وإعادة تشغيل فورية
type TauriBridge = { core: { invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T> } };
const tauri = (): TauriBridge | undefined => (window as unknown as { __TAURI__?: TauriBridge }).__TAURI__;

type Disk = { path: string; free_gb: number; total_gb: number; label?: string };
type Storage = {
  data_dir: string; backup_dir: string; restart_required: boolean;
  pending: { data_dir: string | null; backup_dir: string | null; move_data: boolean; requested_by: string; requested_at: string } | null;
  last_error: { message: string; at: string } | null;
  history: { from: { data_dir: string }; to: { data_dir: string }; requested_by: string; applied_at: string }[];
  host: { data: Disk; backups: Disk; drives: Disk[]; backup_fallback: boolean; warnings: string[] } | null;
};

export function Settings() {
  const can = useCan();
  return (
    <div className="cols">
      <div className="grow">{can("system.manage") && <StorageCard />}</div>
      <div className="side">{can("users.manage") && <FourEyes />}{can("system.manage") && <><TelegramBot /><ReportSchedule /><Sanctions /></>}</div>
      {can("system.manage") && <div className="grow"><SocialProviders /></div>}
    </div>
  );
}

function FourEyes() {
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => { api<{ enabled: boolean }>("/api/admin/settings/four-eyes").then((r) => setOn(r.enabled)); }, []);
  return (
    <section className="card">
      <h2>قاعدة «العينان الأربع»</h2>
      <span className="mu">إن فُعّلت: من كتب الحكم أو المسودة أو التقييم لا يعتمده بنفسه، حتى لو كان محرّرًا أيضًا.</span>
      <label className="chk">
        <input type="checkbox" checked={!!on} disabled={on === null}
          onChange={async (e) => { const r = await api<{ enabled: boolean }>("/api/admin/settings/four-eyes", { method: "PUT", body: { enabled: e.target.checked } }); setOn(r.enabled); }} />
        مفعّلة
      </label>
    </section>
  );
}

function StorageCard() {
  const [st, setSt] = useState<Storage | null>(null);
  const [f, setF] = useState({ data_dir: "", backup_dir: "", move_data: true });
  const [err, setErr] = useState("");
  const load = () => api<Storage>("/api/admin/storage").then(setSt).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  if (!st) return <section className="card"><h2>التخزين</h2>{err && <div className="msg err">{err}</div>}</section>;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr("");
    try {
      setSt(await api<Storage>("/api/admin/storage", { method: "POST", body: { data_dir: f.data_dir || null, backup_dir: f.backup_dir === "" ? null : f.backup_dir, move_data: f.move_data } }));
    } catch (x) { setErr((x as Error).message); }
  };

  return (
    <section className="card">
      <h2>التخزين</h2>
      <div className="row"><span className="f">مجلد البيانات<br /><code dir="ltr">{st.host?.data.path ?? st.data_dir}</code></span>{st.host && <span className="pill p-n">{st.host.data.free_gb} غيغابايت فارغة</span>}</div>
      <div className="row"><span className="f">النسخ الاحتياطي<br /><code dir="ltr">{st.host?.backups.path ?? (st.backup_dir || "data/backups")}</code></span>{st.host && <span className="pill p-n">{st.host.backups.free_gb} غيغابايت فارغة</span>}</div>
      {st.host?.backup_fallback && <div className="msg warn">قرص النسخ الاحتياطي غير موصول؛ تُحفظ النسخ مؤقتًا داخل مجلد البيانات.</div>}
      {st.last_error && <div className="msg err">لم يُطبَّق آخر تغيير: {st.last_error.message}</div>}
      {st.pending ? (
        <div className="msg warn" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span>تغيير معلّق إلى <code dir="ltr">{st.pending.data_dir ?? st.pending.backup_dir}</code> ({st.pending.move_data ? "مع نقل البيانات" : "مجلد جديد فارغ"}). يُطبَّق عند إعادة تشغيل البرنامج، ولا يُحذف المجلد القديم.</span>
          <div className="tabs">
            {tauri() && <button className="btn sm pri" onClick={() => tauri()!.core.invoke("restart_services")}>أعد التشغيل الآن وطبّق التغيير</button>}
            <button className="btn sm" onClick={async () => setSt(await api<Storage>("/api/admin/storage/pending", { method: "DELETE" }))}>إلغاء الطلب</button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h3>تغيير المكان</h3>
          {!!st.host?.drives.length && (
            <div className="tabs">
              {st.host.drives.map((d) => (
                <button type="button" key={d.path} className="btn sm" onClick={() => setF({ ...f, data_dir: d.path.replace(/[\\/]$/, "") + (d.path.includes("\\") ? "\\Marsad" : "/marsad") })}>
                  {d.label ? `${d.label} ` : ""}<span dir="ltr">{d.path}</span> · {d.free_gb} غ.ب فارغة
                </button>
              ))}
            </div>
          )}
          <label className="fld">مجلد البيانات الجديد<input className="inp" dir="ltr" value={f.data_dir} onChange={(e) => setF({ ...f, data_dir: e.target.value })} placeholder="D:\Marsad" /></label>
          {tauri() && <div><button type="button" className="btn sm" onClick={async () => { const d = await tauri()!.core.invoke<string | null>("pick_folder"); if (d) setF({ ...f, data_dir: d }); }}>اختيار مجلد…</button></div>}
          <label className="chk"><input type="checkbox" checked={f.move_data} onChange={(e) => setF({ ...f, move_data: e.target.checked })} />انقل بياناتي الحالية إليه</label>
          <label className="fld">مجلد النسخ الاحتياطي (قرص خارجي مثلًا)<input className="inp" dir="ltr" value={f.backup_dir} onChange={(e) => setF({ ...f, backup_dir: e.target.value })} placeholder="E:\MarsadBackups" /></label>
          {err && <div className="msg err">{err}</div>}
          <button className="btn pri" disabled={!f.data_dir && !f.backup_dir}>طلب التغيير</button>
        </form>
      )}
      {!!st.history.length && (
        <details><summary className="mu">سجل التغييرات ({st.history.length})</summary>
          {st.history.map((h, i) => <div key={i} className="row mu"><span dir="ltr">{h.from.data_dir} → {h.to.data_dir}</span><span>{h.requested_by} · {h.applied_at.slice(0, 10)}</span></div>)}
        </details>
      )}
    </section>
  );
}

/** قوائم العقوبات والأشخاص ذوي النفوذ لمطابقة أسماء القضايا. */
function Sanctions() {
  const [name, setName] = useState("OpenSanctions");
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState("");
  const go = async (e: React.FormEvent) => {
    e.preventDefault(); setMsg("");
    const f = new FormData(); f.append("list_name", name); f.append("file", file!);
    try { const r = await apiForm<{ entries: number }>("/api/sanctions/import", f); setMsg(`استُوردت ${r.entries} جهة وشخصًا.`); }
    catch (x) { setMsg((x as Error).message); }
  };
  return (
    <form className="card" onSubmit={go} style={{ display: "flex", flexDirection: "column", gap: 8 }} aria-label="قوائم العقوبات">
      <h2>قوائم العقوبات</h2>
      <span className="mu" style={{ fontSize: 12 }}>ملف OpenSanctions «targets.simple.csv» (مجاني للاستخدام غير التجاري) أو CSV بعمود name. استيراد قائمة بالاسم نفسه يستبدلها.</span>
      <input className="inp" value={name} onChange={(e) => setName(e.target.value)} aria-label="اسم القائمة" />
      <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="ملف القائمة" />
      <button className="btn" disabled={!file || !name.trim()}>استيراد</button>
      {msg && <div className="msg" role="status">{msg}</div>}
    </form>
  );
}

type Platform = { platform: string; ar: string; provider: string | null; masked: Record<string, string>; fields: Record<string, string[]>; sources: number };
const FIELD_AR: Record<string, string> = { access_token: "رمز الوصول (Access token)", ig_user_id: "معرّف حساب إنستغرام التجاري", bearer_token: "Bearer token",
  client_key: "Client key", client_secret: "Client secret", api_token: "مفتاح Apify" };

/** موصلات فيسبوك وإنستغرام وX وتيك توك: مبنية، وتعمل حين يُضاف مفتاح مزوّد أو وصول بحثي. */
function SocialProviders() {
  const [d, setD] = useState<{ platforms: Platform[]; providers: Record<string, string>; note: string } | null>(null);
  const load = () => api<typeof d>("/api/social/providers").then(setD);
  useEffect(() => { load(); }, []);
  if (!d) return null;
  return (
    <section className="card" aria-label="موصلات التواصل">
      <h2>موصلات التواصل</h2>
      <span className="mu" style={{ fontSize: 12 }}>{d.note}</span>
      {d.platforms.map((p) => <PlatformRow key={p.platform} p={p} providers={d.providers} reload={load} />)}
    </section>
  );
}

function PlatformRow({ p, providers, reload }: { p: Platform; providers: Record<string, string>; reload: () => void }) {
  const [prov, setProv] = useState(p.provider ?? "");
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [handle, setHandle] = useState("");
  const [msg, setMsg] = useState("");
  const save = async () => {
    setMsg("");
    try { await api(`/api/social/providers/${p.platform}`, { method: "PUT", body: { provider: prov || null, credentials: creds } }); setCreds({}); setMsg(prov ? "حُفظ؛ المفتاح مشفّر." : "أُوقف الموصل."); reload(); }
    catch (x) { setMsg((x as Error).message); }
  };
  const test = async () => {
    const r = await api<{ ok: boolean; count?: number; error?: string }>(`/api/social/providers/${p.platform}/test`, { method: "POST", body: { handle } });
    setMsg(r.ok ? `يعمل: ${r.count} منشورًا من @${handle}` : r.error ?? "تعذّر");
  };
  return (
    <div className="row" style={{ flexDirection: "column", alignItems: "stretch" }} data-platform={p.platform}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <b style={{ flex: 1 }}>{p.ar}</b>
        <span className="mu" style={{ fontSize: 12 }}>{p.sources} مصدر</span>
        <span className={`pill ${p.provider ? "p-ok" : "p-warn"}`}>{p.provider ? providers[p.provider] : "ينتظر مزوّدًا"}</span>
      </div>
      <select className="inp" value={prov} onChange={(e) => setProv(e.target.value)} aria-label={`مزوّد ${p.ar}`}>
        <option value="">دون مزوّد</option>{Object.entries(providers).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      {prov && p.fields[prov].map((f) => (
        <input key={f} className="inp" dir="ltr" type="password" autoComplete="off" value={creds[f] ?? ""} onChange={(e) => setCreds({ ...creds, [f]: e.target.value })}
               placeholder={p.provider === prov && p.masked[f] ? `${FIELD_AR[f]} · محفوظ ${p.masked[f]}` : FIELD_AR[f]} aria-label={`${FIELD_AR[f]} ${p.ar}`} />
      ))}
      <div style={{ display: "flex", gap: 6 }}>
        <button className="btn sm" onClick={save}>حفظ</button>
        {p.provider && <><input className="inp" dir="ltr" style={{ width: 160, height: 32 }} value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="اسم حساب للتجربة" aria-label={`حساب تجربة ${p.ar}`} />
          <button className="btn sm" disabled={!handle} onClick={test}>جرّب</button></>}
      </div>
      {msg && <div className="msg" role="status">{msg}</div>}
    </div>
  );
}

/** بوت تيليغرام للتنبيهات: يُنشأ عبر @BotFather ويُلصق رمزه هنا. */
function TelegramBot() {
  const [st, setSt] = useState<{ configured: boolean; username: string | null; masked: string | null } | null>(null);
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api<typeof st>("/api/alerts/telegram").then(setSt);
  useEffect(() => { load(); }, []);
  const save = async (t: string | null) => {
    setMsg("");
    try { const r = await api<{ bot: string | null }>("/api/alerts/telegram/bot", { method: "PUT", body: { token: t } }); setToken(""); setMsg(r.bot ? `يعمل: @${r.bot}` : "أُزيل البوت."); load(); }
    catch (x) { setMsg((x as Error).message); }
  };
  if (!st) return null;
  return (
    <section className="card" aria-label="بوت التنبيهات">
      <h2>تنبيهات تيليغرام</h2>
      {st.configured ? <span>البوت: <b dir="ltr">@{st.username}</b> <span className="mu">({st.masked})</span></span>
        : <span className="mu" style={{ fontSize: 12 }}>أنشئ بوتًا من @BotFather في تيليغرام والصق رمزه هنا. يربط كل مستخدم حسابه من «تفضيلاتي».</span>}
      <input className="inp" dir="ltr" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="رمز البوت" aria-label="رمز البوت" />
      <div style={{ display: "flex", gap: 6 }}>
        <button className="btn sm" disabled={!token.trim()} onClick={() => save(token)}>حفظ وفحص</button>
        {st.configured && <button className="btn sm" onClick={() => save(null)}>إزالة</button>}
      </div>
      {msg && <div className="msg" role="status">{msg}</div>}
    </section>
  );
}

function ReportSchedule() {
  const [s, setS] = useState<{ morning: string; weekly: string; weekly_day: number; enabled: boolean } | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api<{ schedule: typeof s }>("/api/reports").then((r) => setS(r.schedule)).catch(() => {}); }, []);
  if (!s) return null;
  const days = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"];
  const save = async () => { try { await api("/api/reports-schedule", { method: "PUT", body: s }); setMsg("حُفظ."); } catch (x) { setMsg((x as Error).message); } };
  return (
    <section className="card" aria-label="مواعيد التقارير">
      <h2>مواعيد التقارير</h2>
      <label className="fld">الموجز الصباحي<input className="inp" type="time" value={s.morning} onChange={(e) => setS({ ...s, morning: e.target.value })} /></label>
      <div style={{ display: "flex", gap: 6 }}>
        <label className="fld">التقرير الأسبوعي<select className="inp" value={s.weekly_day} onChange={(e) => setS({ ...s, weekly_day: Number(e.target.value) })}>{days.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></label>
        <label className="fld">الساعة<input className="inp" type="time" value={s.weekly} onChange={(e) => setS({ ...s, weekly: e.target.value })} /></label>
      </div>
      <label className="chk"><input type="checkbox" checked={s.enabled} onChange={(e) => setS({ ...s, enabled: e.target.checked })} /> الإنشاء التلقائي</label>
      <button className="btn sm" onClick={save}>حفظ</button>
      {msg && <div className="msg" role="status">{msg}</div>}
    </section>
  );
}
