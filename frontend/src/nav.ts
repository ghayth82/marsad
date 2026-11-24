// أقسام البرنامج والصلاحية التي يتطلبها كل قسم.
// القسم يظهر إن كان للمستخدم أي صلاحية من صلاحياته.
import type { Access } from "./api";

export type Section = { path: string; ar: string; en: string; any: string[] };

export const SECTIONS: Section[] = [
  { path: "/", ar: "الرئيسية", en: "Home", any: [] },
  { path: "/sources", ar: "المصادر", en: "Sources", any: ["sources.view"] },
  { path: "/live", ar: "الرصد", en: "Monitor", any: ["monitor.view"] },
  { path: "/stories", ar: "القصة", en: "Stories", any: ["monitor.view"] },
  { path: "/rumors", ar: "الشائعات", en: "Rumors", any: ["monitor.view", "claims.create"] },
  { path: "/claims", ar: "الادّعاء", en: "Claims", any: ["claims.create", "verdicts.propose", "verdicts.approve"] },
  { path: "/tools", ar: "أدوات التحقق", en: "Tools", any: ["claims.create", "monitor.view", "labs.use", "cases.create", "verdicts.propose", "verdicts.approve"] },
  { path: "/media-lab", ar: "الصور والفيديو", en: "Media lab", any: ["labs.use"] },
  { path: "/audio-lab", ar: "الصوت", en: "Audio lab", any: ["labs.use"] },
  { path: "/entities", ar: "الكيان", en: "Entities", any: ["monitor.view"] },
  { path: "/cases", ar: "التحقيق", en: "Investigation", any: ["cases.create"] },
  { path: "/story-builder", ar: "بناء القصة", en: "Story builder", any: ["stories.write", "stories.approve"] },
  { path: "/ratings", ar: "التقييم", en: "Ratings", any: ["ratings.view", "ratings.configure"] },
  { path: "/engines", ar: "المحركات", en: "Engines", any: ["engines.use", "engines.manage"] },
  { path: "/reports", ar: "التقارير", en: "Reports", any: ["monitor.view"] },
  { path: "/stats", ar: "الإحصاءات", en: "Statistics", any: ["stats.view"] },
  { path: "/training", ar: "التدريب", en: "Training", any: ["training.participate", "training.manage"] },
  { path: "/admin", ar: "الإدارة", en: "Admin", any: ["users.manage", "system.manage", "audit.view", "api.manage"] },
  { path: "/help", ar: "الدليل", en: "Help", any: [] },
];

/** الصلاحيات التي تحكم ما يظهر: كلها، أو صلاحيات دور واحد عند «عرض الواجهة كـ». */
export function visiblePermissions(access: Access, viewAsRole: string | null): Set<string> {
  const effective = new Set(access.effective);
  if (!viewAsRole) return effective;
  const role = access.roles.find((r) => r.key === viewAsRole && r.active);
  if (!role) return effective;
  // صلاحيات الدور المختار فقط، ولا يتجاوز ما يملكه فعلًا (السحب الفردي يبقى ساريًا)
  return new Set(role.permissions.filter((p) => effective.has(p)));
}

export function visibleSections(access: Access, viewAsRole: string | null): Section[] {
  const perms = visiblePermissions(access, viewAsRole);
  return SECTIONS.filter((s) => s.any.length === 0 || s.any.some((p) => perms.has(p)));
}
