"""وقت النشر: الساعة الحقيقية من صفحة الخبر، ولا ساعة مخترعة لتاريخ دون ساعة."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from marsad.monitor import readers
from marsad.monitor.service import page_published, published_date_only


def test_has_time():
    assert not readers.has_time("2026-11-24")
    assert readers.has_time("2026-11-24T09:15:00+03:00")
    assert readers.has_time("Tue, 24 Nov 2026 09:15:00 GMT")


def test_page_published_reads_meta_jsonld_time():
    assert page_published('<meta property="article:published_time" content="2026-11-24T21:10:00+03:00">') == \
        datetime(2026, 11, 24, 18, 10, tzinfo=timezone.utc)
    assert page_published('<script type="application/ld+json">{"datePublished": "2026-11-24T08:05:00Z"}</script>').hour == 8
    assert page_published('<time datetime="2026-11-24T10:00+03:00">اليوم</time>').hour == 7
    assert page_published('<meta property="article:published_time" content="2026-11-24">') is None


def _item(pub, kind="sitemap", meta=None):
    return SimpleNamespace(published_at=pub, meta=meta or {}, source=SimpleNamespace(kind=kind),
                           captured_at=datetime(2026, 11, 24, 18, 45, tzinfo=timezone.utc))


def test_date_only_detection_and_first_time():
    from marsad.analysis.core import first_time

    midnight = datetime(2026, 11, 24, tzinfo=timezone.utc)
    assert published_date_only(_item(midnight))  # مواد قديمة رُصدت قبل الإصلاح
    assert not published_date_only(_item(midnight, kind="rss"))
    assert published_date_only(_item(midnight + timedelta(hours=5), meta={"published_date_only": True}))
    t, basis = first_time(_item(midnight))
    assert basis == "وقت رصدنا لها"  # لا يصير الموقع «أول من نشر» بسبب منتصف ليل وهمي


# ---- الوقت من الصفحة لأي مصدر: البيانات المقروءة آليًا، ثم الظاهر تحت العنوان، ثم «منذ…» ----
import pytest

from marsad.monitor.pubtime import from_page

NOW = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)  # 23:00 بتوقيت عمّان


def page(head_meta="", under_title="", after=""):
    return f"""<html><head>{head_meta}</head><body><header>الثلاثاء: 24 نوفمبر 2026</header>
    <h1>وثيقة استخبارية عراقية تكشف استمرار تهريب النفط</h1><div class="meta">{under_title}</div>
    <p>نص الخبر هنا.</p><aside>أخبار ذات صلة 2026-11-20 08:00</aside>{after}</body></html>"""


@pytest.mark.parametrize("under,expected_local", [
    ("24 نوفمبر 2026 <span>21:45</span>", (21, 45)),            # خبرني: التاريخ ثم الساعة في عنصر منفصل
    ("21:45 | 24 نوفمبر 2026", (21, 45)),                         # الساعة قبل التاريخ
    ("نشر بتاريخ: 24 تشرين الثاني 2026 - 09:15 م", (21, 15)),     # الأشهر الشامية و«م»
    ("2026/11/24 09:15 ص", (9, 15)),
    ("24-11-2026 ١٠:٣٠", (10, 30)),                               # أرقام عربية مشرقية
    ("Nov 24, 2026 7:05 pm", (19, 5)),
])
def test_visible_time_under_title(under, expected_local):
    d, how = from_page(page(under_title=under), country="الأردن", now=NOW)
    assert how == "page_text"
    amman = d.astimezone(timezone(timedelta(hours=3)))
    assert (amman.year, amman.month, amman.day, amman.hour, amman.minute) == (2026, 11, 24, *expected_local)


def test_meta_beats_text_and_country_timezone():
    d, how = from_page(page('<meta property="article:published_time" content="2026-11-24T10:00:00+02:00">', "24 نوفمبر 2026 21:45"), now=NOW)
    assert how == "page_meta" and d.hour == 8
    # موقع مصري يكتب 21:45 بتوقيت القاهرة (UTC+2 شتاءً)
    d, _ = from_page(page(under_title="24 نوفمبر 2026 21:45"), country="مصر", now=NOW)
    assert (d.hour, d.minute) == (19, 45)


def test_header_date_without_time_and_related_news_are_ignored():
    d, how = from_page(page(), now=NOW)  # لا ساعة تحت العنوان: لا يُؤخذ تاريخ الترويسة ولا أوقات الأخبار الأخرى
    assert d is None and how == ""


def test_relative_and_future_rejected():
    d, how = from_page(page(under_title="منذ 3 ساعات"), now=NOW)
    assert how == "relative" and d == NOW - timedelta(hours=3)
    d, how = from_page(page(under_title="قبل ساعتين"), now=NOW)
    assert d == NOW - timedelta(hours=2)
    d, how = from_page(page(under_title="25 نوفمبر 2026 21:45"), country="الأردن", now=NOW)  # في المستقبل
    assert how != "page_text"


def test_refresh_from_archive_fixes_old_items(admin):
    from datetime import datetime as dt

    from marsad.db import get_db
    from marsad.models.monitoring import Item, ItemVersion, Outlet, Source
    from marsad.monitor.pubtime import refresh_from_archive
    from marsad.monitor.service import archive_html

    db = next(get_db())
    o = Outlet(name="خبرني", country="الأردن")
    db.add(o)
    db.flush()
    s = Source(outlet_id=o.id, url="https://kh.example/", kind="sitemap", read_url="https://kh.example/sm.xml")
    db.add(s)
    db.flush()
    cap = dt(2026, 11, 24, 18, 50, tzinfo=timezone.utc)
    raw = page(under_title="24 نوفمبر 2026 <span>21:45</span>").encode()
    rel, sha = archive_html(raw, cap)
    it = Item(source_id=s.id, outlet_id=o.id, url="https://kh.example/1", title="وثيقة استخبارية عراقية تكشف استمرار تهريب النفط",
              text="", captured_at=cap, published_at=dt(2026, 11, 24, tzinfo=timezone.utc), content_hash="x", version=1)
    it.versions.append(ItemVersion(version=1, change="new", title=it.title, text="", content_hash="x", captured_at=cap,
                                   archive_path=rel, archive_sha256=sha))
    db.add(it)
    db.commit()
    assert refresh_from_archive(db) == {"checked": 1, "fixed": 1}
    db.refresh(it)
    assert (it.published_at.hour, it.published_at.minute) == (18, 45)  # 21:45 بتوقيت عمّان
    r = admin.get(f"/api/items/{it.id}").json()
    assert r["published_date_only"] is False and r["published_source"] == "النص الظاهر في صفحة الخبر"
    db.close()


def test_tz_info_labels():
    from marsad.monitor.pubtime import tz_info

    assert tz_info("مصر") == {"tz": "Africa/Cairo", "tz_label": "مصر", "tz_assumed": False}
    assert tz_info("الأردن")["tz_label"] == "الأردن"
    assert tz_info("") == {"tz": "Asia/Amman", "tz_label": "الأردن", "tz_assumed": True}
    assert tz_info("دولي")["tz_assumed"] is True


def test_changing_outlet_country_recomputes_text_times(admin):
    from datetime import datetime as dt

    from marsad.db import get_db
    from marsad.models.monitoring import Item, ItemVersion, Outlet, Source
    from marsad.monitor.service import archive_html

    db = next(get_db())
    o = Outlet(name="موقع مصري", country="")
    db.add(o)
    db.flush()
    s = Source(outlet_id=o.id, url="https://eg.example/", kind="page", read_url="https://eg.example/")
    db.add(s)
    db.flush()
    cap = dt(2026, 11, 24, 19, 30, tzinfo=timezone.utc)
    rel, sha = archive_html(page(under_title="24 نوفمبر 2026 21:15").encode(), cap)
    it = Item(source_id=s.id, outlet_id=o.id, url="https://eg.example/1", title="وثيقة استخبارية عراقية تكشف استمرار تهريب النفط",
              text="", captured_at=cap, published_at=dt(2026, 11, 24, 18, 15, tzinfo=timezone.utc),  # 21:15 بتوقيت عمّان
              content_hash="x", version=1, meta={"published_source": "page_text"})
    it.versions.append(ItemVersion(version=1, change="new", title=it.title, text="", content_hash="x", captured_at=cap,
                                   archive_path=rel, archive_sha256=sha))
    db.add(it)
    db.commit()
    iid, oid = it.id, o.id
    db.close()
    assert admin.get(f"/api/items/{iid}").json()["published_tz_assumed"] is True
    r = admin.put(f"/api/outlets/{oid}", json={"name": "موقع مصري", "country": "مصر"})
    assert r.status_code == 200
    j = admin.get(f"/api/items/{iid}").json()
    assert j["published_tz_label"] == "مصر" and j["published_tz_assumed"] is False
    assert j["published_at"].startswith("2026-11-24T19:15")  # 21:15 بتوقيت القاهرة
