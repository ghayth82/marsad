"""فحص المتصفح لتقييم المواقع: داخلي فقط، ترتيب ← بطاقة ← المواد خلف الرقم ← حق الرد ← المنهجية بإصدار جديد ← منع النشر.
يعتمد على مواد أدخلها فحص الرصد (test_monitoring.py) قبله."""

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
        page.goto(f"{BASE}/ratings")
        expect(page.get_by_role("note")).to_contain_text("داخلي فقط")
        expect(page.get_by_role("heading", name="الترتيب", exact=False)).to_be_visible()
        first = page.locator("table tbody tr").first
        expect(first).to_be_visible(timeout=30000)
        name = first.locator("td").first.inner_text()
        first.locator("a").click()
        expect(page.get_by_role("heading", name=f"بطاقة: {name}")).to_be_visible()
        page.get_by_role("button", name="أمثلة خلو العناوين من الإثارة").click()
        expect(page.get_by_label("المواد خلف الرقم")).to_contain_text("ترفع المؤشر")
        page.get_by_label("نص الاعتراض").fill("العنوان مطابق لبيان الجهة الرسمية")
        page.get_by_label("قناة الرد").fill("بريد")
        page.get_by_role("button", name="تسجيل الرد").click()
        expect(page.get_by_text("سُجّل الرد.")).to_be_visible()
        page.get_by_label("سبب القرار").fill("المادة لا تخص المؤشر")
        page.get_by_role("button", name="رفض").click()
        expect(page.get_by_text("سُجّل القرار.")).to_be_visible()
        page.screenshot(path=SHOTS / "50-ratings-card.png", full_page=True)

        page.goto(f"{BASE}/ratings/methodology")
        page.get_by_label("وزن الدقة").fill("30")
        page.get_by_label("سبب التغيير").fill("رفع وزن الدقة بعد مراجعة اللجنة")
        page.get_by_role("button", name="حفظ إصدار جديد").click()
        expect(page.get_by_role("status")).to_contain_text("حُفظ الإصدار")
        expect(page.get_by_text("رفع وزن الدقة بعد مراجعة اللجنة")).to_be_visible()
        page.screenshot(path=SHOTS / "51-ratings-methodology.png", full_page=True)

        r = ctx.request.post(f"{BASE}/api/ratings/publish", headers=H)
        assert r.status == 403, r.status
        page.goto(f"{BASE}/ratings/review")
        expect(page.get_by_label("الاتفاق")).to_contain_text("كوهين كابا")
        browser.close()
    print("E2E التقييم: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
