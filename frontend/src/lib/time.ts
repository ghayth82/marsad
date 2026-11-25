// عرض الأوقات. وقت النشر يُعرض بتوقيت بلد الموقع مع اسمه («9:45 م بتوقيت مصر»)، ومعه وقت جهازك حين يختلف.
// وقت النشر قد يكون تاريخًا دون ساعة (خرائط بعض المواقع)، فلا نخترع له ساعة.

export const fmtTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("ar", { dateStyle: "short", timeStyle: "short" }) : "—";

export type PubTz = { published_tz?: string; published_tz_label?: string; published_tz_assumed?: boolean };

const fmtIn = (d: Date, tz: string | undefined, withDate: boolean) => {
  try {
    return d.toLocaleString("ar", { ...(withDate ? { dateStyle: "short" as const } : {}), timeStyle: "short", ...(tz ? { timeZone: tz } : {}) });
  } catch {
    return d.toLocaleString("ar", { ...(withDate ? { dateStyle: "short" as const } : {}), timeStyle: "short" });
  }
};

/** «24/11/2026، 9:45 م بتوقيت مصر (10:45 م بتوقيت جهازك)». compact: دون التوضيح الزائد في القوائم. */
export function fmtPublished(iso: string | null | undefined, dateOnly?: boolean, tz?: PubTz, compact?: boolean): string {
  if (!iso) return "—";
  const d = new Date(iso);
  // التاريخ دون ساعة محفوظ عند منتصف الليل بتوقيت غرينتش؛ نعرض اليوم نفسه دون تحويله لتوقيت آخر
  if (dateOnly) return `${d.toLocaleDateString("ar", { dateStyle: "short", timeZone: "UTC" })} (الساعة غير معلنة)`;
  if (!tz?.published_tz) return fmtTime(iso);
  const there = fmtIn(d, tz.published_tz, true);
  const label = `بتوقيت ${tz.published_tz_label ?? ""}`.trim();
  const mineTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const differs = fmtIn(d, tz.published_tz, false) !== fmtIn(d, mineTz, false);
  const assumed = tz.published_tz_assumed && !compact ? " (بلد الموقع غير مسجّل؛ يُفترض توقيت الأردن)" : "";
  return `${there} ${label}${assumed}${differs ? ` (${fmtIn(d, mineTz, false)} بتوقيت جهازك)` : ""}`;
}
