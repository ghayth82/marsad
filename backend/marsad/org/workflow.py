"""سير العمل التحريري: إسناد الادّعاء وأولويته ومهلته، ومراجع ثانٍ إلزامي، وتنبيه حين تقترب المهلة أو تتجاوزها.

الحالات: جديد ← مُسند ← قيد التحقق ← بانتظار المراجعة (حكم مقترح) ← معتمد، أو مرفوض (لا يستحق التحقق).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.audit import record
from marsad.db import utcnow
from marsad.models import User
from marsad.models.claims import Claim
from marsad.models.engines import Notification
from marsad.rbac.service import effective_permissions, get_setting, set_setting

SLA_KEY = "workflow.sla_hours"
DEFAULT_SLA = {"urgent": 2, "high": 8, "normal": 24}
PRIORITIES = {"urgent": "عاجل", "high": "مهم", "normal": "عادي"}
STATES = {"new": "جديد", "assigned": "مُسند", "investigating": "قيد التحقق", "proposed": "بانتظار المراجعة",
          "verdict": "معتمد", "dismissed": "مرفوض", "archived": "مؤرشف"}
OPEN = ("new", "assigned", "investigating", "proposed")
SOON_FRACTION = 0.25  # التنبيه حين يبقى ربع المهلة
SOON_MIN = timedelta(minutes=30)


class WorkflowError(ValueError):
    pass


def sla(db: Session) -> dict:
    return {**DEFAULT_SLA, **(get_setting(db, SLA_KEY, {}) or {})}


def set_sla(db: Session, actor: User, hours: dict) -> dict:
    clean = {}
    for k in DEFAULT_SLA:
        v = float(hours.get(k, DEFAULT_SLA[k]))
        if not 0.25 <= v <= 24 * 30:
            raise WorkflowError("المهلة بين ربع ساعة وثلاثين يومًا")
        clean[k] = v
    set_setting(db, SLA_KEY, clean, actor)
    return clean


def in_workflow(c: Claim) -> bool:
    """ادّعاء دخل سير العمل (أُسند لصحفي): مراجعه الثاني إلزامي."""
    return c.assignee_id is not None


def assign(db: Session, actor: User, c: Claim, assignee: User | None, priority: str | None = None,
           due_at: datetime | None = None) -> Claim:
    if c.status in ("verdict", "dismissed", "archived"):
        raise WorkflowError("الادّعاء محسوم؛ لا يُسند")
    if assignee is not None and not ({"claims.create", "verdicts.propose"} & effective_permissions(assignee)):
        raise WorkflowError("لا يملك هذا المستخدم صلاحية العمل على الادّعاءات")
    if priority is not None and priority not in PRIORITIES:
        raise WorkflowError("الأولوية غير معروفة")
    before = {"assignee_id": c.assignee_id, "priority": c.priority, "due_at": c.due_at.isoformat() if c.due_at else None}
    now = utcnow()
    if priority:
        c.priority = priority
    if assignee is not None and assignee.id != c.assignee_id:
        c.assignee_id, c.assigned_at = assignee.id, now
        if c.status == "new":
            c.status = "assigned"
        db.add(Notification(user_id=assignee.id, kind="workflow.assigned",
                            text=f"📌 أُسند إليك ادّعاء ({PRIORITIES[c.priority]}): «{c.text[:140]}»\n/claims/{c.id}"))
    c.due_at = due_at or ((c.assigned_at or now) + timedelta(hours=sla(db)[c.priority]) if c.assignee_id else None)
    c.meta = {**(c.meta or {}), "sla_alerts": []}
    record(db, actor, "workflow.assign", "claim", str(c.id), before,
           {"assignee_id": c.assignee_id, "priority": c.priority, "due_at": c.due_at.isoformat() if c.due_at else None})
    return c


def start(db: Session, actor: User, c: Claim) -> Claim:
    if c.status not in ("new", "assigned"):
        raise WorkflowError("بدأ العمل عليه من قبل")
    if c.assignee_id is None:
        assign(db, actor, c, actor)
    c.status = "investigating"
    record(db, actor, "workflow.start", "claim", str(c.id), None, {"status": c.status})
    return c


def dismiss(db: Session, actor: User, c: Claim, reason: str) -> Claim:
    if c.status not in OPEN:
        raise WorkflowError("لا يُرفض ادّعاء محسوم")
    if len(reason.strip()) < 3:
        raise WorkflowError("اكتب سبب الرفض")
    before = c.status
    c.status = "dismissed"
    c.meta = {**(c.meta or {}), "dismissed": {"by": actor.id, "reason": reason.strip(), "at": utcnow().isoformat()}}
    record(db, actor, "workflow.dismiss", "claim", str(c.id), {"status": before}, {"status": "dismissed", "reason": reason})
    return c


def _editors(db: Session) -> list[User]:
    return [u for u in db.scalars(select(User).where(User.is_active.is_(True))) if "verdicts.approve" in effective_permissions(u)]


def sla_alerts(db: Session, now: datetime | None = None) -> int:
    """تنبيه «تقترب المهلة» للمُسند إليه، و«تجاوز المهلة» له وللمحرّرين؛ كلٌّ مرة واحدة."""
    now = now or utcnow()
    hours = sla(db)
    n = 0
    for c in db.scalars(select(Claim).where(Claim.status.in_(OPEN), Claim.due_at.is_not(None))).all():
        sent = set((c.meta or {}).get("sla_alerts", []))
        due = c.due_at if c.due_at.tzinfo else c.due_at.replace(tzinfo=now.tzinfo)
        span = timedelta(hours=hours.get(c.priority, 24))
        new = []
        if now >= due and "overdue" not in sent:
            who = {c.assignee_id} | {u.id for u in _editors(db)}
            for uid in who - {None}:
                db.add(Notification(user_id=uid, kind="workflow.overdue",
                                    text=f"⏱ تجاوز ادّعاء مهلته ({PRIORITIES[c.priority]}): «{c.text[:140]}»\n/claims/{c.id}"))
            new += ["overdue", "soon"]
        elif now < due and now >= due - max(span * SOON_FRACTION, SOON_MIN) and "soon" not in sent and c.assignee_id:
            left = int((due - now).total_seconds() // 60)
            db.add(Notification(user_id=c.assignee_id, kind="workflow.soon",
                                text=f"⏳ تبقى {left} دقيقة على مهلة ادّعاء: «{c.text[:140]}»\n/claims/{c.id}"))
            new.append("soon")
        if new:
            c.meta = {**(c.meta or {}), "sla_alerts": sorted(sent | set(new))}
            n += 1
    return n


def view(c: Claim, users: dict[int, str]) -> dict:
    now = utcnow()
    due = c.due_at
    return {"id": c.id, "text": c.text, "status": c.status, "state_ar": STATES.get(c.status, c.status), "priority": c.priority,
            "priority_ar": PRIORITIES.get(c.priority, c.priority), "assignee_id": c.assignee_id,
            "assignee": users.get(c.assignee_id, "") if c.assignee_id else "", "due_at": due.isoformat() if due else None,
            "overdue": bool(due and c.status in OPEN and due <= now), "created_at": c.created_at.isoformat()}


def board(db: Session, user: User | None = None) -> dict:
    users = {u.id: u.full_name for u in db.scalars(select(User)).all()}
    rows = db.scalars(select(Claim).where(Claim.status.in_(OPEN)).order_by(Claim.due_at.is_(None), Claim.due_at, Claim.id.desc()).limit(500)).all()
    cols = {s: [] for s in OPEN}
    for c in rows:
        cols[c.status].append(view(c, users))
    return {"columns": [{"key": k, "title": STATES[k], "claims": v} for k, v in cols.items()], "sla": sla(db), "priorities": PRIORITIES}


def mine(db: Session, user: User) -> dict:
    users = {u.id: u.full_name for u in db.scalars(select(User)).all()}
    tasks = db.scalars(select(Claim).where(Claim.assignee_id == user.id, Claim.status.in_(("assigned", "investigating")))
                       .order_by(Claim.due_at.is_(None), Claim.due_at)).all()
    review = []
    if "verdicts.approve" in effective_permissions(user):
        for c in db.scalars(select(Claim).where(Claim.status == "proposed").order_by(Claim.due_at.is_(None), Claim.due_at)).all():
            v = c.verdicts[-1] if c.verdicts else None
            if v and v.author_id != user.id:
                review.append(view(c, users))
    return {"tasks": [view(c, users) for c in tasks], "review": review}
