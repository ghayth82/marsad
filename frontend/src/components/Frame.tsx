import { useEffect, useState, type ReactNode } from "react";
import { DEFAULT_APPEARANCE, type Prefs } from "../api";

const FONTS: Record<string, string> = {
  noto: "'Noto Sans Arabic',sans-serif",
  naskh: "'Noto Naskh Arabic','Noto Sans Arabic',serif",
  plex: "'IBM Plex Sans Arabic',sans-serif",
  readex: "'Readex Pro','IBM Plex Sans Arabic',sans-serif",
};
const LEADING = { normal: 1.7, comfy: 2, wide: 2.3 } as const;
const WIDTH = { narrow: "620px", medium: "760px", full: "100%" } as const;

/** يطبّق مظهر المستخدم: فاتح أو داكن، الخط وحجمه، القراءة، لون التمييز، التباين، الكثافة، واتجاه اللغة. */
export function Frame({ prefs, children }: { prefs: Pick<Prefs, "pattern" | "theme" | "language" | "font_scale"> & { appearance?: Prefs["appearance"] }; children: ReactNode }) {
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
  const a = { ...DEFAULT_APPEARANCE, ...(prefs.appearance ?? {}) };
  // النمط «أ» القديم كان داكنًا دائمًا: يبقى داكنًا لمن اختاره ما لم يختر «فاتح» صراحة
  const dark = prefs.theme === "dark" || (prefs.theme === "system" && (systemDark || prefs.pattern === "a"));
  return (
    <div className="app" data-pattern="c" data-dark={dark ? "1" : "0"} data-accent={a.accent} data-contrast={a.contrast ? "1" : "0"}
      data-density={a.density} data-hints={a.hints ? "1" : "0"}
      style={{
        ["--scale" as string]: prefs.font_scale, ["--font" as string]: FONTS[a.font] ?? FONTS.noto,
        ["--read-scale" as string]: a.read_scale, ["--read-leading" as string]: LEADING[a.leading], ["--read-width" as string]: WIDTH[a.read_width],
      }}>
      {children}
    </div>
  );
}

export const DEFAULT_FRAME = { pattern: "c", theme: "system", language: "ar", font_scale: 1, appearance: DEFAULT_APPEARANCE } as const;
