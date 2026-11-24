"""الحالات 60–63 من الواجهة: إسناد ادّعاء بأولوية ومهلة، لوحة سير العمل و«مهامي»، رمز وصول يظهر مرة واحدة، وسجل التصحيحات وصفحته العامة."""

from __future__ import annotations

import os
import re
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
        me = ctx.request.get(f"{BASE}/api/me").json()
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        import time

        text = f"ادّعاء لفحص سير العمل رقم {int(time.time())}: تأجيل الامتحانات الوزارية أسبوعين"
        cid = ctx.request.post(f"{BASE}/api/claims", data={"text": text}, headers=H).json()["id"]
        page.goto(f"{BASE}/claims/{cid}")
        wf = page.get_by_role("region", name="سير العمل")
        wf.get_by_label("الأولوية").select_option("urgent")
        expect(wf.get_by_text("حُفظ.")).to_be_visible()
        wf.get_by_label("المُسند إليه").select_option(str(me["id"]))
        expect(wf.get_by_text("المهلة:")).to_be_visible()
        page.goto(f"{BASE}/")
        expect(page.get_by_role("link", name=text).first).to_be_visible()
        page.goto(f"{BASE}/tools/workflow")
        expect(page.get_by_role("region", name="مُسند").get_by_text(text)).to_be_visible()
        page.screenshot(path=SHOTS / "120-workflow.png", full_page=True)
        # رمز وصول يظهر مرة واحدة ويعمل
        page.goto(f"{BASE}/admin/api")
        page.get_by_label("الاسم").fill("نظام النشر التجريبي")
        page.get_by_role("button", name="إنشاء").click()
        tok = page.locator("code.blk").inner_text()
        assert tok.startswith("mrs_")
        r = ctx.request.get(f"{BASE}/api/v1/verdicts", headers={"Authorization": f"Bearer {tok}"})
        assert r.ok and "verdicts" in r.json()
        page.get_by_role("button", name="نسختُه").click()
        expect(page.locator("code.blk")).to_have_count(0)
        page.screenshot(path=SHOTS / "121-api.png", full_page=True)
        # تصحيح حكم معتمد يظهر في السجل وصفحته العامة
        c2 = ctx.request.post(f"{BASE}/api/claims", data={"text": "صورة لجسر منهار في الطريق الصحراوي صباح اليوم"}, headers=H).json()["id"]
        ctx.request.post(f"{BASE}/api/claims/{c2}/verdict", data={"label": "مفبرك", "evidence_grade": "مؤشر قوي", "explanation": "الصورة من بلد آخر عام 2023."}, headers=H)
        ctx.request.post(f"{BASE}/api/claims/{c2}/approve", data={"approve": True}, headers=H)
        page.goto(f"{BASE}/claims/{c2}")
        fld = lambda t: page.locator("label.fld").filter(has_text=re.compile(rf"^{t}"))  # noqa: E731
        fld("الحكم").locator("select").select_option("صحيح جزئيًا")
        fld("درجة الدليل").locator("select").select_option("مؤشر قوي")
        fld("الشرح").locator("textarea").fill("الجسر انهار فعلًا لكن في طريق آخر.")
        expect(page.get_by_role("button", name="اقتراح تصحيح")).to_be_disabled()
        page.get_by_label("سبب التصحيح (يظهر في سجل التصحيحات)").fill("وصلت صورة أصلية من الدفاع المدني")
        page.get_by_role("button", name="اقتراح تصحيح").click()
        page.get_by_role("button", name="اعتماد").click()
        page.goto(f"{BASE}/tools/corrections")
        expect(page.get_by_text("وصلت صورة أصلية من الدفاع المدني", exact=False)).to_be_visible()
        if page.get_by_role("button", name="فعّل الصفحة العامة").count():
            page.get_by_role("button", name="فعّل الصفحة العامة").click()
            expect(page.get_by_role("button", name="أطفئ الصفحة العامة")).to_be_visible()
        anon = browser.new_context(ignore_https_errors=INSECURE).new_page()
        anon.goto(f"{BASE}/public/corrections")
        expect(anon.get_by_role("heading", name="سجل التصحيحات")).to_be_visible()
        expect(anon.get_by_text("صورة لجسر منهار", exact=False)).to_be_visible()
        assert "غيث" not in anon.content()
        anon.screenshot(path=SHOTS / "122-public-corrections.png", full_page=True)
        assert not errors, errors
        browser.close()
    print("E2E أدوات المؤسسات: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
