// «ابدأ من هنا»: ثلاث خطوات للمستخدم الجديد تُشطب حين تُنجز، و«ماذا تريد أن تفعل؟» يوصلك إلى الشاشة الصحيحة.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useCan } from "../session";

type G = { sources: number; items: number; claims: number; media: number };
const KEY = "marsad.getstarted.hidden";

export function GetStarted({ onTour }: { onTour: () => void }) {
  const can = useCan();
  const [g, setG] = useState<G | null>(null);
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } });
  useEffect(() => { api<G>("/api/me/getting-started").then(setG).catch(() => {}); }, []);
  if (!g || hidden) return null;
  const steps = [
    can("sources.manage") && { done: g.sources > 0, text: "أضف أول مصدر تتابعه", to: "/sources", go: "أضف مصدرًا" },
    can("monitor.view") && { done: g.items > 0, text: "اقرأ أول خبر مرصود", to: "/live", go: "افتح الرصد" },
    can("claims.create") && { done: g.claims > 0, text: "سجّل أول ادّعاء للتحقق منه", to: "/rumors", go: "سجّل ادّعاءً" },
    can("labs.use") && { done: g.media > 0, text: "افحص أول صورة أو فيديو", to: "/media-lab", go: "افحص صورة" },
  ].filter(Boolean) as { done: boolean; text: string; to: string; go: string }[];
  if (!steps.length || steps.every((s) => s.done)) return null;
  const hide = () => { try { localStorage.setItem(KEY, "1"); } catch { /* */ } setHidden(true); };
  return (
    <section className="card start-card" aria-labelledby="gs-h">
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <h2 id="gs-h" style={{ flex: 1 }} data-hint="خطوات البداية. تختفي البطاقة حين تنجزها كلها.">ابدأ من هنا</h2>
        <button className="btn sm" onClick={onTour} data-hint="جولة قصيرة تعرّفك بالبرنامج في دقيقة.">جولة تعريفية</button>
        <button className="btn sm" onClick={hide} data-hint="أخفِ هذه البطاقة. الجولة تبقى متاحة من «الدليل».">إخفاء</button>
      </div>
      {steps.map((s, k) => (
        <div key={s.to} className="row">
          <span className={`pill ${s.done ? "p-ok" : "p-n"}`} aria-hidden="true">{s.done ? "✓" : k + 1}</span>
          <span className="f" style={s.done ? { textDecoration: "line-through", color: "var(--mu)" } : undefined}>{s.text}</span>
          {!s.done && <Link className="btn sm pri" to={s.to}>{s.go}</Link>}
        </div>
      ))}
    </section>
  );
}

const GOALS: { perm: string; icon: string; text: string; to: string }[] = [
  { perm: "sources.manage", icon: "📡", text: "أتابع موقعًا أو قناة", to: "/sources" },
  { perm: "monitor.view", icon: "📰", text: "أقرأ آخر الأخبار", to: "/live" },
  { perm: "claims.create", icon: "🔎", text: "أتحقق من خبر أو شائعة", to: "/rumors" },
  { perm: "labs.use", icon: "🖼️", text: "أتحقق من صورة أو فيديو", to: "/media-lab" },
  { perm: "labs.use", icon: "🎙️", text: "أتحقق من تسجيل صوتي", to: "/audio-lab" },
  { perm: "monitor.view", icon: "👥", text: "أبحث عن شخص أو جهة", to: "/entities" },
  { perm: "cases.create", icon: "🗂️", text: "أعمل على تحقيق", to: "/cases" },
  { perm: "monitor.view", icon: "🗄️", text: "أحفظ صفحة قبل أن تُحذف", to: "/tools/archive" },
];

export function Goals() {
  const can = useCan();
  const goals = GOALS.filter((x) => can(x.perm));
  if (!goals.length) return null;
  return (
    <section className="card" aria-labelledby="goals-h">
      <h2 id="goals-h" data-hint="اختر ما تريد فعله فيأخذك البرنامج إلى الشاشة المناسبة.">ماذا تريد أن تفعل؟</h2>
      <div className="goal-grid">
        {goals.map((x) => <Link key={x.text} className="goal" to={x.to}><span aria-hidden="true">{x.icon}</span>{x.text}</Link>)}
      </div>
    </section>
  );
}
