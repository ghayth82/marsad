import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

GOLD = json.loads((Path(__file__).parent / "gold" / "stories.json").read_text(encoding="utf-8"))
T0 = datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)


@pytest.fixture
def feed(admin):
    """ينشئ جهات ومصادر ويُدخل مواد مباشرة (دون شبكة)."""
    from marsad.db import get_db
    from marsad.models.monitoring import Outlet, Source
    from marsad.monitor.service import store_entry

    db = next(get_db())
    made = {}

    def add(outlet, title, text, published=None, captured=None, url=None):
        if outlet not in made:
            o = Outlet(name=outlet)
            db.add(o)
            db.flush()
            s = Source(outlet_id=o.id, url=f"https://{len(made)}.example/rss", kind="rss")
            db.add(s)
            db.flush()
            made[outlet] = s
        e = {"url": url or f"https://{outlet}.example/{abs(hash(title))}", "title": title, "text": text,
             "published_at": published, "full": True, "media": []}
        it = store_entry(db, made[outlet], e, fetch_full=False)
        if captured:
            it.captured_at = captured
        db.commit()
        return it.id

    yield add
    db.close()


def test_case13_five_sites_same_news_one_story(admin, feed):
    ids = [feed(f"موقع{n}", t, x, published=T0 + timedelta(minutes=10 * n)) for n, (t, x) in enumerate(GOLD["same"])]
    others = [feed(f"آخر{n}", t, x, published=T0 + timedelta(minutes=5 * n)) for n, (t, x) in enumerate(GOLD["other"])]
    stories = {s["id"]: s for s in admin.get("/api/stories").json()}
    fuel = {admin.get(f"/api/items/{i}").json()["story_id"] for i in ids}
    assert len(fuel) == 1, "الصياغات الخمس يجب أن تتجمع في قصة واحدة"
    sid = fuel.pop()
    assert stories[sid]["item_count"] == 5 and stories[sid]["source_count"] == 5
    other_sids = {admin.get(f"/api/items/{i}").json()["story_id"] for i in others}
    assert len(other_sids) == 4 and sid not in other_sids  # لا خلط مع أخبار أخرى


def test_case14_first_publisher_across_timezones(admin, feed):
    from datetime import timezone as tz

    amman = tz(timedelta(hours=3))
    t, x = GOLD["same"][0]
    # موقع «ب» نشر 08:05 بتوقيت عمّان = 05:05 UTC، قبل «أ» 05:30 UTC رغم أن ساعته المحلية أكبر
    a = feed("أ", t, x, published=datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc), captured=datetime(2026, 11, 20, 5, 31, tzinfo=timezone.utc))
    b = feed("ب", GOLD["same"][1][0], GOLD["same"][1][1], published=datetime(2026, 11, 20, 8, 5, tzinfo=amman),
             captured=datetime(2026, 11, 20, 5, 6, tzinfo=timezone.utc))
    # «ج» يدّعي نشرًا مبكرًا مستحيلًا (بعد رصدنا بساعات): يُعتمد وقت رصدنا
    c = feed("ج", GOLD["same"][2][0], GOLD["same"][2][1], published=datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc),
             captured=datetime(2026, 11, 20, 4, 30, tzinfo=timezone.utc))
    sid = admin.get(f"/api/items/{a}").json()["story_id"]
    v = admin.get(f"/api/stories/{sid}").json()
    assert v["first"]["outlet"] == "ج" and v["first"]["basis"] == "وقت النشر المعلن"
    order = [x["outlet"] for x in v["timeline"]]
    assert order == ["ج", "ب", "أ"]
    assert v["timeline"][1]["time"].startswith("2026-11-20T05:05")  # التحويل إلى UTC صحيح
    assert b and c


def test_case14b_declared_time_after_capture_is_not_trusted(admin, feed):
    t, x = GOLD["same"][0]
    i = feed("د", t, x, published=datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc), captured=datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc))
    sid = admin.get(f"/api/items/{i}").json()["story_id"]
    assert admin.get(f"/api/stories/{sid}").json()["first"]["basis"] == "وقت رصدنا لها"


def test_case15_contradicting_narratives_side_by_side(admin, feed):
    a = feed("صحيفة الأولى", "حادث سير على طريق المطار يودي بحياة 3 أشخاص",
             "قالت مديرية الأمن العام إن حادث تصادم على طريق المطار أسفر عن وفاة 3 أشخاص وإصابة 7 آخرين صباح اليوم.", published=T0)
    b = feed("صحيفة الثانية", "حادث تصادم على طريق المطار ووفاة 5 أشخاص",
             "أفادت مصادر مطلعة بأن حادث تصادم على طريق المطار أدى إلى وفاة 5 أشخاص وإصابة 7 آخرين، فيما لم تعلق مديرية الأمن العام.", published=T0 + timedelta(minutes=20))
    sid = admin.get(f"/api/items/{a}").json()["story_id"]
    assert admin.get(f"/api/items/{b}").json()["story_id"] == sid
    cmp_ = admin.get(f"/api/stories/{sid}").json()["comparison"]
    dis = cmp_["disagreements"]
    assert dis and {v["value"] for v in dis[0]["values"]} == {"3", "5"}
    assert {o for v in dis[0]["values"] for o in v["outlets"]} == {"صحيفة الأولى", "صحيفة الثانية"}
    assert cmp_["anonymous_sources"] == ["صحيفة الثانية"]
    assert any("الامن العام" in n["name"].replace("أ", "ا") for n in cmp_["names"])


def test_copy_without_attribution_vs_attributed(admin, feed):
    t, x = GOLD["same"][0]
    body = x + " وأوضحت الوزارة أن القرار يراعي تغيرات الأسعار العالمية خلال الشهر الماضي ومتوسط سعر الصرف."
    first = feed("المصدر الأصلي", t, body, published=T0)
    feed("الناسخ", t, body, published=T0 + timedelta(hours=1))
    feed("الناقل", t, "نقلًا عن المصدر الأصلي: " + body, published=T0 + timedelta(hours=2))
    sid = admin.get(f"/api/items/{first}").json()["story_id"]
    rel = {r["outlet"]: r for r in admin.get(f"/api/stories/{sid}").json()["relations"]}
    assert rel["الناسخ"]["kind"] == "نسخ دون نسبة" and rel["الناسخ"]["from_outlet"] == "المصدر الأصلي"
    assert rel["الناقل"]["kind"] == "نقل مع نسبة"
    again = feed("المصدر الأصلي", t + " (محدّث)", body, published=T0 + timedelta(hours=3))
    rel2 = {r["item_id"]: r for r in admin.get(f"/api/stories/{sid}").json()["relations"]}
    assert rel2[again]["kind"] == "من الموقع نفسه"  # لا ينسخ موقع عن نفسه


def test_entities_statements_promises_and_contradiction(admin, feed):
    feed("أ", "وزير الطاقة: لا رفع للأسعار", "قال وزير الطاقة صالح الخرابشة إن الحكومة لن ترفع أسعار الكهرباء على الشرائح المنزلية خلال العام الحالي.", published=T0)
    feed("ب", "وزير الطاقة يتحدث عن الكهرباء", "أكد وزير الطاقة صالح الخرابشة أن الحكومة سترفع أسعار الكهرباء على الشرائح المنزلية مطلع العام المقبل.", published=T0 + timedelta(days=30))
    ents = admin.get("/api/entities", params={"q": "الخرابشه"}).json()
    assert ents and ents[0]["kind"] == "person" and ents[0]["mentions"] == 2
    e = admin.get(f"/api/entities/{ents[0]['id']}").json()
    assert len(e["statements"]) == 2 and e["promises"] >= 1
    assert e["contradictions"] and e["contradictions"][0]["reason"] == "نفي مقابل إثبات"
    assert {t["outlet"] for t in e["tone_by_outlet"]} == {"أ", "ب"}


def test_journalist_moves_item_and_merges(admin, feed):
    a = feed("أ", *GOLD["same"][0], published=T0)
    w = feed("ب", *GOLD["other"][0], published=T0)
    sa = admin.get(f"/api/items/{a}").json()["story_id"]
    sw = admin.get(f"/api/items/{w}").json()["story_id"]
    assert admin.put(f"/api/items/{w}/story", json={"story_id": sa}).status_code == 200
    assert admin.get(f"/api/stories/{sa}").json()["story"]["item_count"] == 2
    new = admin.put(f"/api/items/{w}/story", json={"story_id": None}).json()["story_id"]
    assert new not in (sa, sw)
    r = admin.post(f"/api/stories/{sa}/merge", json={"other_id": new})
    assert r.json()["story"]["item_count"] == 2 and r.json()["story"]["locked"]
    assert any(x["action"] == "story.merge" for x in admin.get("/api/admin/audit").json())


def test_entity_alias_merge(admin, feed):
    feed("أ", "وزارة الطاقة تعلن", "أعلنت وزارة الطاقة والثروة المعدنية عن خطة جديدة.", published=T0)
    feed("ب", "وزاره الطاقه", "قالت وزارة الطاقة إن الخطة جاهزة للتنفيذ في الربع الأول.", published=T0)
    ents = admin.get("/api/entities", params={"q": "وزاره الطاقه", "kind": "org"}).json()
    assert len(ents) >= 2
    keep, drop = ents[0], ents[1]
    admin.put(f"/api/entities/{drop['id']}", json={"merge_into": keep["id"]})
    merged = admin.get(f"/api/entities/{keep['id']}").json()
    assert drop["name"] in merged["aliases"] and merged["mentions"] >= 2
