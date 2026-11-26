import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { ApiAccess } from "./ApiAccess";
import { api } from "../../api";
import { useCan } from "../../session";
import { Roles } from "./Roles";
import { Settings } from "./System";
import { Users } from "./Users";

export function Admin() {
  const can = useCan();
  const tabs = [
    { to: "users", label: "المستخدمون", ok: can("users.manage") },
    { to: "roles", label: "الأدوار", ok: can("users.manage") },
    { to: "settings", label: "التخزين والإعدادات", ok: can("system.manage") || can("users.manage") },
    { to: "audit", label: "سجل التدقيق", ok: can("audit.view") },
    { to: "api", label: "الواجهة البرمجية", ok: can("api.manage") },
  ].filter((t) => t.ok);
  if (!tabs.length) return <div className="msg err">لا تملك صلاحية لهذه الصفحة. اطلبها من المدير.</div>;
  return (
    <>
      <nav className="tabs" aria-label="أقسام الإدارة">
        {tabs.map((t) => <NavLink key={t.to} to={t.to} className={({ isActive }) => (isActive ? "on" : "") + (t.to === "api" ? " adv" : "")}>{t.label}</NavLink>)}
      </nav>
      <Routes>
        <Route index element={<Navigate to={tabs[0].to} replace />} />
        {can("users.manage") && <Route path="users" element={<Users />} />}
        {can("users.manage") && <Route path="roles" element={<Roles />} />}
        <Route path="settings" element={<Settings />} />
        {can("audit.view") && <Route path="audit" element={<Audit />} />}
        {can("api.manage") && <Route path="api" element={<ApiAccess />} />}
      </Routes>
    </>
  );
}

type A = { id: number; at: string; actor_id: number | null; action: string; target_type: string; target_id: string; before: unknown; after: unknown; ip: string };

const ACTIONS: Record<string, string> = {
  "login.success": "دخول", "login.failed": "محاولة دخول فاشلة", "login.lockout": "قفل الحساب بعد محاولات خاطئة", "login.locked": "محاولة على حساب مقفل",
  "user.role.assign": "إسناد دور", "user.role.remove": "سحب دور", "user.roles.set": "تعديل الأدوار", "user.permission": "صلاحية فردية",
  "role.create": "إنشاء دور", "role.permissions": "تعديل صلاحيات دور", "role.delete": "حذف دور", "invite.create": "دعوة", "invite.accepted": "قبول دعوة",
  "user.activate": "تفعيل حساب", "user.deactivate": "إيقاف حساب", "storage.request": "طلب تغيير مكان التخزين", "setting.change": "تغيير إعداد",
};

function Audit() {
  const [rows, setRows] = useState<A[]>([]);
  useEffect(() => { api<A[]>("/api/admin/audit").then(setRows); }, []);
  return (
    <section className="card">
      <h2>سجل التدقيق</h2>
      <div className="tw">
        <table>
          <thead><tr><th>الوقت</th><th>الحدث</th><th>المنفّذ</th><th>الهدف</th><th>التفاصيل</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td dir="ltr" style={{ whiteSpace: "nowrap" }}>{r.at.slice(0, 19).replace("T", " ")}</td>
                <td>{ACTIONS[r.action] ?? r.action}</td>
                <td>{r.actor_id ?? "—"}</td>
                <td>{r.target_type} {r.target_id}</td>
                <td className="mu" dir="ltr" style={{ fontSize: 11 }}>{r.after ? JSON.stringify(r.after) : r.before ? JSON.stringify(r.before) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
