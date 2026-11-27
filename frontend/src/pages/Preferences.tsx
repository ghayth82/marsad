import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { useSearchParams } from "react-router-dom";
import { api, DEFAULT_APPEARANCE, type Appearance, type Prefs } from "../api";
import { DASHBOARD_CARDS } from "./Dashboard";
import { useSession } from "../session";

const ACCENTS: [Appearance["accent"], string, string][] = [
  ["teal", "أخضر مزرق (الافتراضي)", "#0F766E"], ["blue", "أزرق", "#1F4FD1"], ["indigo", "نيلي", "#4F46E5"],
  ["purple", "بنفسجي", "#7E22CE"], ["graphite", "رمادي داكن", "#334155"],
];

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
  const a = { ...DEFAULT_APPEARANCE, ...(p.appearance ?? {}) };
  const ap = (c: Partial<Appearance>) => save({ appearance: c as Appearance, ...(p.pattern !== "c" ? { pattern: "c" as const } : {}) });
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
        {params.get("welcome") && <div className="msg ok">أهلًا بك. اختر مظهر واجهتك؛ يمكنك تغييره متى شئت من هنا.</div>}
        {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}
        <section className="card" aria-labelledby="ap-h">
          <h2 id="ap-h">مظهر الواجهة</h2>
          <span className="mu">يخصك وحدك، ويتبعك إلى أي جهاز تدخل منه. يتغير المثال أدناه فورًا.</span>
          <div className="ap-sample" aria-label="مثال">
            <b style={{ fontSize: "calc(18px * var(--read-scale,1))" }}>وزير الطاقة: لا رفع لأسعار المحروقات هذا الشهر</b>
            <p className="reader-text" style={{ margin: "6px 0 0", maxWidth: "var(--read-width)" }}>
              أكد وزير الطاقة في مؤتمر صحفي اليوم أن الحكومة لن ترفع أسعار المحروقات خلال تشرين الثاني، وأن اللجنة ستراجع الأسعار العالمية مطلع الشهر المقبل. (نص تجريبي)
            </p>
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}><button className="btn sm pri" type="button">زر رئيسي</button><a href="#ap-h">رابط</a></div>
          </div>
          <div className="g4">
            <label className="fld">الوضع
              <select className="inp" aria-label="الوضع" value={p.pattern === "a" && p.theme === "system" ? "dark" : p.theme} onChange={(e) => save({ theme: e.target.value as Prefs["theme"], pattern: "c" })}>
                <option value="light">فاتح</option>
                <option value="dark">داكن</option>
                <option value="system">حسب جهازي (يتبع إعداد ويندوز)</option>
              </select>
            </label>
            <label className="fld">اللغة
              <select className="inp" aria-label="اللغة" value={p.language} onChange={(e) => save({ language: e.target.value as Prefs["language"] })}>
                <option value="ar">العربية</option>
                <option value="en">English</option>
              </select>
            </label>
          </div>

          <h3>الخط</h3>
          <div className="g4">
            <label className="fld">حجم خط الواجهة كلها: {Math.round(p.font_scale * 100)}٪
              <input type="range" aria-label="حجم خط الواجهة" min={0.8} max={1.6} step={0.05} value={p.font_scale} onChange={(e) => save({ font_scale: Number(e.target.value) })} />
            </label>
            <label className="fld">نوع الخط
              <select className="inp" aria-label="نوع الخط" value={a.font} onChange={(e) => ap({ font: e.target.value as Appearance["font"] })}>
                <option value="noto">نوتو سانس: واضح للعمل اليومي</option>
                <option value="naskh">نوتو نسخ: خط الصحف والكتب</option>
                <option value="plex">بلكس: عصري ومضغوط</option>
                <option value="readex">ريدكس: عريض وسهل على الشاشات</option>
              </select>
            </label>
            <label className="fld">تباعد الأسطر في النصوص
              <select className="inp" aria-label="تباعد الأسطر" value={a.leading} onChange={(e) => ap({ leading: e.target.value as Appearance["leading"] })}>
                <option value="normal">عادي</option>
                <option value="comfy">مريح</option>
                <option value="wide">واسع</option>
              </select>
            </label>
          </div>

          <h3>قراءة الأخبار</h3>
          <div className="g4">
            <label className="fld">حجم نص الخبر وحده: {Math.round(a.read_scale * 100)}٪
              <input type="range" aria-label="حجم نص الخبر" min={0.8} max={1.8} step={0.05} value={a.read_scale} onChange={(e) => ap({ read_scale: Number(e.target.value) })} />
              <span className="mu">يكبّر الخبر في القارئ دون تكبير القوائم والأزرار.</span>
            </label>
            <label className="fld">عرض عمود الخبر (في ملء الشاشة والصفحة المستقلة)
              <select className="inp" aria-label="عرض عمود الخبر" value={a.read_width} onChange={(e) => ap({ read_width: e.target.value as Appearance["read_width"] })}>
                <option value="narrow">ضيق: أسطر قصيرة أريح للعين</option>
                <option value="medium">متوسط</option>
                <option value="full">بعرض الشاشة</option>
              </select>
            </label>
          </div>

          <h3>الألوان</h3>
          <div className="g4">
            <div className="fld">لون الأزرار والروابط
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }} role="group" aria-label="لون التمييز">
                {ACCENTS.map(([k, label, color]) => (
                  <button key={k} type="button" className="swatch" style={{ background: color }} aria-pressed={a.accent === k}
                    title={label} aria-label={label} onClick={() => ap({ accent: k })} />
                ))}
              </div>
              <span className="mu">الأخضر والبرتقالي والأحمر محجوزة لمعنى «يعمل» و«تنبيه» و«خطأ».</span>
            </div>
            <label className="chk"><input type="checkbox" aria-label="تباين عالٍ" checked={a.contrast} onChange={(e) => ap({ contrast: e.target.checked })} />تباين عالٍ: نص أغمق وحدود أوضح (للشاشات الضعيفة أو لمن يحتاج وضوحًا أكبر)</label>
          </div>

          <h3>المساعدة والتبسيط</h3>
          <div className="g4">
            <label className="chk"><input type="checkbox" aria-label="التلميحات" checked={a.hints} onChange={(e) => ap({ hints: e.target.checked })} />التلميحات: شرح قصير لكل زر وعنوان عند الوقوف عليه، وسطر تعريف أعلى كل صفحة (زر المصباح في الأعلى يفعل الشيء نفسه)</label>
            <label className="fld">طريقة العرض
              <select className="inp" aria-label="طريقة العرض" value={a.mode} onChange={(e) => ap({ mode: e.target.value as Appearance["mode"] })}>
                <option value="full">كامل: كل الخيارات</option>
                <option value="simple">مبسّط: يخفي الخيارات المتقدمة النادرة</option>
              </select>
            </label>
            <div><a className="btn" href="/?tour=1">أعد الجولة التعريفية</a></div>
          </div>

          <h3>أخرى</h3>
          <div className="g4">
            <label className="fld">كثافة العرض
              <select className="inp" aria-label="كثافة العرض" value={a.density} onChange={(e) => ap({ density: e.target.value as Appearance["density"] })}>
                <option value="comfortable">مريح: مسافات أوسع</option>
                <option value="compact">مضغوط: عناصر أكثر في الشاشة</option>
              </select>
            </label>
          </div>
          <div><button className="btn" type="button" onClick={() => save({ theme: "system", pattern: "c", font_scale: 1, appearance: DEFAULT_APPEARANCE })}>إرجاع المظهر الافتراضي</button></div>
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
            {([["in_app", "داخل البرنامج"], ["telegram", "تيليغرام"]] as const).map(([k, l]) => (
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
          <label className="chk">
            <input type="checkbox" checked={!!p.alerts.quiet_hours} onChange={(e) => save({ alerts: { ...p.alerts, quiet_hours: e.target.checked ? [22, 7] : null } })} />
            ساعات هدوء من 22:00 إلى 07:00 (إلا الشائعات العاجلة)
          </label>
          <TelegramLink />
          <label className="fld">مواضيع وكيانات أتابعها (تنبيه عند ظهورها، مفصولة بفاصلة)
            <input className="inp" defaultValue={[...(p.follows.topics ?? []), ...(p.follows.entities ?? [])].join("، ")} aria-label="ما أتابعه"
                   onBlur={(e) => save({ follows: { ...p.follows, topics: e.target.value.split(/[،,]/).map((x) => x.trim()).filter(Boolean), entities: [] } })} />
          </label>
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

function TelegramLink() {
  const [st, setSt] = useState<{ configured: boolean; username: string | null; linked: boolean } | null>(null);
  const [code, setCode] = useState<{ code: string; link: string | null } | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => api<typeof st>("/api/alerts/telegram").then(setSt).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!st) return null;
  if (!st.configured) return <span className="mu" style={{ fontSize: 12 }}>تنبيهات تيليغرام تعمل حين يضيف المدير بوت البرنامج.</span>;
  const check = async () => {
    try { const r = await api<{ linked: boolean; note?: string }>("/api/alerts/telegram/check", { method: "POST" }); setMsg(r.linked ? "رُبط حسابك." : r.note ?? ""); load(); }
    catch (x) { setMsg((x as Error).message); }
  };
  return (
    <div className="row" aria-label="ربط تيليغرام">
      {st.linked ? (
        <><span className="f">تيليغرام مربوط ({"@" + st.username})</span>
          <button className="btn sm" onClick={() => api("/api/alerts/test", { method: "POST" }).then(() => setMsg("أُرسل تنبيه تجريبي."))}>تنبيه تجريبي</button>
          <button className="btn sm" onClick={() => api("/api/alerts/telegram/link", { method: "DELETE" }).then(load)}>فك الربط</button></>
      ) : code ? (
        <><span className="f">افتح {code.link ? <a href={code.link} target="_blank" rel="noreferrer noopener">البوت</a> : "البوت"} واضغط «ابدأ» (أو أرسل <b dir="ltr">/start {code.code}</b>)، ثم:</span>
          <button className="btn sm" onClick={check}>تحقّق</button></>
      ) : <button className="btn sm" onClick={() => api<typeof code>("/api/alerts/telegram/link", { method: "POST" }).then(setCode)}>اربط تيليغرام</button>}
      {msg && <span className="mu" role="status">{msg}</span>}
    </div>
  );
}
