"""البحث في المواد المرصودة.

- Meilisearch إن كان متاحًا (MARSAD_MEILI_URL): سريع في ملايين المواد.
- وإلا البحث في قاعدة البيانات على النص الموحّد (يعمل دائمًا، أبطأ مع الحجم الكبير).
النص والاستعلام كلاهما يُوحَّدان (همزات، تاء مربوطة، تشكيل، أرقام هندية) فتظهر كل أشكال الكلمة.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx
from sqlalchemy import and_, event, func, select
from sqlalchemy.orm import Session

from marsad.models.monitoring import Item
from marsad.text import normalize_ar

INDEX = "items"
SEARCH_REV = 2  # يرتفع حين تتغيّر إعدادات الفهارس أو شكل الوثائق، فيُعاد بناؤها مرة واحدة في الخلفية
_ready: set[str] = set()
log = logging.getLogger(__name__)


def _meili() -> tuple[str, dict] | None:
    url = os.environ.get("MARSAD_MEILI_URL")
    if not url:
        return None
    key = os.environ.get("MARSAD_MEILI_KEY") or os.environ.get("MEILI_MASTER_KEY") or ""
    return url.rstrip("/"), ({"Authorization": f"Bearer {key}"} if key else {})


def available() -> bool:
    return _meili() is not None


def _ts(d) -> int | None:
    return int(d.timestamp()) if d else None


# كل فهرس: إعداداته ودالة وثيقته. الوثيقة تحمل النص الموحّد فقط (الاستعلام يوحَّد أيضًا) وحقول التصفية،
# فلا يُخزَّن النص الأصلي مرتين ويصغر الفهرس إلى نحو النصف.
def _doc_item(i: Item) -> dict:
    return {"id": i.id, "norm_title": normalize_ar(i.title), "norm": (i.norm or "")[:20000], "source_id": i.source_id,
            "outlet_id": i.outlet_id, "status": i.status, "published_ts": _ts(i.published_at),
            "captured_ts": _ts(i.captured_at), "story_id": i.story_id}


def _doc_claim(c) -> dict:
    return {"id": c.id, "norm": c.norm or normalize_ar(c.text), "speaker": normalize_ar(c.speaker or ""),
            "status": c.status, "created_ts": _ts(c.created_at)}


def _doc_entity(e) -> dict:
    return {"id": e.id, "norm": e.norm, "aliases": [normalize_ar(a) for a in (e.aliases or []) if isinstance(a, str)],
            "kind": e.kind}


def _doc_story(s) -> dict:
    return {"id": s.id, "norm": normalize_ar(s.title or ""), "item_count": s.item_count, "source_count": s.source_count,
            "updated_ts": _ts(s.updated_at)}


INDEXES: dict[str, dict] = {
    "items": {"doc": _doc_item, "settings": {
        "searchableAttributes": ["norm_title", "norm"],
        "filterableAttributes": ["source_id", "outlet_id", "status", "published_ts", "captured_ts", "story_id"],
        "sortableAttributes": ["published_ts", "captured_ts"]}},
    "claims": {"doc": _doc_claim, "settings": {
        "searchableAttributes": ["norm", "speaker"], "filterableAttributes": ["status", "created_ts"],
        "sortableAttributes": ["created_ts"]}},
    "entities": {"doc": _doc_entity, "settings": {
        "searchableAttributes": ["norm", "aliases"], "filterableAttributes": ["kind"]}},
    "stories": {"doc": _doc_story, "settings": {
        "searchableAttributes": ["norm"], "filterableAttributes": ["item_count", "source_count"],
        "sortableAttributes": ["updated_ts"]}},
}


def _setup(base: str, h: dict, kind: str = INDEX) -> None:
    if kind in _ready:
        return
    httpx.post(f"{base}/indexes", headers=h, json={"uid": kind, "primaryKey": "id"}, timeout=10)
    httpx.patch(f"{base}/indexes/{kind}/settings", headers=h, timeout=10, json=INDEXES[kind]["settings"])
    _ready.add(kind)


def index_docs(kind: str, objs: list) -> None:
    m = _meili()
    objs = [o for o in objs if getattr(o, "id", None)]
    if not m or not objs:
        return
    base, h = m
    _setup(base, h, kind)
    httpx.post(f"{base}/indexes/{kind}/documents", headers=h, json=[INDEXES[kind]["doc"](o) for o in objs], timeout=30)


def delete_docs(kind: str, ids: list[int]) -> None:
    m = _meili()
    if not m or not ids:
        return
    base, h = m
    httpx.post(f"{base}/indexes/{kind}/documents/delete-batch", headers=h, json=list(ids), timeout=20)


def index_items(items: list[Item]) -> None:
    index_docs("items", items)


def search_ids(kind: str, q: str, *, filters: list[str] | None = None, sort: list[str] | None = None,
               limit: int = 50, offset: int = 0) -> tuple[list[int], int] | None:
    """أرقام النتائج من Meilisearch، أو None إن لم يكن متاحًا (فيبحث المتصل في القاعدة)."""
    m = _meili()
    nq = normalize_ar(q)
    if not m or not nq:
        return None
    base, h = m
    try:
        _setup(base, h, kind)
        r = httpx.post(f"{base}/indexes/{kind}/search", headers=h, timeout=10, json={
            "q": nq, "limit": limit, "offset": offset, "filter": " AND ".join(filters or []) or None,
            "sort": sort, "attributesToRetrieve": ["id"]})
        r.raise_for_status()
        j = r.json()
        return [x["id"] for x in j.get("hits", [])], j.get("estimatedTotalHits", 0)
    except (httpx.HTTPError, ValueError):
        return None


# ---------- مزامنة تلقائية: الادّعاءات والكيانات والقصص تُفهرس حين تُحفظ ----------

_TRACKED = {"claims": "claims", "entities": "entities", "stories": "stories"}


def _track(session: Session, flush_context=None) -> None:
    if not available():
        return
    pend = session.info.setdefault("_search_pending", {"up": {}, "del": {}})
    for obj in list(session.new) + list(session.dirty):
        kind = _TRACKED.get(getattr(obj, "__tablename__", ""))
        if kind and getattr(obj, "id", None):
            pend["up"].setdefault(kind, {})[obj.id] = obj
    for obj in session.deleted:
        kind = _TRACKED.get(getattr(obj, "__tablename__", ""))
        if kind and getattr(obj, "id", None):
            pend["del"].setdefault(kind, set()).add(obj.id)


def _push(session: Session) -> None:
    pend = session.info.pop("_search_pending", None)
    if not pend:
        return
    try:
        for kind, objs in pend["up"].items():
            index_docs(kind, [o for o in objs.values() if o.id not in pend["del"].get(kind, set())])
        for kind, ids in pend["del"].items():
            delete_docs(kind, sorted(ids))
    except Exception:  # noqa: BLE001 — تعذّر البحث لا يوقف الحفظ؛ إعادة البناء تلتقط ما فات
        log.warning("تعذّرت مزامنة فهرس البحث", exc_info=True)


def _discard(session: Session) -> None:
    session.info.pop("_search_pending", None)


event.listen(Session, "after_flush", _track)
event.listen(Session, "after_commit", _push)
event.listen(Session, "after_rollback", _discard)


def rebuild(db: Session, kinds: list[str] | None = None, batch: int = 2000) -> dict:
    """يعيد بناء الفهارس من قاعدة البيانات (بعد الترقية أو الاسترداد)."""
    from marsad.models.analysis import Entity, Story
    from marsad.models.claims import Claim

    model = {"items": Item, "claims": Claim, "entities": Entity, "stories": Story}
    out = {}
    m = _meili()
    if not m:
        return out
    base, h = m
    for kind in kinds or list(INDEXES):
        _ready.discard(kind)
        _setup(base, h, kind)
        n, last = 0, 0
        while True:
            rows = list(db.scalars(select(model[kind]).where(model[kind].id > last).order_by(model[kind].id).limit(batch)))
            if not rows:
                break
            index_docs(kind, rows)
            last, n = rows[-1].id, n + len(rows)
            db.expunge_all()
        out[kind] = n
    return out


def rebuild_if_needed() -> None:
    """في الخلفية عند بدء الخادم: يعيد بناء الفهارس إن تغيّر شكلها في هذا الإصدار."""
    if not available():
        return
    import threading

    def run() -> None:
        from marsad.db import get_db
        from marsad.rbac.service import get_setting, set_setting

        s = next(get_db())
        try:
            if int(get_setting(s, "search_rev", 1) or 1) >= SEARCH_REV:
                return
            log.info("إعادة بناء فهارس البحث: %s", rebuild(s))
            set_setting(s, "search_rev", SEARCH_REV)
            s.commit()
        except Exception:  # noqa: BLE001
            log.warning("تعذّرت إعادة بناء فهارس البحث؛ ستُعاد في التشغيل التالي", exc_info=True)
        finally:
            s.close()

    threading.Thread(target=run, name="search-rebuild", daemon=True).start()


def search(db: Session, q: str = "", *, source_id: int | None = None, outlet_id: int | None = None,
           status: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
           story_id: int | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Item], int, str]:
    """يُرجع (المواد، العدد الكلي، الطريقة: meili | db)."""
    nq = normalize_ar(q)
    if nq and available():
        filt = []
        for k, v in (("source_id", source_id), ("outlet_id", outlet_id), ("story_id", story_id)):
            if v is not None:
                filt.append(f"{k} = {int(v)}")
        if status:
            filt.append(f'status = "{status}"')
        if date_from:
            filt.append(f"captured_ts >= {int(date_from.timestamp())}")
        if date_to:
            filt.append(f"captured_ts <= {int(date_to.timestamp())}")
        r = search_ids("items", nq, filters=filt, sort=["captured_ts:desc"], limit=limit, offset=offset)
        if r is not None:
            ids, total = r
            found = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(ids)))}
            return [found[i] for i in ids if i in found], total, "meili"
    conds = []
    for term in nq.split():
        conds.append(Item.norm.contains(term))
    if source_id is not None:
        conds.append(Item.source_id == source_id)
    if outlet_id is not None:
        conds.append(Item.outlet_id == outlet_id)
    if story_id is not None:
        conds.append(Item.story_id == story_id)
    if status:
        conds.append(Item.status == status)
    if date_from:
        conds.append(Item.captured_at >= date_from)
    if date_to:
        conds.append(Item.captured_at <= date_to)
    where = and_(*conds) if conds else True
    total = db.scalar(select(func.count(Item.id)).where(where))
    rows = db.scalars(select(Item).where(where).order_by(Item.captured_at.desc(), Item.id.desc()).offset(offset).limit(limit))
    return list(rows), total, "db"
