"""موصلات التواصل: مبنية ومختبرة بخادم يحاكي الواجهات الرسمية وApify، وتعمل فور إضافة المفتاح. ومؤشرات الحملات المنسّقة."""

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

NOW = datetime.now(timezone.utc)
ISO = lambda m: (NOW - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S+0000")  # noqa: E731
SEEN: list[dict] = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, status=200):
        b = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode() if n else ""

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        SEEN.append({"path": u.path, "q": q, "auth": self.headers.get("Authorization")})
        if u.path == "/2/users/by/username/MinistryJO":
            if self.headers.get("Authorization") != "Bearer x-good":
                return self._send({"title": "Unauthorized"}, 401)
            return self._send({"data": {"id": "42", "username": "MinistryJO"}})
        if u.path == "/2/users/42/tweets":
            return self._send({"data": [
                {"id": "1001", "text": "بيان: لا صحة لإغلاق المدارس غدا #عاجل_الأردن", "created_at": ISO(30),
                 "public_metrics": {"retweet_count": 5}, "entities": {"hashtags": [{"tag": "عاجل_الأردن"}],
                                                                      "urls": [{"expanded_url": "https://moe.example/statement"}]}},
                {"id": "1002", "text": "تحديث حول الامتحانات الوزارية", "created_at": ISO(90)}]})
        if u.path == "/v21.0/newspage/posts":
            assert q["access_token"] == ["fb-token"]
            return self._send({"data": [{"id": "9_1", "message": "خبر من صفحة فيسبوك عن الطقس", "created_time": ISO(20),
                                         "permalink_url": "https://www.facebook.com/newspage/posts/1", "full_picture": "https://img.example/1.jpg"}]})
        if u.path == "/v21.0/17840000":
            return self._send({"business_discovery": {"media": {"data": [
                {"id": "m1", "caption": "منشور إنستغرام عن مهرجان جرش", "timestamp": ISO(15), "permalink": "https://www.instagram.com/p/abc/",
                 "media_type": "IMAGE", "media_url": "https://img.example/ig.jpg", "like_count": 10}]}}})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()
        SEEN.append({"path": u.path, "q": parse_qs(u.query), "body": body, "auth": self.headers.get("Authorization")})
        if u.path == "/v2/oauth/token/":
            f = parse_qs(body)
            if f.get("client_secret") != ["tt-secret"]:
                return self._send({"error": "invalid_client"}, 401)
            return self._send({"access_token": "tt-access", "expires_in": 7200})
        if u.path == "/v2/research/video/query/":
            assert self.headers.get("Authorization") == "Bearer tt-access"
            return self._send({"data": {"videos": [{"id": 7000000001, "video_description": "فيديو تيك توك عن ازدحام الطرق",
                                                    "create_time": int((NOW - timedelta(minutes=10)).timestamp()), "username": "roadsjo",
                                                    "like_count": 3, "hashtag_names": ["طرق"]}]}})
        if u.path.startswith("/v2/acts/") and u.path.endswith("/run-sync-get-dataset-items"):
            assert parse_qs(u.query)["token"] == ["apify-token"]
            inp = json.loads(body)
            if "twitterHandles" in inp:
                return self._send([{"url": f"https://x.com/{h}/status/5{n}", "text": "منشور عبر Apify", "createdAt": ISO(5),
                                    "author": {"userName": h}} for n, h in enumerate(inp["twitterHandles"])])
            return self._send([])
        return self._send({"error": "not found"}, 404)


@pytest.fixture
def fake_api(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    b = f"http://127.0.0.1:{srv.server_port}"
    for k in ("META", "X", "TIKTOK", "APIFY"):
        monkeypatch.setenv(f"MARSAD_SOCIAL_BASE_{k}", b)
    SEEN.clear()
    yield b
    srv.shutdown()


def add(admin, url):
    r = admin.post("/api/sources", json={"url": url})
    assert r.status_code == 200, r.text
    return r.json()["source"]


def test_connectors_waiting_without_provider(admin):
    s = add(admin, "https://x.com/MinistryJO")
    assert s["kind"] == "social"
    r = admin.post(f"/api/sources/{s['id']}/check").json()
    assert "ينتظر مزوّد بيانات" in r["error"]
    st = admin.get("/api/social/providers").json()
    x = next(p for p in st["platforms"] if p["platform"] == "x")
    assert x["provider"] is None and x["sources"] == 1 and "bearer_token" in x["fields"]["official"]
    from marsad.db import get_db
    from marsad.monitor.service import due_sources

    db = next(get_db())
    assert all(d.kind != "social" for d in due_sources(db))  # لا فحص قبل المفتاح
    db.close()


def test_official_connectors_all_platforms(admin, fake_api):
    # مفتاح خاطئ يُرفض برسالة واضحة، ولا يُحفظ المفتاح في سجل التدقيق
    assert admin.put("/api/social/providers/x", json={"provider": "official", "credentials": {}}).status_code == 422
    admin.put("/api/social/providers/x", json={"provider": "official", "credentials": {"bearer_token": "x-bad-token-123"}})
    t = admin.post("/api/social/providers/x/test", json={"handle": "MinistryJO"}).json()
    assert t["ok"] is False and "المفتاح مرفوض" in t["error"]
    st = admin.put("/api/social/providers/x", json={"provider": "official", "credentials": {"bearer_token": "x-good"}})
    assert st.status_code == 200
    assert admin.post("/api/social/providers/x/test", json={"handle": "MinistryJO"}).json()["count"] == 2
    admin.put("/api/social/providers/facebook", json={"provider": "official", "credentials": {"access_token": "fb-token"}})
    admin.put("/api/social/providers/instagram", json={"provider": "official", "credentials": {"access_token": "fb-token", "ig_user_id": "17840000"}})
    admin.put("/api/social/providers/tiktok", json={"provider": "official", "credentials": {"client_key": "ck", "client_secret": "tt-secret"}})
    masked = {p["platform"]: p["masked"] for p in admin.get("/api/social/providers").json()["platforms"]}
    assert "x-good" not in json.dumps(masked) and "tt-secret" not in json.dumps(masked)
    audit = json.dumps(admin.get("/api/admin/audit").json(), ensure_ascii=False)
    assert "fb-token" not in audit and "tt-secret" not in audit

    for url in ("https://x.com/MinistryJO", "https://www.facebook.com/newspage", "https://www.instagram.com/jerashfest",
                "https://www.tiktok.com/@roadsjo"):
        s = add(admin, url)  # الإضافة تبدأ الرصد فورًا
        r = admin.post(f"/api/sources/{s['id']}/check").json()
        assert r.get("error") in (None, "") and r["new"] == 0 and r["source"]["status"] == "ok", r  # الفحص الثاني: لا تكرار
    items = admin.get("/api/items?limit=50").json()
    rows = items["items"] if isinstance(items, dict) else items
    by_url = {i["url"]: i for i in rows}
    tw = by_url["https://x.com/MinistryJO/status/1001"]
    assert "لا صحة لإغلاق المدارس" in tw["title"]
    assert by_url["https://www.tiktok.com/@roadsjo/video/7000000001"]
    assert by_url["https://www.instagram.com/p/abc/"]
    assert by_url["https://www.facebook.com/newspage/posts/1"]
    # TikTok: الطلب برموز البحث الصحيحة
    q = next(x for x in SEEN if x["path"] == "/v2/research/video/query/")
    assert json.loads(q["body"])["query"]["and"][0]["field_values"] == ["roadsjo"]
    # المادة من المنصة تدخل سجل الشائعات والقصص كأي مادة
    from marsad.db import get_db
    from marsad.monitor.service import due_sources

    db = next(get_db())
    from marsad.models.monitoring import Source

    for s in db.query(Source).filter_by(kind="social"):
        s.last_checked_at = None
    db.commit()
    assert sum(d.kind == "social" for d in due_sources(db)) == 4
    db.close()


def test_apify_provider(admin, fake_api):
    admin.put("/api/social/providers/x", json={"provider": "apify", "credentials": {"api_token": "apify-token"}})
    s = add(admin, "https://x.com/someone")
    rows = admin.get("/api/items?limit=50").json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    assert any(i["url"] == "https://x.com/someone/status/50" for i in rows)
    call = next(x for x in SEEN if x["path"].startswith("/v2/acts/apidojo~tweet-scraper"))
    assert json.loads(call["body"])["twitterHandles"] == ["someone"]
    # إزالة المزوّد تعيد الموصل إلى الانتظار
    admin.put("/api/social/providers/x", json={"provider": None})
    assert "ينتظر" in admin.post(f"/api/sources/{s['id']}/check").json()["error"]


def test_coordinated_campaign_indicators(admin):
    from marsad.db import get_db
    from marsad.models.monitoring import Item, Outlet, Source
    from marsad.monitor.service import store_entry

    db = next(get_db())
    o = Outlet(name="حسابات")
    db.add(o)
    db.flush()
    src = Source(outlet_id=o.id, url="https://x.com/many", kind="social", meta={"platform": "x", "handle": "many"})
    db.add(src)
    db.flush()
    t0 = NOW - timedelta(hours=2)
    text = "عاجل: انقطاع الكهرباء عن العاصمة كلها لمدة ثلاثة أيام بسبب عطل كبير في المحطة الرئيسية، شاركوا الخبر"
    for k in range(6):  # ستة حسابات بالنص نفسه تقريبًا خلال 25 دقيقة، وبالرابط نفسه والوسم نفسه
        store_entry(db, src, {"url": f"https://x.com/acct{k}/status/{k}", "title": text[:100], "text": text + ("!" * k),
                              "author": f"acct{k}", "published_at": t0 + timedelta(minutes=5 * k), "media": [], "full": True,
                              "meta": {"platform": "x", "links": ["https://fake-news.example/power"], "hashtags": ["انقطاع_الكهرباء"]}},
                    fetch_full=False)
    for k in range(4):  # منشورات عادية متفرقة
        store_entry(db, src, {"url": f"https://x.com/normal{k}/status/{k}", "title": f"خبر عادي رقم {k} عن الطقس", "text": f"خبر عادي رقم {k} عن الطقس والأمطار المتوقعة في الشمال",
                              "author": f"normal{k}", "published_at": t0 + timedelta(hours=k), "media": [], "full": True, "meta": {}}, fetch_full=False)
    db.commit()
    db.close()
    r = admin.get("/api/social/campaigns?hours=24").json()
    kinds = [c["kind"] for c in r["clusters"]]
    assert "نص متطابق تقريبًا" in kinds and "الرابط نفسه: https://fake-news.example/power" in kinds and "وسم يتفجّر: انقطاع_الكهرباء" in kinds
    copy = next(c for c in r["clusters"] if c["kind"] == "نص متطابق تقريبًا")
    assert len(copy["accounts"]) == 6 and copy["span_minutes"] == 25 and "لا حكم" in copy["note"]
    assert all("normal" not in a for c in r["clusters"] for a in c["accounts"])


def test_social_permissions(admin, make_client):
    from tests.conftest import invite_user

    j, _ = invite_user(admin, make_client, "j@example.com", ["journalist"])
    assert j.get("/api/social/providers").status_code == 403
    assert j.put("/api/social/providers/x", json={"provider": "official", "credentials": {"bearer_token": "x"}}).status_code == 403
    assert j.get("/api/social/campaigns").status_code == 200
