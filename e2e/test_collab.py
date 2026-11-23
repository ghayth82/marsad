"""الحالة 40 في المتصفح: مستخدمان على بطاقة الادّعاء نفسها يرى كل منهما الآخر، وتعديل الحقل نفسه لا يمحو تعديل الآخر."""

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
EDITOR = {"email": "collab-editor@example.com", "password": "editor-password-1"}


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME) if CHROME else p.chromium.launch()
        a = browser.new_context(viewport={"width": 1280, "height": 860}, ignore_https_errors=INSECURE)
        b = browser.new_context(viewport={"width": 1280, "height": 860}, ignore_https_errors=INSECURE)
        if a.request.get(f"{BASE}/api/setup").json()["needs_setup"]:
            assert a.request.post(f"{BASE}/api/setup", data=ADMIN, headers=H).ok
        else:
            assert a.request.post(f"{BASE}/api/auth/login", data=ADMIN, headers=H).ok
        if not b.request.post(f"{BASE}/api/auth/login", data={"email": EDITOR["email"], "password": EDITOR["password"]}, headers=H).ok:
            inv = a.request.post(f"{BASE}/api/admin/users", data={"email": EDITOR["email"], "full_name": "المحرّر",
                                                                  "roles": [{"key": "editor"}]}, headers=H).json()
            assert b.request.post(f"{BASE}/api/invite/accept", data={"token": inv["invite_token"], "password": EDITOR["password"]}, headers=H).ok
        cid = a.request.post(f"{BASE}/api/claims", data={"text": "ادّعاء للعمل المشترك في المتصفح"}, headers=H).json()["id"]
        pa, pb = a.new_page(), b.new_page()
        pa.goto(f"{BASE}/claims/{cid}")
        pb.goto(f"{BASE}/claims/{cid}")
        expect(pb.get_by_label("الحاضرون")).to_contain_text("غيث", timeout=20000)
        pa.reload()
        expect(pa.get_by_label("الحاضرون")).to_contain_text("المحرّر", timeout=20000)
        # كلاهما يفتح التعديل؛ غيث يحفظ أولًا؛ حفظ المحرّر يُرفض ويُعرض له الحالي
        pa.get_by_role("button", name="تعديل").click()
        pb.get_by_role("button", name="تعديل").click()
        pa.get_by_label("نص الادّعاء").fill("صياغة غيث")
        pa.get_by_role("button", name="حفظ", exact=True).click()
        expect(pa.get_by_role("heading", name="«صياغة غيث»")).to_be_visible()
        pb.get_by_label("نص الادّعاء").fill("صياغة المحرّر")
        pb.get_by_role("button", name="حفظ", exact=True).click()
        expect(pb.get_by_text("عدّل زميل هذا الحقل")).to_be_visible()
        pb.screenshot(path=SHOTS / "90-collab-conflict.png", full_page=True)
        assert a.request.get(f"{BASE}/api/claims/{cid}").json()["text"] == "صياغة غيث"
        browser.close()
    print("E2E العمل المشترك: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
