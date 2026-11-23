"""فحص المتصفح لبطاقة الادّعاء: تسجيل ← دليل قاطع ← اقتراح حكم ← اعتماد ← ClaimReview."""

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


def field(page, label):
    import re

    return page.locator("label.fld").filter(has_text=re.compile(rf"^\s*{label}"))


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
        page.goto(f"{BASE}/rumors")
        page.get_by_label("نص الادّعاء").fill("صورة تُظهر طوابير طويلة أمام محطات الوقود صباح اليوم")
        page.get_by_role("button", name="تسجيل وفتح البطاقة").click()
        expect(page.get_by_text("«صورة تُظهر طوابير طويلة أمام محطات الوقود صباح اليوم»")).to_be_visible()
        page.get_by_label("عنوان الدليل").fill("البصمة البصرية تطابق صورة منشورة في مارس 2024")
        page.get_by_label("نوع الدليل").select_option("check")
        page.get_by_label("درجة الدليل", exact=True).select_option("قاطع")
        page.get_by_role("checkbox", name="دليل قاطع (نتيجة فحص)").check()
        page.get_by_role("button", name="إضافة دليل").click()
        expect(page.get_by_text("أُضيف الدليل.")).to_be_visible()
        field(page, "الحكم").locator("select").select_option("مضلل")
        field(page, "درجة الدليل").locator("select").select_option("قاطع")
        field(page, "الشرح").locator("textarea").fill("الصورة من مارس 2024، وأُعيد نشرها على أنها من اليوم.")
        page.get_by_role("button", name="اقتراح الحكم").click()
        expect(page.get_by_text("بانتظار الاعتماد")).to_be_visible()
        page.get_by_role("button", name="اعتماد", exact=True).click()
        expect(page.get_by_text("حكم معتمد")).to_be_visible()
        expect(page.locator("summary", has_text="ClaimReview")).to_be_visible()
        page.screenshot(path=SHOTS / "30-claim-card.png", full_page=True)
        browser.close()
    print("E2E الادّعاء: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
