"""القصص (الشاشة 4) والكيانات (الشاشة 9)."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marsad.analysis import core
from marsad.api.deps import require
from marsad.audit import record
from marsad.db import get_db
from marsad.models import User
from marsad.models.analysis import Entity, EntityMention, Statement, Story
from marsad.models.monitoring import Item, Outlet
from marsad.text import normalize_ar

router = APIRouter(prefix="/api", tags=["analysis"])
view = require("monitor.view")
edit = require("claims.create")  # الصحفي يعدّل التجميع والكيانات


def _404():
    raise HTTPException(404, "غير موجود")


@router.get("/stories")
def stories(limit: int = 40, min_items: int = 1, min_sources: int = 1, q: str = "", exclude: int | None = None,
            _: User = Depends(view), db: Session = Depends(get_db)):
    """قائمة القصص؛ q للبحث بالعنوان (لاختيار قصة للدمج أو النقل)، بكل أشكال الكلمة."""
    stmt = select(Story).where(Story.item_count >= min_items, Story.source_count >= min_sources)
    if exclude:
        stmt = stmt.where(Story.id != exclude)
    stmt = stmt.order_by(Story.updated_at.desc())
    if q.strip():
        from marsad.text import normalize_ar

        nq = normalize_ar(q)
        rows = [s for s in db.scalars(stmt.limit(2000)) if nq in normalize_ar(s.title)][:min(limit, 200)]
    else:
        rows = db.scalars(stmt.limit(min(limit, 200)))
    return [{"id": s.id, "title": s.title, "item_count": s.item_count, "source_count": s.source_count,
             "updated_at": s.updated_at.isoformat(), "created_at": s.created_at.isoformat()} for s in rows]


@router.get("/stories/{sid}")
def story(sid: int, _: User = Depends(view), db: Session = Depends(get_db)):
    return core.story_view(db, db.get(Story, sid) or _404())


class MoveIn(BaseModel):
    story_id: int | None  # None = قصة جديدة مستقلة


@router.put("/items/{iid}/story")
def move(iid: int, body: MoveIn, actor: User = Depends(edit), db: Session = Depends(get_db)):
    it = db.get(Item, iid) or _404()
    old = it.story_id
    if body.story_id is not None and not db.get(Story, body.story_id):
        _404()
    target = core.move_item(db, it, body.story_id)
    record(db, actor, "story.move_item", "item", str(iid), {"story_id": old}, {"story_id": target.id})
    db.commit()
    return {"story_id": target.id, "from_story_id": old}  # from_story_id: للتراجع


class MergeIn(BaseModel):
    other_id: int


@router.post("/stories/{sid}/merge")
def merge(sid: int, body: MergeIn, actor: User = Depends(edit), db: Session = Depends(get_db)):
    keep, other = db.get(Story, sid) or _404(), db.get(Story, body.other_id) or _404()
    if keep.id == other.id:
        raise HTTPException(422, "لا تُدمج القصة مع نفسها")
    moved = [i.id for i in db.scalars(select(Item).where(Item.story_id == other.id))]
    core.merge_stories(db, keep, other)
    record(db, actor, "story.merge", "story", str(sid), None, {"merged": body.other_id, "items": moved})
    db.commit()
    return {**core.story_view(db, keep), "moved": moved, "from_story_id": other.id}


class MoveManyIn(BaseModel):
    item_ids: list[int]
    story_id: int


@router.post("/stories/move-items")
def move_items(body: MoveManyIn, actor: User = Depends(edit), db: Session = Depends(get_db)):
    """نقل عدة مواد إلى قصة (للتراجع عن دمج: تعود المواد إلى قصتها الأولى)."""
    db.get(Story, body.story_id) or _404()
    for iid in body.item_ids:
        it = db.get(Item, iid) or _404()
        old = it.story_id
        core.move_item(db, it, body.story_id)
        record(db, actor, "story.move_item", "item", str(iid), {"story_id": old}, {"story_id": body.story_id})
    db.commit()
    return {"story_id": body.story_id, "moved": body.item_ids}


@router.get("/entities")
def entities(q: str = "", kind: str | None = None, limit: int = 50, _: User = Depends(view), db: Session = Depends(get_db)):
    cnt = func.count(EntityMention.id).label("n")
    stmt = select(Entity, cnt).join(EntityMention, EntityMention.entity_id == Entity.id).group_by(Entity.id)
    if q:
        stmt = stmt.where(Entity.norm.contains(normalize_ar(q)))
    if kind:
        stmt = stmt.where(Entity.kind == kind)
    rows = db.execute(stmt.order_by(cnt.desc()).limit(min(limit, 200))).all()
    return [{"id": e.id, "name": e.name, "kind": e.kind, "mentions": n, "aliases": e.aliases} for e, n in rows]


@router.get("/entities/{eid}")
def entity(eid: int, _: User = Depends(view), db: Session = Depends(get_db)):
    e = db.get(Entity, eid) or _404()
    ms = db.execute(select(EntityMention, Item, Outlet).join(Item, Item.id == EntityMention.item_id)
                    .join(Outlet, Outlet.id == Item.outlet_id).where(EntityMention.entity_id == eid)).all()
    by_outlet: dict[str, list[float]] = defaultdict(list)
    for m, _, o in ms:
        by_outlet[o.name].append(m.tone)
    sts = db.execute(select(Statement, Item).join(Item, Item.id == Statement.item_id)
                     .where(Statement.entity_id == eid).order_by(Statement.said_at.desc())).all()
    return {"id": e.id, "name": e.name, "kind": e.kind, "aliases": e.aliases, "mentions": len(ms),
            "tone_by_outlet": [{"outlet": k, "mentions": len(v), "tone": round(sum(v) / len(v), 2)} for k, v in
                               sorted(by_outlet.items(), key=lambda x: -len(x[1]))],
            "statements": [{"id": s.id, "quote": s.quote, "said_at": s.said_at.isoformat() if s.said_at else None,
                            "is_promise": s.is_promise, "item_id": i.id, "item_title": i.title, "url": i.url} for s, i in sts],
            "promises": sum(s.is_promise for s, _ in sts),
            "contradictions": core.contradictions(db, e),
            "recent_items": [{"id": i.id, "title": i.title, "outlet": o.name, "captured_at": i.captured_at.isoformat()}
                             for _, i, o in sorted(ms, key=lambda x: x[1].captured_at, reverse=True)[:50]]}


class EntityEdit(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    merge_into: int | None = None  # الكيان نفسه بكتابة أخرى


@router.put("/entities/{eid}")
def edit_entity(eid: int, body: EntityEdit, actor: User = Depends(edit), db: Session = Depends(get_db)):
    e = db.get(Entity, eid) or _404()
    if body.merge_into:
        t = db.get(Entity, body.merge_into) or _404()
        for m in db.scalars(select(EntityMention).where(EntityMention.entity_id == eid)):
            if db.scalar(select(EntityMention.id).where(EntityMention.entity_id == t.id, EntityMention.item_id == m.item_id)):
                db.delete(m)
            else:
                m.entity_id = t.id
        for s in db.scalars(select(Statement).where(Statement.entity_id == eid)):
            s.entity_id = t.id
        t.aliases = sorted(set(t.aliases or []) | {e.name, *(e.aliases or [])})
        db.flush()
        db.delete(e)
        record(db, actor, "entity.merge", "entity", str(eid), None, {"into": t.id})
        db.commit()
        return {"id": t.id}
    if body.name:
        e.name = body.name
    if body.aliases is not None:
        e.aliases = body.aliases
    record(db, actor, "entity.update", "entity", str(eid), None, body.model_dump(exclude_none=True))
    db.commit()
    return {"id": e.id}
