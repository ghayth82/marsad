// الرجوع والتقدّم داخل البرنامج: سهمان ثابتان، وAlt+← وAlt+→، وزرّا الفأرة الجانبيان،
// والعودة إلى الموضع نفسه في الصفحة عند الرجوع (لا إلى أعلاها).
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router-dom";

const positions = new Map<string, number>(); // موضع التمرير لكل خطوة في السجل

const idx = () => (window.history.state as { idx?: number } | null)?.idx ?? 0;

export function HistoryNav({ en }: { en: boolean }) {
  const nav = useNavigate();
  const loc = useLocation();
  const type = useNavigationType();
  const maxIdx = useRef(idx());
  const [, force] = useState(0);

  // آخر خطوة وصلها المستخدم: التقدّم ممكن ما دمنا قبلها
  useEffect(() => {
    if (type === "PUSH") maxIdx.current = idx();
    else maxIdx.current = Math.max(maxIdx.current, idx());
    force((n) => n + 1);
  }, [loc.key, type]);

  // حفظ موضع التمرير قبل مغادرة الصفحة، واستعادته عند الرجوع إليها (ننتظر تحميل بياناتها)
  useEffect(() => {
    const key = loc.key;
    const save = () => positions.set(key, scrollY);
    addEventListener("scroll", save, { passive: true });
    return () => { save(); removeEventListener("scroll", save); };
  }, [loc.key]);
  useLayoutEffect(() => {
    if (type !== "POP") { if (!new URLSearchParams(loc.search).has("item")) scrollTo({ top: 0 }); return; }
    const y = positions.get(loc.key);
    if (y == null) return;
    let tries = 0;
    const t = setInterval(() => {
      if (document.documentElement.scrollHeight - innerHeight >= y || ++tries > 30) { scrollTo({ top: y }); clearInterval(t); }
    }, 50);
    return () => clearInterval(t);
  }, [loc.key, type, loc.search]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        nav(e.key === "ArrowLeft" ? -1 : 1);  // كما في كل المتصفحات: Alt+← رجوع، Alt+→ تقدّم
      }
    };
    const mouse = (e: MouseEvent) => {
      if (e.button === 3) { e.preventDefault(); nav(-1); }
      if (e.button === 4) { e.preventDefault(); nav(1); }
    };
    addEventListener("keydown", key);
    addEventListener("mouseup", mouse);
    return () => { removeEventListener("keydown", key); removeEventListener("mouseup", mouse); };
  }, [nav]);

  const canBack = idx() > 0;
  const canFwd = idx() < maxIdx.current;
  return (
    <div className="seg hist" role="group" aria-label={en ? "History" : "التنقل"}>
      <button disabled={!canBack} onClick={() => nav(-1)} title={en ? "Back (Alt+←)" : "رجوع (Alt+←)"} aria-label={en ? "Back" : "رجوع"}>{en ? "←" : "→"}</button>
      <button disabled={!canFwd} onClick={() => nav(1)} title={en ? "Forward (Alt+→)" : "تقدّم (Alt+→)"} aria-label={en ? "Forward" : "تقدّم"}>{en ? "→" : "←"}</button>
    </div>
  );
}
