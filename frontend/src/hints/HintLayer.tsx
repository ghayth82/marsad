// طبقة التلميحات: فقاعة تشرح وظيفة العنصر عند الوقوف عليه أو التركيز عليه أو لمسه.
// تعمل على كل الشاشات من قاموس واحد (hints/data.ts) دون تعديل كل صفحة، وتُطفأ وتُشغَّل من زر «التلميحات».
import { useEffect, useRef, useState } from "react";
import { GLOSSARY, HINT_PREFIX, HINTS, WHY_DISABLED, WHY_GENERIC } from "./data";

const SELECTOR = "button, a.btn, .tabs a, nav.nav a, h2, h3, label.fld, label.chk, .pill, th, dt, summary > b, .seg button, [data-hint], .term";
const MARKED = "h2, h3, label.fld"; // تظهر بجانبها علامة ⓘ

/** النص الظاهر للعنصر نفسه (دون نص الحقول والعناصر التي بداخله). */
function ownText(el: Element): string {
  let t = "";
  el.childNodes.forEach((n) => { if (n.nodeType === Node.TEXT_NODE) t += n.textContent; });
  t = t.replace(/\s+/g, " ").trim();
  if (!t && el.children.length <= 2 && !el.querySelector("input,select,textarea")) t = (el.textContent ?? "").replace(/\s+/g, " ").trim();
  return t.replace(/[:：]$/, "").trim();
}

export function hintFor(el: Element): string {
  const explicit = el.getAttribute("data-hint");
  if (explicit) return explicit;
  if (el.classList.contains("term")) return GLOSSARY[el.getAttribute("data-term") ?? ownText(el)] ?? "";
  const t = ownText(el);
  if (!t || t.length > 70) return "";
  if (el instanceof HTMLButtonElement && el.disabled) return el.getAttribute("data-why") ?? WHY_DISABLED[t] ?? WHY_GENERIC;
  if (HINTS[t]) return HINTS[t];
  const p = HINT_PREFIX.find(([k]) => t.startsWith(k));
  return p ? p[1] : "";
}

type Tip = { text: string; x: number; y: number; below: boolean };

export function HintLayer({ on }: { on: boolean }) {
  const [tip, setTip] = useState<Tip | null>(null);
  const cur = useRef<Element | null>(null);

  // علامة ⓘ بجانب العناوين والحقول التي لها تلميح
  useEffect(() => {
    if (!on) { document.querySelectorAll("[data-h]").forEach((e) => e.removeAttribute("data-h")); setTip(null); return; }
    let timer = 0;
    const mark = () => {
      document.querySelectorAll(MARKED).forEach((e) => {
        const has = !!hintFor(e);
        if (has !== e.hasAttribute("data-h")) has ? e.setAttribute("data-h", "") : e.removeAttribute("data-h");
      });
    };
    const obs = new MutationObserver(() => { clearTimeout(timer); timer = window.setTimeout(mark, 150); });
    obs.observe(document.body, { childList: true, subtree: true, characterData: true });
    mark();
    return () => { obs.disconnect(); clearTimeout(timer); };
  }, [on]);

  useEffect(() => {
    if (!on) return;
    const show = (target: EventTarget | null) => {
      const el = target instanceof Element ? target.closest(SELECTOR) : null;
      if (!el || el === cur.current) { if (!el) hide(); return; }
      const text = hintFor(el);
      if (!text) { hide(); return; }
      cur.current = el;
      const r = el.getBoundingClientRect();
      const below = r.top < 90;
      setTip({ text, x: Math.min(Math.max(r.left + r.width / 2, 150), innerWidth - 150), y: below ? r.bottom + 8 : r.top - 8, below });
    };
    const hide = () => { cur.current = null; setTip(null); };
    const over = (e: Event) => show(e.target);
    const out = (e: PointerEvent) => { if (cur.current && !(e.relatedTarget instanceof Node && cur.current.contains(e.relatedTarget))) hide(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };
    document.addEventListener("pointerover", over, true);
    document.addEventListener("pointerout", out, true);
    document.addEventListener("focusin", over, true);
    document.addEventListener("focusout", hide, true);
    document.addEventListener("keydown", key, true);
    addEventListener("scroll", hide, true);
    return () => {
      document.removeEventListener("pointerover", over, true);
      document.removeEventListener("pointerout", out, true);
      document.removeEventListener("focusin", over, true);
      document.removeEventListener("focusout", hide, true);
      document.removeEventListener("keydown", key, true);
      removeEventListener("scroll", hide, true);
    };
  }, [on]);

  if (!on || !tip) return null;
  return (
    <div className="hint-bubble" role="tooltip" style={{ left: tip.x, top: tip.y, transform: `translate(-50%, ${tip.below ? "0" : "-100%"})` }}>
      {tip.text}
    </div>
  );
}

/** مصطلح تقني مشروح: خط منقّط تحته، والوقوف عليه يشرحه. */
export function Term({ k, children }: { k: string; children?: React.ReactNode }) {
  return <span className="term" data-term={k} tabIndex={0}>{children ?? k}</span>;
}
