import { useEffect, useState, type ReactNode } from "react";
import type { Prefs } from "../api";

/** يطبّق نمط المستخدم (أ/ب/ج)، الفاتح أو الداكن، حجم الخط، واتجاه اللغة. */
export function Frame({ prefs, children }: { prefs: Pick<Prefs, "pattern" | "theme" | "language" | "font_scale">; children: ReactNode }) {
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq?.addEventListener("change", on);
    return () => mq?.removeEventListener("change", on);
  }, []);
  useEffect(() => {
    document.documentElement.lang = prefs.language;
    document.documentElement.dir = prefs.language === "ar" ? "rtl" : "ltr";
  }, [prefs.language]);
  const dark = prefs.pattern !== "a" && (prefs.theme === "dark" || (prefs.theme === "system" && systemDark));
  return (
    <div className="app" data-pattern={prefs.pattern} data-dark={dark ? "1" : "0"} style={{ ["--scale" as string]: prefs.font_scale }}>
      {children}
    </div>
  );
}

export const DEFAULT_FRAME = { pattern: "c", theme: "system", language: "ar", font_scale: 1 } as const;
