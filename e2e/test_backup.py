"""النسخ الاحتياطي من الواجهة: باقة بقائمة اختيار ومكان وموعد، نسخ الآن، ثم استرداد ما يُختار منها.
وزر «نزّل الصفحة الأصلية» في الخبر."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("MARSAD_E2E_URL", "http://localhost:8000")
SHOTS = Path(os.environ.get("MARSAD_E2E_SHOTS", "e2e/screenshots"))
INSECURE = os.environ.get("MARSAD_E2E_INSECURE") == "1"
H = {"X-Marsad": "1"}
ADMIN = {"email": "ghayth@example.com", "password": "correct-horse-1", "full_name": "غيث"}


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="marsad-usb-"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=INSECURE, viewport={"width": 1440, "height": 900})
        if ctx.request.get(f"{BASE}/api/setup").json()["needs_setup"]:
            assert ctx.request.post(f"{BASE}/api/setup", data=ADMIN, headers=H).ok
        else:
            assert ctx.request.post(f"{BASE}/api/auth/login", data=ADMIN, headers=H).ok
        text = f"ادّعاء لفحص النسخ الاحتياطي رقم {int(time.time())}"
        cid = ctx.request.post(f"{BASE}/api/claims", data={"text": text}, headers=H).json()["id"]
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{BASE}/admin/backup")
        expect(page.locator(".page-intro")).to_contain_text("باقات النسخ الاحتياطي")

        # النسخة اليومية موجودة من البداية: قاعدة البيانات وحدها، ويختار المدير ما يضيفه إليها
        daily = page.locator("[data-pkg='النسخة اليومية']")
        expect(daily).to_contain_text("تلقائية")
        expect(daily.get_by_role("button", name="حذف")).to_have_count(0)
        daily.get_by_role("button", name="تعديل").click()
        dform = page.get_by_role("form", name="الباقة")
        expect(dform.get_by_label("اسم الباقة")).to_have_count(0)
        expect(dform.get_by_label("قاعدة البيانات: الشائعات والادعاءات")).to_be_checked()
        dform.get_by_label("الملفات: التحقيقات").check()  # (على قاعدة جديدة تكون غير مؤشّرة؛ السكربت يُعاد على القاعدة نفسها)
        dform.get_by_role("button", name="حفظ الباقة").click()
        expect(daily).to_contain_text("التحقيقات")
        # «أين ملفاتي؟» لم يعد يذكر التحقيقات بين ما لا يُنسخ
        page.goto(f"{BASE}/admin/settings")
        warn = page.locator("section.card", has=page.get_by_role("heading", name="أين ملفاتي؟")).locator(".msg.warn")
        expect(warn).to_contain_text("لا تُنسخ تلقائيًا")
        expect(warn).not_to_contain_text("التحقيقات")
        page.goto(f"{BASE}/admin/backup")

        # باقة جديدة: الاختيار من القائمة يُظهر ما يُضاف تلقائيًا
        page.get_by_role("button", name="باقة جديدة").click()
        form = page.get_by_role("form", name="الباقة")
        save = form.get_by_role("button", name="حفظ الباقة")
        expect(save).to_be_disabled()
        name = f"أسبوعي للقرص {int(time.time()) % 100000}"  # فريد: السكربت يُعاد على القاعدة نفسها
        form.get_by_label("اسم الباقة").fill(name)
        form.get_by_label("قاعدة البيانات: الشائعات والادعاءات").check()
        expect(form.locator("label.chk", has_text="المصادر والأخبار")).to_contain_text("يُضاف تلقائيًا")
        form.get_by_label("مكان الحفظ").fill(str(dest))
        form.get_by_label("الموعد").select_option("weekly")
        form.get_by_label("اليوم").select_option("4")
        form.get_by_label("الساعة").fill("03:30")
        expect(form.get_by_label("تشفير النسخ")).to_be_checked()  # الافتراضي للقرص الخارجي
        save.click()
        expect(form.get_by_role("alert")).to_contain_text("عبارة مرور")
        form.get_by_label("عبارة المرور").fill("correct horse 9")
        page.screenshot(path=SHOTS / "70-backup-package.png", full_page=True)
        save.click()
        row = page.locator(f"[data-pkg='{name}']")
        expect(row).to_contain_text("كل الجمعة 03:30")
        expect(row).to_contain_text("مشفّرة")

        # انسخ الآن
        row.get_by_role("button", name="انسخ الآن").click()
        expect(row.get_by_role("status")).to_contain_text("آخر نسخة", timeout=30000)

        # بعد النسخة يُضاف ادّعاء آخر؛ «استبدل» يعيد الادّعاءات كما كانت فيختفي، ويبقى الذي في النسخة
        later = f"ادّعاء أُضيف بعد النسخة رقم {int(time.time())}"
        ctx.request.post(f"{BASE}/api/claims", data={"text": later}, headers=H)
        restore = page.get_by_role("region", name="الاسترداد")
        restore.get_by_role("button", name=str(dest)).click()
        restore.locator(".row", has_text=name).get_by_role("button", name="اختر").click()
        restore.get_by_label("عبارة مرور النسخة").fill("correct horse 9")
        restore.get_by_role("button", name="افتح").click()
        expect(restore.get_by_label("قاعدة البيانات: الشائعات والادعاءات")).to_be_checked()
        expect(restore.get_by_label("قاعدة البيانات: المصادر والأخبار")).not_to_be_checked()  # أُضيف تلقائيًا للنسخة، لا يُسترد إلا باختيارك
        restore.get_by_text("استبدل", exact=True).click()
        page.screenshot(path=SHOTS / "71-backup-restore.png", full_page=True)
        page.once("dialog", lambda d: d.accept())
        restore.get_by_role("button", name="استرد المختار").click()
        expect(restore.get_by_role("status")).to_contain_text("تمّ الاسترداد", timeout=30000)
        expect(restore.get_by_role("status")).to_contain_text("قبل الاسترداد")
        texts = {c["text"] for c in ctx.request.get(f"{BASE}/api/claims?limit=300").json()}
        assert text in texts and later not in texts, texts
        assert any(c["id"] == cid for c in ctx.request.get(f"{BASE}/api/claims?limit=300").json())

        # «نزّل الصفحة الأصلية» في الخبر (إن كان في القاعدة خبر مؤرشف)
        items = ctx.request.get(f"{BASE}/api/items?limit=50").json()["items"]
        archived = next((i for i in items if any(v.get("archived") for v in ctx.request.get(f"{BASE}/api/items/{i['id']}").json()["versions"])), None)
        if archived:
            page.goto(f"{BASE}/item/{archived['id']}")
            with page.expect_download() as dl:
                page.get_by_role("link", name="نزّل الصفحة الأصلية").first.click()
            assert dl.value.suggested_filename.endswith(".html") and " - " in dl.value.suggested_filename, dl.value.suggested_filename
        assert not errors, errors
        browser.close()
    print("E2E النسخ الاحتياطي: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
