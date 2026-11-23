import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, type Me } from "../api";
import { DEFAULT_FRAME, Frame } from "../components/Frame";
import { useSession } from "../session";

function AuthCard({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <Frame prefs={DEFAULT_FRAME}>
      <div className="center">
        <div className="card auth">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="logo" aria-hidden="true" style={{ margin: 0 }}>م</span>
            <div><h2 style={{ fontSize: 18 }}>{title}</h2>{sub && <span className="mu">{sub}</span>}</div>
          </div>
          {children}
        </div>
      </div>
    </Frame>
  );
}

function useSubmit(fn: () => Promise<void>) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try { await fn(); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  };
  return { err, busy, onSubmit };
}

export function Setup() {
  const { setMe } = useSession();
  const nav = useNavigate();
  const [f, setF] = useState({ full_name: "", email: "", password: "", confirm: "" });
  const { err, busy, onSubmit } = useSubmit(async () => {
    if (f.password !== f.confirm) throw new Error("كلمتا المرور غير متطابقتين");
    setMe(await api<Me>("/api/setup", { method: "POST", body: { full_name: f.full_name, email: f.email, password: f.password } }));
    nav("/me?welcome=1");
  });
  return (
    <AuthCard title="مرحبًا بك في مرصد التحقق" sub="أنشئ حساب المدير لتبدأ">
      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label className="fld">الاسم<input className="inp" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} autoComplete="name" /></label>
        <label className="fld">البريد<input className="inp" type="email" required dir="ltr" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="email" /></label>
        <label className="fld">كلمة المرور (10 أحرف على الأقل)<input className="inp" type="password" required minLength={10} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></label>
        <label className="fld">تأكيد كلمة المرور<input className="inp" type="password" required value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} autoComplete="new-password" /></label>
        {err && <div className="msg err" role="alert">{err}</div>}
        <button className="btn pri" disabled={busy}>إنشاء حساب المدير</button>
      </form>
    </AuthCard>
  );
}

export function Login() {
  const { setMe } = useSession();
  const [f, setF] = useState({ email: "", password: "", totp: "" });
  const [needTotp, setNeedTotp] = useState(false);
  const { err, busy, onSubmit } = useSubmit(async () => {
    try {
      setMe(await api<Me>("/api/auth/login", { method: "POST", body: { ...f, totp: f.totp || null } }));
    } catch (e) {
      if ((e as Error).message.includes("رمز التحقق")) setNeedTotp(true);
      throw e;
    }
  });
  return (
    <AuthCard title="تسجيل الدخول" sub="مرصد التحقق">
      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label className="fld">البريد<input className="inp" type="email" required dir="ltr" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="username" /></label>
        <label className="fld">كلمة المرور<input className="inp" type="password" required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="current-password" /></label>
        {needTotp && (
          <label className="fld">رمز التحقق بخطوتين<input className="inp" inputMode="numeric" dir="ltr" autoFocus value={f.totp} onChange={(e) => setF({ ...f, totp: e.target.value })} autoComplete="one-time-code" /></label>
        )}
        {err && <div className="msg err" role="alert">{err}</div>}
        <button className="btn pri" disabled={busy}>دخول</button>
      </form>
    </AuthCard>
  );
}

export function AcceptInvite() {
  const { setMe } = useSession();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [f, setF] = useState({ password: "", confirm: "" });
  const { err, busy, onSubmit } = useSubmit(async () => {
    if (f.password !== f.confirm) throw new Error("كلمتا المرور غير متطابقتين");
    setMe(await api<Me>("/api/invite/accept", { method: "POST", body: { token: params.get("token") ?? "", password: f.password } }));
    nav("/me?welcome=1");
  });
  return (
    <AuthCard title="قبول الدعوة" sub="اختر كلمة مرورك، ثم واجهتك">
      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label className="fld">كلمة المرور (10 أحرف على الأقل)<input className="inp" type="password" required minLength={10} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></label>
        <label className="fld">تأكيد كلمة المرور<input className="inp" type="password" required value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} autoComplete="new-password" /></label>
        {err && <div className="msg err" role="alert">{err}</div>}
        <button className="btn pri" disabled={busy}>متابعة</button>
      </form>
    </AuthCard>
  );
}
