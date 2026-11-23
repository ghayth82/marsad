"""قرّاء المصادر: كل نوع يُرجع قائمة مداخل موحّدة.

المدخل: {"url", "title", "text", "summary", "published_at", "author", "media", "full": هل النص كامل}
"""

from __future__ import annotations

import gzip
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urljoin, urlparse

import os

import feedparser
from lxml import html as lxml_html

from marsad.monitor import fetch

# قابلان للتغيير في الاختبارات (خادم محلي بدل الإنترنت)
TELEGRAM_BASE = os.environ.get("MARSAD_TELEGRAM_BASE", "https://t.me")
YOUTUBE_BASE = os.environ.get("MARSAD_YOUTUBE_BASE", "https://www.youtube.com")

SOCIAL = {
    "facebook.com": "facebook", "fb.com": "facebook", "instagram.com": "instagram", "x.com": "x",
    "twitter.com": "x", "tiktok.com": "tiktok", "t.me": "telegram", "telegram.me": "telegram",
    "youtube.com": "youtube", "youtu.be": "youtube",
}


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def social_kind(url: str) -> str | None:
    h = _host(url)
    for dom, kind in SOCIAL.items():
        if h == dom or h.endswith("." + dom):
            return kind
    return None


def _dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    for parse in (lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")), parsedate_to_datetime,
                  lambda x: datetime.strptime(x, "%Y%m%dT%H%M%SZ")):
        try:
            d = parse(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", lxml_html.fromstring(f"<div>{text}</div>").text_content()).strip() if text else ""


# ---------- RSS / Atom ----------

def read_feed(url: str, meta: dict) -> tuple[list[dict], dict]:
    r = fetch.get(url, etag=meta.get("etag", ""), last_modified=meta.get("last_modified", ""), check_robots=False)
    new_meta = {"etag": r.headers.get("etag", ""), "last_modified": r.headers.get("last-modified", "")}
    if r.status_code == 304:
        return [], new_meta
    f = feedparser.parse(r.content)
    if f.bozo and not f.entries:
        raise fetch.FetchError("الخلاصة غير صالحة")
    out = []
    for e in f.entries:
        link = e.get("link") or ""
        if not link:
            continue
        content = ""
        if e.get("content"):
            content = _clean(e.content[0].get("value", ""))
        summary = _clean(e.get("summary", ""))
        media = [{"type": "image", "url": m["url"]} for m in e.get("media_content", []) + e.get("media_thumbnail", [])
                 if m.get("url")]
        published = e.get("published") or e.get("updated")
        out.append({"url": link, "title": _clean(e.get("title", "")), "text": content, "summary": summary,
                    "published_at": _dt(published), "author": e.get("author", ""), "media": media,
                    "full": len(content) > 400})
    return out, new_meta


# ---------- خريطة الموقع ----------

def read_sitemap(url: str, meta: dict, limit: int = 60) -> tuple[list[dict], dict]:
    r = fetch.get(url, check_robots=False)
    body = r.content
    if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    doc = lxml_html.fromstring(body)  # متسامح مع المساحات الاسمية
    children = [x.text_content().strip() for x in doc.xpath("//sitemap/loc")]
    if children:  # فهرس خرائط: نأخذ أحدثها
        entries: list[dict] = []
        for child in children[:3]:
            entries += read_sitemap(child, meta, limit)[0]
        return entries[:limit], {}
    out = []
    for u in doc.xpath("//url"):
        loc = u.xpath("./loc")
        if not loc:
            continue
        title = u.xpath(".//*[local-name()='title']")
        date = u.xpath(".//*[local-name()='publication_date']") or u.xpath("./lastmod")
        out.append({"url": loc[0].text_content().strip(), "title": title[0].text_content().strip() if title else "",
                    "text": "", "summary": "", "published_at": _dt(date[0].text_content()) if date else None,
                    "author": "", "media": [], "full": False})
    out.sort(key=lambda x: x["published_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out[:limit], {}


# ---------- صفحة عامة (دون خلاصة) ----------

_ARTICLE_HINT = re.compile(r"/(\d{4}/|\d{5,}|news|article|story|ar/|en/)|[-_][a-z0-9]+-[a-z0-9]+|\d{6,}", re.I)


def read_page(url: str, meta: dict, limit: int = 40) -> tuple[list[dict], dict]:
    r = fetch.get(url)
    doc = fetch.parse_html(r)
    doc.make_links_absolute(str(r.url))
    host = _host(str(r.url))
    seen, out = set(), []
    for a in doc.xpath("//a[@href]"):
        href = a.get("href").split("#")[0]
        if _host(href) != host or href in seen or href.rstrip("/") == str(r.url).rstrip("/"):
            continue
        path = urlparse(href).path
        text = re.sub(r"\s+", " ", a.text_content()).strip()
        if path.count("/") < 2 or len(text) < 15 or not _ARTICLE_HINT.search(path):
            continue
        seen.add(href)
        out.append({"url": href, "title": text, "text": "", "summary": "", "published_at": None, "author": "",
                    "media": [], "full": False})
        if len(out) >= limit:
            break
    return out, {}


# ---------- تيليغرام (المعاينة العامة للقناة) ----------

def telegram_channel(url: str) -> str | None:
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    if not parts:
        return None
    name = parts[1] if parts[0] == "s" and len(parts) > 1 else parts[0]
    return name if re.fullmatch(r"[A-Za-z0-9_]{4,64}", name) else None


def read_telegram(url: str, meta: dict) -> tuple[list[dict], dict]:
    ch = meta.get("channel") or telegram_channel(url)
    r = fetch.get(f"{TELEGRAM_BASE}/s/{ch}", check_robots=False)
    doc = fetch.parse_html(r)
    out = []
    for m in doc.xpath("//div[contains(@class,'tgme_widget_message ') and @data-post]"):
        post = m.get("data-post")
        body = m.xpath(".//div[contains(@class,'tgme_widget_message_text')]")
        text = re.sub(r"\s+", " ", body[0].text_content()).strip() if body else ""
        t = m.xpath(".//time[@datetime]")
        imgs = [re.search(r"url\('([^']+)'\)", s).group(1) for s in
                m.xpath(".//a[contains(@class,'tgme_widget_message_photo_wrap')]/@style") if "url('" in s]
        if not text and not imgs:
            continue
        out.append({"url": f"https://t.me/{post}", "title": text[:140], "text": text, "summary": "",
                    "published_at": _dt(t[0].get("datetime")) if t else None, "author": ch,
                    "media": [{"type": "image", "url": i} for i in imgs] +
                             ([{"type": "video", "url": f"https://t.me/{post}"}] if m.xpath(".//video") else []),
                    "full": True})
    return out, {"channel": ch}


# ---------- يوتيوب (خلاصة القناة العامة، دون مفتاح) ----------

def youtube_channel_id(url: str) -> str | None:
    m = re.search(r"/channel/(UC[\w-]{20,})", url)
    if m:
        return m.group(1)
    r = fetch.get(url, check_robots=False)
    for pat in (r'"channelId":"(UC[\w-]{20,})"', r'<meta itemprop="identifier" content="(UC[\w-]{20,})"',
                r'channel/(UC[\w-]{20,})'):
        m = re.search(pat, r.text)
        if m:
            return m.group(1)
    return None


def read_youtube(url: str, meta: dict) -> tuple[list[dict], dict]:
    cid = meta.get("channel_id") or youtube_channel_id(url)
    if not cid:
        raise fetch.FetchError("تعذّر تحديد معرّف القناة")
    entries, _ = read_feed(f"{YOUTUBE_BASE}/feeds/videos.xml?channel_id={cid}", {})
    for e in entries:
        e["media"] = [{"type": "video", "url": e["url"]}]
        e["full"] = True  # الوصف هو النص، والتفريغ يأتي من محرك «صوتي»
        e["text"] = e["text"] or e["summary"]
    return entries, {"channel_id": cid}


# ---------- GDELT ----------

def gdelt_url(query: str) -> str:
    return ("https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&maxrecords=75&sort=datedesc&query="
            + quote(query))


def read_gdelt(url: str, meta: dict) -> tuple[list[dict], dict]:
    r = fetch.get(meta.get("api_url") or gdelt_url(meta["query"]), check_robots=False)
    try:
        arts = r.json().get("articles", [])
    except ValueError:
        arts = []
    return [{"url": a["url"], "title": a.get("title", ""), "text": "", "summary": "",
             "published_at": _dt(a.get("seendate")), "author": a.get("domain", ""), "media":
             [{"type": "image", "url": a["socialimage"]}] if a.get("socialimage") else [], "full": False,
             "meta": {"domain": a.get("domain"), "language": a.get("language"), "country": a.get("sourcecountry")}}
            for a in arts if a.get("url")], {}


READERS = {"rss": read_feed, "sitemap": read_sitemap, "page": read_page, "telegram": read_telegram,
           "youtube": read_youtube, "gdelt": read_gdelt}
