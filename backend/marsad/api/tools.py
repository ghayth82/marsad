"""البند 13: أدوات الصحفيين — التحقق السابق، البلاغات، الأرقام الرسمية، الوعود، التفريغ، الأرشفة، بطاقة النشر."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.api.deps import current_user, require
from marsad.audit import record
from marsad.core.paths import data_file, ensure_storage
from marsad.db import get_db
from marsad.models import User
from marsad.models.analysis import Entity, Statement
from marsad.models.claims import Claim
from marsad.models.labs import MediaFile
from marsad.models.tools import OfficialFigure, Promise, Snapshot, Tip
from marsad.rbac.service import effective_permissions, get_setting
from marsad.tools import factcheck, figures, promises, snapshots, tips, transcripts

router = APIRouter(prefix="/api", tags=["tools"])


def any_of(*permissions: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not set(permissions) & effective_permissions(user):
            raise HTTPException(403, "لا تملك صلاحية لهذه الصفحة. اطلبها من المدير.")
        return user

    return dep


CLAIM_WORK = any_of("claims.create", "verdicts.propose", "verdicts.approve")
READ = any_of("monitor.view", "claims.create", "verdicts.propose", "verdicts.approve")


def _claim(db: Session, cid: int) -> Claim:
    c = db.get(Claim, cid)
    if c is None:
        raise HTTPException(404, "غير موجود")
    return c


# ---------- «هل تحقق منها أحد قبلي؟» ----------

@router.get("/tools/factcheck")
def factcheck_info(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return factcheck.info(db)


class KeyIn(BaseModel):
    key: str | None = None


@router.put("/tools/factcheck/key")
def factcheck_key(body: KeyIn, user: User = Depends(require("system.manage")), db: Session = Depends(get_db)):
    try:
        r = factcheck.set_key(db, body.key, user)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return r


@router.post("/claims/{cid}/factcheck")
def claim_factcheck(cid: int, _: User = Depends(CLAIM_WORK), db: Session = Depends(get_db)):
    r = factcheck.search(db, _claim(db, cid))
    db.commit()
    return r


# ---------- البلاغات ----------

@router.get("/tips")
def list_tips(status: str = "new", _: User = Depends(require("claims.create")), db: Session = Depends(get_db)):
    q = select(Tip).order_by(Tip.received_at.desc()).limit(300)
    if status != "all":
        q = q.where(Tip.status == status)
    counts = {s: db.query(Tip).filter(Tip.status == s).count() for s in ("new", "claim", "answered", "rejected")}
    from marsad.reports import alerts

    return {"tips": [tips.view(t) for t in db.scalars(q).all()], "counts": counts, "bot": alerts.bot_info(db)}


@router.post("/tips/poll")
def poll_tips(_: User = Depends(require("claims.create")), db: Session = Depends(get_db)):
    r = tips.poll(db)
    db.commit()
    return r


def _tip(db: Session, tid: int) -> Tip:
    t = db.get(Tip, tid)
    if t is None:
        raise HTTPException(404, "غير موجود")
    return t


class TipClaimIn(BaseModel):
    text: str = ""
    reply: bool = True


@router.post("/tips/{tid}/claim")
def tip_to_claim(tid: int, body: TipClaimIn, user: User = Depends(require("claims.create")), db: Session = Depends(get_db)):
    from marsad.claims.core import ClaimError

    try:
        c = tips.to_claim(db, user, _tip(db, tid), body.text, body.reply)
    except (tips.TipError, ClaimError) as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return {"claim_id": c.id}


class TipRejectIn(BaseModel):
    note: str = ""
    reply_text: str = ""


@router.post("/tips/{tid}/reject")
def tip_reject(tid: int, body: TipRejectIn, user: User = Depends(require("claims.create")), db: Session = Depends(get_db)):
    try:
        t = tips.reject(db, user, _tip(db, tid), body.note, body.reply_text)
    except tips.TipError as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return tips.view(t)


# ---------- الأرقام الرسمية ----------

@router.get("/figures")
def list_figures(_: User = Depends(READ), db: Session = Depends(get_db)):
    rows = db.scalars(select(OfficialFigure).order_by(OfficialFigure.indicator, OfficialFigure.as_of.desc())).all()
    return {"figures": [figures.view(f) for f in rows]}


class FigureIn(BaseModel):
    indicator: str
    value: float | str
    unit: str = ""
    as_of: str
    agency: str = ""
    url: str = ""
    keywords: list[str] | str = []
    note: str = ""


@router.post("/figures")
def add_figure(body: FigureIn, user: User = Depends(require("figures.manage")), db: Session = Depends(get_db)):
    try:
        f = figures.save(db, user, body.model_dump())
    except figures.FigureError as e:
        raise HTTPException(422, str(e)) from None
    record(db, user, "figure.create", "figure", str(f.id), None, figures.view(f))
    db.commit()
    return figures.view(f)


@router.put("/figures/{fid}")
def edit_figure(fid: int, body: FigureIn, user: User = Depends(require("figures.manage")), db: Session = Depends(get_db)):
    f = db.get(OfficialFigure, fid)
    if f is None:
        raise HTTPException(404, "غير موجود")
    before = figures.view(f)
    try:
        figures.save(db, user, body.model_dump(), f)
    except figures.FigureError as e:
        raise HTTPException(422, str(e)) from None
    record(db, user, "figure.update", "figure", str(f.id), before, figures.view(f))
    db.commit()
    return figures.view(f)


@router.delete("/figures/{fid}")
def delete_figure(fid: int, user: User = Depends(require("figures.manage")), db: Session = Depends(get_db)):
    f = db.get(OfficialFigure, fid)
    if f is None:
        raise HTTPException(404, "غير موجود")
    record(db, user, "figure.delete", "figure", str(f.id), figures.view(f), None)
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.post("/figures/import")
async def import_figures(file: UploadFile = File(...), user: User = Depends(require("figures.manage")), db: Session = Depends(get_db)):
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(422, "الملف أكبر من 5 ميغابايت")
    r = figures.import_csv(db, user, raw)
    record(db, user, "figure.import", "figure", file.filename or "", None, {"added": r["added"]})
    db.commit()
    return r


@router.get("/claims/{cid}/figures")
def claim_figures(cid: int, _: User = Depends(READ), db: Session = Depends(get_db)):
    c = _claim(db, cid)
    return {"matches": figures.match(db, c.text)}


class TextIn(BaseModel):
    text: str


@router.post("/figures/match")
def match_figures(body: TextIn, _: User = Depends(READ), db: Session = Depends(get_db)):
    return {"matches": figures.match(db, body.text[:20000])}


# ---------- الوعود ----------

@router.get("/promises")
def list_promises(entity_id: int | None = None, status: str = "", _: User = Depends(READ), db: Session = Depends(get_db)):
    q = select(Promise).order_by(Promise.due_at.is_(None), Promise.due_at, Promise.id.desc())
    if entity_id:
        q = q.where(Promise.entity_id == entity_id)
    if status:
        q = q.where(Promise.status == status)
    return {"promises": [promises.view(db, p) for p in db.scalars(q.limit(500)).all()], "statuses": promises.STATUSES}


class PromiseIn(BaseModel):
    entity_id: int | None = None
    entity_name: str = ""
    text: str = ""
    due_at: str | None = None
    said_at: str | None = None
    source_url: str = ""
    statement_id: int | None = None


@router.post("/promises")
def add_promise(body: PromiseIn, user: User = Depends(require("claims.create")), db: Session = Depends(get_db)):
    st = db.get(Statement, body.statement_id) if body.statement_id else None
    if body.statement_id and st is None:
        raise HTTPException(404, "التصريح غير موجود")
    e = db.get(Entity, body.entity_id or (st.entity_id if st else 0))
    if e is None and body.entity_name.strip():
        from marsad.text import normalize_ar

        n = normalize_ar(body.entity_name)
        e = db.scalar(select(Entity).where(Entity.norm == n)) or Entity(name=body.entity_name.strip()[:300], norm=n, kind="person")
        db.add(e)
        db.flush()
    if e is None:
        raise HTTPException(422, "اختر صاحب الوعد")
    try:
        p = promises.create(db, user, e, body.text, body.due_at, body.said_at, body.source_url, st)
    except (promises.PromiseError, ValueError) as ex:
        raise HTTPException(422, str(ex)) from None
    if st is not None and not st.is_promise:
        st.is_promise = True
    db.commit()
    return promises.view(db, p)


class PromiseUpdate(BaseModel):
    status: str | None = None
    evidence_url: str | None = None
    evidence_note: str | None = None
    due_at: str | None = None


@router.patch("/promises/{pid}")
def edit_promise(pid: int, body: PromiseUpdate, user: User = Depends(require("claims.create")), db: Session = Depends(get_db)):
    p = db.get(Promise, pid)
    if p is None:
        raise HTTPException(404, "غير موجود")
    try:
        promises.update(db, user, p, body.status, body.evidence_url, body.evidence_note, body.due_at)
    except (promises.PromiseError, ValueError) as ex:
        raise HTTPException(422, str(ex)) from None
    db.commit()
    return promises.view(db, p)


# ---------- تفريغ المؤتمرات والتسجيلات ----------

def _media(db: Session, mid: int) -> MediaFile:
    m = db.get(MediaFile, mid)
    if m is None:
        raise HTTPException(404, "غير موجود")
    return m


@router.get("/transcripts")
def list_transcripts(_: User = Depends(require("labs.use")), db: Session = Depends(get_db)):
    rows = db.scalars(select(MediaFile).where(MediaFile.kind.in_(("audio", "video"))).order_by(MediaFile.id.desc()).limit(200)).all()
    out = []
    for m in rows:
        v = transcripts.view(db, m)
        out.append({k: v[k] for k in ("media_id", "kind", "filename", "available", "summary", "checkable")})
    return {"media": out}


@router.post("/transcripts/{mid}")
def run_transcript(mid: int, _: User = Depends(require("labs.use")), db: Session = Depends(get_db)):
    try:
        transcripts.transcribe(db, _media(db, mid))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except Exception as e:  # noqa: BLE001 — ffmpeg أو ملف تالف
        raise HTTPException(422, f"تعذّر استخراج الصوت من الملف: {e.__class__.__name__}") from None
    db.commit()
    return transcripts.view(db, _media(db, mid))


@router.get("/transcripts/{mid}")
def get_transcript(mid: int, _: User = Depends(require("labs.use")), db: Session = Depends(get_db)):
    return transcripts.view(db, _media(db, mid))


class SegClaimIn(BaseModel):
    i: int
    text: str = ""
    speaker: str = ""


@router.post("/transcripts/{mid}/claim")
def transcript_claim(mid: int, body: SegClaimIn, user: User = Depends(require("claims.create")), db: Session = Depends(get_db)):
    from marsad.claims.core import ClaimError

    try:
        c = transcripts.to_claim(db, user, _media(db, mid), body.i, body.text or None, body.speaker)
    except (ValueError, ClaimError) as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return {"claim_id": c.id}


# ---------- الأرشفة الفورية ----------

ARCHIVE = any_of("monitor.view", "claims.create", "cases.create")


class SnapIn(BaseModel):
    url: str
    wayback: bool = False
    claim_id: int | None = None
    case_id: int | None = None


@router.post("/snapshots")
def make_snapshot(body: SnapIn, user: User = Depends(ARCHIVE), db: Session = Depends(get_db)):
    if body.case_id:
        from marsad.api.cases import _case

        _case(db, body.case_id, user)  # الأرشفة لقضية تتطلب عضويتها
    try:
        s = snapshots.archive(db, user, body.url, wayback=body.wayback, claim_id=body.claim_id, case_id=body.case_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if body.claim_id and s.status == "ok":
        from marsad.models.claims import Evidence

        db.add(Evidence(claim_id=body.claim_id, kind="link", title=f"نسخة مؤرشفة: {s.title or s.url}"[:400], url=s.url,
                        sha256=s.sha256, added_by=user.id, data={"snapshot_id": s.id}))
    record(db, user, "snapshot.create", "snapshot", str(s.id), None, {"url": s.url, "sha256": s.sha256, "wayback": s.wayback_status})
    db.commit()
    return snapshots.view(s)


@router.get("/snapshots")
def list_snapshots(claim_id: int | None = None, case_id: int | None = None, user: User = Depends(ARCHIVE),
                   db: Session = Depends(get_db)):
    q = select(Snapshot).order_by(Snapshot.id.desc()).limit(300)
    if claim_id:
        q = q.where(Snapshot.claim_id == claim_id)
    if case_id:
        from marsad.api.cases import _case

        _case(db, case_id, user)
        q = q.where(Snapshot.case_id == case_id)
    else:
        q = q.where(Snapshot.case_id.is_(None))  # أرشيف القضايا لا يظهر إلا لأعضائها
    return {"snapshots": [snapshots.view(s) for s in db.scalars(q).all()]}


def _snap_file(db: Session, sid: int, user: User, which: str) -> FileResponse:
    s = db.get(Snapshot, sid)
    if s is None:
        raise HTTPException(404, "غير موجود")
    if s.case_id:
        from marsad.api.cases import _case

        _case(db, s.case_id, user)
    rel = s.html_path if which == "html" else s.screenshot_path
    if not rel:
        raise HTTPException(404, "غير موجود")
    path = data_file(rel)
    media = "text/plain; charset=utf-8" if which == "html" else "image/png"
    # الصفحة المؤرشفة تُعرض نصًا خامًا أو تُنزَّل، ولا تُشغَّل داخل البرنامج
    return FileResponse(path, media_type=media, filename=path.name,
                        content_disposition_type="attachment" if which == "html" else "inline",
                        headers={"Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


@router.get("/snapshots/{sid}/html")
def snapshot_html(sid: int, user: User = Depends(ARCHIVE), db: Session = Depends(get_db)):
    return _snap_file(db, sid, user, "html")


@router.get("/snapshots/{sid}/screenshot")
def snapshot_shot(sid: int, user: User = Depends(ARCHIVE), db: Session = Depends(get_db)):
    return _snap_file(db, sid, user, "png")


# ---------- بطاقة نتيجة التحقق ----------

@router.get("/claims/{cid}/card")
def claim_card(cid: int, _: User = Depends(CLAIM_WORK), db: Session = Depends(get_db)):
    c = _claim(db, cid)
    v = next((v for v in reversed(c.verdicts) if v.status == "approved"), None)
    if v is None:
        raise HTTPException(422, "البطاقة لأحكام الادّعاءات المعتمدة فقط")
    when = v.approved_at.astimezone(ZoneInfo("Asia/Amman")).date().isoformat() if v.approved_at else ""
    return {"claim": c.text, "label": v.label, "grade": v.evidence_grade, "explanation": (v.explanation or "")[:280],
            "date": when, "org": get_setting(db, "org.name", "مرصد التحقق") or "مرصد التحقق"}
