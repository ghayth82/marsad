"""البحث في المواد المرصودة.

- Meilisearch إن كان متاحًا (MARSAD_MEILI_URL): سريع في ملايين المواد.
- وإلا البحث في قاعدة البيانات على النص الموحّد (يعمل دائمًا، أبطأ مع الحجم الكبير).
النص والاستعلام كلاهما يُوحَّدان (همزات، تاء مربوطة، تشكيل، أرقام هندية) فتظهر كل أشكال الكلمة.
"""

from __future__ import annotations

import os
from datetime import datetime

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from marsad.models.monitoring import Item
from marsad.text import normalize_ar

INDEX = "items"
_ready = False


def _meili() -> tuple[str, dict] | None:
    url = os.environ.get("MARSAD_MEILI_URL")
    if not url:
        return None
    key = os.environ.get("MARSAD_MEILI_KEY") or os.environ.get("MEILI_MASTER_KEY") or ""
    return url.rstrip("/"), ({"Authorization": f"Bearer {key}"} if key else {})


def _setup(base: str, h: dict) -> None:
    global _ready
    if _ready:
        return
    httpx.post(f"{base}/indexes", headers=h, json={"uid": INDEX, "primaryKey": "id"}, timeout=10)
    httpx.patch(f"{base}/indexes/{INDEX}/settings", headers=h, timeout=10, json={
        "searchableAttributes": ["norm_title", "norm", "title", "text"],
        "filterableAttributes": ["source_id", "outlet_id", "status", "published_ts", "captured_ts", "story_id"],
        "sortableAttributes": ["published_ts", "captured_ts"],
    })
    _ready = True


def _doc(i: Item) -> dict:
    ts = lambda d: int(d.timestamp()) if d else None  # noqa: E731
    return {"id": i.id, "title": i.title, "text": i.text[:20000], "norm_title": normalize_ar(i.title),
            "norm": i.norm[:20000], "source_id": i.source_id, "outlet_id": i.outlet_id, "status": i.status,
            "published_ts": ts(i.published_at), "captured_ts": ts(i.captured_at), "story_id": i.story_id}


def index_items(items: list[Item]) -> None:
    m = _meili()
    if not m or not items:
        return
    base, h = m
    _setup(base, h)
    ids = [i for i in items if i.id]
    if ids:
        httpx.post(f"{base}/indexes/{INDEX}/documents", headers=h, json=[_doc(i) for i in ids], timeout=20)


def search(db: Session, q: str = "", *, source_id: int | None = None, outlet_id: int | None = None,
           status: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
           story_id: int | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Item], int, str]:
    """يُرجع (المواد، العدد الكلي، الطريقة: meili | db)."""
    nq = normalize_ar(q)
    m = _meili()
    if m and nq:
        base, h = m
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
        try:
            _setup(base, h)
            r = httpx.post(f"{base}/indexes/{INDEX}/search", headers=h, timeout=10, json={
                "q": nq, "limit": limit, "offset": offset, "filter": " AND ".join(filt) or None,
                "sort": ["captured_ts:desc"], "attributesToRetrieve": ["id"]}).json()
            ids = [x["id"] for x in r.get("hits", [])]
            found = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(ids)))}
            return [found[i] for i in ids if i in found], r.get("estimatedTotalHits", len(ids)), "meili"
        except (httpx.HTTPError, ValueError):
            pass  # نرجع إلى القاعدة
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
