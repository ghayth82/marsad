import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.conftest import invite_user
from tests.test_analysis import feed  # noqa: F401  نفس أداة إدخال المواد

GOLD = json.loads((Path(__file__).parent / "gold" / "rumors.json").read_text(encoding="utf-8"))
T0 = datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)


def debunk(c, text, item_id=None, label="مفبرك"):
    cid = c.post("/api/claims", json={"text": text, "item_id": item_id}).json()["id"]
    c.post(f"/api/claims/{cid}/evidence", json={"kind": "check", "title": "البصمة تطابق صورة من 2024", "grade": "قاطع", "is_conclusive": True})
    assert c.post(f"/api/claims/{cid}/verdict", json={"label": label, "evidence_grade": "قاطع", "explanation": "الصورة قديمة من 2024 ونُشرت على أنها حديثة."}).status_code == 200
    return cid


def test_case16_debunked_rumor_returns_reworded_alert(admin, make_client, feed):  # noqa: F811
    ed, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    ids = []
    for old, _new in GOLD["pairs"]:
        cid = debunk(admin, old)
        assert ed.post(f"/api/claims/{cid}/approve", json={}).status_code == 200
        ids.append(cid)
    for n, (_old, new) in enumerate(GOLD["pairs"]):
        feed(f"قناة{n}", new, "", published=T0 + timedelta(days=30))
    for u in GOLD["unrelated"]:
        feed("موقع عادي", u, "", published=T0 + timedelta(days=30))
    alerts = admin.get("/api/rumors/alerts").json()
    assert len(alerts) == len(GOLD["pairs"])  # كل عائدة اكتُشفت، ولا إنذار كاذب من الأخبار غير المتعلقة
    assert all("/claims/" in a["text"] for a in alerts)  # مع رابط التحقق السابق
    c = admin.get(f"/api/claims/{ids[0]}").json()
    assert c["returns"] == 1 and any(n["kind"] == "return" for n in c["spread"]["nodes"])


def test_verdict_cycle_four_eyes_conclusive_rule_and_history(admin, make_client):
    j, jid = invite_user(admin, make_client, "j@example.com", ["journalist"])
    ed, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    cid = j.post("/api/claims", json={"text": "صورة لطوابير أمام محطات الوقود اليوم في عمان"}).json()["id"]
    r = j.post(f"/api/claims/{cid}/verdict", json={"label": "مضلل", "evidence_grade": "قاطع", "explanation": "صورة قديمة كما يبدو"})
    assert r.status_code == 422 and "قاطع" in r.json()["detail"]  # لا حكم قاطع دون دليل قاطع
    assert j.post(f"/api/claims/{cid}/verdict", json={"label": "مضلل", "evidence_grade": "مؤشر قوي", "explanation": "شعار المحطة قديم وتغيّر في 2025."}).status_code == 200
    assert j.post(f"/api/claims/{cid}/approve", json={}).status_code == 403  # الصحفي لا يعتمد
    admin.put("/api/admin/settings/four-eyes", json={"enabled": True})
    ed_self = ed.post("/api/claims", json={"text": "قرار بإغلاق طريق المطار ثلاثة أيام"}).json()["id"]
    ed.post(f"/api/claims/{ed_self}/verdict", json={"label": "مفبرك", "evidence_grade": "مؤشر قوي", "explanation": "لا يوجد أي قرار بذلك."})
    assert ed.post(f"/api/claims/{ed_self}/approve", json={}).status_code == 403  # العينان الأربع
    assert ed.post(f"/api/claims/{cid}/approve", json={}).status_code == 200
    # تعديل حكم معتمد تصحيح: يُرفض دون سبب (البند 14)
    assert j.post(f"/api/claims/{cid}/verdict", json={"label": "صحيح جزئيًا", "evidence_grade": "مؤشر قوي", "explanation": "الطوابير حقيقية لكن في مدينة أخرى."}).status_code == 422
    j.post(f"/api/claims/{cid}/verdict", json={"label": "صحيح جزئيًا", "evidence_grade": "مؤشر قوي", "explanation": "الطوابير حقيقية لكن في مدينة أخرى.",
                                                "correction_reason": "ظهرت صورة أصلية بموقع مختلف"})
    c = admin.get(f"/api/claims/{cid}").json()
    assert [h["status"] for h in c["history"]] == ["approved", "proposed"]  # كل نسخة محفوظة
    audit = [a for a in admin.get("/api/admin/audit").json() if a["target_type"] == "claim" and a["target_id"] == str(cid)]
    assert any(a["action"] == "verdict.propose" and a["before"] and a["before"]["label"] == "مضلل" for a in audit)  # حالة 38


def test_auto_extraction_and_appearances(admin, feed):  # noqa: F811
    feed("قناة شائعات", "متداول: صورة لانهيار جسر عبدون في عمان صباح اليوم", "صورة متداولة على مواقع التواصل.", published=T0)
    cl = admin.get("/api/claims").json()
    assert len(cl) == 1 and cl[0]["origin"] == "auto"
    feed("قناة أخرى", "لحظة انهيار جسر عبدون في العاصمة عمان (فيديو)", "", published=T0 + timedelta(hours=1))
    assert admin.get("/api/claims").json()[0]["appearances"] == 2  # لا ادّعاء مكرر، بل ظهور جديد
    feed("موقع إخباري", "افتتاح مطعم جديد في عمان", "خبر عادي عن مطعم.", published=T0)
    assert len(admin.get("/api/claims").json()) == 1  # الأخبار العادية لا تُنشئ ادّعاءات


def test_spread_tree_and_coordination(admin, feed):  # noqa: F811
    text = "عاجل: قرار بتعطيل المدارس غدا الأحد بسبب المنخفض الجوي"
    first = feed("المصدر الأول", text, "", published=T0)
    cid = admin.post("/api/claims", json={"text": text, "item_id": first}).json()["id"]
    for n in range(3):
        feed(f"حساب{n}", text, "", published=T0 + timedelta(minutes=5 + n * 5))
    sp = admin.get(f"/api/claims/{cid}").json()["spread"]
    assert len(sp["nodes"]) == 4 and sp["nodes"][0]["parent_item_id"] is None
    assert all(n["parent_item_id"] for n in sp["nodes"][1:])
    assert sp["coordination"] and len(sp["coordination"][0]["outlets"]) == 4


def test_radar_detects_spike(admin, feed):  # noqa: F811
    from marsad.db import get_db
    from marsad.models.monitoring import Item

    now = datetime.now(timezone.utc)
    for n in range(8):
        feed("أ", f"خبر عادي رقم {n} عن الاقتصاد", "", captured=now - timedelta(days=3, hours=n))
    ids = [feed(f"م{n}", f"حريق كبير في سوق الخضار المركزي {n}", "", captured=now - timedelta(minutes=10 * n)) for n in range(5)]
    assert ids
    r = admin.get("/api/rumors/radar").json()
    top = " ".join(x["term"] for x in r[:3])
    assert r and any(w in top for w in ("حريق", "سوق", "خضار")) and r[0]["count"] >= 3
    assert not any("اقتصاد" in x["term"] for x in r)  # الموضوع المعتاد لا يظهر صاعدًا
    assert next(get_db()).get(Item, ids[0])


def test_case34_claimreview_and_csv_export(admin, make_client):
    ed, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    cid = debunk(admin, "الحكومة تقرر رفع سعر ربطة الخبز إلى دينار")
    ed.post(f"/api/claims/{cid}/approve", json={})
    cr = admin.get("/api/claims/export/claimreview").json()
    assert len(cr) == 1 and cr[0]["@type"] == "ClaimReview" and cr[0]["@context"] == "https://schema.org"
    assert cr[0]["reviewRating"]["alternateName"] == "مفبرك" and cr[0]["reviewRating"]["ratingValue"] == 1
    assert cr[0]["claimReviewed"].startswith("الحكومة تقرر")
    csv_text = admin.get("/api/claims/export/csv").text
    assert csv_text.startswith("﻿id,claim") and "مفبرك" in csv_text


def test_engines_suggest_verdict_for_claim(admin):
    out = {"label": "مضلل", "evidence": "مؤشر قوي", "reasoning": "سبب", "items": []}
    eid = admin.post("/api/engines", json={"name": "وهمي", "provider": "fake", "model": "m", "options": {"fake_output": out}}).json()["id"]
    admin.put("/api/engines/settings/current", json={"default_engine_id": eid})
    cid = admin.post("/api/claims", json={"text": "صورة لطوابير أمام محطات الوقود اليوم"}).json()["id"]
    bid = admin.post(f"/api/claims/{cid}/engines", json={}).json()["batch_id"]
    b = admin.get(f"/api/engines/batches/{bid}").json()
    assert b["status"] == "done" and b["runs"][0]["output"]["label"] == "مضلل"
    assert admin.get(f"/api/claims/{cid}").json()["verdict"] is None  # اقتراح المحرك لا يصبح حكمًا


def test_official_statement_suggestion(admin, feed):  # noqa: F811
    from marsad.db import get_db
    from marsad.models.monitoring import Outlet

    fid = feed("حساب مجهول", "متداول: وزارة التربية تعلن تعطيل المدارس يوم الأحد بسبب المنخفض الجوي", "", published=T0)
    oid = feed("وزارة التربية والتعليم", "وزارة التربية تنفي تعطيل المدارس يوم الأحد", "قالت الوزارة إن الأنباء المتداولة عن تعطيل الدوام غير صحيحة.", published=T0 + timedelta(hours=2))
    db = next(get_db())
    for o in db.query(Outlet).filter(Outlet.name == "وزارة التربية والتعليم"):
        o.kind = "official"
    db.commit()
    cid = admin.get("/api/claims").json()[0]["id"]
    s = admin.get(f"/api/claims/{cid}").json()["official_suggestions"]
    assert s and s[0]["item_id"] == oid and s[0]["denial"]
    admin.put(f"/api/claims/{cid}", json={"official_item_id": oid})
    assert admin.get(f"/api/claims/{cid}").json()["official_item"]["id"] == oid
    assert fid
