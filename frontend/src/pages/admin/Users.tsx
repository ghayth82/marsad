import { useEffect, useState } from "react";
import { api, type Access } from "../../api";
import { useSession } from "../../session";

export type Role = { key: string; id: number; name_ar: string; description: string; builtin: boolean; priority: number; permissions: string[] };
export type Perm = { key: string; ar: string; group: string };
type U = Access & { id: number; email: string; full_name: string; is_active: boolean; totp_enabled: boolean; has_password: boolean; last_login_at: string | null; locked: boolean };

const toLocal = (iso: string | null) => (iso ? iso.slice(0, 10) : "");
const fromLocal = (d: string) => (d ? new Date(d + "T23:59:59").toISOString() : null);

export function inviteLink(token: string) {
  return `${window.location.origin}/invite?token=${encodeURIComponent(token)}`;
}

export function Users() {
  const [users, setUsers] = useState<U[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [perms, setPerms] = useState<Perm[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const load = async () => {
    const [u, r, p] = await Promise.all([api<U[]>("/api/admin/users"), api<Role[]>("/api/admin/roles"), api<Perm[]>("/api/admin/permissions")]);
    setUsers(u); setRoles(r); setPerms(p);
  };
  useEffect(() => { load().catch((e) => setErr(e.message)); }, []);

  return (
    <div className="cols">
      <div className="grow">
        {err && <div className="msg err">{err}</div>}
        <section className="card">
          <h2>المستخدمون ({users.length})</h2>
          <div className="tw">
            <table>
              <thead><tr><th>الاسم</th><th>الأدوار</th><th>استثناءات</th><th>الحالة</th><th></th></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.full_name || "—"}<br /><span className="mu" dir="ltr">{u.email}</span></td>
                    <td>{u.roles.map((r) => <span key={r.key} className={`pill ${r.active ? "p-ac" : "p-n"}`} style={{ margin: 2 }}>{r.name_ar}{r.expires_at ? " ⏱" : ""}</span>)}</td>
                    <td>{u.overrides.length ? <span className="pill p-warn">{u.overrides.length}</span> : "—"}</td>
                    <td>
                      {!u.is_active ? <span className="pill p-n">موقوف</span> : !u.has_password ? <span className="pill p-warn">لم يقبل الدعوة</span> : u.locked ? <span className="pill p-bad">مقفل</span> : <span className="pill p-ok">نشط</span>}
                    </td>
                    <td><button className="btn sm" onClick={() => setOpen(open === u.id ? null : u.id)}>{open === u.id ? "إغلاق" : "تعديل"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        {open !== null && users.find((u) => u.id === open) && (
          <UserEditor key={open} user={users.find((u) => u.id === open)!} roles={roles} perms={perms} onSaved={load} />
        )}
      </div>
      <div className="side"><NewUser roles={roles} onCreated={load} /></div>
    </div>
  );
}

function RolePicker({ roles, value, onChange }: { roles: Role[]; value: Record<string, string | null>; onChange: (v: Record<string, string | null>) => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {roles.map((r) => {
        const on = r.key in value;
        return (
          <div key={r.key} className="row" style={{ padding: "4px 0" }}>
            <label className="chk f">
              <input type="checkbox" checked={on} onChange={(e) => {
                const v = { ...value };
                if (e.target.checked) v[r.key] = null; else delete v[r.key];
                onChange(v);
              }} />
              <span><b>{r.name_ar}</b> <span className="mu">{r.description}</span></span>
            </label>
            {on && (
              <label className="chk mu">حتى
                <input className="inp" type="date" style={{ height: 32, width: 150 }} value={toLocal(value[r.key])}
                  onChange={(e) => onChange({ ...value, [r.key]: fromLocal(e.target.value) })} aria-label={`انتهاء دور ${r.name_ar}`} />
              </label>
            )}
          </div>
        );
      })}
      <span className="mu">يمكن اختيار أكثر من دور. اترك التاريخ فارغًا لدور دائم.</span>
    </div>
  );
}

function NewUser({ roles, onCreated }: { roles: Role[]; onCreated: () => Promise<void> }) {
  const [f, setF] = useState({ email: "", full_name: "" });
  const [sel, setSel] = useState<Record<string, string | null>>({ journalist: null });
  const [link, setLink] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setLink("");
    try {
      const r = await api<{ invite_token: string }>("/api/admin/users", { method: "POST", body: { ...f, roles: Object.entries(sel).map(([key, expires_at]) => ({ key, expires_at })) } });
      setLink(inviteLink(r.invite_token)); setF({ email: "", full_name: "" });
      await onCreated();
    } catch (x) { setErr((x as Error).message); }
  };
  return (
    <section className="card">
      <h2>إضافة مستخدم</h2>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <label className="fld">الاسم<input className="inp" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></label>
        <label className="fld">البريد<input className="inp" type="email" dir="ltr" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        <fieldset style={{ border: "none", padding: 0, margin: 0 }}><legend style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>الأدوار</legend>
          <RolePicker roles={roles} value={sel} onChange={setSel} />
        </fieldset>
        {err && <div className="msg err">{err}</div>}
        <button className="btn pri" disabled={!Object.keys(sel).length}>إنشاء ودعوة</button>
      </form>
      {link && <InviteBox link={link} />}
    </section>
  );
}

function InviteBox({ link }: { link: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="msg ok" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <span>رابط الدعوة صالح 7 أيام. انسخه وأرسله بنفسك؛ البرنامج لا يرسل بريدًا باسمك.</span>
      <code className="blk">{link}</code>
      <button className="btn sm" onClick={() => navigator.clipboard?.writeText(link).then(() => setCopied(true))}>{copied ? "نُسخ" : "نسخ الرابط"}</button>
    </div>
  );
}

function UserEditor({ user, roles, perms, onSaved }: { user: U; roles: Role[]; perms: Perm[]; onSaved: () => Promise<void> }) {
  const { me, refresh } = useSession();
  const [sel, setSel] = useState<Record<string, string | null>>(Object.fromEntries(user.roles.map((r) => [r.key, r.expires_at])));
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [link, setLink] = useState("");
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); await onSaved(); if (user.id === me?.id) await refresh(); setMsg({ kind: "ok", text: ok }); }
    catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const fromRoles = new Set(user.roles.filter((r) => r.active).flatMap((r) => r.permissions));
  const ov = Object.fromEntries(user.overrides.map((o) => [o.permission, o.effect]));
  const groups = [...new Set(perms.map((p) => p.group))];

  return (
    <section className="card">
      <h2>{user.full_name || user.email}</h2>
      {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}
      <h3>الأدوار</h3>
      <RolePicker roles={roles} value={sel} onChange={setSel} />
      <div><button className="btn pri" onClick={() => run(() => api(`/api/admin/users/${user.id}/roles`, { method: "PUT", body: { roles: Object.entries(sel).map(([key, expires_at]) => ({ key, expires_at })) } }), "حُفظت الأدوار.")}>حفظ الأدوار</button></div>

      <h3>صلاحيات فردية فوق الأدوار</h3>
      <span className="mu">«من الأدوار» يتبع أدواره. «منح» يضيف صلاحية دون دور جديد، و«سحب» يمنعها حتى لو منحها أحد أدواره.</span>
      {groups.map((g) => (
        <div key={g}>
          <div className="mu" style={{ fontWeight: 700, margin: "8px 0 4px" }}>{g}</div>
          <div className="perm-grid">
            {perms.filter((p) => p.group === g).map((p) => {
              const cur = ov[p.key] ?? "";
              const effective = user.effective.includes(p.key);
              return (
                <label key={p.key} className="chk" style={{ justifyContent: "space-between" }}>
                  <span>{effective ? "✓" : "✗"} {p.ar}{!cur && fromRoles.has(p.key) && <span className="mu"> (من دور)</span>}</span>
                  <select className="inp" style={{ height: 30, width: 120, fontSize: 12 }} value={cur}
                    onChange={(e) => run(() => api(`/api/admin/users/${user.id}/permissions`, { method: "PUT", body: { permission: p.key, effect: e.target.value || null } }), "حُفظ الاستثناء.")}>
                    <option value="">من الأدوار</option>
                    <option value="grant">منح</option>
                    <option value="deny">سحب</option>
                  </select>
                </label>
              );
            })}
          </div>
        </div>
      ))}

      <h3>الحساب</h3>
      <div className="tabs">
        <button className="btn sm" onClick={() => run(async () => { const r = await api<{ invite_token: string }>(`/api/admin/users/${user.id}/invite`, { method: "POST" }); setLink(inviteLink(r.invite_token)); }, "أُنشئ رابط جديد.")}>رابط دعوة جديد</button>
        {user.locked && <button className="btn sm" onClick={() => run(() => api(`/api/admin/users/${user.id}/unlock`, { method: "POST" }), "فُتح الحساب.")}>فتح القفل</button>}
        {user.totp_enabled && <button className="btn sm" onClick={() => run(() => api(`/api/admin/users/${user.id}/totp`, { method: "DELETE" }), "أُعيد ضبط التحقق بخطوتين.")}>إعادة ضبط التحقق بخطوتين</button>}
        <button className={`btn sm ${user.is_active ? "danger" : ""}`} onClick={() => run(() => api(`/api/admin/users/${user.id}/active`, { method: "PUT", body: { active: !user.is_active } }), user.is_active ? "أُوقف الحساب." : "فُعّل الحساب.")}>{user.is_active ? "إيقاف الحساب" : "تفعيل الحساب"}</button>
      </div>
      {link && <InviteBox link={link} />}
    </section>
  );
}
