"""واجهة بوابة المحركات (الشاشة 13 وبطاقة المقارنة والقرار)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.api.deps import require
from marsad.audit import record
from marsad.db import get_db, utcnow
from marsad.engines import prompts
from marsad.engines import service as svc
from marsad.engines.providers import PROVIDERS, ProviderError, complete
from marsad.models import User
from marsad.models.engines import Engine, EngineBatch, EngineDecision, Notification

router = APIRouter(prefix="/api/engines", tags=["engines"])
use = require("engines.use")
manage = require("engines.manage")


def _fail(e: Exception, code: int = 409):
    raise HTTPException(code, str(e)) from None


def _engine(db: Session, eid: int) -> Engine:
    e = db.get(Engine, eid)
    if e is None:
        raise HTTPException(404, "المحرك غير موجود")
    return e


# ---------- المحركات ----------

@router.get("/providers")
def providers(_: User = Depends(use)):
    return [{"key": k, **v} for k, v in PROVIDERS.items()]


@router.get("/tasks")
def tasks(_: User = Depends(use)):
    return [{"key": k, "name": v["name"], "version": v["version"]} for k, v in prompts.PROMPTS.items()] + [
        {"key": "labels", "verdicts": prompts.VERDICT_LABELS, "evidence": prompts.EVIDENCE_GRADES}]


@router.get("")
def list_engines(_: User = Depends(use), db: Session = Depends(get_db)):
    acc = svc.accuracy(db)
    return {"engines": [svc.engine_public(db, e, acc) for e in db.scalars(select(Engine).order_by(Engine.id))],
            "settings": svc.get_engine_settings(db), "accuracy": acc}


class EngineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str
    model: str = Field(min_length=1)
    base_url: str = ""
    api_key: str | None = None  # يُكتب فقط ولا يُقرأ أبدًا؛ "" يحذفه
    price_in: float | None = Field(None, ge=0)
    price_out: float | None = Field(None, ge=0)
    monthly_limit_usd: float | None = Field(None, ge=0)
    enabled: bool = True
    options: dict = {}


def _apply(db: Session, e: Engine, body: EngineIn) -> None:
    if body.provider not in PROVIDERS:
        raise HTTPException(422, "مزوّد غير معروف")
    local = PROVIDERS[body.provider]["local"]
    if not local and body.enabled and (body.price_in is None or body.price_out is None):
        raise HTTPException(422, "أدخل سعر المحرك (لكل مليون رمز) ليُحسب حد الإنفاق، أو احفظه معطّلًا")
    e.name, e.provider, e.model, e.base_url = body.name.strip(), body.provider, body.model.strip(), body.base_url.strip()
    e.local, e.price_in, e.price_out = local, body.price_in, body.price_out
    e.monthly_limit_usd, e.enabled, e.options = body.monthly_limit_usd, body.enabled, body.options
    if body.api_key is not None:
        if body.api_key.strip():
            e.api_key_enc, e.api_key_hint = crypto.encrypt(body.api_key.strip()), crypto.mask(body.api_key.strip())
        else:
            e.api_key_enc, e.api_key_hint = None, ""


@router.post("")
def create_engine(body: EngineIn, actor: User = Depends(manage), db: Session = Depends(get_db)):
    e = Engine(name=body.name, provider=body.provider, model=body.model)
    _apply(db, e, body)
    db.add(e)
    db.flush()
    record(db, actor, "engine.create", "engine", str(e.id), None, {"name": e.name, "provider": e.provider, "model": e.model})
    db.commit()
    return svc.engine_public(db, e)


@router.put("/{eid}")
def update_engine(eid: int, body: EngineIn, actor: User = Depends(manage), db: Session = Depends(get_db)):
    e = _engine(db, eid)
    before = {"name": e.name, "model": e.model, "price_in": e.price_in, "price_out": e.price_out,
              "limit": e.monthly_limit_usd, "enabled": e.enabled}
    _apply(db, e, body)
    record(db, actor, "engine.update", "engine", str(e.id), before,
           {"name": e.name, "model": e.model, "price_in": e.price_in, "price_out": e.price_out,
            "limit": e.monthly_limit_usd, "enabled": e.enabled, "key_changed": body.api_key is not None})
    db.commit()
    return svc.engine_public(db, e)


@router.delete("/{eid}")
def delete_engine(eid: int, actor: User = Depends(manage), db: Session = Depends(get_db)):
    e = _engine(db, eid)
    st = svc.get_engine_settings(db)
    if eid in (st["default_engine_id"], st["merge_engine_id"]) or eid in st["multi_engine_ids"] \
            or eid in st["task_engines"].values():
        raise HTTPException(409, "المحرك مستخدم في الإعدادات؛ اختر غيره أولًا أو عطّله")
    record(db, actor, "engine.delete", "engine", str(eid), {"name": e.name}, None)
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.post("/{eid}/test")
def test_engine(eid: int, _: User = Depends(manage), db: Session = Depends(get_db)):
    e = _engine(db, eid)
    try:
        c = complete(e.provider, model=e.model, system="أجب بكائن JSON فقط.",
                     user='أعد بالضبط: {"ok": true}', api_key=svc._key(e), base_url=e.base_url,
                     max_tokens=30, options=e.options or {})
    except (ProviderError, ValueError) as err:
        return {"ok": False, "error": str(err)}
    return {"ok": True, "model_version": c.model_version, "reply": c.text[:200]}


@router.put("/settings/current")
def put_settings(changes: dict, actor: User = Depends(manage), db: Session = Depends(get_db)):
    try:
        out = svc.save_engine_settings(db, actor, changes)
    except svc.EngineError as e:
        _fail(e, 422)
    db.commit()
    return out


# ---------- التشغيل والمقارنة والقرار ----------

class RunIn(BaseModel):
    task: str
    input: dict
    mode: str | None = None
    engine_ids: list[int] | None = None
    merge_engine_id: int | None = None


@router.post("/estimate")
def estimate(body: RunIn, _: User = Depends(use), db: Session = Depends(get_db)):
    try:
        mode, ids, merge = svc.resolve_engines(db, body.task, body.mode, body.engine_ids, body.merge_engine_id)
        out = svc.estimate(db, body.task, body.input, ids + ([merge] if merge else []))
    except (svc.EngineError, KeyError) as e:
        _fail(e, 422)
    return {**out, "mode": mode}


@router.post("/runs")
def run(body: RunIn, bg: BackgroundTasks, user: User = Depends(use), db: Session = Depends(get_db)):
    try:
        b = svc.create_batch(db, user, body.task, body.input, body.mode, body.engine_ids, body.merge_engine_id)
    except svc.EngineError as e:
        _fail(e, 422)
    db.commit()
    bg.add_task(svc.execute_batch, b.id)
    return {"batch_id": b.id, "status": b.status}


def batch_out(db: Session, b: EngineBatch) -> dict:
    d = db.scalar(select(EngineDecision).where(EngineDecision.batch_id == b.id))
    return {
        "id": b.id, "task": b.task, "task_name": prompts.PROMPTS[b.task]["name"], "input": b.input, "mode": b.mode,
        "status": b.status, "created_at": b.created_at.isoformat(), "created_by": b.created_by,
        "runs": [{"id": r.id, "engine_id": r.engine_id, "engine": r.engine_name, "task": r.task, "status": r.status,
                  "error": r.error, "output": r.output, "model": r.model, "model_version": r.model_version,
                  "prompt": f"{r.prompt_id}@{r.prompt_version}", "input_tokens": r.input_tokens,
                  "output_tokens": r.output_tokens, "cost_usd": r.cost_usd, "duration_ms": r.duration_ms}
                 for r in b.runs if r.task == b.task],
        "merges": [{"id": m.id, "engine": m.merge_engine_name, "status": m.status, "error": m.error, "output": m.output,
                    "cost_usd": next((r.cost_usd for r in b.runs if r.id == m.engine_run_id), None),
                    "created_at": m.created_at.isoformat()} for m in b.merges],
        "comparison": svc.compare(b),
        "total_cost_usd": round(sum(r.cost_usd or 0 for r in b.runs), 6),
        "decision": None if d is None else {"output": d.output, "source": d.source, "note": d.note,
                                            "decided_by": d.decided_by, "decided_at": d.decided_at.isoformat()},
    }


@router.get("/batches")
def batches(limit: int = 30, user: User = Depends(use), db: Session = Depends(get_db)):
    rows = db.scalars(select(EngineBatch).order_by(EngineBatch.id.desc()).limit(min(limit, 200)))
    return [{"id": b.id, "task": b.task, "task_name": prompts.PROMPTS[b.task]["name"], "mode": b.mode,
             "status": b.status, "created_at": b.created_at.isoformat(),
             "preview": (b.input.get("claim") or b.input.get("text") or "")[:120]} for b in rows]


@router.get("/batches/{bid}")
def get_batch(bid: int, _: User = Depends(use), db: Session = Depends(get_db)):
    b = db.get(EngineBatch, bid)
    if b is None:
        raise HTTPException(404, "غير موجود")
    return batch_out(db, b)


class MergeIn(BaseModel):
    merge_engine_id: int


@router.post("/batches/{bid}/merge")
def remerge(bid: int, body: MergeIn, user: User = Depends(use), db: Session = Depends(get_db)):
    b = db.get(EngineBatch, bid)
    if b is None or b.status != "done":
        raise HTTPException(409, "انتظر انتهاء التشغيل")
    if len([r for r in b.runs if r.status == "ok" and r.task == b.task]) < 2:
        raise HTTPException(409, "الدمج يحتاج مخرجين ناجحين على الأقل")
    try:
        svc.merge(db, b, _engine(db, body.merge_engine_id))
    except svc.EngineError as e:
        _fail(e, 422)
    record(db, user, "engines.merge", "batch", str(bid), None, {"merge_engine_id": body.merge_engine_id})
    db.commit()
    return batch_out(db, db.get(EngineBatch, bid))


class DecisionIn(BaseModel):
    output: dict
    source: str = "manual"
    note: str = ""


@router.post("/batches/{bid}/decision")
def decision(bid: int, body: DecisionIn, user: User = Depends(use), db: Session = Depends(get_db)):
    b = db.get(EngineBatch, bid)
    if b is None:
        raise HTTPException(404, "غير موجود")
    try:
        svc.decide(db, user, b, body.output, body.source, body.note)
    except svc.EngineError as e:
        _fail(e, 422)
    db.commit()
    db.refresh(b)
    return batch_out(db, b)


# ---------- التنبيهات ----------

@router.get("/notifications")
def notifications(_: User = Depends(use), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.read_at.is_(None)).order_by(Notification.id.desc()).limit(50))
    return [{"id": n.id, "kind": n.kind, "text": n.text, "created_at": n.created_at.isoformat()} for n in rows]


@router.post("/notifications/{nid}/read")
def read_notification(nid: int, _: User = Depends(use), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n:
        n.read_at = utcnow()
        db.commit()
    return {"ok": True}
