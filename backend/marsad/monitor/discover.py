"""لصق رابط ← معرفة نوعه وطريقة قراءته واسم الجهة وشعارها وصفحاتها على المنصات."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from lxml import html as lxml_html

from marsad.monitor import fetch, readers


def normalize_url(url: str) -> str:
    url = url.strip()
    if url.startswith("gdelt:"):
        return url
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    if not p.netloc or "." not in p.netloc:
        raise ValueError("الرابط غير صحيح")
    return url


# روابط ليست صفحة جهة: فيديو منفرد، مشاركة، تضمين، منشور واحد
_NOT_PROFILE = {
    "youtube": re.compile(r"^/(watch|embed|shorts|live|playlist|results|redirect|share|v/)", re.I),
    "x": re.compile(r"^/(intent|share|home|hashtag|search|i/)|/status/", re.I),
    "facebook": re.compile(r"^/(sharer|share|dialog|plugins|tr|photo|watch|groups/[^/]+/posts)|/posts/|/videos/", re.I),
    "instagram": re.compile(r"^/(p|reel|reels|stories|explore)/", re.I),
    "tiktok": re.compile(r"/video/|^/(share|embed)", re.I),
    "telegram": re.compile(r"^/(share|joinchat|addstickers|\+)", re.I),
}


def profile_url(href: str) -> tuple[str, str] | None:
    """يُرجع (المنصة، رابط الصفحة الموحّد) إن كان الرابط صفحة جهة على منصة، وإلا None."""
    k = readers.social_kind(href)
    if not k:
        return None
    p = urlparse(href if "://" in href else "https://" + href.lstrip("/"))
    path = re.sub(r"/+$", "", p.path)
    if not path or (k == "youtube" and p.netloc.lower().endswith("youtu.be")):
        return None
    if _NOT_PROFILE.get(k) and _NOT_PROFILE[k].search(path):
        return None
    if k == "youtube":  # الصفحة نفسها: /@اسم أو /channel/… أو /c/… أو /user/…
        m = re.match(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)", path)
        if not m:
            return None
        path = m.group(1) if m.group(1).startswith("@") else m.group(0)
        path = path if path.startswith("/") else "/" + path
    else:
        parts = path.strip("/").split("/")
        if k == "telegram" and parts[0] == "s" and len(parts) > 1:
            parts = parts[1:]
        path = "/" + parts[0]
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    return k, f"https://{host}{path}"


def discover(url: str) -> dict:
    """يُرجع: kind، read_url، title، outlet_name، logo_url، feeds، social (روابط المنصات المكتشفة)، meta."""
    url = normalize_url(url)
    if url.startswith("gdelt:"):
        q = url[6:].strip()
        if not q:
            raise ValueError("اكتب استعلام GDELT بعد gdelt:")
        return {"url": url, "kind": "gdelt", "read_url": readers.gdelt_url(q), "title": f"GDELT: {q}",
                "outlet_name": f"GDELT: {q}", "logo_url": "", "feeds": [], "social": [], "meta": {"query": q}}

    sk = readers.social_kind(url)
    if sk == "telegram":
        ch = readers.telegram_channel(url)
        if not ch:
            raise ValueError("لم أتعرف على اسم قناة تيليغرام في الرابط")
        title, logo = ch, ""
        try:
            doc = fetch.parse_html(fetch.get(f"{readers.TELEGRAM_BASE}/s/{ch}", check_robots=False))
            t = doc.xpath("//meta[@property='og:title']/@content")
            i = doc.xpath("//meta[@property='og:image']/@content")
            title, logo = (t[0] if t else ch), (i[0] if i else "")
        except fetch.FetchError:
            pass
        return {"url": f"https://t.me/{ch}", "kind": "telegram", "read_url": f"{readers.TELEGRAM_BASE}/s/{ch}", "title": title,
                "outlet_name": title, "logo_url": logo, "feeds": [], "social": [], "meta": {"channel": ch}}
    if sk == "youtube":
        cid = readers.youtube_channel_id(url)
        if not cid:
            raise ValueError("تعذّر تحديد قناة يوتيوب من الرابط")
        feed = f"{readers.YOUTUBE_BASE}/feeds/videos.xml?channel_id={cid}"
        title = cid
        try:
            import feedparser

            f = feedparser.parse(fetch.get(feed, check_robots=False).content)
            title = f.feed.get("title") or cid
        except fetch.FetchError:
            pass
        return {"url": f"https://www.youtube.com/channel/{cid}", "kind": "youtube", "read_url": feed, "title": title,
                "outlet_name": title, "logo_url": "", "feeds": [feed], "social": [], "meta": {"channel_id": cid}}
    if sk in ("facebook", "instagram", "x", "tiktok"):
        name = urlparse(url).path.strip("/").split("/")[0] or url
        return {"url": url, "kind": "social", "read_url": "", "title": name, "outlet_name": name, "logo_url": "",
                "feeds": [], "social": [], "meta": {"platform": sk, "handle": name},
                "note": "تُرصد عبر موصل المنصة حين يُضاف مزوّد البيانات أو الوصول البحثي (البند 9)."}

    r = fetch.get(url)
    ctype = r.headers.get("content-type", "")
    body = r.content
    if "xml" in ctype or body.lstrip()[:5] in (b"<?xml", b"<rss ", b"<feed"):
        import feedparser

        f = feedparser.parse(body)
        if f.entries or f.feed.get("title"):
            return {"url": url, "kind": "rss", "read_url": str(r.url), "title": f.feed.get("title", url),
                    "outlet_name": f.feed.get("title", urlparse(url).netloc), "logo_url": (f.feed.get("image") or {}).get("href", ""),
                    "feeds": [str(r.url)], "social": [], "meta": {}}
        return {"url": url, "kind": "sitemap", "read_url": str(r.url), "title": urlparse(url).netloc,
                "outlet_name": urlparse(url).netloc, "logo_url": "", "feeds": [], "social": [], "meta": {}}

    doc = fetch.parse_html(r)
    base = str(r.url)
    feeds = [urljoin(base, h) for h in doc.xpath(
        "//link[@rel='alternate' and (contains(@type,'rss') or contains(@type,'atom'))]/@href")]
    name = (doc.xpath("//meta[@property='og:site_name']/@content") or doc.xpath("//title/text()") or [urlparse(base).netloc])[0]
    name = re.split(r"\s[|\-–—]\s", name.strip())[0][:200]
    icons = doc.xpath("//meta[@property='og:image']/@content") or doc.xpath(
        "//link[contains(@rel,'apple-touch-icon')]/@href") or doc.xpath("//link[contains(@rel,'icon')]/@href")
    logo = urljoin(base, icons[0]) if icons else ""
    social, seen = [], set()
    for h in doc.xpath("//a[@href]/@href"):
        pr = profile_url(h.strip())
        if pr and pr[1].lower() not in seen:
            seen.add(pr[1].lower())
            social.append({"platform": pr[0], "url": pr[1]})
    sitemap = ""
    if not feeds:
        try:
            robots = fetch.get(f"{urlparse(base).scheme}://{urlparse(base).netloc}/robots.txt", check_robots=False).text
            sm = re.findall(r"(?im)^sitemap:\s*(\S+)", robots)
            news = [s for s in sm if "news" in s.lower()]
            sitemap = (news or sm or [""])[0]
        except fetch.FetchError:
            pass
    if feeds:
        kind, read = "rss", feeds[0]
    elif sitemap:
        kind, read = "sitemap", sitemap
    else:
        kind, read = "page", base
    return {"url": base, "kind": kind, "read_url": read, "title": name, "outlet_name": name, "logo_url": logo,
            "feeds": feeds, "sitemap": sitemap, "social": social[:12], "meta": {}}
