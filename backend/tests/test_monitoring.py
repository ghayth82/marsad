"""الرصد على موقع محلي يحاكي صحيفة وقناة تيليغرام وقناة يوتيوب (لا اتصال بالإنترنت)."""

import gzip
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

CID = "UC1234567890abcdefghijkl"
PARA = "<p>" + "أعلنت وزارة الطاقة اليوم عن تعديل أسعار المشتقات النفطية للشهر المقبل، وقالت إن القرار يأتي ضمن آلية التسعير الشهرية. " * 6 + "</p>"


def article(title, extra=""):
    return f"""<html><head><title>{title}</title><meta property="og:title" content="{title}">
<meta property="article:published_time" content="2026-11-20T08:00:00+03:00"></head>
<body><article><h1>{title}</h1>{PARA}<p>وأضافت المؤسسة أن الأسعار ستُراجع مجددًا. {extra}</p>{PARA}</article></body></html>"""


class Site:
    def __init__(self):
        self.pages = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(site):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                status, ctype, body = site.pages.get(self.path, (404, "text/html", "<h1>غير موجود</h1>"))
                b = body.encode() if isinstance(body, str) else body
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
        return H

    def set(self, path, body, ctype="text/html; charset=utf-8", status=200):
        self.pages[path] = (status, ctype, body)


@pytest.fixture
def site(monkeypatch):
    from marsad.monitor import fetch, readers

    s = Site()
    u = s.url
    monkeypatch.setattr(fetch, "HOST_DELAY", 0)
    monkeypatch.setattr(readers, "TELEGRAM_BASE", u)
    monkeypatch.setattr(readers, "YOUTUBE_BASE", u)
    fetch._robots.clear()
    s.set("/robots.txt", "User-agent: *\nDisallow: /private/\n", "text/plain")
    s.set("/", f"""<html><head><title>صحيفة الاختبار | الرئيسية</title><meta property="og:site_name" content="صحيفة الاختبار">
<meta property="og:image" content="{u}/logo.png"><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head>
<body><a href="https://www.facebook.com/testpaper">فيسبوك</a><a href="https://t.me/testchannel">تيليغرام</a>
<a href="https://www.youtube.com/channel/{CID}">يوتيوب</a></body></html>""")
    s.set("/feed.xml", f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>صحيفة الاختبار</title>
<item><title>تعديل أسعار المحروقات</title><link>{u}/news/2026/111-fuel</link><description>ملخص قصير</description>
<pubDate>Fri, 20 Nov 2026 05:00:00 GMT</pubDate></item>
<item><title>خبر محجوب عن الزواحف</title><link>{u}/private/222-secret</link><description>ملخص الخبر المحجوب</description></item>
</channel></rss>""", "application/rss+xml")
    s.set("/news/2026/111-fuel", article("تعديل أسعار المحروقات"))
    s.set("/s/testchannel", """<html><head><meta property="og:title" content="قناة الاختبار"></head><body>
<div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="testchannel/41">
<div class="tgme_widget_message_text">عاجل: إغلاق طريق المطار بسبب الأحوال الجوية</div>
<time datetime="2026-11-21T05:40:00+00:00">05:40</time></div>
<div class="tgme_widget_message js-widget_message" data-post="testchannel/42">
<div class="tgme_widget_message_text">تصريح جديد حول امتحانات الشامل</div><time datetime="2026-11-21T06:00:00+00:00"></time></div>
</body></html>""")
    s.set(f"/feeds/videos.xml?channel_id={CID}", f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/"><title>قناة يوتيوب الاختبار</title>
<entry><title>مؤتمر صحفي لوزير الطاقة</title><link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
<published>2026-11-21T07:00:00+00:00</published><media:group><media:description>وصف المؤتمر</media:description></media:group></entry>
</feed>""", "application/atom+xml")
    yield s
    s.server.shutdown()


def test_case7_paste_news_site_detects_everything(admin, site):
    d = admin.post("/api/sources/discover", json={"url": site.url}).json()
    assert d["kind"] == "rss" and d["read_url"].endswith("/feed.xml")
    assert d["outlet_name"] == "صحيفة الاختبار" and d["logo_url"].endswith("/logo.png")
    assert {s["platform"] for s in d["social"]} == {"facebook", "telegram", "youtube"}


def test_case8_site_telegram_youtube_as_one_outlet_and_items_flow(admin, site):
    r = admin.post("/api/sources", json={"url": site.url, "also": [
        "https://t.me/testchannel", f"https://www.youtube.com/channel/{CID}"]})
    assert r.status_code == 200, r.text
    outlets = admin.get("/api/outlets").json()
    assert len(outlets) == 1 and {s["kind"] for s in outlets[0]["sources"]} == {"rss", "telegram", "youtube"}
    items = admin.get("/api/items").json()["items"]  # الفحص الأول يجري فورًا
    titles = {i["title"] for i in items}
    assert "تعديل أسعار المحروقات" in titles
    assert any("طريق المطار" in t for t in titles)  # تيليغرام
    assert "مؤتمر صحفي لوزير الطاقة" in titles  # يوتيوب
    fuel = next(i for i in items if i["title"] == "تعديل أسعار المحروقات")
    full = admin.get(f"/api/items/{fuel['id']}").json()
    assert "آلية التسعير الشهرية" in full["text"]  # النص الكامل لا الملخص
    assert full["versions"][0]["archived"] and full["published_at"].startswith("2026-11-20")
    # robots.txt يمنع /private/: لا نجلب الصفحة ونبقي ملخص الخلاصة
    secret = next(i for i in items if "محجوب" in i["title"])
    assert admin.get(f"/api/items/{secret['id']}").json()["text"] == "ملخص الخبر المحجوب"


def _fuel_item(admin, site):
    admin.post("/api/sources", json={"url": site.url})
    items = admin.get("/api/items").json()["items"]
    return next(i for i in items if i["title"] == "تعديل أسعار المحروقات")["id"]


def test_one_bad_page_does_not_block_the_outlet(admin, site, monkeypatch):
    from marsad.monitor import readers

    monkeypatch.setattr(readers, "youtube_channel_id", lambda url: None)
    # فيديو يوتيوب منفرد (لا قناة) ورابط مكرر: يُتخطّيان ويُضاف الموقع وتيليغرام
    r = admin.post("/api/sources", json={"url": site.url, "also": [
        "https://www.youtube.com/watch?v=abc", "https://t.me/testchannel", "https://t.me/testchannel"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["kind"] for x in body["also"]] == ["telegram"]
    assert len(body["skipped"]) == 2 and all(x["reason"] for x in body["skipped"])
    assert {s["kind"] for s in admin.get("/api/outlets").json()[0]["sources"]} == {"rss", "telegram"}


def test_check_now_runs_in_background_and_reports_running(admin, site):
    from marsad.api import sources as api_sources

    sid = admin.post("/api/sources", json={"url": site.url}).json()["source"]["id"]
    r = admin.post(f"/api/sources/{sid}/check").json()
    assert r["started"] is True and "source" in r  # يعود فورًا دون انتظار جلب المقالات
    api_sources._CHECKING.add(sid)  # فحص جارٍ: لا يبدأ فحص ثانٍ، والواجهة ترى الحالة
    try:
        r = admin.post(f"/api/sources/{sid}/check").json()
        assert r["already"] is True and r["source"]["checking"] is True
    finally:
        api_sources._CHECKING.discard(sid)
    s = admin.get("/api/outlets").json()[0]["sources"][0]
    assert s["status"] == "ok" and s["last_checked_at"] and s["checking"] is False


def test_case10_edited_headline_two_versions_and_diff(admin, site):
    from marsad.db import get_db
    from marsad.models.monitoring import Item
    from marsad.monitor.service import recheck_item

    iid = _fuel_item(admin, site)
    site.set("/news/2026/111-fuel", article("تعديل أسعار المحروقات ابتداءً من الغد", "وتراجعت الوزارة عن جزء من القرار."))
    db = next(get_db())
    assert recheck_item(db, db.get(Item, iid)) == "edit"
    assert recheck_item(db, db.get(Item, iid)) == "same"
    db.commit()
    db.close()
    full = admin.get(f"/api/items/{iid}").json()
    assert full["status"] == "edited" and [v["change"] for v in full["versions"]] == ["new", "edit"]
    d = full["diffs"][0]
    assert d["title_changed"] and d["title_after"] == "تعديل أسعار المحروقات ابتداءً من الغد"
    assert any("تراجعت الوزارة" in x["after"] for x in d["text"])
    assert full["versions"][1]["captured_at"]
    r = admin.get(f"/api/items/{iid}/archive/1")
    assert r.status_code == 200 and "sandbox" in r.headers["content-security-policy"]


def test_case11_deleted_item_keeps_archive(admin, site):
    from marsad.db import get_db
    from marsad.models.monitoring import Item
    from marsad.monitor.service import recheck_item

    iid = _fuel_item(admin, site)
    del site.pages["/news/2026/111-fuel"]
    db = next(get_db())
    assert recheck_item(db, db.get(Item, iid)) == "delete"
    db.commit()
    db.close()
    full = admin.get(f"/api/items/{iid}").json()
    assert full["status"] == "deleted" and full["versions"][-1]["change"] == "delete"
    assert "آلية التسعير" in full["text"]  # آخر نص معروف باقٍ
    assert admin.get(f"/api/items/{iid}/archive/1").status_code == 200  # النسخة المؤرشفة باقية
    assert admin.get("/api/items", params={"status": "deleted"}).json()["total"] == 1


def test_case12_arabic_search_variants(admin, site):
    _fuel_item(admin, site)
    for q in ["المؤسسة", "المؤسَّسة", "الموسسه", "أسعار", "اسعار"]:
        r = admin.get("/api/items", params={"q": q}).json()
        assert r["total"] >= 1, q
    assert admin.get("/api/items", params={"q": "كلمة غير موجودة إطلاقًا"}).json()["total"] == 0


def test_case9_failing_source_alerts_never_silent(admin, site):
    from marsad.db import get_db
    from marsad.models.monitoring import Source
    from marsad.monitor.service import check_source

    admin.post("/api/sources", json={"url": site.url})
    site.set("/feed.xml", "خطأ", status=500)
    db = next(get_db())
    s = db.scalars(__import__("sqlalchemy").select(Source)).first()
    for _ in range(3):
        check_source(db, s)
    db.commit()
    assert s.status == "error" and "500" in s.last_error
    db.close()
    notes = admin.get("/api/engines/notifications").json()
    assert any("توقف رصد المصدر" in n["text"] for n in notes)
    assert admin.get("/api/monitor/status").json()["error"] == 1


def test_import_export_and_seed(admin, site):
    r = admin.post("/api/sources/import", json={"csv": "outlet,url,kind,tags\nجهة,https://example.org,page,محلي|رسمي\n"})
    assert r.json()["added"] == 1
    csv_text = admin.get("/api/sources/export").text
    assert "https://example.org" in csv_text and "محلي|رسمي" in csv_text
    r = admin.post("/api/sources/seed").json()
    assert r["added"] == 50 and not r["errors"]
    assert admin.post("/api/sources/seed").json()["skipped"] == 50  # لا تكرار
    gd = [s for o in admin.get("/api/outlets").json() for s in o["sources"] if s["kind"] == "gdelt"]
    assert len(gd) == 2 and "api.gdeltproject.org" in gd[0]["read_url"]


def test_pausing_source_never_deletes_items(admin, site):
    admin.post("/api/sources", json={"url": site.url})
    sid = admin.get("/api/outlets").json()[0]["sources"][0]["id"]
    n = admin.get("/api/items").json()["total"]
    assert admin.delete(f"/api/sources/{sid}").json()["status"] == "paused"
    assert admin.get("/api/items").json()["total"] == n


def test_permissions(admin, make_client, site):
    from tests.conftest import invite_user

    t, _ = invite_user(admin, make_client, "t@example.com", ["trainee"])
    assert t.get("/api/items").status_code == 403
    r, _ = invite_user(admin, make_client, "r@example.com", ["researcher"])
    assert r.get("/api/items").status_code == 200
    assert r.post("/api/sources", json={"url": site.url}).status_code == 403


def test_tick_schedules_due_sources(app_env, site):
    from marsad.db import get_db, init_engine, migrate
    from marsad.models.monitoring import Outlet, Source
    from marsad.tasks import build_app, monitor_tick

    init_engine()
    migrate()
    db = next(get_db())
    o = Outlet(name="x")
    db.add(o)
    db.flush()
    db.add(Source(outlet_id=o.id, url=site.url + "/feed.xml", kind="rss", read_url=site.url + "/feed.xml"))
    db.commit()
    app = build_app("")
    with app.open():
        monitor_tick.defer(timestamp=0)
        app.run_worker(wait=False, queues=["monitor"])
    db.expire_all()
    s = db.scalars(__import__("sqlalchemy").select(Source)).first()
    assert s.status == "ok" and s.last_item_at is not None
    db.close()
