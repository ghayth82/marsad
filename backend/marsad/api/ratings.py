"""تقييم المواقع (الشاشة 12). داخلي فقط: لا نشر علني قبل المراجعة القانونية واعتماد المحرّر."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.api.deps import require
from marsad.audit import record
from marsad.db import get_db, utcnow
from marsad.models import User
from marsad.models.monitoring import Item, Outlet
from marsad.models.ratings import Methodology, Reply, ReviewLabel, Score
from marsad.ratings import core
from marsad.rbac.service import get_setting

router = APIRouter(prefix="/api/ratings", tags=["ratings"])
view = require("ratings.view")
configure = require("ratings.configure")
approve = require("ratings.approve")
INTERNAL = "داخلي فقط · لا يُنشر قبل المراجعة القانونية"


def _outlet(db: Session, oid: int) -> Outlet:
    o = db.get(Outlet, oid)
    if o is None:
        raise HTTPException(404, "الجهة غير موجودة")
    return o


def _slim(r: dict) -> dict:
    return {**r, "indicators": {k: {x: v[x] for x in ("ar", "value", "ci", "sample", "min_sample", "enough", "good", "bad")}
                                for k, v in r["indicators"].items()}}


@router.get("")
def ranking(kind: str = "news", _: User = Depends(view), db: Session = Depends(get_db)):
    meth = core.current_methodology(db)
    stmt = select(Outlet).order_by(Outlet.name)
    if kind:
        stmt = stmt.where(Outlet.kind == kind)
    rows = [_slim(core.compute(db, o, meth=meth)) for o in db.scalars(stmt)]
    rows = [r for r in rows if r["items"]]
    rows.sort(key=lambda r: (r["composite"] is None, -(r["composite"] or 0), r["outlet"]["name"]))
    db.commit()
    return {"notice": INTERNAL, "methodology_version": meth.version, "period_days": meth.period_days, "rows": rows,
            "indicators": {k: v["ar"] for k, v in core.INDICATORS.items()}}


@router.get("/outlets/{oid}")
def card(oid: int, _: User = Depends(view), db: Session = Depends(get_db)):
    o = _outlet(db, oid)
    r = core.compute(db, o)
    r["evolution"] = core.evolution(db, o)
    r["replies"] = [_reply(x) for x in db.scalars(select(Reply).where(Reply.outlet_id == oid).order_by(Reply.received_at.desc()))]
    r["snapshots"] = [{"id": s.id, "end": s.period_end.isoformat(), "composite": s.composite, "status": s.status,
                       "methodology_version": s.methodology_version}
                      for s in db.scalars(select(Score).where(Score.outlet_id == oid).order_by(Score.period_end.desc()).limit(24))]
    r["notice"] = INTERNAL
    db.commit()
    return r


@router.get("/outlets/{oid}/indicators/{key}")
def trace(oid: int, key: str, _: User = Depends(view), db: Session = Depends(get_db)):
    """كل المواد التي بُني عليها الرقم، دون اختصار."""
    if key not in core.INDICATORS:
        raise HTTPException(404, "مؤشر غير معروف")
    r = core.compute(db, _outlet(db, oid), full=True)
    return r["indicators"][key]


class TransparencyIn(BaseModel):
    ownership: str = ""
    editorial_team: str = ""
    corrections_policy: str = ""
    contact: str = ""
    funding: str = ""


@router.put("/outlets/{oid}/transparency")
def transparency(oid: int, body: TransparencyIn, user: User = Depends(configure), db: Session = Depends(get_db)):
    o = _outlet(db, oid)
    before = dict(o.transparency or {})
    o.transparency = {k: v.strip()[:500] for k, v in body.model_dump().items()}
    record(db, user, "ratings.transparency", "outlet", o.id, before=before, after=o.transparency)
    db.commit()
    return o.transparency


# ---------- المنهجية ----------

def _meth(m: Methodology) -> dict:
    return {"version": m.version, "weights": m.weights, "min_sample": m.min_sample, "period_days": m.period_days, "note": m.note,
            "created_by": m.created_by, "created_at": m.created_at.isoformat()}


@router.get("/methodology")
def methodology(_: User = Depends(view), db: Session = Depends(get_db)):
    cur = core.current_methodology(db)
    db.commit()
    return {"current": _meth(cur), "history": [_meth(m) for m in db.scalars(select(Methodology).order_by(Methodology.version.desc()))],
            "indicators": core.INDICATORS, "jti": core.JTI_ITEMS,
            "rules": ["حد أدنى للعيّنة، وكل نسبة بهامش ثقة 95٪ (فترة ويلسون).", "كل رقم بأمثلته: نقرة على المؤشر تعرض المواد.",
                      "المؤشرات اللغوية تُراجَع على عيّنة بشرية ويُقاس الاتفاق (كوهين كابا).",
                      "الأوزان منشورة، وكل تغيير إصدار جديد برقم وتاريخ وسبب.", "المعايير نفسها على كل الجهات.",
                      "حق الرد: الرد المقبول على مادة يُخرجها من المؤشر.", "لا نشر علني دون اعتماد المحرّر والمراجعة القانونية."],
            "references": [{"name": "JTI (CWA 17493)", "url": "https://journalismtrustinitiative.org/jti-the-standard/"},
                           {"name": "معايير مرصد «أكيد»", "url": "https://akeed.jo/en/page/almaaayyr"},
                           {"name": "Kohring & Matthes (2007)", "url": "https://journals.sagepub.com/doi/10.1177/0093650206298071"}]}


class MethIn(BaseModel):
    weights: dict[str, float]
    min_sample: int = 30
    period_days: int = 90
    note: str


@router.post("/methodology")
def change_methodology(body: MethIn, user: User = Depends(configure), db: Session = Depends(get_db)):
    before = _meth(core.current_methodology(db))
    try:
        m = core.new_methodology(db, user, body.weights, body.min_sample, body.period_days, body.note)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    record(db, user, "ratings.methodology", "methodology", m.version, before=before, after=_meth(m))
    db.commit()
    return _meth(m)


# ---------- المراجعة البشرية والاتفاق ----------

@router.get("/review/{indicator}")
def review(indicator: str, user: User = Depends(view), db: Session = Depends(get_db)):
    if indicator not in core.LINGUISTIC:
        raise HTTPException(404, "المراجعة للمؤشرات اللغوية فقط")
    return {"indicator": indicator, "question": QUESTIONS[indicator], "items": core.review_queue(db, indicator, user)}


QUESTIONS = {"sensational": "هل العنوان مثير أو مهوّل أو يصطنع الفضول؟", "headline": "هل العنوان لا يعكس ما في متن الخبر؟",
             "opinion": "هل في المادة الخبرية لغة تقييمية أو رأي واضح؟"}


class LabelIn(BaseModel):
    item_id: int
    indicator: str
    value: bool


@router.post("/review")
def label(body: LabelIn, user: User = Depends(view), db: Session = Depends(get_db)):
    if body.indicator not in core.LINGUISTIC or db.get(Item, body.item_id) is None:
        raise HTTPException(422, "مادة أو مؤشر غير صحيح")
    row = db.scalars(select(ReviewLabel).where(ReviewLabel.item_id == body.item_id, ReviewLabel.indicator == body.indicator,
                                               ReviewLabel.user_id == user.id)).first()
    if row:
        row.value = body.value
    else:
        db.add(ReviewLabel(item_id=body.item_id, indicator=body.indicator, user_id=user.id, value=body.value))
    db.commit()
    return {"ok": True}


@router.get("/agreement")
def agreement(_: User = Depends(view), db: Session = Depends(get_db)):
    out = {}
    for ind in core.LINGUISTIC:
        labels = list(db.scalars(select(ReviewLabel).where(ReviewLabel.indicator == ind)))
        by_item: dict[int, dict[int, bool]] = {}
        for lab in labels:
            by_item.setdefault(lab.item_id, {})[lab.user_id] = lab.value
        mh, hh = [], []
        for iid, users in by_item.items():
            it = db.get(Item, iid)
            m = core.machine_label(it, ind) if it else None
            vals = list(users.values())
            if m is not None:
                mh.append((m, sum(vals) * 2 > len(vals)))
            if len(vals) >= 2:
                hh.append((vals[0], vals[1]))
        k = core.kappa(mh)
        out[ind] = {"ar": core.INDICATORS[ind]["ar"], "reviewed_items": len(by_item), "kappa_machine_human": k,
                    "kappa_human_human": core.kappa(hh), "double_reviewed": len(hh),
                    "acceptable": k is not None and k >= 0.6,
                    "reading": "لا عيّنة كافية بعد (5 مواد على الأقل)" if k is None else
                    "اتفاق جيد أو أفضل" if k >= 0.6 else "اتفاق متوسط: راجع قواعد المؤشر" if k >= 0.4 else "اتفاق ضعيف: لا يُعتمد المؤشر"}
    return out


# ---------- حق الرد ----------

def _reply(r: Reply) -> dict:
    return {"id": r.id, "outlet_id": r.outlet_id, "item_id": r.item_id, "indicator": r.indicator, "text": r.text, "channel": r.channel,
            "status": r.status, "resolution": r.resolution, "received_at": r.received_at.isoformat(),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None}


class ReplyIn(BaseModel):
    outlet_id: int
    item_id: int | None = None
    indicator: str = ""
    text: str
    channel: str = ""


@router.post("/replies")
def add_reply(body: ReplyIn, user: User = Depends(view), db: Session = Depends(get_db)):
    _outlet(db, body.outlet_id)
    if body.indicator and body.indicator not in core.INDICATORS:
        raise HTTPException(422, "مؤشر غير معروف")
    if not body.text.strip():
        raise HTTPException(422, "اكتب نص الاعتراض كما وصل")
    if body.item_id is not None:
        it = db.get(Item, body.item_id)
        if it is None or it.outlet_id != body.outlet_id:
            raise HTTPException(422, "المادة ليست من هذه الجهة")
    r = Reply(outlet_id=body.outlet_id, item_id=body.item_id, indicator=body.indicator, text=body.text.strip(),
              channel=body.channel.strip()[:60], recorded_by=user.id)
    db.add(r)
    db.flush()
    record(db, user, "ratings.reply", "reply", r.id, after=_reply(r))
    db.commit()
    return _reply(r)


class DecideIn(BaseModel):
    status: str
    resolution: str


@router.post("/replies/{rid}/decide")
def decide(rid: int, body: DecideIn, user: User = Depends(approve), db: Session = Depends(get_db)):
    r = db.get(Reply, rid)
    if r is None:
        raise HTTPException(404, "غير موجود")
    if body.status not in ("accepted", "rejected") or not body.resolution.strip():
        raise HTTPException(422, "اختر القبول أو الرفض واكتب السبب")
    before = _reply(r)
    r.status, r.resolution, r.decided_by, r.decided_at = body.status, body.resolution.strip(), user.id, utcnow()
    record(db, user, "ratings.reply_decision", "reply", r.id, before=before, after=_reply(r))
    db.commit()
    return _reply(r)


# ---------- اللقطات والاعتماد والنشر ----------

@router.post("/outlets/{oid}/snapshot")
def take_snapshot(oid: int, user: User = Depends(view), db: Session = Depends(get_db)):
    s = core.snapshot(db, _outlet(db, oid))
    record(db, user, "ratings.snapshot", "score", s.id, after={"composite": s.composite, "version": s.methodology_version})
    db.commit()
    return {"id": s.id, "composite": s.composite, "status": s.status}


@router.post("/scores/{sid}/approve")
def approve_score(sid: int, user: User = Depends(approve), db: Session = Depends(get_db)):
    s = db.get(Score, sid)
    if s is None:
        raise HTTPException(404, "غير موجود")
    s.status, s.approved_by, s.approved_at = "approved", user.id, utcnow()
    record(db, user, "ratings.approve", "score", s.id, before={"status": "draft"}, after={"status": "approved"})
    db.commit()
    return {"id": s.id, "status": s.status, "public": False, "note": "الاعتماد داخلي؛ النشر العلني ممنوع حتى المراجعة القانونية"}


@router.post("/publish")
def publish(user: User = Depends(approve), db: Session = Depends(get_db)):
    """الحالة 29: النشر العلني ممنوع حتى تُفعَّل المراجعة القانونية. حتى بعد تفعيلها لا يوجد مسار نشر آلي:
    يُصدَّر التقييم المعتمد ملفًا يقرّر المحرّر ما يفعله به."""
    record(db, user, "ratings.publish_attempt", "ratings", "", after={"legal_review": bool(get_setting(db, "ratings.legal_review_done", False))})
    db.commit()
    raise HTTPException(403, "النشر العلني لتقييم المواقع ممنوع حتى تُفعَّل المراجعة القانونية ويُعتمد التقييم من المحرّر.")


def daily_snapshots(db: Session) -> int:
    """لقطة يومية لكل جهة لها مواد، لحفظ التطوّر بإصدار المنهجية الذي حُسب به."""
    since = utcnow() - timedelta(hours=23)
    n = 0
    for o in db.scalars(select(Outlet)):
        if db.scalars(select(Score.id).where(Score.outlet_id == o.id, Score.created_at >= since)).first():
            continue
        if db.scalars(select(Item.id).where(Item.outlet_id == o.id).limit(1)).first() is None:
            continue
        core.snapshot(db, o)
        n += 1
    db.commit()
    return n
