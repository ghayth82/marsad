"""فحص المتصفح لغرفة التحقيق وبناء القصة: قضية ← وثائق ممسوحة ← كيانات وخريطة ← تأكيد صلة وحدث ← مسودة بمصادرها ← Word."""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("MARSAD_E2E_URL", "http://localhost:8000")
SHOTS = Path(os.environ.get("MARSAD_E2E_SHOTS", "e2e/screenshots"))
CHROME = os.environ.get("MARSAD_E2E_CHROME")
INSECURE = os.environ.get("MARSAD_E2E_INSECURE") == "1"
H = {"X-Marsad": "1"}
ADMIN = {"email": "ghayth@example.com", "password": "correct-horse-1", "full_name": "غيث"}
LINES = Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures" / "case_lines"


def scanned_pdf(idx: list[int], mark: int) -> bytes:
    from PIL import Image

    lines = [Image.open(LINES / f"l{i}.png") for i in range(1, 6)]
    im = Image.new("L", (1500, 900), 255)
    y = 80
    for i in idx:
        im.paste(lines[i], (1500 - lines[i].width - 20, y))
        y += 150
    im.putpixel((5 + mark, 5), 0)
    b = io.BytesIO()
    im.convert("RGB").save(b, "PDF", resolution=150)
    return b.getvalue()


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    for k, idx in enumerate(([0, 3], [1, 4], [2, 0])):
        (tmp / f"مسح_{k + 1}.pdf").write_bytes(scanned_pdf(idx, k))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME) if CHROME else p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=INSECURE, accept_downloads=True)
        page = ctx.new_page()
        if ctx.request.get(f"{BASE}/api/setup").json()["needs_setup"]:
            assert ctx.request.post(f"{BASE}/api/setup", data=ADMIN, headers=H).ok
        else:
            assert ctx.request.post(f"{BASE}/api/auth/login", data=ADMIN, headers=H).ok
        page.goto(f"{BASE}/cases")
        page.get_by_label("العنوان").fill("عقود صيانة الطرق")
        page.get_by_label("الملخص").fill("تتبّع العقود والشركات المرتبطة")
        page.get_by_role("button", name="إنشاء").click()
        expect(page.get_by_role("heading", name="غرفة التحقيق: عقود صيانة الطرق")).to_be_visible()
        page.get_by_role("tab", name="الوثائق", exact=False).click()
        page.get_by_label("رفع وثائق").set_input_files([str(f) for f in sorted(tmp.glob("*.pdf"))])
        page.get_by_role("button", name="رفع", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("أُضيفت 3 وثيقة")
        expect(page.locator("[data-doc='3']")).to_contain_text("مسح ضوئي · استُخرج النص", timeout=120000)
        expect(page.locator("[data-doc='1']")).to_contain_text("كيانًا")
        page.locator("[data-doc='1'] a").click()
        expect(page.get_by_label("نص الوثيقة")).to_contain_text("وزارة الأشغال العامة")
        page.screenshot(path=SHOTS / "60-case-docs.png", full_page=True)

        page.get_by_role("tab", name="خريطة العلاقات").click()
        expect(page.get_by_role("img", name="خريطة العلاقات")).to_contain_text("شركة الأفق للمقاولات")
        page.locator("svg[aria-label='خريطة العلاقات'] line").first.click()
        expect(page.get_by_label("الصلة المختارة")).to_contain_text("وثيقة")
        page.get_by_role("button", name="تأكيد الصلة").click()
        page.screenshot(path=SHOTS / "61-case-map.png", full_page=True)

        page.get_by_role("tab", name="الخط الزمني").click()
        page.get_by_role("button", name="تأكيد").first.click()
        expect(page.get_by_text("مؤكد").first).to_be_visible()
        page.get_by_role("tab", name="المهام", exact=False).click()
        page.get_by_label("مهمة جديدة").fill("طلب نسخة محضر الإحالة")
        page.get_by_role("button", name="إضافة").click()
        expect(page.get_by_text("طلب نسخة محضر الإحالة")).to_be_visible()

        page.get_by_role("button", name="ابنِ القصة من الأدلة").click()
        expect(page.get_by_label("نص المسودة")).to_contain_text("[وثيقة")
        page.get_by_label("الزاوية").fill("عقد بالملايين بعد شراكة حديثة")
        body = page.get_by_label("نص المسودة")
        body.fill(body.input_value() + "\nوقال مسؤول إن العقد أُحيل دون مناقصة.")
        page.get_by_role("button", name="حفظ وفحص المصادر").click()
        expect(page.locator("[data-unsourced]")).to_contain_text("دون مناقصة")
        body.fill(body.input_value().replace("دون مناقصة.", "دون مناقصة [وثيقة 2]."))
        page.get_by_role("button", name="حفظ وفحص المصادر").click()
        expect(page.locator("[data-unsourced]")).to_have_count(0)
        for label in ("حق الرد أُرسل للأطراف المذكورة", "عُرضت رواية كل طرف", "مراجعة قانونية"):
            page.get_by_label("قبل النشر").get_by_text(label).click()
            page.wait_for_timeout(300)
        expect(page.get_by_label("المصادر", exact=True)).to_contain_text("وثيقة 2")
        with page.expect_download() as dl:
            page.get_by_role("link", name="تصدير Word").click()
        path = dl.value.path()
        import docx

        text = "\n".join(p.text for p in docx.Document(path).paragraphs)
        assert "SHA-256" in text and "[وثيقة" not in text, text[:500]
        page.screenshot(path=SHOTS / "62-story-builder.png", full_page=True)
        # «أين ملفاتي؟»: مجلد لكل وظيفة باسمه العربي، ومسودة Word المصدَّرة حُفظت في «القصص»، وخيار تشفير الوثائق
        page.goto(f"{BASE}/admin/settings")
        card = page.locator("section.card", has=page.get_by_role("heading", name="أين ملفاتي؟"))
        expect(card.locator(".row", has_text="التحقيقات")).to_contain_text("ملف")
        expect(card.locator(".row", has_text="القصص")).to_contain_text("1 ملف")
        box = card.get_by_label("تشفير وثائق التحقيقات")
        expect(box).not_to_be_checked()  # الافتراضي: مقروءة من ويندوز
        page.once("dialog", lambda d: d.accept())
        box.click()
        expect(card.get_by_role("status")).to_contain_text("فُعّل التشفير")
        expect(box).to_be_checked()
        page.screenshot(path=SHOTS / "63-where-are-my-files.png", full_page=True)
        page.once("dialog", lambda d: d.accept())
        box.click()
        expect(card.get_by_role("status")).to_contain_text("أُلغي التشفير")
        browser.close()
    print("E2E التحقيق وبناء القصة: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
