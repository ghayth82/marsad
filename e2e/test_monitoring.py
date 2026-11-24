"""فحص المتصفح للرصد: لصق رابط ← اكتشاف ← إضافة ← تدفق المواد ← بحث بشكل مختلف للكلمة ← معاينة المادة.
يشغّل موقعًا محليًا يحاكي صحيفة (لا اتصال بالإنترنت). يحتاج الخادم على MARSAD_E2E_URL."""

from __future__ import annotations

import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("MARSAD_E2E_URL", "http://localhost:8000")
SHOTS = Path(os.environ.get("MARSAD_E2E_SHOTS", "e2e/screenshots"))
CHROME = os.environ.get("MARSAD_E2E_CHROME")
INSECURE = os.environ.get("MARSAD_E2E_INSECURE") == "1"
SITE_HOST = os.environ.get("MARSAD_E2E_SITE_HOST", "127.0.0.1")  # العنوان الذي يصل منه الخادم إلى الموقع المحلي
H = {"X-Marsad": "1"}
ADMIN = {"email": "ghayth@example.com", "password": "correct-horse-1", "full_name": "غيث"}
PARA = "<p>" + "أعلنت المؤسسة العامة للغذاء والدواء اليوم عن إجراءات جديدة لمراقبة أسعار الأدوية في الصيدليات. " * 6 + "</p>"


def site() -> str:
    pages: dict[str, tuple[str, str]] = {}

    class Hd(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            ctype, body = pages.get(self.path, ("text/html", ""))
            b = body.encode()
            self.send_response(200 if self.path in pages else 404)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("0.0.0.0", 0), Hd)
    u = f"http://{SITE_HOST}:{srv.server_address[1]}"
    pages["/robots.txt"] = ("text/plain", "User-agent: *\nAllow: /\n")
    pages["/"] = ("text/html", '<html><head><meta property="og:site_name" content="صحيفة المتصفح"><link rel="alternate" '
                               'type="application/rss+xml" href="/rss"></head><body>الرئيسية</body></html>')
    items = "".join(f"<item><title>خبر رقم {n} عن أسعار الأدوية</title><link>{u}/news/2026/{n}00-story</link></item>" for n in range(1, 4))
    pages["/rss"] = ("application/rss+xml", f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>صحيفة المتصفح</title>{items}</channel></rss>')
    for n in range(1, 4):
        pages[f"/news/2026/{n}00-story"] = ("text/html", f"<html><body><article><h1>خبر رقم {n} عن أسعار الأدوية</h1>{PARA}{PARA}</article></body></html>")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return u


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    url = site()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME) if CHROME else p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=INSECURE)
        page = ctx.new_page()
        if ctx.request.get(f"{BASE}/api/setup").json()["needs_setup"]:
            assert ctx.request.post(f"{BASE}/api/setup", data=ADMIN, headers=H).ok
        else:
            assert ctx.request.post(f"{BASE}/api/auth/login", data=ADMIN, headers=H).ok

        page.goto(f"{BASE}/sources")
        page.get_by_label("رابط المصدر").fill(url)
        page.get_by_role("button", name="افحص الرابط").click()
        expect(page.get_by_text("طريقة القراءة: خلاصة RSS")).to_be_visible()
        expect(page.get_by_label("اسم الجهة")).to_have_value("صحيفة المتصفح")
        page.get_by_label("وسوم (مفصولة بفاصلة)").fill("محلي")
        page.get_by_role("button", name="إضافة وبدء الرصد").click()
        expect(page.get_by_text("أُضيف المصدر")).to_be_visible()
        page.reload()
        expect(page.get_by_text("صحيفة المتصفح")).to_be_visible()
        page.screenshot(path=SHOTS / "20-sources.png", full_page=True)

        for _ in range(15):  # الفحص الأول يجري في الخلفية بعد الإضافة
            page.goto(f"{BASE}/live")
            if page.get_by_text("خبر رقم 3 عن أسعار الأدوية").count():
                break
            page.wait_for_timeout(2000)
        expect(page.get_by_text("خبر رقم 3 عن أسعار الأدوية")).to_be_visible()
        page.get_by_label("بحث في المواد").fill("اسعار الادويه")  # دون همزات وبهاء بدل التاء المربوطة
        page.get_by_role("button", name="بحث", exact=True).click()
        expect(page.get_by_text("3 مادة")).to_be_visible()
        page.get_by_text("خبر رقم 2 عن أسعار الأدوية").click()
        reader = page.get_by_role("complementary", name="قارئ المادة")
        expect(reader.get_by_text("المؤسسة العامة للغذاء والدواء").first).to_be_visible()
        expect(reader.get_by_role("heading", name="تعديلات الخبر")).to_be_visible()
        expect(reader.get_by_role("link", name="النسخة المحفوظة")).to_be_visible()
        page.screenshot(path=SHOTS / "21-live.png", full_page=True)
        reader.get_by_role("button", name="ملء الشاشة").click()
        expect(reader.get_by_role("button", name="تصغير")).to_be_visible()
        page.keyboard.press("Escape")  # يغلق القارئ ويعود للقائمة بالبحث نفسه
        expect(reader).to_have_count(0)
        expect(page.get_by_text("3 مادة")).to_be_visible()
        page.get_by_text("خبر رقم 2 عن أسعار الأدوية").click()
        page.get_by_role("complementary", name="قارئ المادة").get_by_role("button", name="صفحة مستقلة").click()
        expect(page).to_have_url(re.compile(r"/item/\d+$"))
        expect(page.get_by_role("heading", name="تعديلات الخبر")).to_be_visible()
        page.get_by_role("button", name="رجوع").click()  # سهم الرجوع يعيد القائمة والقارئ كما كانا
        expect(page.get_by_role("complementary", name="قارئ المادة")).to_be_visible()

        # البند 4: المواد الثلاث عن الحدث نفسه في قصة واحدة، بأول ناشر
        page.goto(f"{BASE}/stories")
        # المرشّح الافتراضي «أكثر من مصدر» يعدّ الجهات: قصة جهة واحدة لا تظهر فيه
        expect(page.get_by_text("لا قصة نشرتها جهتان أو أكثر بعد")).to_be_visible()
        page.get_by_label("التي نشرها أكثر من مصدر فقط").uncheck()
        expect(page.get_by_text("3 مادة · 1 مصدر")).to_be_visible()
        page.locator("a[href^=\x27/stories/\x27]").first.click()
        expect(page.get_by_text("أول ناشر: صحيفة المتصفح")).to_be_visible()
        expect(page.get_by_role("heading", name="مقارنة الروايات")).to_be_visible()
        page.screenshot(path=SHOTS / "22-story.png", full_page=True)
        page.goto(f"{BASE}/entities")
        expect(page.get_by_role("link", name="المؤسسة العامة")).to_be_visible()
        browser.close()
    print("E2E الرصد: كل الخطوات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
