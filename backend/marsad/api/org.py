"""البند 14: سير العمل التحريري، الواجهة البرمجية للأنظمة الخارجية وإشعاراتها، سجل التصحيحات العلني."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.api.deps import current_user, require
from marsad.claims import core as claims_core
from marsad.db import get_db
from marsad.models import User
from marsad.models.claims import Claim, Verdict
from marsad.models.org import ApiToken, Correction, Webhook
from marsad.org import corrections, public_api, workflow
from marsad.rbac.service import effective_permissions, set_setting

router = APIRouter(prefix="/api", tags=["org"])
v1 = APIRouter(prefix="/api/v1", tags=["الواجهة البرمجية العامة"])
public = APIRouter(tags=["public"])


def _claim(db: Session, cid: int) -> Claim:
    c = db.get(Claim, cid)
    if c is None:
        raise HTTPException(404, "غير موجود")
    return c


def claim_workers(user: User = Depends(current_user)) -> User:
    if not ({"claims.create", "verdicts.propose", "verdicts.approve"} & effective_permissions(user)):
        raise HTTPException(403, "لا تملك صلاحية لهذه الصفحة. اطلبها من المدير.")
    return user


# ---------- سير العمل ----------

@router.get("/workflow/board")
def board(_: User = Depends(claim_workers), db: Session = Depends(get_db)):
    return workflow.board(db)


@router.get("/workflow/mine")
def mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return workflow.mine(db, user)


@router.get("/workflow/people")
def people(_: User = Depends(claim_workers), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all()
    return {"people": [{"id": u.id, "name": u.full_name} for u in rows
                       if {"claims.create", "verdicts.propose"} & effective_permissions(u)]}


class AssignIn(BaseModel):
    assignee_id: int | None = None
    priority: str | None = None
    due_at: str | None = None


@router.put("/claims/{cid}/workflow")
def assign(cid: int, body: AssignIn, user: User = Depends(claim_workers), db: Session = Depends(get_db)):
    c = _claim(db, cid)
    # الإسناد لغيرك للمحرّر؛ الصحفي يسند لنفسه أو يغيّر الأولوية فقط
    if body.assignee_id not in (None, user.id) and "verdicts.approve" not in effective_permissions(user):
        raise HTTPException(403, "إسناد الادّعاء لزميل للمحرّر")
    who = db.get(User, body.assignee_id) if body.assignee_id else None
    if body.assignee_id and who is None:
        raise HTTPException(404, "المستخدم غير موجود")
    try:
        due = datetime.fromisoformat(body.due_at) if body.due_at else None
        workflow.assign(db, user, c, who, body.priority, due)
    except (workflow.WorkflowError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return workflow.view(c, {u.id: u.full_name for u in db.scalars(select(User))})


@router.post("/claims/{cid}/workflow/start")
def start(cid: int, user: User = Depends(claim_workers), db: Session = Depends(get_db)):
    c = _claim(db, cid)
    try:
        workflow.start(db, user, c)
    except workflow.WorkflowError as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return {"status": c.status}


class DismissIn(BaseModel):
    reason: str


@router.post("/claims/{cid}/workflow/dismiss")
def dismiss(cid: int, body: DismissIn, user: User = Depends(require("verdicts.approve")), db: Session = Depends(get_db)):
    c = _claim(db, cid)
    try:
        workflow.dismiss(db, user, c, body.reason)
    except workflow.WorkflowError as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return {"status": c.status}


class SlaIn(BaseModel):
    urgent: float
    high: float
    normal: float


@router.put("/workflow/sla")
def put_sla(body: SlaIn, user: User = Depends(require("system.manage")), db: Session = Depends(get_db)):
    try:
        r = workflow.set_sla(db, user, body.model_dump())
    except workflow.WorkflowError as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return r


# ---------- إدارة الرموز وWebhook ----------

manage = require("api.manage")


@router.get("/api-access")
def api_access(_: User = Depends(manage), db: Session = Depends(get_db)):
    return {"tokens": [public_api.token_view(t) for t in db.scalars(select(ApiToken).order_by(ApiToken.id.desc())).all()],
            "webhooks": [public_api.webhook_view(db, w) for w in db.scalars(select(Webhook).order_by(Webhook.id.desc())).all()],
            "scopes": public_api.SCOPES, "events": public_api.EVENTS}


class TokenIn(BaseModel):
    name: str
    scopes: list[str]
    expires_days: int | None = 365


@router.post("/api-access/tokens")
def new_token(body: TokenIn, user: User = Depends(manage), db: Session = Depends(get_db)):
    try:
        t, raw = public_api.create_token(db, user, body.name, body.scopes, body.expires_days)
    except public_api.ApiError_ as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return {**public_api.token_view(t), "token": raw, "note": "انسخ الرمز الآن؛ لن يظهر مرة أخرى."}


@router.delete("/api-access/tokens/{tid}")
def revoke_token(tid: int, user: User = Depends(manage), db: Session = Depends(get_db)):
    t = db.get(ApiToken, tid)
    if t is None:
        raise HTTPException(404, "غير موجود")
    public_api.revoke(db, user, t)
    db.commit()
    return public_api.token_view(t)


class HookIn(BaseModel):
    url: str
    events: list[str]


@router.post("/api-access/webhooks")
def new_hook(body: HookIn, user: User = Depends(manage), db: Session = Depends(get_db)):
    try:
        w, secret = public_api.create_webhook(db, user, body.url, body.events)
    except public_api.ApiError_ as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return {**public_api.webhook_view(db, w), "secret": secret, "note": "سر التوقيع يظهر مرة واحدة؛ احفظه في النظام المستقبِل."}


@router.delete("/api-access/webhooks/{wid}")
def delete_hook(wid: int, user: User = Depends(manage), db: Session = Depends(get_db)):
    from marsad.audit import record

    w = db.get(Webhook, wid)
    if w is None:
        raise HTTPException(404, "غير موجود")
    w.active = False
    record(db, user, "api.webhook.disable", "webhook", str(w.id), None, {"url": w.url})
    db.commit()
    return {"ok": True}


@router.post("/api-access/webhooks/{wid}/test")
def test_hook(wid: int, user: User = Depends(manage), db: Session = Depends(get_db)):
    from marsad.models.org import WebhookDelivery

    w = db.get(Webhook, wid)
    if w is None or not w.active:
        raise HTTPException(404, "غير موجود")
    db.add(WebhookDelivery(webhook_id=w.id, event="ping", payload={"event": "ping", "data": {"message": "اختبار من مرصد التحقق"}}))
    db.flush()
    r = public_api.deliver(db)
    db.commit()
    return {**r, "webhook": public_api.webhook_view(db, w)}


@router.get("/api-access/openapi.json")
def v1_openapi(_: User = Depends(current_user)):
    return get_openapi(title="مرصد التحقق — الواجهة البرمجية العامة", version="1", routes=v1.routes,
                       description="كل طلب يحمل Authorization: Bearer <الرمز>. الأحكام دون أسماء الصحفيين.")


# ---------- الواجهة البرمجية العامة (برموز الوصول) ----------

def token(scope: str):
    def dep(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> ApiToken:
        try:
            t = public_api.authenticate(db, authorization, scope)
        except PermissionError as e:
            code, msg = str(e).split("|", 1)
            raise HTTPException(int(code), msg) from None
        db.commit()
        return t

    return dep


def _since(since: str | None) -> datetime | None:
    if not since:
        return None
    try:
        return datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "since بصيغة ISO 8601، مثل 2026-11-01T00:00:00Z") from None


@v1.get("/verdicts", summary="الأحكام المعتمدة (الأحدث أولًا)")
def v1_verdicts(since: str | None = None, limit: int = 100, _: ApiToken = Depends(token("verdicts.read")), db: Session = Depends(get_db)):
    q = select(Verdict).where(Verdict.status == "approved").order_by(Verdict.approved_at.desc()).limit(min(max(limit, 1), 500))
    s = _since(since)
    if s:
        q = q.where(Verdict.approved_at >= s)
    out = []
    for v in db.scalars(q).all():
        c = db.get(Claim, v.claim_id)
        if c is not None and claims_core.current_verdict(c, approved_only=True).id == v.id:
            out.append(claims_core.verdict_payload(c, v))
    return {"verdicts": out}


def _claim_public(c: Claim) -> dict:
    v = claims_core.current_verdict(c, approved_only=True)
    return {"id": c.id, "text": c.text, "speaker": c.speaker, "status": c.status,
            "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else None, "created_at": c.created_at.isoformat(),
            "verdict": None if v is None else {"label": v.label, "evidence_grade": v.evidence_grade, "explanation": v.explanation,
                                               "approved_at": v.approved_at.isoformat() if v.approved_at else None}}


@v1.get("/claims", summary="الادّعاءات (الأحدث أولًا)")
def v1_claims(since: str | None = None, limit: int = 100, _: ApiToken = Depends(token("claims.read")), db: Session = Depends(get_db)):
    q = select(Claim).order_by(Claim.created_at.desc()).limit(min(max(limit, 1), 500))
    s = _since(since)
    if s:
        q = q.where(Claim.created_at >= s)
    return {"claims": [_claim_public(c) for c in db.scalars(q).all()]}


@v1.get("/claims/{cid}", summary="ادّعاء واحد بحكمه المعتمد")
def v1_claim(cid: int, _: ApiToken = Depends(token("claims.read")), db: Session = Depends(get_db)):
    return _claim_public(_claim(db, cid))


class V1ClaimIn(BaseModel):
    text: str
    speaker: str = ""
    source_url: str = ""


@v1.post("/claims", summary="إنشاء ادّعاء ليُتحقق منه", status_code=201)
def v1_create(body: V1ClaimIn, t: ApiToken = Depends(token("claims.write")), db: Session = Depends(get_db)):
    from marsad.audit import record
    from marsad.models.claims import Evidence

    try:
        c = claims_core.create_claim(db, None, body.text, speaker=body.speaker, origin="api")
    except claims_core.ClaimError as e:
        raise HTTPException(422, str(e)) from None
    c.meta = {**(c.meta or {}), "api_token": t.name}
    if body.source_url.startswith(("http://", "https://")):
        db.add(Evidence(claim_id=c.id, kind="link", title=f"المصدر كما أرسله {t.name}", url=body.source_url[:1000]))
    record(db, None, "api.claim.create", "claim", str(c.id), None, {"token": t.name})
    db.commit()
    return _claim_public(c)


# ---------- سجل التصحيحات ----------

@router.get("/corrections")
def list_corrections(_: User = Depends(claim_workers), db: Session = Depends(get_db)):
    return {"corrections": [corrections.view(db, k) for k in corrections.listing(db)], "public": corrections.is_public(db)}


class PublicIn(BaseModel):
    public: bool


@router.put("/corrections/public")
def set_public(body: PublicIn, user: User = Depends(require("system.manage")), db: Session = Depends(get_db)):
    set_setting(db, corrections.PUBLIC_KEY, body.public, user)
    db.commit()
    return {"public": body.public}


@router.put("/corrections/{kid}")
def toggle_one(kid: int, body: PublicIn, user: User = Depends(require("verdicts.approve")), db: Session = Depends(get_db)):
    from marsad.audit import record

    k = db.get(Correction, kid)
    if k is None:
        raise HTTPException(404, "غير موجود")
    k.public = body.public
    record(db, user, "correction.visibility", "correction", str(k.id), None, {"public": body.public})
    db.commit()
    return corrections.view(db, k)


@public.get("/public/corrections", include_in_schema=False)
def public_page(db: Session = Depends(get_db)):
    if not corrections.is_public(db):
        raise HTTPException(404, "غير موجود")
    return HTMLResponse(corrections.public_html(db),
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


@public.get("/public/corrections.json", include_in_schema=False)
def public_json(request: Request, db: Session = Depends(get_db)):
    if not corrections.is_public(db):
        raise HTTPException(404, "غير موجود")
    return {"corrections": [corrections.view(db, k, internal=False) for k in corrections.listing(db, public_only=True)]}
