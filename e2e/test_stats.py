"""الحالات 49–52 من الواجهة: صفحة «الإحصاءات» بلوحاتها الخمس، والنقر على رقم يفتح ما حُسب منه، وتقرير الأثر."""

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
        text = "ادّعاء لفحص الإحصاءات: ارتفاع البطالة إلى ثلاثين بالمئة"
        cid = ctx.request.post(f"{BASE}/api/claims", data={"text": text}, headers=H).json()["id"]
        api = ctx.request.get(f"{BASE}/api/stats?days=7").json()
        assert cid in api["verification"]["claims"]["drill"]["ids"]
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{BASE}/stats?days=7")
        expect(page.get_by_role("heading", name="توزيع الأحكام")).to_be_visible()
        page.get_by_role("button", name="ادّعاء ظهر في الفترة").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_role("link", name=text)).to_be_visible()
        page.screenshot(path=SHOTS / "100-stats-drill.png", full_page=True)
        dialog.get_by_role("button", name="إغلاق").click()
        # الموضوع: «اقتصاد» يُبقي الادّعاء، و«صحة» يخفيه
        page.get_by_label("الموضوع").select_option("اقتصاد")
        expect(page.get_by_role("button", name="ادّعاء ظهر في الفترة")).to_contain_text(str(
            ctx.request.get(f"{BASE}/api/stats?days=7&topic=اقتصاد").json()["verification"]["claims"]["n"]))
        page.get_by_label("الموضوع").select_option("")
        for tab, heading in (("الانتشار", "ساعات الذروة في النشر"), ("المصادر", "المصادر"), ("الفريق", "حجم العمل"), ("الأثر", "الطريقة")):
            page.get_by_role("navigation", name="اللوحات").get_by_role("link", name=tab).click()
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        page.screenshot(path=SHOTS / "101-stats-impact.png", full_page=True)
        r = ctx.request.get(f"{BASE}/api/stats/impact/print?days=7")
        assert r.ok and "تقرير الأثر" in r.text()
        assert not errors, errors
        browser.close()
    print("E2E الإحصاءات: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
