"""الرصد: فحص المصادر، حفظ المواد بنصها الكامل ونسخة مؤرشفة، وتتبّع التعديل والحذف.

مبدأ أساسي: لا يُحذف شيء رُصد. التعديل نسخة جديدة، والحذف نسخة بعلامة «محذوف» تبقى معها آخر نسخة مؤرشفة.
"""

from __future__ import annotations

import difflib
import gzip
import hashlib
import logging
from datetime import datetime, timedelta

import trafilatura
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from marsad.core.paths import ensure_storage
from marsad.db import utcnow
from marsad.models.engines import Notification
from marsad.models.monitoring import Item, ItemVersion, Outlet, Source
from marsad.monitor import fetch, readers
from marsad.text import normalize_ar

log = logging.getLogger("marsad.monitor")
ERRORS_BEFORE_ALERT = 3


def content_hash(title: str, text: str) -> str:
    return hashlib.sha256((" ".join(title.split()) + "\n" + " ".join(text.split())).encode()).hexdigest()


def archive_html(raw: bytes, captured: datetime) -> tuple[str, str]:
    """يحفظ الصفحة كما وصلت (مضغوطة) في الأرشيف، ويُرجع المسار النسبي وبصمة SHA-256."""
    sha = hashlib.sha256(raw).hexdigest()
    rel = f"pages/{captured:%Y/%m}/{sha}.html.gz"
    path = ensure_storage().archive / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(raw))
    return rel, sha


def extract(raw: bytes, url: str) -> dict:
    """النص الكامل والعنوان والتاريخ والكاتب والصورة من صفحة الخبر."""
    html = raw.decode("utf-8", errors="replace")
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False, favor_precision=True) or ""
    md = trafilatura.extract_metadata(html, default_url=url)
    return {"text": text.strip(), "title": (md.title if md else "") or "", "author": (md.author if md else "") or "",
            "date": readers._dt(md.date) if md and md.date else None,
            "image": md.image if md and md.image else ""}


def _version(item: Item, change: str, archive: tuple[str, str] | None, at: datetime) -> ItemVersion:
    v = ItemVersion(version=item.version, change=change, title=item.title, text=item.text,
                    content_hash=item.content_hash, captured_at=at,
                    archive_path=archive[0] if archive else "", archive_sha256=archive[1] if archive else "")
    item.versions.append(v)
    return v


def _index(item: Item) -> None:
    item.norm = normalize_ar(f"{item.title} {item.text}")
    try:
        from marsad import search

        search.index_items([item])
    except Exception:  # محرك البحث غير متاح لا يوقف الرصد؛ يبقى البحث من القاعدة
        log.debug("search index skipped", exc_info=True)


def store_entry(db: Session, src: Source, e: dict, fetch_full: bool = True) -> Item | None:
    """يحفظ مدخلًا جديدًا (أو يتجاهله إن كان مرصودًا). يُرجع المادة الجديدة أو None."""
    if db.scalar(select(Item.id).where(Item.source_id == src.id, Item.url == e["url"])):
        return None
    now = utcnow()
    title, text, author = e.get("title", ""), e.get("text", ""), e.get("author", "")
    published, media, archive = e.get("published_at"), list(e.get("media", [])), None
    if fetch_full and not e.get("full") and src.kind != "gdelt":
        try:
            r = fetch.get(e["url"])
            archive = archive_html(r.content, now)
            x = extract(r.content, e["url"])
            text = x["text"] or text or e.get("summary", "")
            title = title or x["title"]
            author = author or x["author"]
            published = published or x["date"]
            if x["image"] and not any(m.get("url") == x["image"] for m in media):
                media.append({"type": "image", "url": x["image"]})
        except fetch.FetchError as err:
            text = text or e.get("summary", "")
            e.setdefault("meta", {})["fetch_error"] = str(err)
    else:
        text = text or e.get("summary", "")
    item = Item(source_id=src.id, outlet_id=src.outlet_id, url=e["url"], title=title.strip(), text=text.strip(),
                author=author[:300], published_at=published, captured_at=now, media=media,
                content_hash=content_hash(title, text), version=1, last_checked_at=now, meta=e.get("meta", {}))
    db.add(item)
    _version(item, "new", archive, now)
    _index(item)
    return item


def check_source(db: Session, src: Source, fetch_full: bool = True) -> dict:
    """يفحص المصدر الآن. أي خطأ يُسجَّل؛ وبعد 3 أخطاء متتالية يصل تنبيه، فلا يتوقف مصدر بصمت."""
    now = utcnow()
    if (src.meta or {}).get("auto_discover"):
        # مصدر من قائمة مستوردة: نكتشف نوعه وطريقة قراءته في أول فحص
        from marsad.monitor.discover import discover

        try:
            info = discover(src.url)
            src.kind, src.read_url = info["kind"], info["read_url"]
            src.meta = {k: v for k, v in {**(src.meta or {}), **info.get("meta", {})}.items() if k != "auto_discover"}
            if info.get("logo_url") and not src.outlet.logo_url:
                src.outlet.logo_url = info["logo_url"]
            if not src.outlet.website:
                src.outlet.website = info["url"]
        except Exception as err:
            src.last_checked_at = now
            src.consecutive_errors += 1
            src.last_error = f"تعذّر اكتشاف المصدر: {err}"
            if src.consecutive_errors >= ERRORS_BEFORE_ALERT and src.status != "error":
                src.status = "error"
                db.add(Notification(kind="source.error", text=f"توقف رصد المصدر «{src.title or src.url}»: {src.last_error}"))
            return {"new": 0, "error": src.last_error}
    reader = readers.READERS.get(src.kind)
    src.last_checked_at = now
    if reader is None:
        src.status = "paused"
        src.last_error = "هذا النوع يُرصد عبر موصل المنصة حين يُضاف مزوّد البيانات (البند 9)"
        return {"new": 0, "error": src.last_error}
    try:
        entries, meta = reader(src.read_url or src.url, dict(src.meta or {}))
    except Exception as err:  # كل عطل يُسجَّل ولا يوقف بقية المصادر
        msg = str(err) if isinstance(err, fetch.FetchError) else f"عطل في القراءة: {err.__class__.__name__}"
        src.consecutive_errors += 1
        src.last_error = msg
        if src.consecutive_errors >= ERRORS_BEFORE_ALERT and src.status != "error":
            src.status = "error"
            db.add(Notification(kind="source.error", text=f"توقف رصد المصدر «{src.title or src.url}»: {msg}"))
        return {"new": 0, "error": msg}
    if src.status == "error":
        db.add(Notification(kind="source.recovered", text=f"عاد رصد المصدر «{src.title or src.url}» للعمل."))
    src.meta = {**(src.meta or {}), **{k: v for k, v in meta.items() if v}}
    src.status, src.consecutive_errors, src.last_error, src.last_ok_at = "ok", 0, "", now
    new = 0
    for e in entries:
        if store_entry(db, src, e, fetch_full=fetch_full):
            new += 1
            src.last_item_at = now
    return {"new": new, "error": ""}


def diff_versions(a: ItemVersion, b: ItemVersion) -> dict:
    """الفرق بين نسختين: العنوان والنص سطرًا بسطر (للعرض جنبًا إلى جنب)."""
    def lines(t: str) -> list[str]:
        return [x.strip() for x in t.replace("\r", "").split("\n") if x.strip()] or [t]

    return {"title_changed": a.title != b.title, "title_before": a.title, "title_after": b.title,
            "text": [{"op": op[0], "before": " ".join(lines(a.text)[op[1]:op[2]]), "after": " ".join(lines(b.text)[op[3]:op[4]])}
                     for op in difflib.SequenceMatcher(None, lines(a.text), lines(b.text)).get_opcodes() if op[0] != "equal"]}


def recheck_item(db: Session, item: Item) -> str:
    """يعيد فحص مادة: «edit» إن تغيّرت، «delete» إن حُذفت، «same» إن لم تتغير."""
    now = utcnow()
    item.last_checked_at = now
    if item.source.kind in ("telegram", "youtube", "gdelt", "social"):
        return "same"  # تعديل منشورات المنصات يُتتبّع بإعادة قراءة القناة، لا الصفحة
    try:
        r = fetch.get(item.url)
    except fetch.FetchError as err:
        if err.status in (404, 410):
            if item.status != "deleted":
                item.status = "deleted"
                item.version += 1
                _version(item, "delete", None, now)
                return "delete"
            return "same"
        return "same"  # خطأ مؤقت: لا نستنتج حذفًا
    x = extract(r.content, item.url)
    title = x["title"] or item.title
    text = x["text"] or item.text
    h = content_hash(title, text)
    if h == item.content_hash and item.status != "deleted":
        return "same"
    change = "restore" if item.status == "deleted" else "edit"
    item.title, item.text, item.content_hash = title, text, h
    item.status = "edited" if change == "edit" else ("edited" if item.version > 1 else "live")
    item.version += 1
    _version(item, change, archive_html(r.content, now), now)
    _index(item)
    return change


def due_sources(db: Session, now: datetime | None = None) -> list[Source]:
    now = now or utcnow()
    out = []
    for s in db.scalars(select(Source).where(Source.active.is_(True), Source.kind != "social")):
        if s.last_checked_at is None or s.last_checked_at + timedelta(minutes=s.check_minutes) <= now:
            out.append(s)
    return out


def items_to_recheck(db: Session, now: datetime | None = None, limit: int = 200) -> list[Item]:
    """أحدث 48 ساعة: كل ساعتين. حتى 7 أيام: يوميًا."""
    now = now or utcnow()
    q = select(Item).where(Item.captured_at >= now - timedelta(days=7), or_(
        Item.last_checked_at.is_(None),
        (Item.captured_at >= now - timedelta(hours=48)) & (Item.last_checked_at <= now - timedelta(hours=2)),
        Item.last_checked_at <= now - timedelta(days=1)))
    return list(db.scalars(q.order_by(Item.last_checked_at).limit(limit)))


def find_or_create_outlet(db: Session, name: str, website: str = "", logo: str = "", kind: str = "news") -> Outlet:
    o = db.scalar(select(Outlet).where(Outlet.name == name))
    if o is None:
        o = Outlet(name=name, website=website, logo_url=logo, kind=kind)
        db.add(o)
        db.flush()
    return o
