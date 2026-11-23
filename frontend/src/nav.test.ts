import { describe, expect, it } from "vitest";
import { visibleSections } from "./nav";
import type { Access } from "./api";

const role = (key: string, permissions: string[], active = true) => ({ key, name_ar: key, expires_at: null, active, permissions });

describe("الأقسام حسب الأدوار", () => {
  it("المتدرّب يرى الرئيسية والتدريب فقط", () => {
    const a: Access = { roles: [role("trainee", ["training.participate"])], overrides: [], effective: ["training.participate"] };
    expect(visibleSections(a, null).map((s) => s.path)).toEqual(["/", "/training"]);
  });

  it("دوران معًا يجمعان الأقسام، و«عرض كـ» يركّز على دور واحد", () => {
    const j = ["sources.view", "monitor.view", "claims.create", "labs.use"];
    const r = ["sources.view", "monitor.view", "ratings.view", "data.export"];
    const a: Access = { roles: [role("journalist", j), role("researcher", r)], overrides: [], effective: [...new Set([...j, ...r])] };
    const all = visibleSections(a, null).map((s) => s.path);
    expect(all).toContain("/claims");
    expect(all).toContain("/ratings");
    const asResearcher = visibleSections(a, "researcher").map((s) => s.path);
    expect(asResearcher).not.toContain("/claims");
    expect(asResearcher).toContain("/ratings");
  });

  it("الصلاحية المسحوبة فرديًا لا تعود عبر «عرض كـ»", () => {
    const a: Access = { roles: [role("researcher", ["ratings.view", "data.export"])], overrides: [], effective: ["data.export"] };
    expect(visibleSections(a, "researcher").map((s) => s.path)).not.toContain("/ratings");
  });

  it("الإدارة تظهر لمن يملك إدارة المستخدمين وحدها", () => {
    const a: Access = { roles: [], overrides: [], effective: ["users.manage"] };
    expect(visibleSections(a, null).map((s) => s.path)).toContain("/admin");
  });
});
