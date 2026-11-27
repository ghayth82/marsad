// أقسام البرنامج والصلاحية التي يتطلبها كل قسم.
// القسم يظهر إن كان للمستخدم أي صلاحية من صلاحياته.
import type { Access } from "./api";

export type Section = { path: string; ar: string; en: string; any: string[]; group: GroupKey; icon: string; hidden?: boolean };
export type GroupKey = "home" | "watch" | "verify" | "write" | "follow" | "setup";

/** مجموعات القائمة الجانبية بلغة ما يفعله المستخدم. */
export const GROUPS: { key: GroupKey; ar: string; en: string }[] = [
  { key: "home", ar: "", en: "" },
  { key: "watch", ar: "أرصد", en: "Monitor" },
  { key: "verify", ar: "أتحقق", en: "Verify" },
  { key: "write", ar: "أحقق وأكتب", en: "Investigate" },
  { key: "follow", ar: "أتابع", en: "Follow up" },
  { key: "setup", ar: "الإعداد", en: "Setup" },
];

export const SECTIONS: Section[] = [
  { path: "/", ar: "الرئيسية", en: "Home", any: [], group: "home", icon: "home" },
  { path: "/sources", ar: "المصادر", en: "Sources", any: ["sources.view"], group: "watch", icon: "sources" },
  { path: "/live", ar: "الرصد", en: "Monitor", any: ["monitor.view"], group: "watch", icon: "live" },
  { path: "/stories", ar: "القصة", en: "Stories", any: ["monitor.view"], group: "watch", icon: "stories" },
  { path: "/rumors", ar: "الشائعات", en: "Rumors", any: ["monitor.view", "claims.create"], group: "verify", icon: "rumors" },
  { path: "/claims", ar: "الادّعاء", en: "Claims", any: ["claims.create", "verdicts.propose", "verdicts.approve"], group: "verify", icon: "claims" },
  { path: "/media-lab", ar: "الصور والفيديو", en: "Media lab", any: ["labs.use"], group: "verify", icon: "media" },
  { path: "/audio-lab", ar: "الصوت", en: "Audio lab", any: ["labs.use"], group: "verify", icon: "audio" },
  { path: "/tools", ar: "أدوات التحقق", en: "Tools", any: ["claims.create", "monitor.view", "labs.use", "cases.create", "verdicts.propose", "verdicts.approve"], group: "verify", icon: "tools" },
  { path: "/cases", ar: "التحقيق", en: "Investigation", any: ["cases.create"], group: "write", icon: "cases" },
  { path: "/story-builder", ar: "بناء القصة", en: "Story builder", any: ["stories.write", "stories.approve"], group: "write", icon: "write" },
  { path: "/entities", ar: "الكيان", en: "Entities", any: ["monitor.view"], group: "write", icon: "entities" },
  { path: "/reports", ar: "التقارير", en: "Reports", any: ["monitor.view"], group: "follow", icon: "reports" },
  { path: "/stats", ar: "الإحصاءات", en: "Statistics", any: ["stats.view"], group: "follow", icon: "stats" },
  { path: "/ratings", ar: "التقييم", en: "Ratings", any: ["ratings.view", "ratings.configure"], group: "follow", icon: "ratings" },
  { path: "/engines", ar: "المحركات", en: "Engines", any: ["engines.use", "engines.manage"], group: "setup", icon: "engines" },
  { path: "/training", ar: "التدريب", en: "Training", any: ["training.participate", "training.manage"], group: "setup", icon: "training" },
  { path: "/admin", ar: "الإدارة", en: "Admin", any: ["users.manage", "system.manage", "audit.view", "api.manage"], group: "setup", icon: "admin" },
  { path: "/help", ar: "الدليل", en: "Help", any: [], group: "setup", icon: "help" },
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

/** بنود القائمة الجانبية (دون الشاشات التي تُفتح من داخل قسم آخر). */
export function navSections(access: Access, viewAsRole: string | null): Section[] {
  return visibleSections(access, viewAsRole).filter((x) => !x.hidden);
}
