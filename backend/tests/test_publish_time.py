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
