"""فحص من طرف إلى طرف في متصفح حقيقي (Playwright) لمسار الأساس:
أول تشغيل ← إضافة مستخدم بدورين ← قبول الدعوة ← واجهة كل مستخدم ← «عرض كـ» ← صلاحية فردية.

التشغيل: الخادم يعمل على MARSAD_E2E_URL (افتراضيًا http://localhost:8000) بقاعدة فارغة.
    python e2e/test_foundation.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("MARSAD_E2E_URL", "http://localhost:8000")
SHOTS = Path(os.environ.get("MARSAD_E2E_SHOTS", "e2e/screenshots"))
CHROME = os.environ.get("MARSAD_E2E_CHROME")  # مسار Chrome محلي إن وُجد
INSECURE = os.environ.get("MARSAD_E2E_INSECURE") == "1"  # شهادة داخلية (خادم الشبكة الداخلية)


def nav_items(page) -> list[str]:
    return [t.strip() for t in page.locator("nav.nav a").all_inner_texts()]


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME) if CHROME else p.chromium.launch()
        def page(w: int, h: int):
            return browser.new_context(viewport={"width": w, "height": h}, ignore_https_errors=INSECURE).new_page()

        admin = page(1440, 900)

        # 1) أول تشغيل: إنشاء المدير
        admin.goto(BASE)
        expect(admin.get_by_text("أنشئ حساب المدير لتبدأ")).to_be_visible()
        admin.get_by_label("الاسم").fill("غيث")
        admin.get_by_label("البريد").fill("ghayth@example.com")
        admin.get_by_label("كلمة المرور (10 أحرف على الأقل)").fill("correct-horse-1")
        admin.get_by_label("تأكيد كلمة المرور").fill("correct-horse-1")
        admin.get_by_role("button", name="إنشاء حساب المدير").click()
        expect(admin.get_by_text("أهلًا بك")).to_be_visible()
        assert "الإدارة" in nav_items(admin), nav_items(admin)
        admin.screenshot(path=SHOTS / "01-admin-preferences-c.png", full_page=True)

        # 2) المظهر يتغير ويُحفظ: زر الداكن في الأعلى، والخط والألوان من «تفضيلاتي»
        app = admin.locator(".app")
        start_dark = app.get_attribute("data-dark") == "1"
        admin.get_by_role("button", name="الوضع الفاتح" if start_dark else "الوضع الداكن").click()
        expect(app).to_have_attribute("data-dark", "0" if start_dark else "1")
        if not start_dark:
            admin.screenshot(path=SHOTS / "02-dark.png", full_page=True)
        admin.goto(f"{BASE}/me")
        admin.get_by_label("الوضع", exact=True).select_option("dark")
        expect(app).to_have_attribute("data-dark", "1")
        admin.get_by_role("button", name="أزرق", exact=True).click()
        expect(app).to_have_attribute("data-accent", "blue")
        admin.get_by_label("نوع الخط", exact=True).select_option("naskh")
        admin.get_by_label("كثافة العرض", exact=True).select_option("compact")
        admin.get_by_label("تباين عالٍ", exact=True).check()
        admin.screenshot(path=SHOTS / "02-appearance.png", full_page=True)
        admin.reload()
        expect(app).to_have_attribute("data-accent", "blue")
        expect(app).to_have_attribute("data-density", "compact")
        expect(app).to_have_attribute("data-contrast", "1")
        assert "Naskh" in app.evaluate("e => getComputedStyle(e).fontFamily")
        admin.get_by_role("button", name="إرجاع المظهر الافتراضي").click()
        expect(app).to_have_attribute("data-accent", "teal")
        expect(app).to_have_attribute("data-density", "comfortable")

        # 3) إضافة مستخدم بدوري صحفي وباحث
        admin.goto(f"{BASE}/admin/users")
        form = admin.locator("section.card", has=admin.get_by_role("heading", name="إضافة مستخدم"))
        form.get_by_label("الاسم").fill("سارة")
        form.get_by_label("البريد").fill("sara@example.com")
        form.get_by_role("checkbox", name="الباحث").check()  # الصحفي مختار افتراضيًا
        form.get_by_role("button", name="إنشاء ودعوة").click()
        link = form.locator("code.blk").inner_text()
        assert "/invite?token=" in link
        admin.screenshot(path=SHOTS / "03-admin-users.png", full_page=True)

        # 4) سارة تقبل الدعوة من جهاز آخر
        sara = page(1440, 900)
        sara.goto(link)
        sara.get_by_label("كلمة المرور (10 أحرف على الأقل)").fill("sara-password-1")
        sara.get_by_label("تأكيد كلمة المرور").fill("sara-password-1")
        sara.get_by_role("button", name="متابعة").click()
        expect(sara.get_by_text("أهلًا بك")).to_be_visible()
        items = nav_items(sara)
        assert "الادّعاء" in items and "التقييم" in items and "الإدارة" not in items, items
        # واجهة سارة مستقلة عن واجهة المدير (المدير غيّر لونه وكثافته، وسارة على الافتراضي)
        expect(sara.locator(".app")).to_have_attribute("data-accent", "teal")

        # 5) «عرض كـ» الباحث يخفي أقسام الصحفي
        sara.get_by_label("عرض كـ").select_option("researcher")
        expect(sara.locator("nav.nav a", has_text="الادّعاء")).to_have_count(0)
        expect(sara.locator("nav.nav a", has_text="التقييم")).to_have_count(1)
        sara.screenshot(path=SHOTS / "04-sara-view-as-researcher.png", full_page=True)
        sara.get_by_label("عرض كـ").select_option("")

        # 6) المدير يسحب صلاحية «عرض تقييم المواقع» من سارة فرديًا
        admin.goto(f"{BASE}/admin/users")
        admin.locator("tr", has_text="sara@example.com").get_by_role("button", name="تعديل").click()
        row = admin.locator("label.chk", has_text="عرض تقييم المواقع")
        row.locator("select").select_option("deny")
        expect(admin.get_by_text("حُفظ الاستثناء.")).to_be_visible()
        admin.screenshot(path=SHOTS / "05-admin-user-overrides.png", full_page=True)
        sara.reload()
        expect(sara.locator("nav.nav a", has_text="التقييم")).to_have_count(0)

        # 7) المحرّر لا يرى الإدارة، ورابطها المباشر يعيده للرئيسية
        sara.goto(f"{BASE}/admin/users")
        expect(sara).to_have_url(f"{BASE}/")

        # 8) عرض الهاتف
        phone = page(390, 844)
        phone.goto(BASE)
        phone.get_by_label("البريد").fill("ghayth@example.com")
        phone.get_by_label("كلمة المرور").fill("correct-horse-1")
        phone.get_by_role("button", name="دخول").click()
        expect(phone.locator("nav.nav")).to_be_visible()
        phone.screenshot(path=SHOTS / "06-phone.png", full_page=True)

        browser.close()
    print("E2E: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
