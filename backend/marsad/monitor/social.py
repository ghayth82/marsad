"""موصلات فيسبوك وإنستغرام وX وتيك توك.

مبنية كاملة ولا تعمل إلا بمزوّد: واجهة رسمية للمنصة (وصول بحثي أو مفتاح مطوّر) أو مزوّد بيانات تجاري (Apify).
لا اشتراك ولا إنفاق تلقائي: المفاتيح يضيفها غيث من الإدارة، وتُحفظ مشفّرة.

كل موصل يعيد مواد بالصيغة نفسها التي يعيدها قارئ الخلاصات: url، title، text، published_at، author، media، meta.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.monitor.fetch import USER_AGENT, FetchError
from marsad.monitor.readers import _dt

PLATFORMS = {"facebook": "فيسبوك", "instagram": "إنستغرام", "x": "X (تويتر)", "tiktok": "تيك توك"}
PROVIDERS = {
    "official": {"ar": "الواجهة الرسمية للمنصة (وصول بحثي أو مفتاح مطوّر)",
                 "fields": {"facebook": ["access_token"], "instagram": ["access_token", "ig_user_id"], "x": ["bearer_token"],
                            "tiktok": ["client_key", "client_secret"]}},
    "apify": {"ar": "مزوّد بيانات تجاري (Apify)", "fields": {p: ["api_token"] for p in PLATFORMS}},
}
BASES = {"meta": "https://graph.facebook.com", "x": "https://api.x.com", "tiktok": "https://open.tiktokapis.com", "apify": "https://api.apify.com"}
APIFY_ACTORS = {"facebook": "apify~facebook-posts-scraper", "instagram": "apify~instagram-scraper",
                "tiktok": "clockworks~tiktok-scraper", "x": "apidojo~tweet-scraper"}
SETTING = "social.providers"


def base(name: str) -> str:
    return os.environ.get(f"MARSAD_SOCIAL_BASE_{name.upper()}", BASES[name]).rstrip("/")


class SocialError(FetchError):
    pass


# ---------- الإعداد ----------

def load_config(db: Session) -> dict:
    from marsad.rbac.service import get_setting

    return get_setting(db, SETTING, {}) or {}


def credentials(db: Session, platform: str) -> tuple[str | None, dict]:
    cfg = load_config(db).get(platform) or {}
    if not cfg.get("provider") or not cfg.get("secret"):
        return None, {}
    try:
        return cfg["provider"], json.loads(crypto.decrypt(cfg["secret"]))
    except ValueError:
        return None, {}


def save_config(db: Session, platform: str, provider: str | None, creds: dict, actor=None, extra: dict | None = None) -> dict:
    from marsad.rbac.service import set_setting

    if platform not in PLATFORMS:
        raise ValueError("منصة غير معروفة")
    cfg = load_config(db)
    if not provider:
        cfg.pop(platform, None)
    else:
        if provider not in PROVIDERS:
            raise ValueError("مزوّد غير معروف")
        need = PROVIDERS[provider]["fields"][platform]
        old = {}
        if (cfg.get(platform) or {}).get("provider") == provider:
            _, old = credentials(db, platform)
        merged = {k: (creds.get(k) or old.get(k) or "").strip() for k in need}  # الحقل الفارغ يُبقي القيمة المحفوظة
        missing = [k for k in need if not merged[k]]
        if missing:
            raise ValueError("حقول ناقصة: " + "، ".join(missing))
        cfg[platform] = {"provider": provider, "secret": crypto.encrypt(json.dumps(merged)), "extra": extra or {},
                         "masked": {k: crypto.mask(v) for k, v in merged.items()}}
    set_setting(db, SETTING, cfg, actor)
    return status(db)


def status(db: Session) -> list[dict]:
    cfg = load_config(db)
    return [{"platform": p, "ar": ar, "provider": (cfg.get(p) or {}).get("provider"), "masked": (cfg.get(p) or {}).get("masked", {}),
             "fields": {k: v["fields"][p] for k, v in PROVIDERS.items()}} for p, ar in PLATFORMS.items()]


def configured(db: Session, platform: str) -> bool:
    return bool((load_config(db).get(platform) or {}).get("provider"))


# ---------- HTTP ----------

def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=True)


def _json(r: httpx.Response, who: str):
    if r.status_code in (401, 403):
        raise SocialError(f"{who}: المفتاح مرفوض أو لا يملك الصلاحية ({r.status_code})", r.status_code)
    if r.status_code == 429:
        raise SocialError(f"{who}: تجاوز حد الطلبات؛ يُعاد المحاولة لاحقًا", 429)
    if r.status_code >= 400:
        raise SocialError(f"{who}: خطأ {r.status_code}", r.status_code)
    try:
        return r.json()
    except ValueError:
        raise SocialError(f"{who}: رد غير مفهوم") from None


def _entry(url: str, text: str, when, author: str, media: list | None = None, metrics: dict | None = None, links: list | None = None,
           tags: list | None = None, platform: str = "") -> dict:
    text = (text or "").strip()
    return {"url": url, "title": re.sub(r"\s+", " ", text)[:140], "text": text, "summary": "", "published_at": _dt(when),
            "author": author or "", "media": media or [], "full": True,
            "meta": {"platform": platform, "metrics": metrics or {}, "links": links or [], "hashtags": tags or HASHTAG.findall(text)}}


HASHTAG = re.compile(r"#([\w؀-ۿ]+)")


# ---------- الواجهات الرسمية ----------

def _x_official(handle: str, creds: dict, meta: dict) -> tuple[list[dict], dict]:
    h = {"Authorization": f"Bearer {creds['bearer_token']}"}
    with _client() as c:
        uid = meta.get("user_id")
        if not uid:
            uid = _json(c.get(f"{base('x')}/2/users/by/username/{handle}", headers=h), "X")["data"]["id"]
        d = _json(c.get(f"{base('x')}/2/users/{uid}/tweets", headers=h,
                        params={"max_results": 50, "tweet.fields": "created_at,public_metrics,entities,lang"}), "X")
    out = []
    for t in d.get("data", []):
        links = [u.get("expanded_url") for u in (t.get("entities") or {}).get("urls", []) if u.get("expanded_url")]
        tags = [x.get("tag") for x in (t.get("entities") or {}).get("hashtags", [])]
        out.append(_entry(f"https://x.com/{handle}/status/{t['id']}", t.get("text", ""), t.get("created_at"), handle,
                          metrics=t.get("public_metrics"), links=links, tags=tags, platform="x"))
    return out, {"user_id": uid}


def _facebook_official(handle: str, creds: dict, meta: dict) -> tuple[list[dict], dict]:
    with _client() as c:
        d = _json(c.get(f"{base('meta')}/v21.0/{handle}/posts", params={
            "fields": "id,message,created_time,permalink_url,full_picture,shares", "limit": 50, "access_token": creds["access_token"]}), "Meta")
    return [_entry(p.get("permalink_url") or f"https://www.facebook.com/{p['id']}", p.get("message", ""), p.get("created_time"), handle,
                   media=[{"type": "image", "url": p["full_picture"]}] if p.get("full_picture") else [],
                   metrics={"shares": (p.get("shares") or {}).get("count")}, platform="facebook")
            for p in d.get("data", []) if p.get("message") or p.get("full_picture")], {}


def _instagram_official(handle: str, creds: dict, meta: dict) -> tuple[list[dict], dict]:
    fields = f"business_discovery.username({handle}){{media.limit(50){{id,caption,timestamp,permalink,media_type,media_url,like_count,comments_count}}}}"
    with _client() as c:
        d = _json(c.get(f"{base('meta')}/v21.0/{creds['ig_user_id']}", params={"fields": fields, "access_token": creds["access_token"]}), "Meta")
    media = ((d.get("business_discovery") or {}).get("media") or {}).get("data", [])
    return [_entry(m.get("permalink", ""), m.get("caption", ""), m.get("timestamp"), handle,
                   media=[{"type": "video" if m.get("media_type") == "VIDEO" else "image", "url": m["media_url"]}] if m.get("media_url") else [],
                   metrics={"likes": m.get("like_count"), "comments": m.get("comments_count")}, platform="instagram")
            for m in media if m.get("permalink")], {}


def _tiktok_official(handle: str, creds: dict, meta: dict) -> tuple[list[dict], dict]:
    with _client() as c:
        tok = _json(c.post(f"{base('tiktok')}/v2/oauth/token/", data={"client_key": creds["client_key"], "client_secret": creds["client_secret"],
                                                                     "grant_type": "client_credentials"}), "TikTok")["access_token"]
        today = datetime.now(timezone.utc)
        d = _json(c.post(f"{base('tiktok')}/v2/research/video/query/",
                         params={"fields": "id,video_description,create_time,username,like_count,comment_count,share_count,view_count,hashtag_names"},
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"query": {"and": [{"operation": "EQ", "field_name": "username", "field_values": [handle]}]},
                               "start_date": (today - timedelta(days=7)).strftime("%Y%m%d"), "end_date": today.strftime("%Y%m%d"), "max_count": 100}), "TikTok")
    vids = (d.get("data") or {}).get("videos", [])
    return [_entry(f"https://www.tiktok.com/@{v.get('username', handle)}/video/{v['id']}", v.get("video_description", ""),
                   datetime.fromtimestamp(int(v["create_time"]), timezone.utc) if v.get("create_time") else None, v.get("username", handle),
                   media=[{"type": "video", "url": f"https://www.tiktok.com/@{v.get('username', handle)}/video/{v['id']}"}],
                   metrics={k: v.get(k) for k in ("like_count", "comment_count", "share_count", "view_count")}, tags=v.get("hashtag_names"),
                   platform="tiktok") for v in vids], {}


OFFICIAL = {"x": _x_official, "facebook": _facebook_official, "instagram": _instagram_official, "tiktok": _tiktok_official}


# ---------- Apify ----------

def _first(d: dict, *keys):
    for k in keys:
        cur = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur not in (None, ""):
            return cur
    return None


def _apify(platform: str, handle: str, url: str, creds: dict, meta: dict) -> tuple[list[dict], dict]:
    actor = meta.get("apify_actor") or APIFY_ACTORS[platform]
    inp = {"facebook": {"startUrls": [{"url": url}], "resultsLimit": 30},
           "instagram": {"directUrls": [url], "resultsType": "posts", "resultsLimit": 30},
           "tiktok": {"profiles": [handle], "resultsPerPage": 30},
           "x": {"twitterHandles": [handle], "maxItems": 30, "sort": "Latest"}}[platform]
    with _client() as c:
        rows = _json(c.post(f"{base('apify')}/v2/acts/{actor}/run-sync-get-dataset-items", params={"token": creds["api_token"], "timeout": 110},
                            json=inp), "Apify")
    out = []
    for r in rows if isinstance(rows, list) else []:
        link = _first(r, "url", "postUrl", "webVideoUrl", "permalink", "link", "twitterUrl")
        if not link:
            continue
        when = _first(r, "time", "timestamp", "createTimeISO", "createdAt", "created_at", "date")
        if isinstance(when, (int, float)):
            when = datetime.fromtimestamp(when / (1000 if when > 1e11 else 1), timezone.utc)
        img = _first(r, "displayUrl", "full_picture", "media.0.thumbnail", "videoMeta.coverUrl")
        out.append(_entry(link, _first(r, "text", "caption", "message", "postText", "full_text", "fullText", "description") or "", when,
                          _first(r, "ownerUsername", "username", "authorMeta.name", "author.userName", "pageName", "user.name") or handle,
                          media=[{"type": "image", "url": img}] if img else [],
                          metrics={k: _first(r, k) for k in ("likes", "likesCount", "diggCount", "shareCount", "retweetCount", "commentsCount")
                                   if _first(r, k) is not None},
                          links=[x for x in [_first(r, "link.url", "externalUrl")] if x], platform=platform))
    return out, {}


# ---------- القارئ ----------

def read_social(db: Session, url: str, meta: dict) -> tuple[list[dict], dict]:
    platform, handle = meta.get("platform"), (meta.get("handle") or "").strip().lstrip("@")
    if platform not in PLATFORMS or not handle:
        raise SocialError("مصدر تواصل بلا منصة أو اسم حساب")
    provider, creds = credentials(db, platform)
    if not provider:
        raise SocialError(f"ينتظر مزوّد بيانات {PLATFORMS[platform]} (يُضاف من الإدارة ← موصلات التواصل)")
    if provider == "official":
        return OFFICIAL[platform](handle, creds, meta)
    return _apify(platform, handle, url, creds, meta)


# ---------- مؤشرات الحملات المنسّقة ----------

def campaigns(items: list, window_min: int = 60, min_accounts: int = 3) -> list[dict]:
    """مؤشرات لا أحكام: (1) نص شبه متطابق من 3 حسابات أو أكثر خلال ساعة، (2) الرابط نفسه، (3) وسم يتفجّر فجأة من حسابات كثيرة.
    كل مجموعة تُعرض بموادها وحساباتها وتوقيتها، والحكم للصحفي."""
    from marsad.text import normalize_ar, similar

    def acct(i) -> str:
        return (i.author or "").strip() or f"outlet:{i.outlet_id}"

    def t(i):
        return i.published_at or i.captured_at

    items = sorted(items, key=t)
    out: list[dict] = []

    # 1) نسخ ولصق
    used: set[int] = set()
    for k, a in enumerate(items):
        if a.id in used or len(a.text or a.title) < 30:
            continue
        na = normalize_ar(a.text or a.title)[:600]
        group = [a]
        for b in items[k + 1:]:
            if t(b) - t(a) > timedelta(minutes=window_min):
                break
            if b.id not in used and similar(na, normalize_ar(b.text or b.title)[:600]) >= 0.85:
                group.append(b)
        accounts = {acct(x) for x in group}
        if len(accounts) >= min_accounts:
            used |= {x.id for x in group}
            out.append(_cluster("نص متطابق تقريبًا", group, accounts, t))

    # 2) الرابط نفسه، 3) الوسم نفسه
    for kind, key, need, win in (("الرابط نفسه", "links", min_accounts, window_min), ("وسم يتفجّر", "hashtags", 5, 30)):
        buckets: dict[str, list] = {}
        for i in items:
            for v in set(((i.meta or {}).get(key) or [])):
                buckets.setdefault(str(v).lower(), []).append(i)
        for v, group in buckets.items():
            for k, a in enumerate(group):
                g = [x for x in group[k:] if t(x) - t(a) <= timedelta(minutes=win)]
                accounts = {acct(x) for x in g}
                if len(accounts) >= need:
                    out.append(_cluster(f"{kind}: {v}", g, accounts, t))
                    break
    return sorted(out, key=lambda c: (-c["score"], c["start"]))


def _cluster(kind: str, group: list, accounts: set, t) -> dict:
    span = (t(group[-1]) - t(group[0])).total_seconds() / 60
    score = min(100, int(len(accounts) * 12 + max(0, 60 - span)))
    return {"kind": kind, "accounts": sorted(accounts), "count": len(group), "start": t(group[0]).isoformat(),
            "span_minutes": round(span, 1), "score": score, "items": [{"id": x.id, "author": x.author, "url": x.url, "title": x.title[:140],
                                                                      "time": t(x).isoformat()} for x in group[:30]],
            "note": f"{len(accounts)} حساب خلال {round(span)} دقيقة — مؤشر على تنسيق محتمل، لا حكم"}
