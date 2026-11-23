import { useState } from "react";
import QRCode from "qrcode";
import { useSearchParams } from "react-router-dom";
import { api, type Prefs } from "../api";
import { DASHBOARD_CARDS } from "./Dashboard";
import { useSession } from "../session";

export function Preferences() {
  const { me, savePrefs, logout, refresh, setMe } = useSession();
  const [params] = useSearchParams();
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  if (!me) return null;
  const p = me.preferences;

  const save = async (c: Partial<Prefs>) => {
    setMsg(null);
    try { await savePrefs(c); setMsg({ kind: "ok", text: "حُفظ. يتبعك هذا الاختيار إلى أي جهاز تدخل منه." }); }
    catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const reset = async () => {
    const prefs = await api<Prefs>("/api/me/preferences", { method: "DELETE" });
    setMe({ ...me, preferences: prefs });
    setMsg({ kind: "ok", text: "عادت واجهتك إلى ما حدده المدير لدورك." });
  };
  const toggleCard = (k: string) =>
    save({ dashboard: p.dashboard.includes(k) ? p.dashboard.filter((x) => x !== k) : [...p.dashboard, k] });
  const move = (k: string, d: -1 | 1) => {
    const arr = [...p.dashboard];
    const i = arr.indexOf(k), j = i + d;
    if (j < 0 || j >= arr.length) return;
    [arr[i], arr[j]] = [arr[j], arr[i]];
    save({ dashboard: arr });
  };

  return (
    <div className="cols">
      <div className="grow">
        {params.get("welcome") && <div className="msg ok">أهلًا بك. اختر واجهتك؛ يمكنك تغييرها متى شئت من هنا.</div>}
        {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}
        <section className="card">
          <h2>واجهتي</h2>
          <div className="g4">
            <label className="fld">النمط
              <select className="inp" value={p.pattern} onChange={(e) => save({ pattern: e.target.value as Prefs["pattern"] })}>
                <option value="c">ج · مساحة التحقيق</option>
                <option value="b">ب · تحريري فاتح</option>
                <option value="a">أ · غرفة الأخبار الليلية</option>
              </select>
            </label>
            <label className="fld">الإضاءة
              <select className="inp" value={p.theme} disabled={p.pattern === "a"} onChange={(e) => save({ theme: e.target.value as Prefs["theme"] })}>
                <option value="system">حسب الجهاز</option>
                <option value="light">فاتح</option>
                <option value="dark">داكن</option>
              </select>
              {p.pattern === "a" && <span className="mu">النمط أ داكن دائمًا</span>}
            </label>
            <label className="fld">اللغة
              <select className="inp" value={p.language} onChange={(e) => save({ language: e.target.value as Prefs["language"] })}>
                <option value="ar">العربية</option>
                <option value="en">English</option>
              </select>
            </label>
            <label className="fld">حجم الخط: {Math.round(p.font_scale * 100)}٪
              <input type="range" min={0.8} max={1.6} step={0.05} value={p.font_scale} onChange={(e) => save({ font_scale: Number(e.target.value) })} />
            </label>
          </div>
        </section>

        <section className="card">
          <h2>لوحتي الرئيسية</h2>
          <span className="mu">اختر البطاقات التي تظهر لك ورتّبها.</span>
          {p.dashboard.map((k, i) => (
            <div className="row" key={k}>
              <span className="f">{DASHBOARD_CARDS[k] ?? k}</span>
              <button className="btn sm" disabled={i === 0} onClick={() => move(k, -1)} aria-label="أعلى">↑</button>
              <button className="btn sm" disabled={i === p.dashboard.length - 1} onClick={() => move(k, 1)} aria-label="أسفل">↓</button>
              <button className="btn sm" onClick={() => toggleCard(k)}>إخفاء</button>
            </div>
          ))}
          <div className="tabs">
            {Object.entries(DASHBOARD_CARDS).filter(([k]) => !p.dashboard.includes(k)).map(([k, label]) => (
              <button key={k} className="btn sm" onClick={() => toggleCard(k)}>+ {label}</button>
            ))}
          </div>
        </section>

        <section className="card">
          <h2>التنبيهات</h2>
          <div className="tabs">
            {([["in_app", "داخل البرنامج"], ["telegram", "تيليغرام"], ["email", "البريد"]] as const).map(([k, l]) => (
              <label key={k} className="chk">
                <input type="checkbox" checked={p.alerts.channels.includes(k)}
                  onChange={(e) => save({ alerts: { ...p.alerts, channels: e.target.checked ? [...p.alerts.channels, k] : p.alerts.channels.filter((x) => x !== k) } })} />
                {l}
              </label>
            ))}
            <label className="chk">
              <input type="checkbox" checked={p.alerts.urgent_only} onChange={(e) => save({ alerts: { ...p.alerts, urgent_only: e.target.checked } })} />
              العاجل فقط
            </label>
          </div>
        </section>
        <div><button className="btn" onClick={reset}>إرجاع واجهتي إلى قالب دوري</button></div>
      </div>

      <div className="side">
        <section className="card">
          <h2>أدواري وصلاحياتي</h2>
          {me.access.roles.map((r) => (
            <div className="row" key={r.key}>
              <span className="f">{r.name_ar}{r.expires_at && <span className="mu"> · حتى {new Date(r.expires_at).toLocaleDateString("ar")}</span>}</span>
              {!r.active && <span className="pill p-n">منتهٍ</span>}
            </div>
          ))}
          <details>
            <summary className="mu">ما أستطيع فعله ({me.access.effective.length})</summary>
            <ul style={{ margin: "8px 0", paddingInlineStart: 18, fontSize: 13 }}>
              {me.access.effective.map((x) => <li key={x}>{me.permission_labels[x] ?? x}</li>)}
            </ul>
          </details>
        </section>
        <Security onChange={refresh} />
        <button className="btn" onClick={logout}>تسجيل الخروج</button>
      </div>
    </div>
  );
}

function Security({ onChange }: { onChange: () => Promise<void> }) {
  const { me } = useSession();
  const [qr, setQr] = useState<{ img: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState({ old: "", new: "" });
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const run = async (fn: () => Promise<void>, ok: string) => {
    setMsg(null);
    try { await fn(); setMsg({ kind: "ok", text: ok }); } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  return (
    <section className="card">
      <h2>الأمان</h2>
      {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}
      {me?.totp_enabled ? (
        <span className="pill p-ok">التحقق بخطوتين مفعّل</span>
      ) : qr ? (
        <>
          <span className="mu">امسح الرمز بتطبيق المصادقة في هاتفك، ثم أدخل الرقم الذي يظهر.</span>
          <img src={qr.img} alt="رمز QR للتحقق بخطوتين" width={180} height={180} style={{ background: "#fff", padding: 6, borderRadius: 8 }} />
          <label className="fld">الرمز<input className="inp" dir="ltr" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} /></label>
          <button className="btn pri" onClick={() => run(async () => { await api("/api/me/totp/confirm", { method: "POST", body: { code } }); setQr(null); await onChange(); }, "فُعّل التحقق بخطوتين.")}>تأكيد</button>
        </>
      ) : (
        <button className="btn" onClick={() => run(async () => {
          const { otpauth_uri } = await api<{ otpauth_uri: string }>("/api/me/totp/start", { method: "POST" });
          setQr({ uri: otpauth_uri, img: await QRCode.toDataURL(otpauth_uri, { margin: 1, width: 360 }) });
        }, "")}>تفعيل التحقق بخطوتين</button>
      )}
      <form style={{ display: "flex", flexDirection: "column", gap: 8 }} onSubmit={(e) => { e.preventDefault(); run(async () => { await api("/api/me/password", { method: "POST", body: pw }); setPw({ old: "", new: "" }); }, "تغيّرت كلمة المرور."); }}>
        <h3>تغيير كلمة المرور</h3>
        <label className="fld">الحالية<input className="inp" type="password" required value={pw.old} onChange={(e) => setPw({ ...pw, old: e.target.value })} autoComplete="current-password" /></label>
        <label className="fld">الجديدة<input className="inp" type="password" required minLength={10} value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} autoComplete="new-password" /></label>
        <button className="btn">حفظ</button>
      </form>
    </section>
  );
}
