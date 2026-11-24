"""البند 14: الحالات 60–63 — سير العمل التحريري، الواجهة البرمجية، Webhook، سجل التصحيحات العلني."""

import hashlib
import hmac
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from tests.conftest import invite_user

GOT: list[dict] = []
FAIL = {"n": 0}


class Receiver(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if FAIL["n"] > 0:
            FAIL["n"] -= 1
            self.send_response(500)
            self.end_headers()
            return
        GOT.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        self.send_response(200)
        self.end_headers()


@pytest.fixture
def receiver():
    srv = HTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    GOT.clear()
    FAIL["n"] = 0
    yield f"http://127.0.0.1:{srv.server_port}/hook"
    srv.shutdown()


def db_session():
    from marsad.db import get_db

    return next(get_db())


def propose(c, cid, label="مضلل", reason=""):
    return c.post(f"/api/claims/{cid}/verdict", json={"label": label, "evidence_grade": "مؤشر قوي",
                                                      "explanation": "الصورة من عام 2024 ونُشرت على أنها حديثة.", "correction_reason": reason})


def raw(client):
    """طلب دون ترويسة الواجهة: كما يأتي من نظام خارجي."""
    return lambda method, url, **kw: TestClient.request(client, method, url, **kw)


def test_case60_editorial_workflow_with_deadline(admin, make_client):
    ed, ed_id = invite_user(admin, make_client, "ed@example.com", ["editor"])
    ed2, _ = invite_user(admin, make_client, "ed2@example.com", ["editor"])
    j, j_id = invite_user(admin, make_client, "j@example.com", ["journalist"])
    cid = admin.post("/api/claims", json={"text": "صورة لطوابير طويلة أمام محطات الوقود صباح اليوم"}).json()["id"]
    assert j.put(f"/api/claims/{cid}/workflow", json={"assignee_id": ed_id}).status_code == 403  # الصحفي لا يسند لغيره
    people = {p["name"] for p in ed.get("/api/workflow/people").json()["people"]}
    assert "j" in people
    t0 = datetime.now(timezone.utc)
    w = ed.put(f"/api/claims/{cid}/workflow", json={"assignee_id": j_id, "priority": "urgent"}).json()
    assert w["status"] == "assigned" and w["assignee"] == "j" and w["priority_ar"] == "عاجل"
    due = datetime.fromisoformat(w["due_at"])
    assert timedelta(hours=1, minutes=59) < due - t0 < timedelta(hours=2, minutes=1)  # مهلة العاجل ساعتان
    assert j.get("/api/dashboard").json()["my_tasks"]["tasks"][0]["id"] == cid
    from marsad.models.engines import Notification
    from marsad.org import workflow

    db = db_session()
    assert db.query(Notification).filter_by(kind="workflow.assigned", user_id=j_id).count() == 1
    assert workflow.sla_alerts(db, now=t0 + timedelta(minutes=30)) == 0  # ما زال الوقت مبكرًا
    assert workflow.sla_alerts(db, now=t0 + timedelta(minutes=95)) == 1  # تبقى أقل من ربع المهلة
    db.commit()
    assert workflow.sla_alerts(db, now=t0 + timedelta(minutes=100)) == 0  # مرة واحدة
    assert db.query(Notification).filter_by(kind="workflow.soon", user_id=j_id).count() == 1
    assert workflow.sla_alerts(db, now=t0 + timedelta(hours=2, minutes=5)) == 1
    db.commit()
    over = {n.user_id for n in db.query(Notification).filter_by(kind="workflow.overdue")}
    assert j_id in over and ed_id in over  # المُسند إليه والمحرّرون
    db.close()
    col = ed.get("/api/workflow/board").json()["columns"][1]
    assert col["title"] == "مُسند" and col["claims"][0]["id"] == cid
    # العمل ثم المراجعة: لا اعتماد دون مراجع ثانٍ
    assert j.post(f"/api/claims/{cid}/workflow/start").json()["status"] == "investigating"
    assert propose(j, cid).status_code == 200
    assert ed2.get("/api/workflow/mine").json()["review"][0]["id"] == cid
    # المحرّر يكتب الحكم بنفسه في ادّعاء مُسند، فلا يعتمده هو
    cid2 = admin.post("/api/claims", json={"text": "إغلاق المدارس في كل المحافظات غدًا بسبب المنخفض"}).json()["id"]
    ed.put(f"/api/claims/{cid2}/workflow", json={"assignee_id": ed_id, "priority": "normal"})
    assert propose(ed, cid2).status_code == 200
    r = ed.post(f"/api/claims/{cid2}/approve", json={"approve": True})
    assert r.status_code in (403, 422) and "مراجع ثانٍ" in r.json()["detail"]
    assert ed2.post(f"/api/claims/{cid2}/approve", json={"approve": True}).status_code == 200
    # الرفض يحتاج سببًا وصلاحية المحرّر
    cid3 = admin.post("/api/claims", json={"text": "ادّعاء لا يستحق التحقق لأنه رأي شخصي بحت"}).json()["id"]
    assert j.post(f"/api/claims/{cid3}/workflow/dismiss", json={"reason": "رأي"}).status_code == 403
    assert ed.post(f"/api/claims/{cid3}/workflow/dismiss", json={"reason": ""}).status_code == 422
    assert ed.post(f"/api/claims/{cid3}/workflow/dismiss", json={"reason": "رأي لا واقعة"}).json()["status"] == "dismissed"
    # المهل قابلة للتعديل
    assert admin.put("/api/workflow/sla", json={"urgent": 1, "high": 4, "normal": 12}).json()["urgent"] == 1
    assert admin.put("/api/workflow/sla", json={"urgent": 0, "high": 4, "normal": 12}).status_code == 422


def test_case61_api_tokens_and_scopes(admin, make_client):
    cid = admin.post("/api/claims", json={"text": "صورة لفيضان في وسط العاصمة صباح اليوم"}).json()["id"]
    propose(admin, cid, "مفبرك")
    admin.post(f"/api/claims/{cid}/approve", json={"approve": True})
    r = admin.post("/api/api-access/tokens", json={"name": "نظام النشر", "scopes": ["verdicts.read"], "expires_days": 30}).json()
    tok = r["token"]
    assert tok.startswith("mrs_") and r["prefix"] == tok[:10]
    lst = admin.get("/api/api-access").json()
    assert tok not in json.dumps(lst) and lst["tokens"][0]["name"] == "نظام النشر"
    req = raw(admin)
    H = {"Authorization": f"Bearer {tok}"}
    v = req("GET", "/api/v1/verdicts", headers=H).json()["verdicts"]
    assert v[0]["claim_id"] == cid and v[0]["label"] == "مفبرك" and "author_id" not in v[0] and "approved_by" not in v[0]
    assert req("GET", "/api/v1/verdicts").status_code == 401
    assert req("GET", "/api/v1/verdicts", headers={"Authorization": "Bearer mrs_wrong"}).status_code == 401
    r2 = req("POST", "/api/v1/claims", headers=H, json={"text": "ادّعاء من نظام النشر للتحقق منه"})
    assert r2.status_code == 403 and "الصلاحية" in r2.json()["detail"]
    w = admin.post("/api/api-access/tokens", json={"name": "نموذج البلاغات", "scopes": ["claims.write", "claims.read"]}).json()["token"]
    c = req("POST", "/api/v1/claims", headers={"Authorization": f"Bearer {w}"},
            json={"text": "ادّعاء من نظام النشر للتحقق منه", "source_url": "https://news.example/a"})
    assert c.status_code == 201 and c.json()["verdict"] is None
    card = admin.get(f"/api/claims/{c.json()['id']}").json()
    assert card["origin"] == "api" and card["evidence"][0]["url"] == "https://news.example/a"
    assert req("GET", f"/api/v1/claims/{cid}", headers={"Authorization": f"Bearer {w}"}).json()["verdict"]["label"] == "مفبرك"
    # الرمز المنتهي والمسحوب يُرفضان
    from marsad.models.org import ApiToken

    db = db_session()
    t = db.query(ApiToken).filter_by(name="نظام النشر").one()
    assert t.token_hash == hashlib.sha256(tok.encode()).hexdigest() and t.uses >= 1
    t.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()
    e = req("GET", "/api/v1/verdicts", headers=H)
    assert e.status_code == 401 and "انتهت" in e.json()["detail"]
    tid = next(x["id"] for x in admin.get("/api/api-access").json()["tokens"] if x["name"] == "نموذج البلاغات")
    admin.delete(f"/api/api-access/tokens/{tid}")
    assert req("GET", "/api/v1/claims", headers={"Authorization": f"Bearer {w}"}).status_code == 401
    # الإدارة للمدير وحده، والتوثيق متاح
    ed, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    assert ed.get("/api/api-access").status_code == 403
    spec = admin.get("/api/api-access/openapi.json").json()
    assert "/api/v1/verdicts" in spec["paths"] and "/api/claims" not in spec["paths"]


def test_case62_signed_webhook_with_retries(admin, receiver):
    h = admin.post("/api/api-access/webhooks", json={"url": receiver, "events": ["verdict.approved", "verdict.corrected"]}).json()
    secret = h["secret"]
    assert secret not in json.dumps(admin.get("/api/api-access").json())
    cid = admin.post("/api/claims", json={"text": "صورة لطوابير طويلة أمام محطات الوقود صباح اليوم"}).json()["id"]
    propose(admin, cid)
    FAIL["n"] = 1  # المحاولة الأولى تفشل
    admin.post(f"/api/claims/{cid}/approve", json={"approve": True})
    from marsad.org import public_api

    db = db_session()
    assert public_api.deliver(db) == {"sent": 0, "failed": 0}
    db.commit()
    assert GOT == []
    assert public_api.deliver(db) == {"sent": 0, "failed": 0}  # لم يحن موعد الإعادة
    assert public_api.deliver(db, now=datetime.now(timezone.utc) + timedelta(minutes=2))["sent"] == 1
    db.commit()
    db.close()
    got = GOT[-1]
    ts, sig = got["headers"]["x-marsad-timestamp"], got["headers"]["x-marsad-signature"]
    assert sig == "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + got["body"], hashlib.sha256).hexdigest()
    payload = json.loads(got["body"])
    assert got["headers"]["x-marsad-event"] == "verdict.approved" and payload["data"]["claim_id"] == cid and payload["data"]["label"] == "مضلل"
    d = admin.get("/api/api-access").json()["webhooks"][0]["deliveries"][0]
    assert d["status"] == "sent" and d["attempts"] == 2
    t = admin.post(f"/api/api-access/webhooks/{h['id']}/test").json()
    assert t["sent"] == 1 and json.loads(GOT[-1]["body"])["event"] == "ping"


def test_case63_public_corrections_log(admin, make_client, receiver):
    admin.post("/api/api-access/webhooks", json={"url": receiver, "events": ["verdict.corrected"]})
    cid = admin.post("/api/claims", json={"text": "صورة لفيضان في وسط العاصمة صباح اليوم"}).json()["id"]
    propose(admin, cid, "مفبرك")
    admin.post(f"/api/claims/{cid}/approve", json={"approve": True})
    r = propose(admin, cid, "صحيح جزئيًا")
    assert r.status_code == 422 and "سبب التصحيح" in r.json()["detail"]
    assert propose(admin, cid, "صحيح جزئيًا", "ظهر تسجيل أصلي يثبت أن الفيضان حدث فعلًا في حي آخر").status_code == 200
    admin.post(f"/api/claims/{cid}/approve", json={"approve": True})
    k = admin.get("/api/corrections").json()
    assert k["public"] is False
    row = k["corrections"][0]
    assert row["before"]["label"] == "مفبرك" and row["after"]["label"] == "صحيح جزئيًا" and "تسجيل أصلي" in row["reason"]
    from marsad.org import public_api

    db = db_session()
    public_api.deliver(db)
    db.commit()
    db.close()
    p = json.loads(GOT[-1]["body"])
    assert p["event"] == "verdict.corrected" and p["data"]["previous"]["label"] == "مفبرك"
    # الصفحة العامة مغلقة حتى يفتحها المدير، وتُفتح دون دخول
    anon = make_client()
    assert anon.get("/public/corrections").status_code == 404
    ed, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    assert ed.put("/api/corrections/public", json={"public": True}).status_code == 403
    admin.put("/api/corrections/public", json={"public": True})
    html = anon.get("/public/corrections")
    assert html.status_code == 200 and "صورة لفيضان" in html.text and "مفبرك" in html.text and "تسجيل أصلي" in html.text
    assert "غيث" not in html.text and "ghayth" not in html.text  # دون أسماء
    j = anon.get("/public/corrections.json").json()["corrections"][0]
    assert "by" not in j and j["after"]["label"] == "صحيح جزئيًا"
    # المحرّر يخفي تصحيحًا بعينه من الصفحة العامة
    ed.put(f"/api/corrections/{row['id']}", json={"public": False})
    assert anon.get("/public/corrections.json").json()["corrections"] == []
