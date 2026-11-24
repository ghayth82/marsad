// عرض الأوقات: وقت النشر قد يكون تاريخًا دون ساعة (خرائط بعض المواقع)، فلا نخترع له ساعة.

export const fmtTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("ar", { dateStyle: "short", timeStyle: "short" }) : "—";

export function fmtPublished(iso: string | null | undefined, dateOnly?: boolean): string {
  if (!iso) return "—";
  // التاريخ دون ساعة محفوظ عند منتصف الليل بتوقيت غرينتش؛ نعرض اليوم نفسه دون تحويله لتوقيت آخر
  return dateOnly ? `${new Date(iso).toLocaleDateString("ar", { dateStyle: "short", timeZone: "UTC" })} (الساعة غير معلنة)` : fmtTime(iso);
}
