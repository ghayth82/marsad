"""فحص المتصفح لموصلات التواصل: تظهر منتظرة، يُحفظ المفتاح مشفّرًا ولا يُعرض، ولوحة مؤشرات الحملات في الشائعات."""

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
        page.goto(f"{BASE}/admin/settings")
        card = page.get_by_label("موصلات التواصل")
        expect(card).to_contain_text("ينتظر مزوّدًا")
        row = card.locator("[data-platform='x']")
        row.get_by_label("مزوّد X (تويتر)").select_option("official")
        row.get_by_label("Bearer token X (تويتر)").fill("AAAA-test-bearer-token-9876")
        row.get_by_role("button", name="حفظ").click()
        expect(row.get_by_role("status")).to_contain_text("حُفظ")
        expect(row).to_contain_text("الواجهة الرسمية")
        expect(row).to_contain_text("…9876")  # المفتاح مقنّعًا، بعد أن تعيد الصفحة تحميل الحالة
        assert "AAAA-test-bearer-token-9876" not in page.content()
        page.screenshot(path=SHOTS / "70-social-providers.png", full_page=True)
        row.get_by_label("مزوّد X (تويتر)").select_option("")
        row.get_by_role("button", name="حفظ").click()
        expect(row.get_by_role("status")).to_contain_text("أُوقف")
        page.goto(f"{BASE}/rumors")
        expect(page.get_by_label("الحملات المنسّقة")).to_contain_text("مؤشرات")
        browser.close()
    print("E2E موصلات التواصل: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
