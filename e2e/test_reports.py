"""فحص المتصفح للتقارير والتدريب والدليل والرئيسية: موجز يُنشأ ويُقرأ، تمرين يُصحَّح ويظهر حله النموذجي، دليل يُبحث فيه."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("MARSAD_E2E_URL", "http://localhost:8000")
SHOTS = Path(os.environ.get("MARSAD_E2E_SHOTS", "e2e/screenshots"))
CHROME = os.environ.get("MARSAD_E2E_CHROME")
INSECURE = os.environ.get("MARSAD_E2E_INSECURE") == "1"
H = {"X-Marsad": "1"}
ADMIN = {"email": "ghayth@example.com", "password": "correct-horse-1", "full_name": "غيث"}


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME) if CHROME else p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=INSECURE)
        page = ctx.new_page()
        if ctx.request.get(f"{BASE}/api/setup").json()["needs_setup"]:
            assert ctx.request.post(f"{BASE}/api/setup", data=ADMIN, headers=H).ok
        else:
            assert ctx.request.post(f"{BASE}/api/auth/login", data=ADMIN, headers=H).ok
        page.goto(f"{BASE}/reports")
        page.get_by_role("button", name="موجز آخر 24 ساعة").click()
        page.get_by_role("link", name="الموجز الصباحي", exact=False).first.click()
        expect(page.get_by_role("heading", name="القصص الصاعدة")).to_be_visible()
        expect(page.get_by_text("مادة جديدة", exact=True)).to_be_visible()
        page.screenshot(path=SHOTS / "80-report.png", full_page=True)

        page.goto(f"{BASE}/")
        expect(page.locator("[data-card='daily_brief']")).to_contain_text("الموجز كاملًا")
        expect(page.locator("[data-card='sources_status']")).to_contain_text("مصدرًا")
        page.screenshot(path=SHOTS / "81-dashboard.png", full_page=True)

        page.goto(f"{BASE}/training")
        page.get_by_role("link", name="صورة «فيضان اليوم» في وسط المدينة").click()
        expect(page.get_by_label("مادة التمرين")).to_contain_text("شارع السوق")
        expect(page.get_by_label("الحل النموذجي")).to_be_visible()  # المدرّب يرى الحل دائمًا
        page.get_by_label("الحكم").select_option("مضلل")
        page.get_by_label("درجة الدليل").select_option("قاطع")
        page.get_by_label("التعليل").fill("الصورة لها نسخة أقدم في الأرشيف قبل اربع سنوات، والأرصاد تقول لا أمطار، والبيانات الوصفية لا تكفي.")
        page.get_by_role("button", name="تسليم").click()
        expect(page.get_by_label("النتيجة")).to_contain_text("100 / 100")
        page.screenshot(path=SHOTS / "82-training.png", full_page=True)

        page.goto(f"{BASE}/help")
        page.get_by_label("ابحث في الدليل").fill("C2PA")
        expect(page.get_by_role("heading", name="المختبرات")).to_be_visible()
        expect(page.get_by_role("heading", name="تقييم المواقع")).to_have_count(0)
        page.goto(f"{BASE}/me")
        expect(page.get_by_text("تنبيهات تيليغرام تعمل حين يضيف المدير بوت البرنامج.")).to_be_visible()
        page.goto(f"{BASE}/admin/settings")
        expect(page.get_by_label("بوت التنبيهات")).to_contain_text("@BotFather")
        expect(page.get_by_label("مواعيد التقارير")).to_be_visible()
        browser.close()
    print("E2E التقارير والتدريب والدليل: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
