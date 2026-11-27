"""الشائعات (الشاشة 5) وبطاقة الادّعاء (الشاشة 6)."""

from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.api.deps import current_user, require
from marsad.audit import record
from marsad.claims import core
from marsad.db import get_db, utcnow
from marsad.engines import service as engines
from marsad.models import User
from marsad.models.claims import Claim, ClaimItem, Evidence
from marsad.models.engines import Notification
from marsad.models.monitoring import Item, Outlet
from marsad.rbac.service import PermissionError_, effective_permissions, get_setting
from marsad.text import normalize_ar

router = APIRouter(prefix="/api", tags=["claims"])
create = require("claims.create")
export = require("data.export")


def viewer(user: User = Depends(current_user)) -> User:
    if not ({"monitor.view", "claims.create", "verdicts.approve"} & effective_permissions(user)):
        raise HTTPException(403, "لا تملك صلاحية لهذه الصفحة. اطلبها من المدير.")
    return user


def _404():
    raise HTTPException(404, "غير موجود")


def _v(v):
    return None if v is None else {"id": v.id, "label": v.label, "evidence_grade": v.evidence_grade, "explanation": v.explanation,
                                   "status": v.status, "author_id": v.author_id, "approved_by": v.approved_by,
                                   "approved_at": v.approved_at.isoformat() if v.approved_at else None,
                                   "created_at": v.created_at.isoformat(), "engine_batch_id": v.engine_batch_id}


def claim_row(c: Claim) -> dict:
    v = core.current_verdict(c)
    return {"id": c.id, "text": c.text, "status": c.status, "origin": c.origin, "speaker": c.speaker,
            "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else None, "appearances": len(c.appearances),
            "returns": sum(a.kind == "return" for a in c.appearances), "verdict": _v(v), "tags": c.tags,
            "assignee_id": c.assignee_id, "priority": c.priority, "due_at": c.due_at.isoformat() if c.due_at else None,
            "has_approved": core.current_verdict(c, approved_only=True) is not None}


@router.get("/claims")
def claims(q: str = "", status: str | None = None, limit: int = 50, _: User = Depends(viewer), db: Session = Depends(get_db)):
    stmt = select(Claim).order_by(Claim.created_at.desc())
    if status:
        stmt = stmt.where(Claim.status == status)
    if q:
        for t in normalize_ar(q).split():
            stmt = stmt.where(Claim.norm.contains(t))
    return [claim_row(c) for c in db.scalars(stmt.limit(min(limit, 300)))]


class ClaimIn(BaseModel):
    text: str = Field(min_length=10)
    item_id: int | None = None
    speaker: str = ""
    tags: list[str] = []


@router.post("/claims")
def create_claim(body: ClaimIn, user: User = Depends(create), db: Session = Depends(get_db)):
    item = db.get(Item, body.item_id) if body.item_id else None
    try:
        c = core.create_claim(db, user, body.text, item, body.speaker, "manual", body.tags)
    except core.ClaimError as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return claim_row(c)


@router.get("/claims/{cid}")
def claim(cid: int, request: Request, _: User = Depends(viewer), db: Session = Depends(get_db)):
    c = db.get(Claim, cid) or _404()
    first = db.get(Item, c.first_item_id) if c.first_item_id else None
    official = db.get(Item, c.official_item_id) if c.official_item_id else None
    sugg = [db.get(Item, i) for i in (c.meta or {}).get("suggestions", [])]
    return {**claim_row(c),
            "first_item": None if not first else {"id": first.id, "title": first.title, "url": first.url,
                                                  "outlet": db.get(Outlet, first.outlet_id).name},
            "official_item": None if not official else {"id": official.id, "title": official.title, "url": official.url},
            "official_suggestions": core.official_suggestions(db, c),
            "similar_suggestions": [{"id": i.id, "title": i.title} for i in sugg if i][:10],
            "spread": core.spread_tree(db, c),
            "evidence": [{"id": e.id, "kind": e.kind, "title": e.title, "url": e.url, "item_id": e.item_id, "sha256": e.sha256,
                          "grade": e.grade, "note": e.note, "is_conclusive": e.is_conclusive, "data": e.data,
                          "added_by": e.added_by, "added_at": e.added_at.isoformat()} for e in c.evidence],
            "history": [_v(v) for v in c.verdicts],
            "factcheck": (c.meta or {}).get("factcheck"), "tip": (c.meta or {}).get("tip"),
            "transcript": (c.meta or {}).get("transcript"),
            "claimreview": core.claimreview(db, c, str(request.base_url), _org(db))}


def _org(db: Session) -> str:
    return get_setting(db, "org.name", "مرصد التحقق") or "مرصد التحقق"


class ClaimEdit(BaseModel):
    status: str | None = None
    speaker: str | None = None
    tags: list[str] | None = None
    official_item_id: int | None = None
    text: str | None = None
    base: dict | None = None  # القيم كما رآها المحرِّر قبل تعديله؛ إن غيّرها زميل في الأثناء يُرفض الحفظ ولا يُمحى تعديله


@router.put("/claims/{cid}")
def edit_claim(cid: int, body: ClaimEdit, user: User = Depends(create), db: Session = Depends(get_db)):
    c = db.get(Claim, cid) or _404()
    ch = body.model_dump(exclude_none=True)
    base = ch.pop("base", None) or {}
    stale = {k: getattr(c, k) for k in ch if k in base and base[k] != getattr(c, k)}
    if stale:
        return JSONResponse({"detail": "عدّل زميل هذا الحقل بعد أن فتحت البطاقة. راجع القيمة الحالية ثم أعد تعديلك؛ لم يُحذف شيء.",
                             "current": stale}, status_code=409)
    if "status" in ch and ch["status"] not in ("new", "investigating", "archived"):
        raise HTTPException(422, "الحالة تتغير إلى «حكم» فقط بالاعتماد")
    before = {k: getattr(c, k) for k in ch}
    for k, v in ch.items():
        setattr(c, k, v)
    if "text" in ch:
        c.norm = normalize_ar(c.text)
        c.meta = {k: v for k, v in (c.meta or {}).items() if k != "sig"}
    record(db, user, "claim.update", "claim", str(cid), before, ch)
    db.commit()
    return claim_row(c)


class EvidenceIn(BaseModel):
    kind: str  # link | item | check | official
    title: str = ""
    url: str = ""
    item_id: int | None = None
    grade: str = ""
    note: str = ""
    is_conclusive: bool = False
    data: dict = {}


@router.post("/claims/{cid}/evidence")
def add_evidence(cid: int, body: EvidenceIn, user: User = Depends(create), db: Session = Depends(get_db)):
    c = db.get(Claim, cid) or _404()
    if body.kind not in ("link", "item", "check", "official", "file"):
        raise HTTPException(422, "نوع دليل غير معروف")
    if body.is_conclusive and body.kind not in ("check", "file", "item"):
        raise HTTPException(422, "الدليل القاطع يكون نتيجة فحص أو ملفًا أو مادة مؤرشفة")
    e = Evidence(claim_id=c.id, added_by=user.id, **body.model_dump())
    if body.item_id:
        it = db.get(Item, body.item_id) or _404()
        e.title = e.title or it.title
        e.url = e.url or it.url
        e.sha256 = it.versions[-1].archive_sha256 if it.versions else ""
    db.add(e)
    if c.status == "new":
        c.status = "investigating"
    db.flush()
    record(db, user, "evidence.add", "claim", str(cid), None, {"evidence_id": e.id, "kind": e.kind, "grade": e.grade})
    db.commit()
    return {"id": e.id}


class VerdictIn(BaseModel):
    label: str
    evidence_grade: str
    explanation: str
    engine_batch_id: int | None = None
    correction_reason: str = ""


@router.post("/claims/{cid}/verdict")
def propose(cid: int, body: VerdictIn, user: User = Depends(create), db: Session = Depends(get_db)):
    c = db.get(Claim, cid) or _404()
    try:
        core.propose_verdict(db, user, c, body.label, body.evidence_grade, body.explanation, body.engine_batch_id,
                            body.correction_reason)
    except (core.ClaimError, PermissionError_) as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return claim_row(c)


class ApproveIn(BaseModel):
    approve: bool = True
    note: str = ""


@router.post("/claims/{cid}/approve")
def approve(cid: int, body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Claim, cid) or _404()
    try:
        core.approve_verdict(db, user, c, body.approve, body.note)
    except core.ClaimError as e:
        raise HTTPException(422, str(e)) from None
    except PermissionError_ as e:
        raise HTTPException(403, str(e)) from None
    db.commit()
    return claim_row(c)


class EngineAsk(BaseModel):
    mode: str | None = None
    engine_ids: list[int] | None = None
    merge_engine_id: int | None = None


@router.post("/claims/{cid}/engines")
def ask_engines(cid: int, body: EngineAsk, bg: BackgroundTasks, user: User = Depends(require("engines.use", "claims.create")),
                db: Session = Depends(get_db)):
    """يرسل الادّعاء وأدلته إلى بوابة المحركات (اقتراح حكم)، والقرار يبقى للصحفي."""
    c = db.get(Claim, cid) or _404()
    first = db.get(Item, c.first_item_id) if c.first_item_id else None
    notes = "\n".join(f"- دليل ({e.kind}، {e.grade or 'دون درجة'}): {e.title} {e.note}".strip() for e in c.evidence)
    data = {"claim": c.text, "text": "\n\n".join(x for x in [first.text[:6000] if first else "", notes] if x)}
    try:
        b = engines.create_batch(db, user, "classify_verdict", data, body.mode, body.engine_ids, body.merge_engine_id)
    except engines.EngineError as e:
        raise HTTPException(422, str(e)) from None
    c.meta = {**(c.meta or {}), "engine_batches": [*(c.meta or {}).get("engine_batches", []), b.id]}
    db.commit()
    bg.add_task(engines.execute_batch, b.id)
    return {"batch_id": b.id}


# ---------- الرادار والتنبيهات والإحصاءات ----------

@router.get("/rumors/radar")
def radar(hours: int = 3, _: User = Depends(viewer), db: Session = Depends(get_db)):
    rows = core.radar(db, hours=hours)
    titles = {i.id: i.title for i in db.scalars(select(Item).where(Item.id.in_({x for r in rows for x in r["items"]})))}
    return [{**r, "samples": [titles.get(i, "") for i in r["items"][:3]]} for r in rows]


@router.get("/rumors/alerts")
def alerts(_: User = Depends(viewer), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.kind == "rumor.return").order_by(Notification.id.desc()).limit(50))
    return [{"id": n.id, "text": n.text, "created_at": n.created_at.isoformat(), "read": n.read_at is not None} for n in rows]


@router.get("/rumors/stats")
def stats(days: int = 30, _: User = Depends(viewer), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    cs = list(db.scalars(select(Claim).where(Claim.created_at >= since)))
    labels = Counter(v.label for c in cs if (v := core.current_verdict(c, approved_only=True)))
    return {"days": days, "claims": len(cs), "by_status": dict(Counter(c.status for c in cs)), "by_label": dict(labels),
            "returns": sum(sum(a.kind == "return" for a in c.appearances) for c in cs),
            "auto": sum(c.origin == "auto" for c in cs)}


# ---------- التصدير ----------

@router.get("/claims/export/claimreview")
def export_claimreview(request: Request, _: User = Depends(export), db: Session = Depends(get_db)):
    out = [x for c in db.scalars(select(Claim)) if (x := core.claimreview(db, c, str(request.base_url), _org(db)))]
    import json

    from marsad.core import naming

    body = json.dumps(out, ensure_ascii=False, indent=1)
    return Response(body, media_type="application/json",
                    headers=naming.export("claims", f"تصدير - ClaimReview - {naming.today()}.json", body))


@router.get("/claims/export/csv")
def export_csv(_: User = Depends(export), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "claim", "speaker", "first_seen", "appearances", "returns", "status", "verdict", "evidence_grade",
                "explanation", "approved_at"])
    for c in db.scalars(select(Claim).order_by(Claim.id)):
        v = core.current_verdict(c, approved_only=True)
        w.writerow([c.id, c.text, c.speaker, c.first_seen_at.isoformat() if c.first_seen_at else "", len(c.appearances),
                    sum(a.kind == "return" for a in c.appearances), c.status, v.label if v else "", v.evidence_grade if v else "",
                    v.explanation if v else "", v.approved_at.isoformat() if v and v.approved_at else ""])
    from marsad.core import naming

    body = "﻿" + buf.getvalue()
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers=naming.export("claims", f"تصدير - الادعاءات - {naming.today()}.csv", body))
