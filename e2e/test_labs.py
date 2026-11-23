"""فحص المتصفح للمختبرات: صورة نصها عربي ← فحوص بدرجاتها؛ نسخة أعيد نشرها ← قاطع ← إرفاق بادّعاء؛ تسجيل صوتي بموجته."""

from __future__ import annotations

import io
import math
import os
import struct
import sys
import tempfile
import wave
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("MARSAD_E2E_URL", "http://localhost:8000")
SHOTS = Path(os.environ.get("MARSAD_E2E_SHOTS", "e2e/screenshots"))
CHROME = os.environ.get("MARSAD_E2E_CHROME")
INSECURE = os.environ.get("MARSAD_E2E_INSECURE") == "1"
H = {"X-Marsad": "1"}
ADMIN = {"email": "ghayth@example.com", "password": "correct-horse-1", "full_name": "غيث"}
FIX = Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures"


def scene_jpeg(size=(640, 420), q=90) -> bytes:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (640, 420), (40, 90, 140))
    d = ImageDraw.Draw(im)
    for i in range(12):
        d.ellipse((i * 47 % 560, i * 83 % 340, i * 47 % 560 + 60 + i * 5, i * 83 % 340 + 50 + i * 4), fill=(i * 20 % 255, 200 - i * 9, i * 30 % 255))
    if size != im.size:
        im = im.resize(size)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return b.getvalue()


def tone_wav(path: Path, seconds=6):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        frames = bytearray()
        for i in range(16000 * seconds):
            on = (i // 6000) % 4 != 3
            v = (0.3 * math.sin(2 * math.pi * (300 + 200 * ((i // 8000) % 5)) * i / 16000)) if on else 0.0
            frames += struct.pack("<h", int(v * 32767))
        w.writeframes(bytes(frames))


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    (tmp / "original.jpg").write_bytes(scene_jpeg())
    (tmp / "viral.jpg").write_bytes(scene_jpeg((420, 276), 65))
    tone_wav(tmp / "rec.wav")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME) if CHROME else p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=INSECURE)
        page = ctx.new_page()
        if ctx.request.get(f"{BASE}/api/setup").json()["needs_setup"]:
            assert ctx.request.post(f"{BASE}/api/setup", data=ADMIN, headers=H).ok
        else:
            assert ctx.request.post(f"{BASE}/api/auth/login", data=ADMIN, headers=H).ok

        # 1) صورة فيها نص عربي
        page.goto(f"{BASE}/media-lab")
        page.get_by_label("الملف", exact=True).set_input_files(str(FIX / "arabic_text.png"))
        page.get_by_role("button", name="افحص").click()
        expect(page.get_by_role("heading", name="الفحوص")).to_be_visible(timeout=60000)
        expect(page.get_by_text("وزارة الصحة تعلن إغلاق المدارس").first).to_be_visible()
        expect(page.locator("[data-check=c2pa]")).to_contain_text("لا توجد شهادة محتوى")
        page.screenshot(path=SHOTS / "40-media-lab-ocr.png", full_page=True)

        # 2) الأصل ثم نسخة أعيد نشرها بتاريخ لاحق ← نسخة أقدم في الأرشيف: قاطع
        page.get_by_role("button", name="ملف جديد").click()
        page.get_by_label("الملف", exact=True).set_input_files(str(tmp / "original.jpg"))
        page.get_by_role("button", name="افحص").click()
        expect(page.get_by_role("heading", name="الفحوص")).to_be_visible(timeout=60000)
        page.get_by_role("button", name="ملف جديد").click()
        page.get_by_label("الملف", exact=True).set_input_files(str(tmp / "viral.jpg"))
        page.get_by_label("التاريخ المدّعى").fill("2030-01-01T10:00")
        page.get_by_role("button", name="افحص").click()
        result = page.get_by_label("النتيجة")
        expect(result).to_contain_text("دليل قاطع", timeout=60000)
        expect(page.locator("[data-check=archive]")).to_contain_text("نسخة أقدم في أرشيفنا")
        claim = ctx.request.post(f"{BASE}/api/claims", data={"text": "صورة اليوم لاحتفال في الساحة العامة"}, headers=H).json()
        page.get_by_label("رقم الادّعاء").fill(str(claim["id"]))
        page.get_by_role("button", name="أرفق بالادّعاء").click()
        expect(page.get_by_text(f"أُرفق بالادّعاء #{claim['id']} بدرجة «قاطع»")).to_be_visible()
        page.get_by_label("خط العرض").fill("31.95")
        page.get_by_label("وقت الصورة المدّعى").fill("2026-06-21T12:40")
        page.get_by_role("button", name="احسب").click()
        expect(page.get_by_label("حاسبة الشمس").get_by_role("status")).to_contain_text("ارتفاع الشمس")
        page.screenshot(path=SHOTS / "41-media-lab-archive.png", full_page=True)
        rep = ctx.request.get(f"{BASE}{page.get_by_role('link', name='تقرير التحقق').get_attribute('href')}")
        assert rep.ok and "سلسلة الحفظ" in rep.text()

        # 3) مختبر الصوت
        page.goto(f"{BASE}/audio-lab")
        page.get_by_label("الملف", exact=True).set_input_files(str(tmp / "rec.wav"))
        page.get_by_role("button", name="افحص").click()
        expect(page.get_by_role("img", name="موجة الصوت")).to_be_visible(timeout=60000)
        expect(page.get_by_role("heading", name="التفريغ بمحركات «صوتي»")).to_be_visible()
        expect(page.locator("[data-check=synthetic]")).to_contain_text("لا يُعطى حكم")
        page.screenshot(path=SHOTS / "42-audio-lab.png", full_page=True)
        browser.close()
    print("E2E المختبرات: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
