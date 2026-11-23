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
      <div className="side">{can("users.manage") && <FourEyes />}{can("system.manage") && <Sanctions />}</div>
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
