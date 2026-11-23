"""تقييم المواقع: الحالتان 28 و29، والمنهجية بإصداراتها، والمراجعة البشرية، وحق الرد."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import invite_user
from tests.test_analysis import feed  # noqa: F401

NOW = datetime.now(timezone.utc)
BODY = ("وقال وزير المالية في بيان رسمي إن الموازنة الجديدة تتضمن زيادة في مخصصات التعليم والصحة، "
        "وأوضح أن الحكومة ستعرض التفاصيل على مجلس النواب الأسبوع المقبل، فيما أكد رئيس اللجنة المالية أن المجلس سيناقشها. ") * 2


def seed_month(feed, outlet, n, sensational_every=0, anon_every=0, no_source_every=0):  # noqa: F811
    ids = []
    for k in range(n):
        title = f"الحكومة تعرض الموازنة {k} على مجلس النواب"
        text = BODY.replace("الموازنة الجديدة", f"الموازنة الجديدة رقم {k}")
        if sensational_every and k % sensational_every == 0:
            title = f"شاهد بالفيديو: ماذا حدث في جلسة الموازنة {k}؟!"
        if no_source_every and k % no_source_every == 0:
            text = ("الموازنة الجديدة تتضمن زيادة في مخصصات التعليم والصحة والنقل والطاقة، وتصل نفقاتها إلى أرقام قياسية هذا العام، "
                    f"والتفاصيل تعرض لاحقا على مجلس النواب رقم {k}. ") * 3
        if anon_every and k % anon_every == 0:
            text += " وقال مصدر مطلع إن التعديلات ستشمل الرواتب."
        ids.append(feed(outlet, title, text, published=NOW - timedelta(days=1 + k % 25), captured=NOW - timedelta(days=1 + k % 25),
                        url=f"https://{outlet}.example/n/{k}"))
    return ids


@pytest.fixture
def small_sample(admin):
    """حد أدنى للعيّنة صغير ليناسب الاختبار — ويختبر في الطريق نفسه أن تغيير المنهجية إصدار جديد مسجّل."""
    m = admin.get("/api/ratings/methodology").json()["current"]
    r = admin.post("/api/ratings/methodology", json={"weights": m["weights"], "min_sample": 10, "period_days": 90,
                                                     "note": "عيّنة اختبار صغيرة"})
    assert r.status_code == 200 and r.json()["version"] == m["version"] + 1
    return r.json()


def test_case28_every_number_traceable(admin, feed, small_sample):  # noqa: F811
    ids = seed_month(feed, "موقع المدى", 24, sensational_every=4, anon_every=6, no_source_every=8)
    rank = admin.get("/api/ratings").json()
    assert "داخلي فقط" in rank["notice"]
    row = next(r for r in rank["rows"] if r["outlet"]["name"] == "موقع المدى")
    oid = row["outlet"]["id"]
    card = admin.get(f"/api/ratings/outlets/{oid}").json()
    assert card["items"] == 24
    for key, ind in card["indicators"].items():
        if key == "transparency":
            continue
        full = admin.get(f"/api/ratings/outlets/{oid}/indicators/{key}").json()
        # البسط والمقام قائمتا مواد كاملتان، والرقم يُعاد حسابه منهما
        assert len(full["examples_good"]) == full["good"] and len(full["examples_bad"]) == full["bad"]
        assert full["sample"] == full["good"] + full["bad"]
        assert all(x["item_id"] in ids for x in full["examples_good"] + full["examples_bad"])
        if full["enough"]:
            assert abs(full["value"] - full["good"] / full["sample"]) < 0.001
            assert full["ci"][0] <= full["value"] <= full["ci"][1]
    s = card["indicators"]["sensational"]
    assert s["bad"] == 6 and s["value"] == pytest.approx(18 / 24, abs=0.001)
    a = card["indicators"]["attribution"]
    assert a["bad"] == 2 and a["anonymous"] == 4  # المادة 0 بلا مصدر لكنها تنسب لـ«مصدر مطلع»: مسندة، وتُعدّ في المجهولة
    assert card["indicators"]["accuracy"]["enough"] is False and card["indicators"]["accuracy"]["value"] is None  # لا عيّنة: لا رقم


def test_min_sample_hides_value_and_composite(admin, feed):  # noqa: F811
    seed_month(feed, "موقع صغير", 6)
    row = next(r for r in admin.get("/api/ratings").json()["rows"] if r["outlet"]["name"] == "موقع صغير")
    assert row["composite"] is None
    assert row["indicators"]["sensational"]["value"] is None and row["indicators"]["sensational"]["sample"] == 6


def test_accuracy_corrections_and_right_of_reply(admin, make_client, feed, small_sample):  # noqa: F811
    from marsad.db import get_db
    from marsad.models.monitoring import Item, ItemVersion

    ids = seed_month(feed, "وكالة النبأ", 12)
    ed, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    wrong = ids[:3]
    for n, iid in enumerate(ids[:10]):
        cid = admin.post("/api/claims", json={"text": f"ادعاء رقم {n} عن موازنة الحكومة وأرقامها الجديدة", "item_id": iid}).json()["id"]
        label = "مضلل" if iid in wrong else "صحيح"
        admin.post(f"/api/claims/{cid}/evidence", json={"kind": "check", "title": "مطابقة الأرقام مع الوثيقة الرسمية", "grade": "قاطع",
                                                        "is_conclusive": True})
        assert admin.post(f"/api/claims/{cid}/verdict", json={"label": label, "evidence_grade": "قاطع", "explanation": "بالمطابقة مع الوثيقة."}).status_code == 200
        assert ed.post(f"/api/claims/{cid}/approve", json={}).status_code == 200
    db = next(get_db())
    for k, iid in enumerate(ids[:6]):  # 2 تعديلان معلنان و4 صامتة
        it = db.get(Item, iid)
        db.add(ItemVersion(item_id=iid, version=2, change="edit", title=it.title,
                           text=("تنويه: ورد خطأ في الرقم وتم تصحيحه. " if k < 2 else "") + it.text))
    db.commit()
    db.close()
    oid = next(r for r in admin.get("/api/ratings").json()["rows"] if r["outlet"]["name"] == "وكالة النبأ")["outlet"]["id"]
    acc = admin.get(f"/api/ratings/outlets/{oid}").json()["indicators"]["accuracy"]
    assert (acc["good"], acc["bad"]) == (7, 3) and acc["value"] == 0.7
    assert {x["item_id"] for x in acc["examples_bad"]} == set(wrong)
    cor = admin.get(f"/api/ratings/outlets/{oid}/indicators/corrections").json()
    assert (cor["good"], cor["bad"]) == (2, 4)
    # حق الرد: الجهة تعترض على مادة؛ المحرّر يقبل؛ تخرج المادة من المؤشر
    r = admin.post("/api/ratings/replies", json={"outlet_id": oid, "item_id": wrong[0], "indicator": "accuracy",
                                                 "text": "الرقم المنشور مأخوذ من بيان الوزارة الأول قبل تعديله", "channel": "بريد"}).json()
    assert r["status"] == "open"
    assert admin.post(f"/api/ratings/replies/{r['id']}/decide", json={"status": "accepted", "resolution": ""}).status_code == 422
    assert ed.post(f"/api/ratings/replies/{r['id']}/decide", json={"status": "accepted", "resolution": "ثبت أن البيان الأول احتوى الرقم"}).status_code == 200
    acc2 = admin.get(f"/api/ratings/outlets/{oid}").json()
    assert (acc2["indicators"]["accuracy"]["good"], acc2["indicators"]["accuracy"]["bad"]) == (7, 2)
    assert acc2["replies"][0]["status"] == "accepted"
    log = admin.get("/api/admin/audit").json()
    actions = [x["action"] for x in (log["rows"] if isinstance(log, dict) else log)]
    assert "ratings.reply" in actions and "ratings.reply_decision" in actions and "ratings.methodology" in actions


def test_case29_public_publishing_forbidden(admin, make_client, feed):  # noqa: F811
    seed_month(feed, "موقع الشمال", 3)
    oid = admin.get("/api/ratings").json()["rows"][0]["outlet"]["id"]
    sid = admin.post(f"/api/ratings/outlets/{oid}/snapshot").json()["id"]
    ap = admin.post(f"/api/ratings/scores/{sid}/approve").json()
    assert ap["status"] == "approved" and ap["public"] is False
    r = admin.post("/api/ratings/publish")
    assert r.status_code == 403 and "المراجعة القانونية" in r.json()["detail"]
    # لا مسار عام بلا تسجيل دخول
    anon = make_client()
    assert anon.get("/api/ratings").status_code == 401
    assert anon.get(f"/api/ratings/outlets/{oid}").status_code == 401


def test_review_labels_and_kappa(admin, make_client, feed):  # noqa: F811
    seed_month(feed, "موقع الصدى", 12, sensational_every=3)
    q = admin.get("/api/ratings/review/sensational").json()
    assert q["question"] and len(q["items"]) == 12 and "machine" not in q["items"][0]
    from marsad.ratings.core import SENSATIONAL
    from marsad.text import normalize_ar

    for it in q["items"]:
        assert admin.post("/api/ratings/review", json={"item_id": it["item_id"], "indicator": "sensational",
                                                       "value": bool(SENSATIONAL.search(normalize_ar(it["title"])))}).json()["ok"]
    ag = admin.get("/api/ratings/agreement").json()["sensational"]
    assert ag["kappa_machine_human"] == 1.0 and ag["acceptable"] is True
    # مراجع ثانٍ يخالف في مادتين
    j, _ = invite_user(admin, make_client, "j@example.com", ["journalist"])
    for n, it in enumerate(j.get("/api/ratings/review/sensational").json()["items"]):
        v = bool(SENSATIONAL.search(normalize_ar(it["title"])))
        j.post("/api/ratings/review", json={"item_id": it["item_id"], "indicator": "sensational", "value": (not v) if n < 2 else v})
    ag = admin.get("/api/ratings/agreement").json()["sensational"]
    assert ag["double_reviewed"] == 12 and ag["kappa_human_human"] < 1.0


def test_permissions_and_transparency(admin, make_client, feed):  # noqa: F811
    seed_month(feed, "موقع الضفة", 3)
    oid = admin.get("/api/ratings").json()["rows"][0]["outlet"]["id"]
    res, _ = invite_user(admin, make_client, "r@example.com", ["researcher"])
    assert res.get(f"/api/ratings/outlets/{oid}").status_code == 200
    assert res.post("/api/ratings/methodology", json={"weights": {}, "note": "x"}).status_code == 403
    tr, _ = invite_user(admin, make_client, "t@example.com", ["trainee"])
    assert tr.get("/api/ratings").status_code == 403
    t = admin.put(f"/api/ratings/outlets/{oid}/transparency", json={"ownership": "شركة الضفة للإعلام", "contact": "info@example.com"}).json()
    assert t["ownership"]
    ind = admin.get(f"/api/ratings/outlets/{oid}").json()["indicators"]["transparency"]
    assert ind["value"] == 0.4 and sum(x["declared"] for x in ind["items"]) == 2
    bad = admin.post("/api/ratings/methodology", json={"weights": {"accuracy": 10}, "note": ""})
    assert bad.status_code == 422
