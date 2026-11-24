"""المصادر والجهات (الشاشة 2) والرصد المباشر والبحث (الشاشة 3)."""

from __future__ import annotations

import logging
import threading
import csv
import gzip
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marsad import search as search_mod
from marsad.api.deps import require
from marsad.audit import record
from marsad.core.paths import ensure_storage
from marsad.db import get_db, utcnow
from marsad.models import User
from marsad.models.monitoring import Item, ItemVersion, Outlet, Source
from marsad.monitor import service as mon
from marsad.monitor.discover import discover, normalize_url
from marsad.monitor.fetch import FetchError

router = APIRouter(prefix="/api", tags=["sources"])
view_sources = require("sources.view")
manage_sources = require("sources.manage")
view_items = require("monitor.view")
SEED = Path(__file__).resolve().parents[1] / "monitor" / "seed_sources.json"
KINDS_AR = {"rss": "خلاصة RSS", "sitemap": "خريطة الموقع", "page": "الصفحة العامة", "telegram": "قناة تيليغرام",
            "youtube": "قناة يوتيوب", "gdelt": "GDELT", "social": "منصة تواصل", "manual": "يدوي"}


def _dt(d):
    return d.isoformat() if d else None


log = logging.getLogger(__name__)
_CHECKING: set[int] = set()  # مصادر يجري فحصها الآن في هذه العملية
_CHECK_LOCK = threading.Lock()


def source_out(s: Source) -> dict:
    silent = bool(s.status == "ok" and s.last_item_at and
                  utcnow() - s.last_item_at > timedelta(minutes=max(24 * 60, s.check_minutes * 40)))
    return {"id": s.id, "outlet_id": s.outlet_id, "url": s.url, "kind": s.kind, "kind_ar": KINDS_AR.get(s.kind, s.kind),
            "read_url": s.read_url, "title": s.title, "tags": s.tags, "check_minutes": s.check_minutes,
            "active": s.active, "status": s.status, "last_checked_at": _dt(s.last_checked_at),
            "last_ok_at": _dt(s.last_ok_at), "last_item_at": _dt(s.last_item_at), "last_error": s.last_error,
            "consecutive_errors": s.consecutive_errors, "silent": silent, "checking": s.id in _CHECKING}


def outlet_out(db: Session, o: Outlet) -> dict:
    n = db.scalar(select(func.count(Item.id)).where(Item.outlet_id == o.id))
    return {"id": o.id, "name": o.name, "kind": o.kind, "country": o.country, "website": o.website,
            "logo_url": o.logo_url, "tags": o.tags, "items": n, "sources": [source_out(s) for s in o.sources]}


def item_out(i: Item, full: bool = False) -> dict:
    d = {"id": i.id, "url": i.url, "title": i.title, "excerpt": i.text[:280], "source_id": i.source_id,
         "outlet_id": i.outlet_id, "source_title": i.source.title, "source_kind": i.source.kind,
         "published_at": _dt(i.published_at), "captured_at": _dt(i.captured_at), "status": i.status,
         "version": i.version, "media": i.media, "author": i.author, "story_id": i.story_id,
         "published_date_only": mon.published_date_only(i)}
    if full:
        d["text"] = i.text
        d["meta"] = i.meta
        d["versions"] = [{"version": v.version, "change": v.change, "title": v.title, "captured_at": _dt(v.captured_at),
                          "archived": bool(v.archive_path), "archive_sha256": v.archive_sha256} for v in i.versions]
    return d


# ---------- الجهات ----------

@router.get("/outlets")
def outlets(_: User = Depends(view_sources), db: Session = Depends(get_db)):
    return [outlet_out(db, o) for o in db.scalars(select(Outlet).order_by(Outlet.name))]


class OutletIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "news"
    country: str = ""
    website: str = ""
    tags: list[str] = []


@router.post("/outlets")
def create_outlet(body: OutletIn, actor: User = Depends(manage_sources), db: Session = Depends(get_db)):
    o = Outlet(**body.model_dump())
    db.add(o)
    db.flush()
    record(db, actor, "outlet.create", "outlet", str(o.id), None, {"name": o.name})
    db.commit()
    return outlet_out(db, o)


@router.put("/outlets/{oid}")
def update_outlet(oid: int, body: OutletIn, actor: User = Depends(manage_sources), db: Session = Depends(get_db)):
    o = db.get(Outlet, oid) or _404()
    for k, v in body.model_dump().items():
        setattr(o, k, v)
    record(db, actor, "outlet.update", "outlet", str(oid), None, body.model_dump())
    db.commit()
    return outlet_out(db, o)


def _404():
    raise HTTPException(404, "غير موجود")


# ---------- المصادر ----------

class UrlIn(BaseModel):
    url: str


@router.post("/sources/discover")
def discover_source(body: UrlIn, _: User = Depends(manage_sources)):
    try:
        return discover(body.url)
    except (ValueError, FetchError) as e:
        raise HTTPException(422, f"تعذّر فحص الرابط: {e}") from None


class SourceIn(BaseModel):
    url: str
    outlet_id: int | None = None
    outlet_name: str | None = None
    outlet_kind: str = "news"
    country: str = ""
    kind: str | None = None
    read_url: str | None = None
    title: str | None = None
    check_minutes: int = Field(15, ge=5, le=1440)
    tags: list[str] = []
    meta: dict = {}
    also: list[str] = []  # روابط المنصات المكتشفة لإضافتها لنفس الجهة


def _add_source(db: Session, actor: User, body: SourceIn) -> Source:
    url = normalize_url(body.url)
    found = body.kind is None
    info = discover(url) if found else {"url": url, "kind": body.kind, "read_url": body.read_url or url,
                                        "title": body.title or url, "outlet_name": body.outlet_name or url,
                                        "logo_url": "", "meta": body.meta}
    if db.scalar(select(Source).where(Source.url == info["url"])):
        raise HTTPException(409, "هذا المصدر مضاف مسبقًا")
    if body.outlet_id:
        outlet = db.get(Outlet, body.outlet_id) or _404()
    else:
        outlet = mon.find_or_create_outlet(db, (body.outlet_name or info["outlet_name"]).strip(),
                                           website=info["url"] if info["kind"] not in ("telegram", "youtube", "social") else "",
                                           logo=info.get("logo_url", ""), kind=body.outlet_kind)
        if body.country and not outlet.country:
            outlet.country = body.country
        outlet.tags = sorted(set(outlet.tags or []) | set(body.tags))
    s = Source(outlet_id=outlet.id, url=info["url"], kind=info["kind"], read_url=info["read_url"],
               title=body.title or info["title"], check_minutes=body.check_minutes, tags=body.tags,
               meta={**info.get("meta", {}), **body.meta}, status="paused" if info["kind"] == "social" else "new")
    db.add(s)
    db.flush()
    record(db, actor, "source.create", "source", str(s.id), None, {"url": s.url, "kind": s.kind, "outlet": outlet.name})
    return s


@router.post("/sources")
def create_source(body: SourceIn, bg: BackgroundTasks, actor: User = Depends(manage_sources), db: Session = Depends(get_db)):
    try:
        s = _add_source(db, actor, body)
        extra, skipped = [], []
        for u in body.also:  # فشل صفحة واحدة لا يوقف إضافة الجهة ولا بقية صفحاتها
            try:
                with db.begin_nested():
                    extra.append(_add_source(db, actor, SourceIn(url=u, outlet_id=s.outlet_id, check_minutes=body.check_minutes,
                                                                 tags=body.tags)))
            except HTTPException as e:
                skipped.append({"url": u, "reason": str(e.detail)})
            except (ValueError, FetchError) as e:
                skipped.append({"url": u, "reason": str(e)})
    except (ValueError, FetchError) as e:
        raise HTTPException(422, f"تعذّر إضافة المصدر: {e}") from None
    db.commit()
    for x in [s, *extra]:
        bg.add_task(check_now_bg, x.id)  # يبدأ الرصد فورًا
    return {"source": source_out(s), "also": [source_out(x) for x in extra], "skipped": skipped}


def _claim(source_id: int) -> bool:
    with _CHECK_LOCK:
        if source_id in _CHECKING:
            return False
        _CHECKING.add(source_id)
        return True


def check_now_bg(source_id: int, claimed: bool = False) -> None:
    """فحص في الخلفية: يحفظ الحالة والمواد تباعًا فتظهر في الواجهة أثناء الفحص."""
    from marsad.db import get_db as _g

    if not claimed and not _claim(source_id):
        return  # فحص آخر لهذا المصدر جارٍ
    db = next(_g())
    try:
        s = db.get(Source, source_id)
        if s:
            mon.check_source(db, s, commit_every=5)
            db.commit()
    except Exception:
        db.rollback()
        log.exception("فشل فحص المصدر %s", source_id)
    finally:
        _CHECKING.discard(source_id)
        db.close()


class SourceUpdate(BaseModel):
    title: str | None = None
    check_minutes: int | None = Field(None, ge=5, le=1440)
    tags: list[str] | None = None
    active: bool | None = None
    outlet_id: int | None = None
    read_url: str | None = None


@router.put("/sources/{sid}")
def update_source(sid: int, body: SourceUpdate, actor: User = Depends(manage_sources), db: Session = Depends(get_db)):
    s = db.get(Source, sid) or _404()
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(s, k, v)
    if body.active is True and s.status == "error":
        s.status, s.consecutive_errors = "new", 0
    record(db, actor, "source.update", "source", str(sid), None, changes)
    db.commit()
    return source_out(s)


@router.delete("/sources/{sid}")
def delete_source(sid: int, actor: User = Depends(manage_sources), db: Session = Depends(get_db)):
    """إيقاف الرصد فقط: المواد المرصودة لا تُحذف أبدًا (مبدأ الأرشيف)."""
    s = db.get(Source, sid) or _404()
    s.active = False
    s.status = "paused"
    record(db, actor, "source.pause", "source", str(sid))
    db.commit()
    return source_out(s)


@router.post("/sources/{sid}/check")
def check_now(sid: int, bg: BackgroundTasks, wait: bool = False, actor: User = Depends(manage_sources),
              db: Session = Depends(get_db)):
    """يبدأ الفحص في الخلفية ويعود فورًا (قد يستغرق فحص موقع كامل دقائق). wait=true للفحص المتزامن."""
    s = db.get(Source, sid) or _404()
    if wait:
        r = mon.check_source(db, s)
        db.commit()
        return {**r, "started": False, "source": source_out(s)}
    if not _claim(sid):
        return {"started": False, "already": True, "source": source_out(s)}
    db.commit()
    bg.add_task(check_now_bg, sid, True)
    return {"started": True, "already": False, "source": source_out(s)}


@router.get("/sources/export")
def export_sources(_: User = Depends(view_sources), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["outlet", "outlet_kind", "country", "url", "kind", "read_url", "title", "check_minutes", "tags", "active"])
    for s in db.scalars(select(Source).order_by(Source.outlet_id, Source.id)):
        w.writerow([s.outlet.name, s.outlet.kind, s.outlet.country, s.url, s.kind, s.read_url, s.title,
                    s.check_minutes, "|".join(s.tags), int(s.active)])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="marsad-sources.csv"'})


class ImportIn(BaseModel):
    csv: str | None = None
    rows: list[dict] | None = None
    discover: bool = False  # True: يفحص كل رابط ليكتشف نوعه (أبطأ)


@router.post("/sources/import")
def import_sources(body: ImportIn, bg: BackgroundTasks, actor: User = Depends(manage_sources), db: Session = Depends(get_db)):
    rows = body.rows or list(csv.DictReader(io.StringIO((body.csv or "").lstrip("﻿"))))
    added, skipped, errors = [], 0, []
    for r in rows:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        try:
            norm = normalize_url(url)
            if db.scalar(select(Source.id).where(Source.url == norm)):
                skipped += 1
                continue
            kind = None if body.discover else (r.get("kind") or ("gdelt" if norm.startswith("gdelt:") else "page"))
            meta = {"query": norm[6:]} if norm.startswith("gdelt:") else {}
            read = r.get("read_url") or (None if kind != "gdelt" else None)
            if kind == "gdelt":
                from marsad.monitor.readers import gdelt_url

                read = gdelt_url(norm[6:])
            s = _add_source(db, actor, SourceIn(
                url=norm, outlet_name=r.get("outlet") or r.get("name"), outlet_kind=r.get("outlet_kind") or r.get("kind_outlet") or "news",
                country=r.get("country", ""), kind=kind, read_url=read, title=r.get("title") or r.get("name"),
                check_minutes=int(r.get("check_minutes") or 15),
                tags=[t for t in (r.get("tags") if isinstance(r.get("tags"), list) else str(r.get("tags") or "").split("|")) if t],
                meta=meta))
            added.append(s.id)
        except (HTTPException, ValueError, FetchError) as e:
            errors.append({"url": url, "error": getattr(e, "detail", str(e))})
    db.commit()
    return {"added": len(added), "skipped": skipped, "errors": errors}


@router.post("/sources/seed")
def seed(bg: BackgroundTasks, actor: User = Depends(manage_sources), db: Session = Depends(get_db)):
    """يضيف قائمة الخمسين مصدرًا المقترحة (أردنية وعربية ودولية ومنصات تحقق وGDELT). تُعدَّل بعدها كما تشاء."""
    rows = json.loads(SEED.read_text(encoding="utf-8"))
    for r in rows:
        r["outlet"], r["outlet_kind"] = r["name"], r["kind"]
        r["kind"] = "gdelt" if r["url"].startswith("gdelt:") else "page"  # يُصحَّح النوع عند أول فحص
        r["auto_discover"] = True
    out = import_sources(ImportIn(rows=rows), bg, actor, db)
    for s in db.scalars(select(Source).where(Source.kind == "page", Source.status == "new")):
        s.meta = {**(s.meta or {}), "auto_discover": True}
    db.commit()
    return out


# ---------- المواد والبحث ----------

@router.get("/items")
def items(q: str = "", source_id: int | None = None, outlet_id: int | None = None, status: str | None = None,
          date_from: datetime | None = None, date_to: datetime | None = None, story_id: int | None = None,
          limit: int = 50, offset: int = 0, _: User = Depends(view_items), db: Session = Depends(get_db)):
    rows, total, how = search_mod.search(db, q, source_id=source_id, outlet_id=outlet_id, status=status,
                                         date_from=date_from, date_to=date_to, story_id=story_id,
                                         limit=min(limit, 200), offset=offset)
    return {"total": total, "engine": how, "items": [item_out(i) for i in rows]}


@router.get("/items/{iid}")
def item(iid: int, _: User = Depends(view_items), db: Session = Depends(get_db)):
    i = db.get(Item, iid) or _404()
    out = item_out(i, full=True)
    vs = i.versions
    out["diffs"] = [{"from": a.version, "to": b.version, **mon.diff_versions(a, b)}
                    for a, b in zip(vs, vs[1:]) if b.change in ("edit", "restore")]
    return out


@router.get("/items/{iid}/archive/{version}")
def archived(iid: int, version: int, _: User = Depends(view_items), db: Session = Depends(get_db)):
    """النسخة المؤرشفة كما وصلت. تُعرض في وضع معزول: لا سكربتات ولا اتصالات من داخلها."""
    v = db.scalar(select(ItemVersion).where(ItemVersion.item_id == iid, ItemVersion.version == version)) or _404()
    if not v.archive_path:
        raise HTTPException(404, "لا توجد نسخة مؤرشفة لهذه النسخة")
    path = ensure_storage().archive / v.archive_path
    raw = gzip.decompress(path.read_bytes())
    return Response(raw, media_type="text/html; charset=utf-8", headers={
        "Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'",
        "X-Archive-SHA256": v.archive_sha256})


@router.get("/monitor/status")
def status(_: User = Depends(view_items), db: Session = Depends(get_db)):
    srcs = list(db.scalars(select(Source).where(Source.active.is_(True))))
    since = utcnow() - timedelta(hours=24)
    return {"sources": len(srcs), "ok": sum(s.status == "ok" for s in srcs),
            "error": sum(s.status == "error" for s in srcs), "paused": sum(s.status == "paused" for s in srcs),
            "new": sum(s.status == "new" for s in srcs),
            "items_24h": db.scalar(select(func.count(Item.id)).where(Item.captured_at >= since)),
            "edited_24h": db.scalar(select(func.count(ItemVersion.id)).where(ItemVersion.change == "edit", ItemVersion.captured_at >= since)),
            "deleted_24h": db.scalar(select(func.count(ItemVersion.id)).where(ItemVersion.change == "delete", ItemVersion.captured_at >= since)),
            "items_total": db.scalar(select(func.count(Item.id)))}
