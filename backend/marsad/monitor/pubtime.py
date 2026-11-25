"""وقت نشر الخبر من الموقع أو المنصة نفسها، لأي مصدر.

يُبحث بالترتيب من الأدق إلى الأضعف، ويُحفظ مع الوقت من أين جاء:
1. بيانات الصفحة المقروءة آليًا: وسوم meta وJSON-LD و<time datetime>  ← «بيانات صفحة الخبر»
2. الوقت الظاهر تحت العنوان: «24 نوفمبر 2026 · 21:45»، «2026/11/24 09:15 م»  ← «النص الظاهر في صفحة الخبر»
3. الصيغة النسبية: «منذ 3 ساعات»، «قبل ساعتين»، «منذ 5 دقائق»  ← «تقدير من «منذ…» في الصفحة»
الوقت الظاهر بتوقيت بلد الموقع (من بلد الجهة)، ويُحوَّل إلى UTC للمقارنة.
(منصات تيليغرام ويوتيوب وخلاصات RSS تعطي الوقت بالدقيقة من قارئها مباشرة: «بيانات المنصة».)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from lxml import html as lxml_html

from marsad.monitor import readers

SOURCE_AR = {
    "platform": "بيانات المنصة أو الخلاصة",
    "page_meta": "بيانات صفحة الخبر",
    "page_text": "النص الظاهر في صفحة الخبر",
    "relative": "تقدير من «منذ…» في صفحة الخبر",
    "sitemap_date": "تاريخ خريطة الموقع (دون ساعة)",
    "captured": "وقت رصدنا",
}

# بلد الجهة ← منطقتها الزمنية (يراعي التوقيت الصيفي حيث يُعمل به)
COUNTRY_TZ = {
    "الأردن": "Asia/Amman", "jo": "Asia/Amman", "jordan": "Asia/Amman",
    "السعودية": "Asia/Riyadh", "sa": "Asia/Riyadh", "قطر": "Asia/Qatar", "qa": "Asia/Qatar",
    "الكويت": "Asia/Kuwait", "البحرين": "Asia/Bahrain", "العراق": "Asia/Baghdad", "اليمن": "Asia/Aden",
    "الإمارات": "Asia/Dubai", "ae": "Asia/Dubai", "عمان": "Asia/Muscat", "سلطنة عمان": "Asia/Muscat",
    "مصر": "Africa/Cairo", "eg": "Africa/Cairo", "لبنان": "Asia/Beirut", "lb": "Asia/Beirut",
    "سوريا": "Asia/Damascus", "فلسطين": "Asia/Hebron", "تركيا": "Europe/Istanbul",
    "المغرب": "Africa/Casablanca", "الجزائر": "Africa/Algiers", "تونس": "Africa/Tunis", "ليبيا": "Africa/Tripoli",
    "السودان": "Africa/Khartoum", "بريطانيا": "Europe/London", "uk": "Europe/London", "فرنسا": "Europe/Paris",
    "ألمانيا": "Europe/Berlin", "روسيا": "Europe/Moscow", "الولايات المتحدة": "America/New_York", "us": "America/New_York",
}
DEFAULT_TZ = "Asia/Amman"

MONTHS = {
    # الميلادية بأسمائها المصرية والشامية والإنجليزية
    "يناير": 1, "فبراير": 2, "مارس": 3, "ابريل": 4, "أبريل": 4, "إبريل": 4, "مايو": 5, "ماي": 5, "يونيو": 6,
    "يونيه": 6, "يوليو": 7, "يوليه": 7, "اغسطس": 8, "أغسطس": 8, "سبتمبر": 9, "اكتوبر": 10, "أكتوبر": 10,
    "نوفمبر": 11, "ديسمبر": 12, "كانون الثاني": 1, "شباط": 2, "آذار": 3, "اذار": 3, "نيسان": 4, "أيار": 5,
    "ايار": 5, "حزيران": 6, "تموز": 7, "آب": 8, "اب": 8, "أيلول": 9, "ايلول": 9, "تشرين الأول": 10,
    "تشرين الاول": 10, "تشرين الثاني": 11, "كانون الأول": 12, "كانون الاول": 12, "جانفي": 1, "فيفري": 2,
    "أفريل": 4, "افريل": 4, "جوان": 6, "جويلية": 7, "أوت": 8, "اوت": 8,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12,
}
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MONTH_RE = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
_TIME = r"(?P<h>\d{1,2})[:٫.](?P<mi>\d{2})(?::\d{2})?\s*(?P<ap>ص|م|صباحًا|صباحا|مساءً|مساء|am|pm|a\.m\.|p\.m\.)?"
_DATE_PATTERNS = [
    re.compile(rf"(?P<d>\d{{1,2}})\s*(?:/|-|\s)?\s*(?P<mon>{_MONTH_RE})\s*(?:/|-|,|،|\s)?\s*(?P<y>20\d\d)", re.I),
    re.compile(rf"(?P<mon>{_MONTH_RE})\s+(?P<d>\d{{1,2}}),?\s+(?P<y>20\d\d)", re.I),
    re.compile(r"(?P<y>20\d\d)[/\-.](?P<m>\d{1,2})[/\-.](?P<d>\d{1,2})"),
    re.compile(r"(?P<d>\d{1,2})[/\-.](?P<m>\d{1,2})[/\-.](?P<y>20\d\d)"),
]
_TIME_RE = re.compile(_TIME, re.I)
_REL = re.compile(r"(?:منذ|قبل)\s+(?:(?P<n>\d+)\s*)?(?P<u>دقيقتين|دقيقتان|دقائق|دقيقة|ساعتين|ساعتان|ساعات|ساعة|يومين|يومان|أيام|ايام|يوم)")

_META_KEYS = ("article:published_time", "og:published_time", "datepublished", "pubdate", "publishdate",
              "publish-date", "dc.date", "dc.date.issued", "sailthru.date", "parsely-pub-date", "date", "article.published")


TZ_LABEL = {  # اسم المنطقة كما يُقرأ: «21:45 بتوقيت مصر»
    "Asia/Amman": "الأردن", "Asia/Riyadh": "السعودية", "Asia/Qatar": "قطر", "Asia/Kuwait": "الكويت",
    "Asia/Bahrain": "البحرين", "Asia/Baghdad": "العراق", "Asia/Aden": "اليمن", "Asia/Dubai": "الإمارات",
    "Asia/Muscat": "عُمان", "Africa/Cairo": "مصر", "Asia/Beirut": "لبنان", "Asia/Damascus": "سوريا",
    "Asia/Hebron": "فلسطين", "Europe/Istanbul": "تركيا", "Africa/Casablanca": "المغرب", "Africa/Algiers": "الجزائر",
    "Africa/Tunis": "تونس", "Africa/Tripoli": "ليبيا", "Africa/Khartoum": "السودان", "Europe/London": "لندن",
    "Europe/Paris": "باريس", "Europe/Berlin": "برلين", "Europe/Moscow": "موسكو", "America/New_York": "نيويورك",
}


def tz_info(country: str) -> dict:
    """منطقة الجهة الزمنية للعرض: الاسم المعياري، واسمها بالعربية، وهل هي مفترضة لأن البلد غير مسجّل."""
    c = (country or "").strip()
    name = COUNTRY_TZ.get(c.lower()) or COUNTRY_TZ.get(c)
    return {"tz": name or DEFAULT_TZ, "tz_label": TZ_LABEL.get(name or DEFAULT_TZ, c or "الأردن"), "tz_assumed": not name}


def tz_for(country: str):
    from zoneinfo import ZoneInfo

    return ZoneInfo(COUNTRY_TZ.get((country or "").strip().lower(), COUNTRY_TZ.get((country or "").strip(), DEFAULT_TZ)))


def _from_meta(doc) -> datetime | None:
    vals: list[str] = []
    for m in doc.xpath("//meta[@content]"):
        k = (m.get("property") or m.get("name") or m.get("itemprop") or "").strip().lower()
        if k in _META_KEYS:
            vals.append(m.get("content"))
    for s in doc.xpath("//script[@type='application/ld+json']/text()"):
        vals += re.findall(r'"datePublished"\s*:\s*"([^"]+)"', s)
    vals += doc.xpath("//*[@itemprop='datePublished']/@datetime") + doc.xpath("//time[@datetime]/@datetime")
    for v in vals:
        if readers.has_time(v):
            d = readers._dt(v)
            if d:
                return d.astimezone(timezone.utc)
    return None


def _article_text(doc, title: str) -> str:
    """النص قرب العنوان: من بداية <h1> (أو العنوان المطابق) إلى نحو 1500 حرف بعده، فلا تختلط أوقات أخبار أخرى."""
    skip = ("ancestor::script or ancestor::style or ancestor::aside or ancestor::nav or ancestor::footer or "
            "ancestor::*[contains(@class,'related') or contains(@class,'sidebar') or contains(@class,'widget') "
            "or contains(@class,'more-news') or contains(@id,'related') or contains(@id,'sidebar')]")
    body = " ".join(doc.xpath(f"//body//text()[not({skip})]"))
    body = re.sub(r"\s+", " ", body)
    anchors = [t.text_content().strip() for t in doc.xpath("//h1")] + ([title.strip()] if title else [])
    for a in anchors:
        if a and len(a) > 8:
            i = body.find(a[:60])
            if i >= 0:
                # سطر الكاتب والوقت يكون عادة فوق العنوان أو تحته مباشرة، لا بعد فقرات الخبر
                return body[max(0, i - 200):i + len(a) + 400]
    return body[:1500]


def _year_month_day(m) -> tuple[int, int, int] | None:
    g = m.groupdict()
    mon = MONTHS.get((g.get("mon") or "").lower()) if g.get("mon") else int(g["m"])
    try:
        y, d = int(g["y"]), int(g["d"])
        datetime(y, mon, d)
        return y, mon, d
    except (TypeError, ValueError):
        return None


def _from_text(text: str, tz, now: datetime, title: str = "") -> datetime | None:
    text = text.translate(_DIGITS)
    t0 = text.find(title[:60]) if title else -1
    anchor = t0 + len(title) if t0 >= 0 else 0
    found = [m for pat in _DATE_PATTERNS for m in pat.finditer(text)]
    # الأقرب إلى العنوان أولًا (لا تاريخ الترويسة ولا أوقات أخبار أخرى)
    found.sort(key=lambda m: abs(m.start() - anchor))
    for m in found:
        if True:
            ymd = _year_month_day(m)
            if not ymd:
                continue
            # الساعة قريبة من التاريخ: بعده بأربعين حرفًا أو قبله بثلاثين («21:45 | 24 نوفمبر 2026»)
            near = [(text[m.end():m.end() + 40], True), (text[max(0, m.start() - 30):m.start()], False)]
            for chunk, after in near:
                tms = list(_TIME_RE.finditer(chunk))
                if not tms:
                    continue
                t = tms[0] if after else tms[-1]
                h, mi, ap = int(t["h"]), int(t["mi"]), (t["ap"] or "").lower()
                if ap.startswith(("م", "pm", "p.")) and h < 12:
                    h += 12
                if ap.startswith(("ص", "am", "a.")) and h == 12:
                    h = 0
                if h > 23 or mi > 59:
                    continue
                local = datetime(*ymd, h, mi, tzinfo=tz)
                if local.astimezone(timezone.utc) <= now + timedelta(minutes=10):  # لا وقت في المستقبل
                    return local.astimezone(timezone.utc)
    return None


def _relative(text: str, now: datetime) -> datetime | None:
    m = _REL.search(text.translate(_DIGITS))
    if not m:
        return None
    u, n = m["u"], m["n"]
    k = 2 if u in ("دقيقتين", "دقيقتان", "ساعتين", "ساعتان", "يومين", "يومان") else int(n or 1)
    unit = timedelta(minutes=1) if u.startswith("دقي") else timedelta(hours=1) if u.startswith("ساع") else timedelta(days=1)
    return now - k * unit


def from_page(raw: bytes | str, title: str = "", country: str = "", now: datetime | None = None) -> tuple[datetime | None, str]:
    """وقت النشر بالساعة من صفحة الخبر ومن أين جاء، أو (None، "") إن لم تذكر الصفحة الساعة."""
    html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    now = now or datetime.now(timezone.utc)
    try:
        doc = lxml_html.fromstring(html)
    except (ValueError, lxml_html.etree.ParserError):
        return None, ""
    d = _from_meta(doc)
    if d:
        return d, "page_meta"
    near = _article_text(doc, title)
    h1 = next((t.text_content().strip() for t in doc.xpath("//h1") if len(t.text_content().strip()) > 8), title)
    d = _from_text(near, tz_for(country), now, re.sub(r"\s+", " ", h1 or ""))
    if d:
        return d, "page_text"
    d = _relative(near, now)
    if d:
        return d, "relative"
    return None, ""



PUBTIME_REV = 2  # يرتفع كلما تحسّن استخراج وقت النشر، فيُعاد استخراجه من الصفحات المؤرشفة مرة واحدة


def refresh_from_archive(db, outlet_id: int | None = None, recheck_text: bool = False) -> dict:
    """للمواد المحفوظة دون ساعة نشر: يُقرأ الوقت من نسختها المؤرشفة على الجهاز، دون طلب الموقع من جديد.
    recheck_text: يُعاد حساب الأوقات المقروءة من النص الظاهر (بعد تغيير بلد الجهة وتوقيتها)."""
    import gzip

    from sqlalchemy import select

    from marsad.core.paths import ensure_storage
    from marsad.models.monitoring import Item
    from marsad.monitor.service import published_date_only

    from marsad.models.monitoring import Outlet

    countries = {o.id: o.country for o in db.scalars(select(Outlet))}
    root, fixed, seen = ensure_storage().archive, 0, 0
    q = select(Item).where(Item.source_id.is_not(None))
    if outlet_id:
        q = q.where(Item.outlet_id == outlet_id)
    for it in db.scalars(q):
        from_text = (it.meta or {}).get("published_source") == "page_text"
        if it.published_at and not published_date_only(it) and not (recheck_text and from_text):
            continue
        v = next((x for x in it.versions if x.archive_path), None)
        if not v or not (root / v.archive_path).exists():
            continue
        seen += 1
        try:
            raw = gzip.decompress((root / v.archive_path).read_bytes())
        except OSError:
            continue
        d, how = from_page(raw, it.title, countries.get(it.outlet_id, ""), now=it.captured_at)
        if d and d <= it.captured_at + timedelta(minutes=10):
            it.published_at = d
            it.meta = {k: val for k, val in {**(it.meta or {}), "published_source": how}.items() if k != "published_date_only"}
            fixed += 1
    db.commit()
    return {"checked": seen, "fixed": fixed}
