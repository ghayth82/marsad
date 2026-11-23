"""التنبيهات والتقارير والتدريب: الحالات 32 و33 و35، ولوحة الرئيسية ببيانات حقيقية."""

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import invite_user
from tests.test_analysis import feed  # noqa: F401

SENT: list[dict] = []
UPDATES: list[dict] = []


class FakeTG(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        token, method = self.path.split("/")[1][3:], self.path.split("/")[2]
        if token != "123:good":
            out = {"ok": False, "description": "Unauthorized"}
        elif method == "getMe":
            out = {"ok": True, "result": {"id": 1, "username": "marsad_test_bot"}}
        elif method == "getUpdates":
            out = {"ok": True, "result": UPDATES}
        elif method == "sendMessage":
            SENT.append(body)
            out = {"ok": True, "result": {"message_id": len(SENT)}}
        else:
            out = {"ok": False}
        b = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)


@pytest.fixture
def tg(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), FakeTG)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("MARSAD_TELEGRAM_API", f"http://127.0.0.1:{srv.server_port}")
    SENT.clear()
    UPDATES.clear()
    yield
    srv.shutdown()


def link_telegram(c, chat_id):
    code = c.post("/api/alerts/telegram/link").json()["code"]
    UPDATES.append({"update_id": len(UPDATES) + 1, "message": {"text": f"/start {code}", "chat": {"id": chat_id}}})
    r = c.post("/api/alerts/telegram/check").json()
    assert r["linked"] is True
    return code


def run_tick():
    from marsad.db import get_db
    from marsad.reports import alerts

    db = next(get_db())
    made = alerts.scan(db)
    db.commit()
    sent = alerts.dispatch(db)
    db.commit()
    db.close()
    return made, sent


def test_case32_urgent_rumor_reaches_telegram(admin, make_client, feed, tg):  # noqa: F811
    assert admin.put("/api/alerts/telegram/bot", json={"token": "bad"}).status_code == 422
    r = admin.put("/api/alerts/telegram/bot", json={"token": "123:good"}).json()
    assert r["bot"] == "marsad_test_bot"
    assert "123:good" not in json.dumps(admin.get("/api/alerts/telegram").json())
    link_telegram(admin, 5001)
    assert "telegram" in admin.get("/api/me").json()["preferences"]["alerts"]["channels"]
    assert SENT[-1]["chat_id"] == 5001  # رسالة تأكيد الربط
    # صحفي مرتبط بتيليغرام لكنه يريد العاجل فقط؛ وباحث بلا ربط
    j, _ = invite_user(admin, make_client, "j@example.com", ["journalist"])
    link_telegram(j, 5002)
    j.patch("/api/me/preferences", json={"alerts": {"channels": ["in_app", "telegram"], "urgent_only": True}})
    SENT.clear()
    # شائعة عاجلة: الادّعاء نفسه في 3 مصادر خلال دقائق
    now = datetime.now(timezone.utc)
    text = "انتشر خبر عن إغلاق جميع المدارس في المملكة غدًا بسبب انتشار مرض معدٍ بين الطلاب، وتداولته صفحات كثيرة."
    first = feed("صفحة 1", "عاجل: إغلاق جميع المدارس غدًا", text, published=now, captured=now)
    assert first  # الادّعاء يُسجَّل تلقائيًا من المادة (علامات الشائعة: «عاجل»، «تداولته»)
    feed("صفحة 2", "إغلاق المدارس غدًا", text, published=now, captured=now)
    feed("صفحة 3", "خبر إغلاق جميع المدارس", text, published=now, captured=now)
    made, sent = run_tick()
    spikes = [m for m in SENT if "تنتشر بسرعة" in m["text"]]
    assert {m["chat_id"] for m in spikes} == {5001, 5002}, SENT
    import re

    cid = int(re.search(r"/claims/(\d+)", spikes[0]["text"]).group(1))
    assert admin.get(f"/api/claims/{cid}").json()["appearances"] >= 3
    # لا تكرار في الدقيقة التالية
    SENT.clear()
    run_tick()
    assert not [m for m in SENT if "تنتشر بسرعة" in m["text"]]
    # تنبيه غير عاجل (مصدر متوقف) لا يصل لمن اختار العاجل فقط
    from marsad.db import get_db
    from marsad.models.engines import Notification

    db = next(get_db())
    db.add(Notification(kind="source.error", text="توقف رصد المصدر «تجربة»"))
    db.commit()
    db.close()
    run_tick()
    assert [m["chat_id"] for m in SENT if "توقف رصد" in m["text"]] == [5001]


def test_quiet_hours_and_follow(admin, feed, tg):  # noqa: F811
    from marsad.reports import alerts

    admin.put("/api/alerts/telegram/bot", json={"token": "123:good"})
    link_telegram(admin, 7001)
    admin.patch("/api/me/preferences", json={"follows": {"topics": ["محطة التحلية"], "sources": [], "entities": []},
                                             "alerts": {"channels": ["in_app", "telegram"], "quiet_hours": [0, 23]}})
    SENT.clear()
    now = datetime.now(timezone.utc)
    feed("موقع", "بدء العمل في محطة التحلية الجديدة", "أعلنت الشركة بدء العمل في محطة التحلية الجديدة جنوب المدينة.", published=now, captured=now)
    from marsad.db import get_db

    db = next(get_db())
    alerts.scan(db)
    db.commit()
    quiet = datetime.now(ZoneInfo("Asia/Amman")).replace(hour=12)
    alerts.dispatch(db, now=quiet.astimezone(timezone.utc))
    db.commit()
    assert not SENT  # ساعات الهدوء: يُؤجَّل
    admin.patch("/api/me/preferences", json={"alerts": {"channels": ["in_app", "telegram"], "quiet_hours": None}})
    db.expire_all()
    alerts.dispatch(db)
    db.commit()
    db.close()
    assert any("محطة التحلية" in m["text"] for m in SENT)
    assert any(a["kind"] == "follow" for a in admin.get("/api/dashboard").json()["alerts"])


def test_case33_morning_brief_on_schedule(admin, feed):  # noqa: F811
    from marsad.db import get_db
    from marsad.reports import core

    now = datetime.now(timezone.utc)
    feed("موقع أ", "خبر عن الموازنة", "نص طويل عن الموازنة العامة للدولة وأرقامها الجديدة هذا العام.", published=now, captured=now)
    db = next(get_db())
    tz = ZoneInfo("Asia/Amman")
    before = datetime.combine(now.astimezone(tz).date(), datetime.min.time(), tz).replace(hour=6, minute=50)
    after = before.replace(hour=7, minute=4)
    assert "morning" not in core.due(db, before)
    assert "morning" in core.due(db, after)
    for kind in core.due(db, after):
        core.generate(db, kind, now=after)
    db.commit()
    assert "morning" not in core.due(db, after.replace(hour=9))  # مرة واحدة في اليوم
    db.close()
    rows = admin.get("/api/reports").json()["rows"]
    m = next(r for r in rows if r["kind"] == "morning")
    assert m["auto"] is True and "الموجز الصباحي" in m["summary"]
    full = admin.get(f"/api/reports/{m['id']}").json()["content"]
    assert full["items"] >= 1 and "rising_stories" in full and "claims" in full
    assert admin.get(f"/api/reports/{m['id']}/print").status_code == 200
    assert admin.get("/api/dashboard").json()["daily_brief"]["id"] == m["id"]
    # التقرير الأسبوعي يدويًا، وجدول المواعيد يتغيّر من الإدارة
    w = admin.post("/api/reports/weekly").json()
    assert w["kind"] == "weekly" and "engine_cost_usd" in w["content"]
    assert admin.put("/api/reports-schedule", json={"morning": "7am"}).status_code == 422
    assert admin.put("/api/reports-schedule", json={"morning": "06:30", "weekly_day": 6, "weekly": "09:00"}).json()["morning"] == "06:30"


def test_case35_training_exercise_graded_with_model_solution(admin, make_client):
    st, _ = invite_user(admin, make_client, "student@example.com", ["trainee"])
    lst = st.get("/api/training").json()
    assert len(lst) == 3
    ex = st.get(f"/api/training/{lst[0]['id']}").json()
    assert "answer" not in ex  # الحل النموذجي مخفي قبل الإجابة
    r = st.post(f"/api/training/{ex['id']}/submit", json={"label": "مضلل", "grade": "قاطع",
                                                           "reasoning": "وجدنا نسخة أقدم في الأرشيف قبل اربع سنوات، ونشرة الأرصاد تقول لا أمطار."}).json()
    assert r["submission"]["score"] == pytest.approx(50 + 25 + 25 * 2 / 3, abs=0.1)
    assert r["answer"]["label"] == "مضلل" and r["submission"]["feedback"]["missed"] == ["البيانات الوصفيه"]
    again = st.get(f"/api/training/{ex['id']}").json()
    assert again["answer"]["explanation"] and len(again["submissions"]) == 1
    wrong = st.post(f"/api/training/{lst[1]['id']}/submit", json={"label": "صحيح", "grade": "لا يكفي", "reasoning": ""}).json()
    assert wrong["submission"]["score"] == 0 and "الصحيح «مفبرك»" in wrong["submission"]["feedback"]["label"]
    # المتدرّب لا يرى غير التدريب، ولا ينشئ تمارين
    assert st.get("/api/claims").status_code == 403
    assert st.post("/api/training", json={"title": "x", "answer": {"label": "صحيح", "grade": "قاطع"}}).status_code == 403
    # المدرّب: ينشئ تمرينًا، يرى الإجابات، ويعدّل الدرجة (تصحيحه يتقدّم على الآلي) ويُسجَّل
    ex2 = admin.post("/api/training", json={"title": "تمرين جديد", "material": {"text": "مادة"}, "answer": {
        "label": "مفبرك", "grade": "قاطع", "key_points": ["بيان رسمي|نفي"], "explanation": "نفي رسمي"}}).json()
    assert ex2["answer"]["key_points"] == ["بيان رسمي|نفي"]
    assert admin.post("/api/training", json={"title": "x", "answer": {"label": "ربما", "grade": "قاطع"}}).status_code == 422
    subs = admin.get(f"/api/training/{ex['id']}/submissions").json()
    g = admin.post(f"/api/training/submissions/{subs[0]['id']}/grade", json={"score": 100, "note": "تعليل ممتاز"}).json()
    assert g["final_score"] == 100
    assert next(x for x in st.get("/api/training").json() if x["id"] == ex["id"])["my_score"] == 100
    d = st.get("/api/dashboard").json()
    assert d["training"]["total"] == 4 and d["training"]["done"] == 2 and "rising_stories" not in d


def test_dashboard_real_data(admin, make_client, feed):  # noqa: F811
    now = datetime.now(timezone.utc)
    for n in range(3):
        feed(f"موقع {n}", "انقطاع المياه عن أحياء في العاصمة", "أعلنت سلطة المياه انقطاع المياه عن أحياء في العاصمة يوم الخميس بسبب أعمال صيانة.",
             published=now - timedelta(minutes=10 * n), captured=now - timedelta(minutes=10 * n))
    admin.post("/api/claims", json={"text": "المياه ستنقطع أسبوعًا كاملًا عن العاصمة"})
    d = admin.get("/api/dashboard").json()
    assert d["rising_stories"] and d["rising_stories"][0]["outlets"] == 3
    assert d["new_rumors"]["count"] == 1
    assert d["sources_status"]["total"] == 3
    assert "pending_approvals" in d and "my_cases" in d
