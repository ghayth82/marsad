"""البند 13: الحالات 53–59 — أدوات الصحفيين، بخادم وهمي واحد يقوم مقام تيليغرام وGoogle Fact Check وWayback و«صوتي» ومواقع الأخبار."""

import json
import shutil
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from tests.conftest import invite_user

SENT: list[dict] = []
UPDATES: list[dict] = []
PAGES: dict[str, str] = {}
SEARCHES: list[dict] = []


def _png() -> bytes:
    b = BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(b, "PNG")
    return b.getvalue()


PNG = _png()


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/file/bot123:good/"):
            return self._send(200, PNG, "image/png")
        if u.path == "/v1alpha1/claims:search":
            q = parse_qs(u.query)
            SEARCHES.append(q)
            if q["key"][0] != "good-key":
                return self._send(400, {"error": {"message": "API key not valid"}})
            if q["languageCode"][0] == "ar":
                return self._send(200, {"claims": [{"text": "صورة الطوابير من 2024", "claimant": "منشورات",
                                                    "claimReview": [{"publisher": {"name": "مسبار", "site": "misbar.com"},
                                                                     "url": "https://misbar.com/x", "textualRating": "مضلل",
                                                                     "reviewDate": "2026-10-01T00:00:00Z", "languageCode": "ar"}]}]})
            return self._send(200, {})
        if u.path.startswith("/save/"):
            return self._send(200, b"ok", "text/html")
        if u.path in PAGES:
            return self._send(200, PAGES[u.path].encode(), "text/html; charset=utf-8")
        return self._send(404, b"not found", "text/html")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        if self.path == "/transcribe":
            return self._send(200, {"segments": [
                {"start": 0.0, "end": 2.0, "speaker": "الوزير", "text": "أهلًا بكم وشكرًا لحضوركم اليوم"},
                {"start": 2.0, "end": 6.5, "speaker": "الوزير", "text": "انخفضت نسبة البطالة إلى 18 بالمئة خلال العام الماضي"},
                {"start": 6.5, "end": 9.0, "speaker": "الوزير", "text": "افتتحنا ثلاث مدارس جديدة في محافظة الكرك"}]})
        body = json.loads(raw or b"{}")
        parts = self.path.split("/")
        token, method = parts[1][3:], parts[2]
        if token != "123:good":
            return self._send(200, {"ok": False, "description": "Unauthorized"})
        if method == "getMe":
            return self._send(200, {"ok": True, "result": {"id": 1, "username": "marsad_test_bot"}})
        if method == "getUpdates":
            off = body.get("offset") or 0
            return self._send(200, {"ok": True, "result": [u for u in UPDATES if u["update_id"] >= off]})
        if method == "getFile":
            return self._send(200, {"ok": True, "result": {"file_id": body["file_id"], "file_size": len(PNG), "file_path": "photos/p1.png"}})
        if method == "sendMessage":
            SENT.append(body)
            return self._send(200, {"ok": True, "result": {"message_id": len(SENT)}})
        return self._send(200, {"ok": False})


@pytest.fixture
def fake(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    for k in ("MARSAD_TELEGRAM_API", "MARSAD_FACTCHECK_API", "MARSAD_WAYBACK_API", "MARSAD_SAWTI_URL"):
        monkeypatch.setenv(k, base)
    monkeypatch.setenv("MARSAD_SNAPSHOT_SCREENSHOT", "0")
    for x in (SENT, UPDATES, PAGES, SEARCHES):
        x.clear()
    yield base
    srv.shutdown()


def approve(c, cid, label="مضلل", expl="الصورة من عام 2024 ونُشرت على أنها حديثة."):
    assert c.post(f"/api/claims/{cid}/verdict", json={"label": label, "evidence_grade": "مؤشر قوي", "explanation": expl}).status_code == 200
    r = c.post(f"/api/claims/{cid}/approve", json={"approve": True})
    assert r.status_code == 200, r.text


def msg(chat, text=None, photo=False, caption=None):
    m = {"chat": {"id": chat, "type": "private"}}
    if text is not None:
        m["text"] = text
    if photo:
        m["photo"] = [{"file_id": "small"}, {"file_id": "big"}]
    if caption:
        m["caption"] = caption
    UPDATES.append({"update_id": len(UPDATES) + 1, "message": m})


def test_case53_already_checked_by_others(admin, fake):
    old = admin.post("/api/claims", json={"text": "صورة طوابير طويلة أمام محطات الوقود صباح اليوم"}).json()["id"]
    approve(admin, old)
    cid = admin.post("/api/claims", json={"text": "صورة طوابير طويلة أمام محطات الوقود هذا الصباح"}).json()["id"]
    r = admin.post(f"/api/claims/{cid}/factcheck").json()
    assert r["configured"] is False and "مفتاح Google Fact Check" in r["note"] and r["global"] == []
    assert r["local"][0]["claim_id"] == old and r["local"][0]["label"] == "مضلل"  # سجل البرنامج يعمل بلا مفتاح
    assert admin.put("/api/tools/factcheck/key", json={"key": "bad"}).status_code == 422
    assert admin.put("/api/tools/factcheck/key", json={"key": "good-key"}).json()["configured"] is True
    assert "good-key" not in json.dumps(admin.get("/api/tools/factcheck").json())
    r = admin.post(f"/api/claims/{cid}/factcheck").json()
    assert r["configured"] is True and r["error"] == ""
    g = r["global"][0]
    assert g["publisher"] == "مسبار" and g["rating"] == "مضلل" and g["date"] == "2026-10-01" and g["url"] == "https://misbar.com/x"
    assert {q["languageCode"][0] for q in SEARCHES[-2:]} == {"ar", "en"}
    assert admin.get(f"/api/claims/{cid}").json()["factcheck"]["global"][0]["publisher"] == "مسبار"  # محفوظ في البطاقة
    assert admin.put("/api/tools/factcheck/key", json={"key": ""}).json()["configured"] is False


def test_case54_public_tipline(admin, make_client, fake):
    assert admin.put("/api/alerts/telegram/bot", json={"token": "123:good"}).status_code == 200
    msg(900, "/start")
    msg(900, photo=True, caption="هل هذه الصورة لطوابير الوقود اليوم؟ https://social.example/p/1")
    msg(901, "سمعت أن المدارس ستغلق غدًا في كل المحافظات")
    r = admin.post("/api/tips/poll").json()
    assert r == {"tips": 2, "linked": 0}
    assert "صندوق بلاغات" in SENT[0]["text"] and SENT[0]["chat_id"] == 900
    codes = [s["text"].split("رقم متابعته ")[1].split(".")[0] for s in SENT[1:]]
    assert all(c.startswith("T-") for c in codes) and len(set(codes)) == 2
    assert admin.post("/api/tips/poll").json()["tips"] == 0  # لا تكرار
    d = admin.get("/api/tips").json()
    assert d["counts"]["new"] == 2
    photo = next(t for t in d["tips"] if t["media_kind"])
    assert photo["media_kind"] == "image" and photo["urls"] == ["https://social.example/p/1"] and photo["can_reply"]
    assert "900" not in json.dumps(d)  # معرّف المحادثة لا يظهر
    # الصحفي يحوّل البلاغ إلى ادّعاء
    j, _ = invite_user(admin, make_client, "j@example.com", ["journalist"])
    cid = j.post(f"/api/tips/{photo['id']}/claim", json={"text": "صورة لطوابير الوقود اليوم", "reply": True}).json()["claim_id"]
    assert j.post(f"/api/tips/{photo['id']}/claim", json={}).status_code == 422
    card = admin.get(f"/api/claims/{cid}").json()
    kinds = [e["kind"] for e in card["evidence"]]
    assert "file" in kinds and "link" in kinds
    other = next(t for t in d["tips"] if not t["media_kind"])
    SENT.clear()
    j.post(f"/api/tips/{other['id']}/reject", json={"note": "مكرر", "reply_text": "تحققنا من هذا من قبل: لا قرار بالإغلاق."})
    assert SENT[-1]["chat_id"] == 901 and "لا قرار" in SENT[-1]["text"]
    # الحكم يُعتمد فيصل الرد إلى صاحب البلاغ
    approve(admin, cid)
    from marsad.db import get_db
    from marsad.tools import tips

    db = next(get_db())
    assert tips.answer_verdicts(db) == 1
    db.commit()
    assert tips.answer_verdicts(db) == 0
    assert SENT[-1]["chat_id"] == 900 and "الحكم: مضلل" in SENT[-1]["text"]
    # بعد 90 يومًا يُمحى معرّف المحادثة ويبقى البلاغ
    assert tips.purge(db, now=datetime.now(timezone.utc) + timedelta(days=91)) == 2
    db.commit()
    db.close()
    assert all(not t["can_reply"] for t in admin.get("/api/tips?status=all").json()["tips"])
    # ربط الحسابات ما زال يعمل بالقارئ نفسه
    code = admin.post("/api/alerts/telegram/link").json()["code"]
    msg(5001, f"/start {code}")
    assert admin.post("/api/alerts/telegram/check").json()["linked"] is True
    # المتدرّب لا يرى البلاغات
    tr, _ = invite_user(admin, make_client, "t@example.com", ["trainee"])
    assert tr.get("/api/tips").status_code == 403


def test_case55_official_figures(admin, make_client):
    f = admin.post("/api/figures", json={"indicator": "معدل البطالة", "value": "21.4", "unit": "٪", "as_of": "2026-06",
                                         "agency": "دائرة الإحصاءات العامة", "url": "https://dos.gov.jo/x", "keywords": "البطالة، العاطلين"}).json()
    assert f["as_of"] == "2026-06" and f["keywords"] == ["البطالة", "العاطلين"]
    admin.post("/api/figures", json={"indicator": "معدل البطالة", "value": 22.0, "unit": "٪", "as_of": "2025", "keywords": ["البطالة"]})
    cid = admin.post("/api/claims", json={"text": "ارتفعت نسبة البطالة إلى 30٪ هذا العام بحسب ناشطين"}).json()["id"]
    m = admin.get(f"/api/claims/{cid}/figures").json()["matches"]
    assert len(m) == 1
    assert m[0]["claimed"] == 30 and m[0]["official"] == 21.4 and m[0]["diff_pct"] == 40.2 and m[0]["agency"] == "دائرة الإحصاءات العامة"
    same = admin.post("/api/figures/match", json={"text": "بلغ معدل البطالة ٢١٫٤٪ في الربع الثاني"}).json()["matches"]
    assert same[0]["claimed"] == 21.4 and same[0]["same"] is True
    assert admin.post("/api/figures/match", json={"text": "البطالة مشكلة كبيرة"}).json()["matches"] == []
    csv = "المؤشر,القيمة,الوحدة,التاريخ,الجهة,الكلمات\nعدد السكان,11.7,مليون نسمة,2025,دائرة الإحصاءات,السكان|عدد سكان\nخطأ,abc,,2025,,\n"
    r = admin.post("/api/figures/import", files={"file": ("f.csv", csv.encode("utf-8-sig"))}).json()
    assert r["added"] == 1 and "السطر 3" in r["errors"][0]
    pop = admin.post("/api/figures/match", json={"text": "عدد سكان الأردن 12 مليونًا"}).json()["matches"]
    assert pop[0]["indicator"] == "عدد السكان" and pop[0]["diff_pct"] == 2.6
    j, _ = invite_user(admin, make_client, "j@example.com", ["journalist"])
    assert j.post("/api/figures", json={"indicator": "x", "value": 1, "as_of": "2025"}).status_code == 403
    assert len(j.get("/api/figures").json()["figures"]) == 3
    audit = admin.get("/api/admin/audit").json()
    assert any(a["action"] == "figure.create" for a in (audit["rows"] if isinstance(audit, dict) else audit))


def test_case56_promises_and_reminders(admin):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    p = admin.post("/api/promises", json={"entity_name": "وزير الأشغال", "text": "سننجز طريق المطار الجديد قبل نهاية العام",
                                          "due_at": past, "said_at": "2026-01-10", "source_url": "https://news.example/1"}).json()
    assert p["status"] == "tracking" and p["overdue"] is True and p["entity"] == "وزير الأشغال"
    from marsad.db import get_db
    from marsad.models.engines import Notification
    from marsad.tools import promises

    db = next(get_db())
    assert promises.due_reminders(db) == 1
    db.commit()
    assert promises.due_reminders(db) == 0
    assert "حان موعد وعد" in db.query(Notification).filter_by(kind="promise.due").one().text
    db.close()
    assert admin.patch(f"/api/promises/{p['id']}", json={"status": "broken"}).status_code == 422  # بلا دليل
    u = admin.patch(f"/api/promises/{p['id']}", json={"status": "partial", "evidence_url": "https://news.example/2",
                                                     "evidence_note": "افتُتح نصف الطريق فقط"}).json()
    assert u["status_ar"] == "تحقق جزئيًا" and u["overdue"] is False and len(u["history"]) == 2
    assert admin.get(f"/api/promises?entity_id={p['entity_id']}").json()["promises"][0]["id"] == p["id"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg غير مثبت")
def test_case57_press_conference_transcript(admin, fake, tmp_path):
    import subprocess

    wav = tmp_path / "conf.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(wav)], check=True)
    mid = admin.post("/api/labs/media", files={"file": ("conf.wav", wav.read_bytes())}).json()["id"]
    t = admin.post(f"/api/transcripts/{mid}").json()
    assert t["available"] is True and len(t["segments"]) == 3
    flags = [s["reasons"] for s in t["segments"]]
    assert flags[0] == []  # تحية: لا تُبرز
    assert "رقم" in flags[1] and "نسبة" in flags[1] and "مقارنة" in flags[1]
    assert "واقعة منسوبة" in flags[2]
    assert t["checkable"] == 2
    cid = admin.post(f"/api/transcripts/{mid}/claim", json={"i": 1}).json()["claim_id"]
    card = admin.get(f"/api/claims/{cid}").json()
    ev = next(e for e in card["evidence"] if e["kind"] == "check")
    assert "00:00:02" in ev["title"] and card["speaker"] == "الوزير" and card["transcript"]["start"] == 2.0
    assert admin.post(f"/api/transcripts/{mid}/claim", json={"i": 9}).status_code == 422
    assert any(m["media_id"] == mid and m["checkable"] == 2 for m in admin.get("/api/transcripts").json()["media"])


def test_case58_instant_archive(admin, fake):
    PAGES["/news/1"] = "<html><head><title>قرار إغلاق المدارس</title></head><body><article><p>" + "قررت الوزارة إغلاق المدارس غدًا بسبب المنخفض الجوي. " * 20 + "</p></article></body></html>"
    url = f"{fake}/news/1"
    s = admin.post("/api/snapshots", json={"url": url}).json()
    assert s["status"] == "ok" and len(s["sha256"]) == 64 and s["wayback_status"] == "off" and "المدارس" in s["text_preview"]
    del PAGES["/news/1"]  # حُذفت الصفحة الأصلية
    raw = admin.get(f"/api/snapshots/{s['id']}/html")
    assert raw.status_code == 200 and "قرار إغلاق المدارس" in raw.text and "attachment" in raw.headers["content-disposition"]
    import hashlib

    assert hashlib.sha256(raw.content).hexdigest() == s["sha256"]
    gone = admin.post("/api/snapshots", json={"url": url}).json()
    assert gone["status"] == "error"
    PAGES["/news/2"] = "<html><body><p>خبر ثانٍ</p></body></html>"
    w = admin.post("/api/snapshots", json={"url": f"{fake}/news/2", "wayback": True}).json()
    assert w["status"] == "ok", w
    assert w["wayback_status"] == "ok" and "/save/" in w["wayback_url"]
    assert admin.post("/api/snapshots", json={"url": "ftp://x"}).status_code == 422
    # الإرفاق بادّعاء يضيف دليلًا
    cid = admin.post("/api/claims", json={"text": "المدارس ستغلق غدًا في كل المحافظات"}).json()["id"]
    PAGES["/news/3"] = "<html><body><p>ثالث</p></body></html>"
    admin.post("/api/snapshots", json={"url": f"{fake}/news/3", "claim_id": cid})
    assert any(e["kind"] == "link" and "مؤرشفة" in e["title"] for e in admin.get(f"/api/claims/{cid}").json()["evidence"])
    # الروابط في مسودة القصة تُؤرشف تلقائيًا، ولا تظهر خارج القضية
    case = admin.post("/api/cases", json={"title": "قضية اختبار الأرشفة"}).json()["id"]
    PAGES["/src/a"] = "<html><body><p>مصدر المسودة</p></body></html>"
    d = admin.post(f"/api/cases/{case}/drafts", json={"title": "م", "angle": "", "body": "تمهيد"}).json()
    admin.put(f"/api/drafts/{d['id']}", json={"title": "م", "body": f"كما ورد في {fake}/src/a، وأكد مصدر آخر.", "version": d["version"]})
    snaps = admin.get(f"/api/snapshots?case_id={case}").json()["snapshots"]
    assert [x["url"] for x in snaps] == [f"{fake}/src/a"] and snaps[0]["status"] == "ok"
    assert all(x["case_id"] is None for x in admin.get("/api/snapshots").json()["snapshots"])


def test_case59_result_card_only_for_approved_verdicts(admin):
    cid = admin.post("/api/claims", json={"text": "صورة لفيضان في وسط العاصمة صباح اليوم"}).json()["id"]
    assert admin.get(f"/api/claims/{cid}/card").status_code == 422
    approve(admin, cid, "مفبرك", "الصورة مولّدة وتحمل توقيع أداة توليد.")
    c = admin.get(f"/api/claims/{cid}/card").json()
    assert c["label"] == "مفبرك" and c["claim"].startswith("صورة لفيضان") and len(c["date"]) == 10 and c["org"]
