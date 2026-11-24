"""البند 12: الحالات 49–52. بيانات معروفة تُبنى مباشرة، ثم يُقارن كل رقم بالعدّ اليدوي ومعرّفاته."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import invite_user

NOW = datetime.now(timezone.utc).replace(microsecond=0)
T0 = NOW - timedelta(days=3)


@pytest.fixture
def data(admin):
    from marsad.db import get_db
    from marsad.models import User
    from marsad.models.analysis import Story
    from marsad.models.claims import Claim, ClaimItem, Verdict
    from marsad.models.engines import EngineBatch, EngineRun
    from marsad.models.monitoring import Item, ItemVersion, Outlet, Source
    from marsad.text import normalize_ar

    db = next(get_db())
    uid = db.query(User).first().id
    srcs = {}
    for name, kind in (("وكالة الشمال", "rss"), ("صحيفة الوسط", "rss"), ("موقع الجنوب", "rss"), ("قناة البلد", "telegram")):
        o = Outlet(name=name)
        db.add(o)
        db.flush()
        s = Source(outlet_id=o.id, url=f"https://{o.id}.example/feed", kind=kind)
        db.add(s)
        db.flush()
        srcs[name] = s
    n = [0]

    def item(src, title, text, at, status="live"):
        n[0] += 1
        s = srcs[src]
        it = Item(source_id=s.id, outlet_id=s.outlet_id, url=f"https://{s.outlet_id}.example/n/{n[0]}", title=title, text=text,
                  published_at=at, captured_at=at, status=status, norm=normalize_ar(f"{title} {text}"))
        db.add(it)
        db.flush()
        db.add(ItemVersion(item_id=it.id, version=1, change="new", title=title, text=text, captured_at=at))
        return it

    # قصة: الشمال أولًا، الوسط ينقل عنه بذكر اسمه، الجنوب ينقل دون نسبة
    a = item("وكالة الشمال", "حريق في مستودع بمدينة الزرقاء", "اندلع حريق كبير في الزرقاء صباح اليوم", T0)
    b = item("صحيفة الوسط", "حريق الزرقاء", "نقلت وكالة الشمال أن حريقًا اندلع في الزرقاء", T0 + timedelta(minutes=30))
    c = item("موقع الجنوب", "حريق ضخم في الزرقاء", "اندلع حريق في مستودع، ولا إصابات", T0 + timedelta(minutes=90), status="deleted")
    st = Story(title="حريق الزرقاء", first_item_id=a.id, item_count=3, source_count=3)
    db.add(st)
    db.flush()
    for it in (a, b, c):
        it.story_id = st.id
    # تعديل لاحق لمادة الوسط
    db.add(ItemVersion(item_id=b.id, version=2, change="edit", title="حريق الزرقاء (محدّث)", captured_at=T0 + timedelta(hours=2)))

    # ادّعاء 1 (صحة، تيليغرام): 4 ظهورات في الساعات الست قبل الحكم، وظهور بعده، وحكم «مضلل» بعد 10 ساعات
    seen1 = T0 + timedelta(hours=1)
    first = item("قناة البلد", "لقاح جديد يسبب العقم", "منشور: اللقاح الجديد يسبب العقم", seen1)
    c1 = Claim(text="اللقاح الجديد يسبب العقم لدى النساء", norm=normalize_ar("اللقاح الجديد يسبب العقم لدى النساء"),
               first_item_id=first.id, first_seen_at=seen1, created_by=uid, created_at=seen1, status="verdict")
    db.add(c1)
    db.flush()
    db.add(ClaimItem(claim_id=c1.id, item_id=first.id, kind="first"))
    vt1 = seen1 + timedelta(hours=10)
    apps = []
    for h in (5, 6, 7, 8):  # كلها في [vt-6، vt)
        apps.append(item("صحيفة الوسط" if h % 2 else "موقع الجنوب", f"اللقاح والعقم {h}", "يتداول ناشطون أن اللقاح يسبب العقم",
                         seen1 + timedelta(hours=h)))
    apps.append(item("وكالة الشمال", "اللقاح والعقم بعد التحقق", "ما زال البعض يتداول", vt1 + timedelta(hours=2)))
    for it in apps:
        db.add(ClaimItem(claim_id=c1.id, item_id=it.id, kind="appearance"))
    # الناشر صحّح إحدى المواد بعد الحكم
    db.add(ItemVersion(item_id=apps[0].id, version=2, change="edit", title="تصحيح", captured_at=vt1 + timedelta(hours=1)))
    batch = EngineBatch(task="verdict", input={}, mode="single", engine_ids=[], status="done")
    db.add(batch)
    db.flush()
    db.add(EngineRun(batch_id=batch.id, engine_name="وهمي", task="verdict", prompt_id="x", prompt_version="1", model="m",
                     request={}, status="ok", cost_usd=0.5, created_at=seen1 + timedelta(hours=2)))
    db.add(Verdict(claim_id=c1.id, label="مضلل", evidence_grade="مؤشر قوي", status="rejected", author_id=None,
                   engine_batch_id=batch.id, created_at=seen1 + timedelta(hours=2)))
    db.add(Verdict(claim_id=c1.id, label="مضلل", evidence_grade="قاطع", status="approved", author_id=uid, approved_by=uid,
                   approved_at=vt1, created_at=vt1 - timedelta(hours=1)))

    # ادّعاء 2 (اقتصاد، يدوي): «صحيح» بعد 4 ساعات
    seen2 = T0 + timedelta(days=1)
    c2 = Claim(text="ارتفاع أسعار البنزين عشرة بالمئة هذا الشهر", norm="", first_seen_at=seen2, created_at=seen2, created_by=uid)
    db.add(c2)
    db.flush()
    db.add(Verdict(claim_id=c2.id, label="صحيح", evidence_grade="قاطع", status="approved", author_id=uid, approved_by=uid,
                   approved_at=seen2 + timedelta(hours=4), created_at=seen2 + timedelta(hours=3)))
    # ادّعاء 3 معلّق
    c3 = Claim(text="إغلاق المدارس في كل المحافظات غدًا", norm="", first_seen_at=T0 + timedelta(days=2),
               created_at=T0 + timedelta(days=2), created_by=uid)
    db.add(c3)
    # ادّعاء 4 قديم يعود في الفترة
    old = NOW - timedelta(days=60)
    c4 = Claim(text="انقطاع المياه عن عمان أسبوعًا كاملًا", norm="", first_seen_at=old, created_at=old)
    db.add(c4)
    db.flush()
    ret = item("موقع الجنوب", "المياه تنقطع عن عمان", "انقطاع المياه أسبوعًا", T0 + timedelta(days=2, hours=3))
    db.add(ClaimItem(claim_id=c4.id, item_id=ret.id, kind="return", added_at=T0 + timedelta(days=2, hours=3)))
    db.commit()
    ids = {"c1": c1.id, "c2": c2.id, "c3": c3.id, "c4": c4.id, "a": a.id, "b": b.id, "c": c.id, "apps": [x.id for x in apps],
           "first": first.id, "ret": ret.id, "outlet": {k: v.outlet_id for k, v in srcs.items()}}
    yield ids
    db.close()


def get(c, **q):
    r = c.get("/api/stats", params={"days": 30, **q})
    assert r.status_code == 200, r.text
    return r.json()


def test_case49_verification_dashboard(admin, data):
    v = get(admin)["verification"]
    assert v["claims"]["n"] == 3 and set(v["claims"]["drill"]["ids"]) == {data["c1"], data["c2"], data["c3"]}
    assert v["decided"]["drill"]["ids"] == [data["c1"], data["c2"]]
    assert v["pending"]["drill"]["ids"] == [data["c3"]]
    labels = {x["label"]: x["drill"]["ids"] for x in v["labels"]}
    assert labels["مضلل"] == [data["c1"]] and labels["صحيح"] == [data["c2"]] and labels["مفبرك"] == []
    t = v["time_to_verdict_hours"]
    assert t == {"median": 7.0, "mean": 7.0, "count": 2}  # 10 ساعات و4
    topics = {x["key"]: x["drill"]["ids"] for x in v["by_topic"]}
    assert topics["صحة"] == [data["c1"]] and topics["اقتصاد"] == [data["c2"]] and topics["تعليم"] == [data["c3"]]
    plat = {x["key"]: x["drill"]["ids"] for x in v["by_platform"]}
    assert plat["تيليغرام"] == [data["c1"]] and set(plat["إدخال يدوي"]) == {data["c2"], data["c3"]}
    assert v["returns"]["drill"]["ids"] == [data["c4"]] and v["returns"]["top"][0]["times"] == 1
    # الفلاتر
    f = get(admin, topic="صحة")["verification"]
    assert f["claims"]["drill"]["ids"] == [data["c1"]] and f["returns"]["n"] == 0
    assert get(admin, platform="تيليغرام")["verification"]["claims"]["drill"]["ids"] == [data["c1"]]
    # كل رقم يفتح ما حُسب منه
    rows = admin.get("/api/stats/rows", params={"kind": "claims", "ids": ",".join(map(str, v["decided"]["drill"]["ids"]))}).json()["rows"]
    assert [r["link"] for r in rows] == [f"/claims/{data['c1']}", f"/claims/{data['c2']}"] and rows[0]["meta"] == "مضلل"
    # فترة سابقة لا تحوي شيئًا
    old = admin.get("/api/stats", params={"start": "2020-01-01", "end": "2020-01-31"}).json()["verification"]
    assert old["claims"]["n"] == 0 and old["time_to_verdict_hours"]["median"] is None


def test_case50_spread_and_correction_effect(admin, data):
    s = admin.get(f"/api/stats/spread/{data['c1']}").json()
    assert s["bucket"] == "hour" and s["verdict_at"]
    assert sum(p["items"] for p in s["points"]) == 6
    e = s["effect"]
    assert e["before"]["n"] == 4 and e["after"]["n"] == 1 and e["drop_pct"] == 75
    assert set(e["before"]["drill"]["ids"]) == set(data["apps"][:4])
    top = get(admin)["spread"]["claims"]
    assert top[0]["claim_id"] == data["c1"] and top[0]["appearances"] == 6 and top[0]["verdict"] == "مضلل"
    # ادّعاء بلا حكم: لا أثر يُحسب
    assert admin.get(f"/api/stats/spread/{data['c3']}").json()["effect"] is None
    g = get(admin)["geography"]
    gov = {x["key"]: x["n"] for x in g["governorates"]}
    assert gov["الزرقاء"] == 3 and gov["العاصمة"] == 1 and gov["الكرك"] == 0
    assert sum(x["n"] for x in g["heatmap"]) == 10 and len(g["heatmap"]) == 168


def test_case51_sources_dashboard(admin, data):
    rows = {r["name"]: r for r in get(admin)["sources"]["outlets"]}
    south, middle, north = rows["موقع الجنوب"], rows["صحيفة الوسط"], rows["وكالة الشمال"]
    assert north["first"]["drill"]["ids"] == [data["a"]]
    assert middle["uncredited"]["n"] == 0 and middle["delay_minutes"]["median"] == 30.0
    assert south["uncredited"]["drill"]["ids"] == [data["c"]] and south["delay_minutes"]["median"] == 90.0
    assert south["deleted"]["drill"]["ids"] == [data["c"]]
    assert set(middle["edited"]["drill"]["ids"]) == {data["b"], data["apps"][0]}
    assert middle["edited_pct"] == round(100 * 2 / middle["items"]["n"], 1)


def test_case52_impact_report(admin, data):
    imp = get(admin)["impact"]
    assert imp["verified"]["drill"]["ids"] == [data["c1"], data["c2"]]
    assert imp["not_true"]["drill"]["ids"] == [data["c1"]]
    assert imp["publisher_corrected"]["drill"]["ids"] == [data["c1"]] and imp["publisher_corrected"]["pct"] == 50.0
    assert imp["publisher_corrected"]["items"]["drill"]["ids"] == [data["apps"][0]]
    assert imp["spread_measured"]["drill"]["ids"] == [data["c1"]] and imp["spread_dropped"]["pct"] == 100.0
    csv = admin.get("/api/stats/impact.csv", params={"days": 30})
    assert csv.status_code == 200 and csv.text.startswith("﻿")
    assert "صحّحه ناشره بعد التحقق,1," in csv.text and f"{data['c1']} {data['c2']}" in csv.text
    html = admin.get("/api/stats/impact/print", params={"days": 30}).text
    assert "تقرير الأثر" in html and "50.0٪" in html


def test_team_dashboard_and_permissions(admin, make_client, data):
    t = get(admin)["team"]
    p = t["people"][0]
    assert p["created"]["n"] == 3 and p["approved"]["n"] == 2 and p["hours_to_verdict"]["median"] == 7.0
    assert t["engine_cost_usd"] == 0.5 and t["cost_per_verdict_usd"] == 0.25
    assert t["engine_agreement"]["pairs"] == 1 and t["engine_agreement"]["kappa"] is None  # أقل من 5 أزواج
    j, _ = invite_user(admin, make_client, "j@example.com", ["journalist"])
    out = get(j)
    assert "team" not in out and out["can_team"] is False and out["verification"]["claims"]["n"] == 3
    assert j.get("/api/stats/impact.csv").status_code == 403  # التصدير يحتاج «تصدير البيانات»
    tr, _ = invite_user(admin, make_client, "t@example.com", ["trainee"])
    assert tr.get("/api/stats").status_code == 403
    ed, _ = invite_user(admin, make_client, "e@example.com", ["editor"])
    assert "team" in get(ed)


def test_kappa_multi():
    from marsad.analytics.core import kappa_multi

    assert kappa_multi([("a", "a")] * 4) is None
    assert kappa_multi([("a", "a"), ("b", "b"), ("a", "a"), ("b", "b"), ("c", "c")]) == 1.0
    k = kappa_multi([("a", "a"), ("b", "a"), ("a", "a"), ("b", "b"), ("c", "b"), ("a", "b")])
    assert -1 <= k < 1


def test_topics_and_governorates():
    from marsad.analytics.topics import governorates_in, topic_of
    from marsad.text import normalize_ar

    assert topic_of("ارتفاع نسبة البطالة بين الشباب") == "اقتصاد"
    assert topic_of("نص عام بلا موضوع واضح") == "أخرى"
    assert topic_of("أي نص", ["رياضة"]) == "رياضة"
    assert governorates_in(normalize_ar("وصل الوفد إلى إربد والعقبة")) == ["إربد", "العقبة"]
    assert governorates_in(normalize_ar("كاربدان")) == []


def test_new_permissions_reach_existing_builtin_roles(admin):
    """تثبيت قديم (قبل صلاحيات الإحصاءات) يحصل عليها في الأدوار الجاهزة، دون إعادة ما سحبه المدير."""
    from marsad.db import get_db
    from marsad.models.accounts import Role, RolePermission
    from marsad.rbac.service import KNOWN_PERMISSIONS_KEY, seed_builtin_roles, set_setting
    from marsad.rbac.permissions import LEGACY_PERMISSIONS

    db = next(get_db())
    j = db.query(Role).filter_by(key="journalist").one()
    db.query(RolePermission).filter(RolePermission.role_id == j.id,
                                    RolePermission.permission.in_(["stats.view", "labs.use"])).delete()
    set_setting(db, KNOWN_PERMISSIONS_KEY, sorted(LEGACY_PERMISSIONS))
    db.commit()
    db.expire_all()  # كبدء تشغيل جديد للبرنامج
    seed_builtin_roles(db)
    db.commit()
    db.refresh(j)
    have = {rp.permission for rp in j.permissions}
    assert "stats.view" in have and "labs.use" not in have
    seed_builtin_roles(db)  # المرة الثانية لا تغيّر شيئًا
    db.commit()
    db.close()
