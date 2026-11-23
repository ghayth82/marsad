"""غرفة التحقيق (الشاشة 10) وبناء القصة (الشاشة 11)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marsad.api.deps import current_user, require
from marsad.audit import record
from marsad.cases import core
from marsad.db import get_db, utcnow
from marsad.models import User
from marsad.models.cases import Case, CaseDocument, CaseMember, CaseRecord, CustodyLog, Draft, SanctionEntry
from marsad.rbac.service import effective_permissions

router = APIRouter(prefix="/api", tags=["cases"])
creator = require("cases.create")


def _err(e: core.CaseError):
    raise HTTPException(e.status, str(e)) from None


def _case(db: Session, cid: int, user: User, need: str = "view") -> Case:
    if not ({"cases.create", "stories.write", "stories.approve"} & effective_permissions(user)):
        raise HTTPException(403, "لا تملك صلاحية لهذه الصفحة. اطلبها من المدير.")
    try:
        return core.require_access(db, db.get(Case, cid), user, need)
    except core.CaseError as e:
        _err(e)


def _docs(db: Session, c: Case) -> list[CaseDocument]:
    return list(db.scalars(select(CaseDocument).where(CaseDocument.case_id == c.id).order_by(CaseDocument.number)))


def _doc(db: Session, c: Case, number: int) -> CaseDocument:
    d = db.scalars(select(CaseDocument).where(CaseDocument.case_id == c.id, CaseDocument.number == number)).first()
    if d is None:
        raise HTTPException(404, "الوثيقة غير موجودة")
    return d


# ---------- القضايا ----------

class CaseIn(BaseModel):
    title: str
    summary: str = ""


@router.get("/cases")
def list_cases(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not ({"cases.create", "stories.write", "stories.approve"} & effective_permissions(user)):
        raise HTTPException(403, "لا تملك صلاحية لهذه الصفحة. اطلبها من المدير.")
    out = []
    for c, access in core.user_cases(db, user):
        n = db.scalar(select(func.count()).select_from(CaseDocument).where(CaseDocument.case_id == c.id))
        out.append({"id": c.id, "title": c.title, "status": c.status, "access": access, "documents": n,
                    "updated_at": c.updated_at.isoformat(), "private": db.scalar(select(func.count()).select_from(CaseMember).where(CaseMember.case_id == c.id)) == 1})
    return out


@router.post("/cases")
def create(body: CaseIn, user: User = Depends(creator), db: Session = Depends(get_db)):
    try:
        c = core.create_case(db, user, body.title, body.summary)
    except core.CaseError as e:
        _err(e)
    record(db, user, "cases.create", "case", c.id)
    db.commit()
    return {"id": c.id, "title": c.title}


@router.get("/cases/{cid}")
def overview(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user)
    members = db.execute(select(CaseMember, User).join(User, User.id == CaseMember.user_id).where(CaseMember.case_id == c.id)).all()
    counts = dict(db.execute(select(CaseRecord.kind, func.count()).where(CaseRecord.case_id == c.id).group_by(CaseRecord.kind)).all())
    return {"id": c.id, "title": c.title, "status": c.status, "summary": core.dec(c, c.summary_enc, ""),
            "access": core.member(db, c, user).access, "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
            "members": [{"user_id": u.id, "email": u.email, "name": u.full_name, "access": m.access} for m, u in members],
            "documents": [core.doc_view(c, d) for d in _docs(db, c)], "counts": counts,
            "open_tasks": db.scalar(select(func.count()).select_from(CaseRecord).where(CaseRecord.case_id == c.id, CaseRecord.kind == "task",
                                                                                        CaseRecord.status != "done")),
            "custody": core.verify_custody(db, c),
            "drafts": [{"id": d.id, "title": d.title, "status": d.status, "updated_at": d.updated_at.isoformat()}
                       for d in db.scalars(select(Draft).where(Draft.case_id == c.id).order_by(Draft.updated_at.desc()))]}


class CasePatch(BaseModel):
    title: str | None = None
    summary: str | None = None
    status: str | None = None


@router.patch("/cases/{cid}")
def patch(cid: int, body: CasePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user, "edit")
    if body.title is not None and body.title.strip():
        c.title = body.title.strip()[:300]
    if body.summary is not None:
        c.summary_enc = core.enc(c, body.summary.strip())
    if body.status in ("open", "closed"):
        c.status = body.status
    core.touch(c)
    core.custody(db, c, user, "edit", detail="تعديل بيانات القضية")
    db.commit()
    return {"ok": True}


class MemberIn(BaseModel):
    email: str
    access: str | None = "edit"


@router.post("/cases/{cid}/members")
def set_member(cid: int, body: MemberIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user, "owner")
    target = db.scalars(select(User).where(func.lower(User.email) == body.email.strip().lower())).first()
    if target is None:
        raise HTTPException(404, "لا مستخدم بهذا البريد")
    try:
        core.set_member(db, c, user, target, body.access)
    except core.CaseError as e:
        _err(e)
    record(db, user, "cases.member", "case", c.id, after={"user": target.email, "access": body.access})
    db.commit()
    return {"ok": True}


# ---------- الوثائق ----------

def _process(cid: int, doc_ids: list[int]) -> None:
    from marsad.db import get_db as _g

    db = next(_g())
    try:
        c = db.get(Case, cid)
        for did in doc_ids:
            d = db.get(CaseDocument, did)
            if d and d.status == "processing":
                core.process_document(db, c, d)
                db.commit()
    finally:
        db.close()


@router.post("/cases/{cid}/documents")
async def upload(cid: int, bg: BackgroundTasks, files: list[UploadFile] = File(...), user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    c = _case(db, cid, user, "edit")
    made, errors = [], []
    for f in files[:50]:
        raw = await f.read(core.MAX_DOC + 1)
        try:
            d = core.add_document(db, c, user, raw, f.filename or "")
            made.append(d)
        except core.CaseError as e:
            errors.append({"file": f.filename, "error": str(e)})
    db.commit()
    if made:
        bg.add_task(_process, c.id, [d.id for d in made])
    return {"added": [{"number": d.number, "status": d.status} for d in made], "errors": errors}


@router.get("/cases/{cid}/documents/{num}")
def document(cid: int, num: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user)
    d = _doc(db, c, num)
    core.custody(db, c, user, "open", d, detail=f"فتح وثيقة {d.number}")
    db.commit()
    return core.doc_view(c, d, text=True)


@router.get("/cases/{cid}/documents/{num}/file")
def document_file(cid: int, num: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user)
    d = _doc(db, c, num)
    try:
        raw = core.read_document(c, d)
    except core.CaseError as e:
        _err(e)
    core.custody(db, c, user, "download", d, detail=f"تنزيل وثيقة {d.number}")
    db.commit()
    name = core.dec(c, d.filename_enc, f"doc-{d.number}")
    from urllib.parse import quote

    return Response(raw, media_type="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "X-Content-Type-Options": "nosniff"})


@router.post("/cases/{cid}/documents/{num}/reprocess")
def reprocess(cid: int, num: int, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user, "edit")
    d = _doc(db, c, num)
    d.status, d.error = "processing", ""
    db.commit()
    bg.add_task(_process, c.id, [d.id])
    return {"ok": True}


# ---------- السجلات ----------

KINDS = ("note", "task", "event", "link", "money")
FIELDS = {"note": ("text",), "task": ("title", "detail"), "event": ("title", "detail", "page"),
          "link": ("a", "a_kind", "b", "b_kind", "relation", "sources"), "money": ("from", "to", "currency", "purpose", "page")}


class RecordIn(BaseModel):
    kind: str
    status: str | None = None
    date: str | None = None
    amount: float | None = None
    doc: int | None = None
    assignee_id: int | None = None
    data: dict = {}


def _date(s: str | None):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        raise HTTPException(422, "صيغة التاريخ غير صحيحة") from None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _body(kind: str, data: dict) -> dict:
    from marsad.text import normalize_ar

    b = {k: data[k] for k in FIELDS[kind] if k in data}
    if kind == "link":
        if not str(b.get("a", "")).strip() or not str(b.get("b", "")).strip():
            raise HTTPException(422, "اكتب الطرفين")
        b["a_norm"], b["b_norm"] = sorted([normalize_ar(b["a"]), normalize_ar(b["b"])])
        if b["a_norm"] != normalize_ar(b["a"]):
            b["a"], b["b"], b["a_kind"], b["b_kind"] = b["b"], b["a"], b.get("b_kind", ""), b.get("a_kind", "")
        b.setdefault("sources", [])
    return b


@router.get("/cases/{cid}/records")
def records(cid: int, kind: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user)
    docs = {d.id: d.number for d in _docs(db, c)}
    stmt = select(CaseRecord).where(CaseRecord.case_id == c.id).order_by(CaseRecord.at_date.is_(None), CaseRecord.at_date, CaseRecord.id)
    if kind:
        stmt = stmt.where(CaseRecord.kind == kind)
    return [core.record_view(c, r, docs) for r in db.scalars(stmt)]


@router.post("/cases/{cid}/records")
def add_record(cid: int, body: RecordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user, "edit")
    if body.kind not in KINDS:
        raise HTTPException(422, "نوع غير معروف")
    doc_id = _doc(db, c, body.doc).id if body.doc else None
    status = body.status or {"task": "open", "note": ""}.get(body.kind, "confirmed")
    r = CaseRecord(case_id=c.id, kind=body.kind, status=status, at_date=_date(body.date), amount=body.amount, doc_id=doc_id,
                   body_enc=core.enc(c, _body(body.kind, body.data)), author_id=user.id, assignee_id=body.assignee_id)
    db.add(r)
    core.touch(c)
    db.flush()
    core.custody(db, c, user, "record", detail=f"إضافة {body.kind} #{r.id}")
    db.commit()
    return core.record_view(c, r, {d.id: d.number for d in _docs(db, c)})


@router.patch("/cases/{cid}/records/{rid}")
def update_record(cid: int, rid: int, body: RecordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user, "edit")
    r = db.get(CaseRecord, rid)
    if r is None or r.case_id != c.id:
        raise HTTPException(404, "غير موجود")
    if body.status is not None:
        r.status = body.status
    if body.date is not None:
        r.at_date = _date(body.date)
    if body.amount is not None:
        r.amount = body.amount
    if body.data:
        cur = core.dec(c, r.body_enc, {}) or {}
        r.body_enc = core.enc(c, {**cur, **_body(r.kind, {**cur, **body.data})})
    if body.assignee_id is not None:
        r.assignee_id = body.assignee_id or None
    r.updated_at = utcnow()
    core.touch(c)
    core.custody(db, c, user, "record", detail=f"تعديل {r.kind} #{r.id}" + (f" → {r.status}" if body.status else ""))
    db.commit()
    return core.record_view(c, r, {d.id: d.number for d in _docs(db, c)})


@router.get("/cases/{cid}/graph")
def graph(cid: int, suggested: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user)
    docs = {d.id: d.number for d in _docs(db, c)}
    links = [core.record_view(c, r, docs) for r in db.scalars(select(CaseRecord).where(CaseRecord.case_id == c.id, CaseRecord.kind == "link"))]
    return core.graph(c, links, suggested)


@router.get("/cases/{cid}/entities")
def entities(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """الكيانات في كل وثائق القضية، مع الوثائق والصفحات التي ذُكرت فيها."""
    c = _case(db, cid, user)
    agg: dict[str, dict] = {}
    for d in _docs(db, c):
        for e in (core.dec(c, d.meta_enc, {}) or {}).get("entities", []):
            x = agg.setdefault(e["norm"], {"name": e["name"], "kind": e["kind"], "count": 0, "docs": []})
            x["count"] += e["count"]
            x["docs"].append({"doc": d.number, "pages": e["pages"]})
    return sorted(agg.values(), key=lambda x: -x["count"])


@router.get("/cases/{cid}/money")
def money(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user)
    docs = {d.id: d.number for d in _docs(db, c)}
    rows = [core.record_view(c, r, docs) for r in db.scalars(select(CaseRecord).where(CaseRecord.case_id == c.id, CaseRecord.kind == "money")
                                                             .order_by(CaseRecord.at_date))]
    flows: dict[tuple, dict] = defaultdict(lambda: {"total": 0.0, "count": 0, "docs": set()})
    for r in rows:
        if r["status"] != "confirmed" or r["amount"] is None:
            continue
        f = flows[(r.get("from", ""), r.get("to", ""), r.get("currency", ""))]
        f["total"] += r["amount"]
        f["count"] += 1
        if r["doc"]:
            f["docs"].add(r["doc"])
    return {"rows": rows, "flows": [{"from": k[0], "to": k[1], "currency": k[2], "total": v["total"], "count": v["count"], "docs": sorted(v["docs"])}
                                    for k, v in sorted(flows.items(), key=lambda kv: -kv[1]["total"])]}


@router.get("/cases/{cid}/sanctions")
def sanctions(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user)
    names = {e["name"] for e in entities(cid, user, db) if e["kind"] in ("person", "org")}
    for r in db.scalars(select(CaseRecord).where(CaseRecord.case_id == c.id, CaseRecord.kind == "link", CaseRecord.status == "confirmed")):
        b = core.dec(c, r.body_enc, {}) or {}
        names |= {b.get("a", ""), b.get("b", "")}
    lists = db.execute(select(SanctionEntry.list_name, func.count()).group_by(SanctionEntry.list_name)).all()
    return {"lists": [{"name": n, "entries": k} for n, k in lists], "checked": len(names),
            "matches": core.match_sanctions(db, sorted(n for n in names if n)),
            "note": "تطابق الأسماء مؤشر لا دليل: تحقق من تاريخ الميلاد والجنسية والصفة قبل أي استنتاج."}


@router.post("/sanctions/import")
async def import_sanctions(list_name: str = Form(...), file: UploadFile = File(...), user: User = Depends(require("system.manage")),
                           db: Session = Depends(get_db)):
    try:
        n = core.import_sanctions(db, list_name.strip() or "قائمة", await file.read())
    except core.CaseError as e:
        _err(e)
    record(db, user, "sanctions.import", "sanctions", list_name, after={"entries": n})
    db.commit()
    return {"list": list_name, "entries": n}


@router.get("/cases/{cid}/custody")
def custody(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _case(db, cid, user)
    users = {u.id: u.full_name or u.email for u in db.scalars(select(User))}
    rows = db.scalars(select(CustodyLog).where(CustodyLog.case_id == c.id).order_by(CustodyLog.id.desc()).limit(500))
    return {"verify": core.verify_custody(db, c),
            "rows": [{"at": e.at.isoformat(), "user": users.get(e.user_id, "النظام"), "action": e.action, "detail": e.detail,
                      "sha256": e.sha256, "entry_hash": e.entry_hash} for e in rows]}


# ---------- بناء القصة ----------

def _draft(db: Session, did: int, user: User, need: str = "view") -> tuple[Case, Draft]:
    d = db.get(Draft, did)
    if d is None:
        raise HTTPException(404, "المسودة غير موجودة")
    return _case(db, d.case_id, user, need), d


def draft_view(db: Session, c: Case, d: Draft) -> dict:
    content = core.dec(c, d.body_enc, {}) or {}
    check = core.draft_check(db, c, content.get("body", ""))
    checklist = {k: bool(d.checklist.get(k)) for k, *_ in core.CHECKLIST}
    checklist["sourced"] = check["all_sourced"]
    checklist["editor"] = d.status == "approved"
    docs = {x.number: x for x in _docs(db, c)}
    return {"id": d.id, "case_id": c.id, "case_title": c.title, "title": d.title, "status": d.status, "version": d.version,
            "author_id": d.author_id, "approved_by": d.approved_by, "updated_at": d.updated_at.isoformat(), **content,
            "check": check, "checklist": [{"key": k, "label": label, "mode": mode, "done": checklist[k]} for k, label, mode in core.CHECKLIST],
            "ready": all(checklist.values()),
            "sources": [{"doc": n, "filename": core.dec(c, docs[n].filename_enc, ""), "sha256": docs[n].sha256, "method": docs[n].method}
                        for n in check["cited_docs"] if n in docs]}


class DraftIn(BaseModel):
    title: str = ""
    angle: str = ""
    body: str = ""
    questions: list[str] = []
    version: int | None = None


@router.post("/cases/{cid}/drafts")
def new_draft(cid: int, body: DraftIn, user: User = Depends(require("stories.write")), db: Session = Depends(get_db)):
    c = _case(db, cid, user, "edit")
    sk = core.skeleton(db, c)
    content = {"angle": body.angle, "body": body.body or sk["suggested_body"], "questions": body.questions or sk["questions"]}
    d = Draft(case_id=c.id, title=body.title or c.title, body_enc=core.enc(c, content), author_id=user.id, checklist={})
    db.add(d)
    db.flush()
    core.custody(db, c, user, "draft", detail=f"مسودة #{d.id}")
    db.commit()
    return draft_view(db, c, d)


@router.get("/cases/{cid}/skeleton")
def skeleton(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return core.skeleton(db, _case(db, cid, user))


@router.get("/drafts/{did}")
def get_draft(did: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c, d = _draft(db, did, user)
    return draft_view(db, c, d)


@router.put("/drafts/{did}")
def save_draft(did: int, body: DraftIn, user: User = Depends(require("stories.write")), db: Session = Depends(get_db)):
    """الحفظ بإصدار: إن عدّل زميل المسودة بعد أن فتحتها يُرفض الحفظ بدل أن يمحو تعديله."""
    c, d = _draft(db, did, user, "edit")
    if body.version is not None and body.version != d.version:
        raise HTTPException(409, "عدّل زميل المسودة بعد أن فتحتها. حمّل النسخة الأحدث وانقل تعديلك إليها؛ لم يُحذف شيء.")
    d.title = body.title or d.title
    d.body_enc = core.enc(c, {"angle": body.angle, "body": body.body, "questions": body.questions})
    d.version += 1
    if d.status == "approved":
        d.status, d.approved_by = "draft", None  # أي تعديل بعد الاعتماد يعيدها للمراجعة
    d.updated_at = utcnow()
    db.commit()
    return draft_view(db, c, d)


class CheckIn(BaseModel):
    key: str
    done: bool


@router.post("/drafts/{did}/checklist")
def tick(did: int, body: CheckIn, user: User = Depends(require("stories.write")), db: Session = Depends(get_db)):
    c, d = _draft(db, did, user, "edit")
    modes = {k: mode for k, _, mode in core.CHECKLIST}
    if modes.get(body.key) != "manual":
        raise HTTPException(422, "هذا البند يُحسب تلقائيًا")
    d.checklist = {**d.checklist, body.key: body.done, f"{body.key}_by": user.id}
    core.custody(db, c, user, "checklist", detail=f"{body.key}: {'نعم' if body.done else 'لا'}")
    db.commit()
    return draft_view(db, c, d)


@router.post("/drafts/{did}/approve")
def approve(did: int, user: User = Depends(require("stories.approve")), db: Session = Depends(get_db)):
    c, d = _draft(db, did, user)
    from marsad.rbac.service import PermissionError_, check_can_approve

    try:
        check_can_approve(db, user, d.author_id, "stories.approve")
    except PermissionError_ as e:
        raise HTTPException(403, str(e)) from None
    v = draft_view(db, c, d)
    pending = [x["label"] for x in v["checklist"] if not x["done"] and x["key"] != "editor"]
    if pending:
        raise HTTPException(422, "قبل الاعتماد: " + "، ".join(pending))
    d.status, d.approved_by = "approved", user.id
    core.custody(db, c, user, "approve", detail=f"اعتماد المسودة #{d.id} (الإصدار {d.version})")
    record(db, user, "stories.approve", "draft", d.id)
    db.commit()
    return draft_view(db, c, d)


@router.get("/drafts/{did}/export.docx")
def export(did: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c, d = _draft(db, did, user)
    data = core.export_docx(db, c, d, user)
    core.custody(db, c, user, "export", detail=f"تصدير Word للمسودة #{d.id}")
    db.commit()
    from urllib.parse import quote

    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote((d.title or 'مسودة') + '.docx')}"})


@router.get("/drafts")
def my_drafts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """مسودات القضايا التي أنا عضو فيها."""
    out = []
    for c, _access in core.user_cases(db, user):
        for d in db.scalars(select(Draft).where(Draft.case_id == c.id).order_by(Draft.updated_at.desc())):
            out.append({"id": d.id, "title": d.title, "status": d.status, "case_id": c.id, "case_title": c.title,
                        "updated_at": d.updated_at.isoformat()})
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)
