import { describe, expect, it } from "vitest";
import { fmtPublished } from "./time";

// 18:45 بتوقيت غرينتش = 21:45 في عمّان = 20:45 في القاهرة (شتاءً)
const ISO = "2026-11-24T18:45:00Z";

describe("وقت النشر بتوقيت بلد الموقع", () => {
  it("يذكر البلد مع الوقت", () => {
    const s = fmtPublished(ISO, false, { published_tz: "Africa/Cairo", published_tz_label: "مصر" });
    expect(s).toContain("بتوقيت مصر");
    expect(s).toMatch(/[8٨]:[4٤][5٥]/);
  });
  it("يضيف وقت جهازك حين يختلف", () => {
    const s = fmtPublished(ISO, false, { published_tz: "Africa/Cairo", published_tz_label: "مصر" });
    const mine = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (mine !== "Africa/Cairo") expect(s).toContain("بتوقيت جهازك");
  });
  it("ينبّه حين يكون البلد غير مسجّل", () => {
    expect(fmtPublished(ISO, false, { published_tz: "Asia/Amman", published_tz_label: "الأردن", published_tz_assumed: true }))
      .toContain("بلد الموقع غير مسجّل");
    expect(fmtPublished(ISO, false, { published_tz: "Asia/Amman", published_tz_label: "الأردن", published_tz_assumed: true }, true))
      .not.toContain("غير مسجّل");
  });
  it("التاريخ دون ساعة لا يخترع ساعة", () => {
    expect(fmtPublished("2026-11-24T00:00:00Z", true, { published_tz: "Africa/Cairo", published_tz_label: "مصر" })).toContain("الساعة غير معلنة");
  });
});
