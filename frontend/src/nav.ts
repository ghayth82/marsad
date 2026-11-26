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
  { path: "/", ar: "الرئيسية", en: "Home", any: [], group: "home", icon: "🏠" },
  { path: "/sources", ar: "المصادر", en: "Sources", any: ["sources.view"], group: "watch", icon: "📡" },
  { path: "/live", ar: "الرصد", en: "Monitor", any: ["monitor.view"], group: "watch", icon: "📰" },
  { path: "/stories", ar: "القصص", en: "Stories", any: ["monitor.view"], group: "watch", icon: "🧩" },
  { path: "/rumors", ar: "الادّعاءات والشائعات", en: "Claims", any: ["monitor.view", "claims.create", "verdicts.propose", "verdicts.approve"], group: "verify", icon: "🔎" },
  // بطاقة الادّعاء (/claims/رقم) تُفتح من القسم أعلاه؛ لا بند مستقل لها في القائمة
  { path: "/claims", ar: "بطاقة الادّعاء", en: "Claim", any: ["claims.create", "verdicts.propose", "verdicts.approve"], group: "verify", icon: "🔎", hidden: true },
  { path: "/media-lab", ar: "الصور والفيديو", en: "Media lab", any: ["labs.use"], group: "verify", icon: "🖼️" },
  { path: "/audio-lab", ar: "الصوت", en: "Audio lab", any: ["labs.use"], group: "verify", icon: "🎙️" },
  { path: "/tools", ar: "أدوات التحقق", en: "Tools", any: ["claims.create", "monitor.view", "labs.use", "cases.create", "verdicts.propose", "verdicts.approve"], group: "verify", icon: "🧰" },
  { path: "/cases", ar: "التحقيقات", en: "Investigations", any: ["cases.create"], group: "write", icon: "🗂️" },
  { path: "/story-builder", ar: "بناء القصة", en: "Story builder", any: ["stories.write", "stories.approve"], group: "write", icon: "✍️" },
  { path: "/entities", ar: "الأشخاص والجهات", en: "People & orgs", any: ["monitor.view"], group: "write", icon: "👥" },
  { path: "/reports", ar: "التقارير", en: "Reports", any: ["monitor.view"], group: "follow", icon: "📋" },
  { path: "/stats", ar: "الإحصاءات", en: "Statistics", any: ["stats.view"], group: "follow", icon: "📊" },
  { path: "/ratings", ar: "تقييم المواقع", en: "Outlet ratings", any: ["ratings.view", "ratings.configure"], group: "follow", icon: "⚖️" },
  { path: "/engines", ar: "الذكاء الاصطناعي", en: "AI engines", any: ["engines.use", "engines.manage"], group: "setup", icon: "🤖" },
  { path: "/training", ar: "التدريب", en: "Training", any: ["training.participate", "training.manage"], group: "setup", icon: "🎓" },
  { path: "/admin", ar: "الإدارة", en: "Admin", any: ["users.manage", "system.manage", "audit.view", "api.manage"], group: "setup", icon: "⚙️" },
  { path: "/help", ar: "الدليل", en: "Help", any: [], group: "setup", icon: "❓" },
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
