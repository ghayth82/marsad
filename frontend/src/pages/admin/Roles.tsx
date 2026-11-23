import { useEffect, useState } from "react";
import { api } from "../../api";
import type { Perm, Role } from "./Users";

export function Roles() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [perms, setPerms] = useState<Perm[]>([]);
  const [edit, setEdit] = useState<Role | null>(null);
  const [draft, setDraft] = useState<Set<string>>(new Set());
  const [nf, setNf] = useState({ key: "", name_ar: "", description: "" });
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const load = async () => {
    const [r, p] = await Promise.all([api<Role[]>("/api/admin/roles"), api<Perm[]>("/api/admin/permissions")]);
    setRoles(r); setPerms(p);
  };
  useEffect(() => { load().catch((e) => setMsg({ kind: "err", text: e.message })); }, []);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); await load(); setMsg({ kind: "ok", text: ok }); } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const startEdit = (r: Role | null) => { setEdit(r); setDraft(new Set(r?.permissions ?? [])); };
  const groups = [...new Set(perms.map((p) => p.group))];
  const isNew = edit === null && nf.key !== "";

  const PermBoxes = ({ disabled }: { disabled?: boolean }) => (
    <>
      {groups.map((g) => (
        <div key={g}>
          <div className="mu" style={{ fontWeight: 700, margin: "8px 0 4px" }}>{g}</div>
          <div className="perm-grid">
            {perms.filter((p) => p.group === g).map((p) => (
              <label key={p.key} className="chk">
                <input type="checkbox" disabled={disabled} checked={draft.has(p.key)} onChange={(e) => {
                  const d = new Set(draft); if (e.target.checked) d.add(p.key); else d.delete(p.key); setDraft(d);
                }} />{p.ar}
              </label>
            ))}
          </div>
        </div>
      ))}
    </>
  );

  return (
    <div className="cols">
      <div className="grow">
        {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}
        <section className="card">
          <h2>الأدوار</h2>
          {roles.map((r) => (
            <div className="row" key={r.key}>
              <span className="f"><b>{r.name_ar}</b> {r.builtin ? <span className="pill p-n">جاهز</span> : <span className="pill p-ac">مخصص</span>}<br /><span className="mu">{r.description} · {r.permissions.length} صلاحية</span></span>
              <button className="btn sm" onClick={() => startEdit(r)}>الصلاحيات</button>
              {!r.builtin && <button className="btn sm danger" onClick={() => run(() => api(`/api/admin/roles/${r.key}`, { method: "DELETE" }), "حُذف الدور.")}>حذف</button>}
            </div>
          ))}
        </section>
        {edit && (
          <section className="card">
            <h2>صلاحيات: {edit.name_ar}</h2>
            {edit.key === "admin" && <div className="msg warn">دور المدير يحمل كل الصلاحيات دائمًا.</div>}
            <PermBoxes disabled={edit.key === "admin"} />
            {edit.key !== "admin" && (
              <div className="tabs">
                <button className="btn pri" onClick={() => run(() => api(`/api/admin/roles/${edit.key}/permissions`, { method: "PUT", body: { permissions: [...draft] } }), "حُفظت صلاحيات الدور، وتسري فورًا على كل من يحمله.")}>حفظ</button>
                <button className="btn" onClick={() => setEdit(null)}>إغلاق</button>
              </div>
            )}
          </section>
        )}
      </div>
      <div className="side">
        <section className="card">
          <h2>دور جديد</h2>
          <span className="mu">مثل «مدقق صور» أو «منسّق تدريب».</span>
          <label className="fld">الاسم<input className="inp" value={nf.name_ar} onChange={(e) => setNf({ ...nf, name_ar: e.target.value })} /></label>
          <label className="fld">مفتاح بالإنجليزية<input className="inp" dir="ltr" pattern="[a-z0-9_]+" placeholder="image_checker" value={nf.key} onChange={(e) => { setNf({ ...nf, key: e.target.value.toLowerCase() }); if (edit) startEdit(null); }} /></label>
          <label className="fld">الوصف<input className="inp" value={nf.description} onChange={(e) => setNf({ ...nf, description: e.target.value })} /></label>
          {isNew && <PermBoxes />}
          <button className="btn pri" disabled={!nf.key || !nf.name_ar || !draft.size}
            onClick={() => run(async () => { await api("/api/admin/roles", { method: "POST", body: { ...nf, permissions: [...draft] } }); setNf({ key: "", name_ar: "", description: "" }); setDraft(new Set()); }, "أُنشئ الدور.")}>إنشاء الدور</button>
        </section>
      </div>
    </div>
  );
}
