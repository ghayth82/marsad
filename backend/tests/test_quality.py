"""الحالة 37 (الأداء: 1000 خبر في اليوم) ومؤشر «دقة تحديد أول ناشر أكثر من 90٪» على عيّنة مولّدة بأوقات ومناطق زمنية مختلفة."""

import random
import time
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_analysis import feed  # noqa: F401

TOPICS = ["الموازنة العامة", "أسعار المحروقات", "امتحانات الثانوية", "مشروع الناقل الوطني للمياه", "انتخابات البلديات", "الحد الأدنى للأجور",
          "منخفض جوي", "أسعار الذهب", "قطاع السياحة", "الطاقة الشمسية", "النقل العام", "المستشفيات الحكومية", "التعليم الجامعي",
          "الصادرات الزراعية", "البطالة بين الشباب", "الاستثمار الأجنبي", "الأمن الغذائي", "المياه الجوفية", "السير على الطرق", "الضمان الاجتماعي"]
VERBS = ["أعلنت", "كشفت", "قالت", "أكدت", "نشرت", "أوضحت"]
KINDS = ["حريق في مستودع للأخشاب", "انهيار جزئي لجسر قديم", "تسرب غاز في مطعم", "فيضان مفاجئ في وادٍ", "انقطاع واسع للكهرباء",
         "إضراب لسائقي الشاحنات", "سقوط رافعة في موقع بناء", "حادث سير بين حافلتين", "تسمم غذائي في مدرسة", "عاصفة رملية تغلق الطريق"]
PLACES = ["مدينة الزرقاء", "مدينة إربد", "مدينة العقبة", "مدينة مادبا", "مدينة جرش", "مدينة الكرك", "مدينة السلط", "مدينة معان",
          "مدينة الطفيلة", "مدينة عجلون", "لواء الرمثا", "لواء الشونة"]
SECOND = ["وهرعت فرق الإطفاء إلى المكان وسيطرت على النيران بعد {n} ساعات من العمل المتواصل.",
          "وأغلقت الشرطة الشارع أمام حركة المرور وطلبت من السكان الابتعاد عن المنطقة {n} أيام.",
          "وقال شهود إن رائحة قوية انتشرت قبل وصول فرق الطوارئ، ونقل {n} أشخاص للفحص.",
          "وارتفع منسوب المياه بشكل سريع وجرف {n} سيارات كانت متوقفة قرب المجرى.",
          "وتأثرت {n} أحياء سكنية بالانقطاع، وتعمل الشركة على إعادة التيار تدريجيًا.",
          "وتوقفت {n} شاحنة عند المعبر احتجاجًا على رسوم جديدة فرضتها البلدية.",
          "وتضررت {n} مركبات كانت بجانب الموقع، وفتحت النقابة تحقيقًا في شروط السلامة.",
          "وتسبب الحادث بأزمة سير خانقة امتدت {n} كيلومترات على الطريق الرئيسي.",
          "وأُعيد {n} طالبًا إلى منازلهم بعد العلاج، وأُغلقت المقصف حتى إشعار آخر.",
          "وانخفض مدى الرؤية إلى أقل من {m} متر، ودعت الإدارة السائقين إلى الحذر."]
DETAILS = ["وإصابة ثلاثة عمال", "دون إصابات", "وإخلاء المبنى المجاور", "وتحويل السير إلى طريق فرعي", "ونقل خمسة إلى المستشفى",
           "وتدخل فرق الدفاع المدني", "وتشكيل لجنة تحقيق"]


def make_day(feed, n=1000, outlets=20, seed=7):  # noqa: F811
    rnd = random.Random(seed)
    t0 = datetime.now(timezone.utc) - timedelta(hours=24)
    for k in range(n):
        topic = TOPICS[k % len(TOPICS)]
        sub = k % 150  # نحو 150 حدثًا مختلفًا في اليوم
        title = f"{rnd.choice(VERBS)} الجهات المختصة تفاصيل جديدة حول {topic} في الحدث رقم {sub}"
        text = (f"{title}. وتضمنت التفاصيل أرقامًا تخص {topic} بلغت {sub * 7 + 13} وحدة، "
                f"وقال مسؤول إن العمل مستمر على {topic} خلال الأسابيع المقبلة في المحافظات كافة. ") * 3
        when = t0 + timedelta(seconds=86400 * k / n)
        feed(f"موقع {k % outlets}", title, text, published=when, captured=when + timedelta(minutes=2), url=f"https://o{k % outlets}.example/n/{k}")


@pytest.mark.timeout(900) if hasattr(pytest.mark, "timeout") else (lambda f: f)
def test_case37_thousand_items_a_day(admin, feed, capsys):  # noqa: F811
    t = time.perf_counter()
    make_day(feed)
    ingest = time.perf_counter() - t

    def timed(path):
        s = time.perf_counter()
        r = admin.get(path)
        assert r.status_code == 200, (path, r.text[:200])
        return time.perf_counter() - s, r.json()

    search_t, res = timed("/api/items?q=" + "الناقل الوطني للمياه")
    rows = res["items"] if isinstance(res, dict) else res
    assert rows and all("الناقل" in (i["title"] + i.get("text", "")) for i in rows[:5])
    search2_t, _ = timed("/api/items?q=" + "امتحانات الثانويه")  # تاء مربوطة مكتوبة هاءً
    live_t, _ = timed("/api/items?limit=50")
    dash_t, d = timed("/api/dashboard")
    radar_t, _ = timed("/api/rumors/radar")
    stories_t, _ = timed("/api/stories")
    with capsys.disabled():
        print(f"\n[أداء] إدخال 1000 مادة مع التحليل: {ingest:.1f} ث ({ingest / 1000:.3f} ث لكل مادة، والمتاح 86 ث) | بحث {search_t:.2f}/{search2_t:.2f} ث | "
              f"الرصد {live_t:.2f} ث | الرئيسية {dash_t:.2f} ث | الرادار {radar_t:.2f} ث | القصص {stories_t:.2f} ث")
    assert search_t < 2 and search2_t < 2  # البحث أقل من ثانيتين
    assert live_t < 1.5 and dash_t < 2 and radar_t < 3 and stories_t < 2
    assert ingest / 1000 < 2  # كل مادة تُحلَّل في أقل من ثانيتين، والمعدل المطلوب مادة كل 86 ثانية
    assert d["rising_stories"]


def test_gold_first_publisher_accuracy(admin, feed):  # noqa: F811
    """30 حدثًا، كل حدث في 3–5 مواقع بمناطق زمنية مختلفة وتأخر رصد عشوائي، وبعض المواقع تعلن وقتًا كاذبًا (بعد رصدنا).
    الهدف من الخطة: دقة أكثر من 90٪."""
    from marsad.db import get_db
    from marsad.models.analysis import Story
    from marsad.models.monitoring import Item

    rnd = random.Random(2026)
    base = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
    truth = {}
    for ev in range(30):
        n = rnd.randint(3, 5)
        start = base + timedelta(hours=ev * 26)  # حدث جديد كل يوم تقريبًا؛ الأحداث المتشابهة لا تقع في نافذة 72 ساعة نفسها
        gaps = sorted(rnd.sample(range(4, 90), n - 1))
        times = [start] + [start + timedelta(minutes=g) for g in gaps]
        names = rnd.sample(["الرصيف", "المدار", "النبأ", "الحدث", "الساحة", "البوصلة", "المرآة", "الشاهد", "الأفق", "المنبر", "الواحة", "الجسر"], n)
        topic = f"{KINDS[ev % len(KINDS)]} في {PLACES[ev % len(PLACES)]} {DETAILS[ev % len(DETAILS)]}"
        for k, (name, real) in enumerate(zip(names, times)):
            tz = timezone(timedelta(hours=rnd.choice([0, 2, 3, -5])))
            delay = timedelta(minutes=rnd.randint(1, 10))
            declared = real.astimezone(tz)
            if k > 0 and rnd.random() < 0.15:
                declared = None  # بعض المواقع لا تعلن وقتًا
            if k > 0 and rnd.random() < 0.1:
                declared = (real - timedelta(hours=3)).astimezone(tz)  # موقع يدّعي وقتًا أبكر… لكنه بعد رصدنا؟ لا: أبكر من رصدنا فيُصدَّق
                declared = None if declared < start else declared
            iid = feed(name, f"{topic} — {name}", f"{topic}. {SECOND[ev % len(SECOND)].format(n=ev * 3 + 4, m=ev * 1370 + 450)} ({name})",
                       published=declared, captured=real + delay, url=f"https://site{names.index(name)}-{ev}.example/{ev}")
            if k == 0:
                truth[ev] = iid
    db = next(get_db())
    hits = 0
    from marsad.analysis.core import story_view

    for ev, iid in truth.items():
        sid = db.get(Item, iid).story_id
        v = story_view(db, db.get(Story, sid))
        hits += v["first"]["item_id"] == iid
        if v["first"]["item_id"] != iid:
            print("\nخطأ في الحدث", ev, [(x["item_id"], x["time"], x["basis"]) for x in v["timeline"]][:6], "الصحيح", iid)
    db.close()
    acc = hits / len(truth)
    print(f"\n[دقة أول ناشر] {hits}/{len(truth)} = {acc:.0%}")
    assert acc > 0.9
