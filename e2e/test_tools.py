"""الحالات 55 و59 من الواجهة، ومرور على «أدوات التحقق»: رقم رسمي يظهر مقارنةً على بطاقة الادّعاء، وبطاقة النشر بعد الاعتماد، والوعود."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("MARSAD_E2E_URL", "http://localhost:8000")
SHOTS = Path(os.environ.get("MARSAD_E2E_SHOTS", "e2e/screenshots"))
INSECURE = os.environ.get("MARSAD_E2E_INSECURE") == "1"
H = {"X-Marsad": "1"}
ADMIN = {"email": "ghayth@example.com", "password": "correct-horse-1", "full_name": "غيث"}


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=INSECURE, viewport={"width": 1440, "height": 900})
        if ctx.request.get(f"{BASE}/api/setup").json()["needs_setup"]:
            assert ctx.request.post(f"{BASE}/api/setup", data=ADMIN, headers=H).ok
        else:
            assert ctx.request.post(f"{BASE}/api/auth/login", data=ADMIN, headers=H).ok
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # إضافة رقم رسمي من الواجهة
        page.goto(f"{BASE}/tools/figures")
        page.get_by_label("المؤشر", exact=True).fill("نسبة الفقر")
        page.get_by_label("القيمة", exact=True).fill("24.1")
        page.get_by_label("الوحدة", exact=True).fill("٪")
        page.get_by_label("التاريخ", exact=True).fill("2026")
        page.get_by_label("كلمات تدل عليه في الأخبار (بفواصل)").fill("الفقر")
        page.get_by_role("button", name="إضافة").click()
        expect(page.get_by_role("cell", name="نسبة الفقر")).to_be_visible()
        # ادّعاء برقم مختلف: المقارنة تظهر على بطاقته
        cid = ctx.request.post(f"{BASE}/api/claims", data={"text": "نسبة الفقر في المملكة تجاوزت 40٪ هذا العام"}, headers=H).json()["id"]
        page.goto(f"{BASE}/claims/{cid}")
        expect(page.get_by_role("heading", name="الأرقام الرسمية")).to_be_visible()
        expect(page.get_by_text("فرق +66")).to_be_visible()
        expect(page.get_by_role("heading", name="بطاقة النتيجة للنشر")).to_have_count(0)  # قبل الاعتماد
        ctx.request.post(f"{BASE}/api/claims/{cid}/verdict", data={"label": "مضلل", "evidence_grade": "مؤشر قوي",
                                                                    "explanation": "آخر رقم رسمي 24.1٪."}, headers=H)
        assert ctx.request.post(f"{BASE}/api/claims/{cid}/approve", data={"approve": True}, headers=H).ok
        page.reload()
        expect(page.get_by_role("img", name="بطاقة: مضلل")).to_be_visible()
        page.get_by_role("button", name="عمودية").click()
        size = page.evaluate("() => { const c = document.querySelector('canvas'); return [c.width, c.height]; }")
        assert size == [1080, 1920], size
        page.screenshot(path=SHOTS / "110-claim-tools.png", full_page=True)
        # الوعود
        page.goto(f"{BASE}/tools/promises")
        page.get_by_label("صاحب الوعد").fill("أمين عمّان")
        page.get_by_label("نص الوعد").fill("سنفتتح خط الحافلات السريع الجديد قبل الصيف")
        page.get_by_role("button", name="ابدأ المتابعة").click()
        expect(page.get_by_text("بدأت المتابعة")).to_be_visible()
        expect(page.get_by_text("«سنفتتح خط الحافلات السريع الجديد قبل الصيف»")).to_be_visible()
        page.screenshot(path=SHOTS / "111-promises.png", full_page=True)
        assert not errors, errors
        browser.close()
    print("E2E أدوات التحقق: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
