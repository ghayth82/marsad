"""متتبّع التصريحات والوعود: لكل كيان وعوده بنصها وتاريخها ومصدرها وموعدها، وتذكير حين يحين الموعد."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.audit import record
from marsad.db import utcnow
from marsad.models import User
from marsad.models.analysis import Entity, Statement
from marsad.models.engines import Notification
from marsad.models.monitoring import Item
from marsad.models.tools import Promise

STATUSES = {"tracking": "قيد المتابعة", "kept": "تحقق", "partial": "تحقق جزئيًا", "broken": "لم يتحقق"}


class PromiseError(ValueError):
    pass


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    from zoneinfo import ZoneInfo

    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=ZoneInfo("Asia/Amman"))


def create(db: Session, user: User, entity: Entity, text: str, due_at: str | None = None, said_at: str | None = None,
           source_url: str = "", statement: Statement | None = None) -> Promise:
    if statement is not None:
        text = text or statement.quote
        said = statement.said_at
        it = db.get(Item, statement.item_id)
        source_url = source_url or (it.url if it else "")
    else:
        said = _dt(said_at)
    text = " ".join((text or "").split())
    if len(text) < 5:
        raise PromiseError("نص الوعد قصير جدًا")
    p = Promise(entity_id=entity.id, statement_id=statement.id if statement else None, text=text, said_at=said,
                source_url=source_url[:1000], due_at=_dt(due_at), created_by=user.id,
                history=[{"at": utcnow().isoformat(), "by": user.id, "status": "tracking", "note": "بدء المتابعة"}])
    db.add(p)
    db.flush()
    record(db, user, "promise.create", "promise", str(p.id), None, {"text": text, "entity_id": entity.id})
    return p


def update(db: Session, user: User, p: Promise, status: str | None = None, evidence_url: str | None = None,
           evidence_note: str | None = None, due_at: str | None = None) -> Promise:
    before = {"status": p.status, "due_at": p.due_at.isoformat() if p.due_at else None}
    if status is not None:
        if status not in STATUSES:
            raise PromiseError("الحالة غير معروفة")
        if status != "tracking" and not ((evidence_url or p.evidence_url) or (evidence_note or p.evidence_note)):
            raise PromiseError("تغيير الحالة يحتاج دليلًا: رابطًا أو ملاحظة")
        p.status = status
    if evidence_url is not None:
        p.evidence_url = evidence_url[:1000]
    if evidence_note is not None:
        p.evidence_note = evidence_note
    if due_at is not None:
        p.due_at = _dt(due_at)
        p.reminded_at = None
    p.history = [*(p.history or []), {"at": utcnow().isoformat(), "by": user.id, "status": p.status,
                                      "note": evidence_note or "", "url": evidence_url or ""}]
    record(db, user, "promise.update", "promise", str(p.id), before, {"status": p.status})
    return p


def due_reminders(db: Session, now: datetime | None = None) -> int:
    """تنبيه واحد لكل وعد حان موعده وما زال قيد المتابعة."""
    now = now or utcnow()
    n = 0
    for p in db.scalars(select(Promise).where(Promise.status == "tracking", Promise.due_at.is_not(None),
                                              Promise.due_at <= now, Promise.reminded_at.is_(None))).all():
        e = db.get(Entity, p.entity_id)
        db.add(Notification(kind="promise.due", text=f"⏰ حان موعد وعد {e.name if e else ''}: «{p.text[:160]}»\n/promises?id={p.id}"))
        p.reminded_at = now
        n += 1
    return n


def view(db: Session, p: Promise) -> dict:
    e = db.get(Entity, p.entity_id)
    return {"id": p.id, "entity_id": p.entity_id, "entity": e.name if e else "", "text": p.text, "statement_id": p.statement_id,
            "said_at": p.said_at.isoformat() if p.said_at else None, "source_url": p.source_url,
            "due_at": p.due_at.isoformat() if p.due_at else None, "status": p.status, "status_ar": STATUSES[p.status],
            "evidence_url": p.evidence_url, "evidence_note": p.evidence_note, "history": p.history,
            "overdue": bool(p.due_at and p.status == "tracking" and p.due_at <= utcnow())}
