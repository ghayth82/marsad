"""قائمة الصلاحيات والأدوار الجاهزة.

الصلاحية مفتاح ثابت بالإنجليزية (يُستخدم في الكود) مع اسم عربي (يظهر للمدير).
أي قسم جديد يضيف صلاحياته هنا فقط.
"""

from __future__ import annotations

PERMISSIONS: dict[str, dict[str, str]] = {
    "sources.view": {"ar": "عرض المصادر", "group": "المصادر والرصد"},
    "sources.manage": {"ar": "إضافة المصادر وتعديلها وحذفها", "group": "المصادر والرصد"},
    "monitor.view": {"ar": "الرصد والبحث", "group": "المصادر والرصد"},
    "claims.create": {"ar": "إنشاء ادّعاء", "group": "التحقق"},
    "verdicts.propose": {"ar": "اقتراح حكم", "group": "التحقق"},
    "verdicts.approve": {"ar": "اعتماد حكم", "group": "التحقق"},
    "labs.use": {"ar": "استخدام مختبرات الصور والفيديو والصوت", "group": "التحقق"},
    "cases.create": {"ar": "إنشاء قضية", "group": "التحقيق والقصة"},
    "stories.write": {"ar": "كتابة قصة", "group": "التحقيق والقصة"},
    "stories.approve": {"ar": "اعتماد قصة", "group": "التحقيق والقصة"},
    "ratings.view": {"ar": "عرض تقييم المواقع", "group": "التقييم"},
    "ratings.configure": {"ar": "تعديل منهجية التقييم وأوزانه", "group": "التقييم"},
    "ratings.approve": {"ar": "اعتماد التقييم", "group": "التقييم"},
    "data.export": {"ar": "تصدير البيانات", "group": "البيانات"},
    "engines.use": {"ar": "استخدام محركات الذكاء الاصطناعي", "group": "المحركات"},
    "engines.manage": {"ar": "إدارة المحركات ومفاتيحها وحدود الإنفاق", "group": "المحركات"},
    "training.participate": {"ar": "حل التمارين", "group": "التدريب"},
    "training.manage": {"ar": "إنشاء التمارين وتصحيحها", "group": "التدريب"},
    "users.manage": {"ar": "إدارة المستخدمين والأدوار والصلاحيات", "group": "الإدارة"},
    "system.manage": {"ar": "إدارة التخزين والنظام والإعدادات", "group": "الإدارة"},
    "audit.view": {"ar": "عرض سجل التدقيق", "group": "الإدارة"},
}

ADMIN_PERMISSION = "users.manage"

_JOURNALIST = ["sources.view", "monitor.view", "claims.create", "verdicts.propose", "labs.use",
               "cases.create", "stories.write", "ratings.view", "engines.use"]

BUILTIN_ROLES: list[dict] = [
    {"key": "admin", "name_ar": "المدير", "name_en": "Administrator", "priority": 10,
     "description": "كل شيء: المستخدمون، المحركات ومفاتيحها، حدود الإنفاق، المنهجية",
     "permissions": list(PERMISSIONS)},
    {"key": "editor", "name_ar": "المحرّر", "name_en": "Editor", "priority": 20,
     "description": "اعتماد الأحكام والتقارير قبل النشر، إدارة المصادر",
     "permissions": _JOURNALIST + ["sources.manage", "verdicts.approve", "stories.approve",
                                   "ratings.approve", "data.export"]},
    {"key": "journalist", "name_ar": "الصحفي", "name_en": "Journalist", "priority": 30,
     "description": "الرصد، التحقق، القضايا التي يعمل عليها، مسودات القصص",
     "permissions": _JOURNALIST},
    {"key": "researcher", "name_ar": "الباحث", "name_en": "Researcher", "priority": 40,
     "description": "قراءة البيانات والمؤشرات وتصديرها للبحث العلمي",
     "permissions": ["sources.view", "monitor.view", "ratings.view", "data.export"]},
    {"key": "trainee", "name_ar": "المتدرّب", "name_en": "Trainee", "priority": 50,
     "description": "الوضع التدريبي فقط، بتمارين مصحّحة",
     "permissions": ["training.participate"]},
]
