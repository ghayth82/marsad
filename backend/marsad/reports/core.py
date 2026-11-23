"""الموجز الصباحي والتقرير الأسبوعي ولوحة الرئيسية — كلها من بيانات حقيقية، وكل رقم برابطه."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marsad.db import utcnow
from marsad.models import User
from marsad.models.analysis import Story
from marsad.models.claims import Claim, ClaimItem, Verdict
from marsad.models.engines import EngineRun, Notification
from marsad.models.monitoring import Item, Outlet, Source
from marsad.models.reports import Report
from marsad.rbac.service import get_setting

SCHEDULE_KEY = "reports.schedule"
DEFAULT_SCHEDULE = {"tz": "Asia/Amman", "morning": "07:00", "weekly_day": 0, "weekly": "08:00", "enabled": True}


def schedule(db: Session) -> dict:
    return {**DEFAULT_SCHEDULE, **(get_setting(db, SCHEDULE_KEY, {}) or {})}


def _rising(db: Session, since: datetime, limit: int = 8) -> list[dict]:
    rows = db.execute(select(Item.story_id, func.count(Item.id), func.count(func.distinct(Item.outlet_id)))
                      .where(Item.captured_at >= since, Item.story_id.is_not(None)).group_by(Item.story_id)
                      .order_by(func.count(func.distinct(Item.outlet_id)).desc(), func.count(Item.id).desc()).limit(limit)).all()
    out = []
    for sid, n, outlets in rows:
        s = db.get(Story, sid)
        if s:
            out.append({"id": sid, "title": s.title, "new_items": n, "outlets": outlets, "link": f"/stories/{sid}"})
    return out


def _claims(db: Session, since: datetime) -> dict:
    new = list(db.scalars(select(Claim).where(Claim.created_at >= since).order_by(Claim.created_at.desc()).limit(15)))
    returns = db.execute(select(ClaimItem.claim_id, func.count()).where(ClaimItem.added_at >= since, ClaimItem.kind == "return")
                         .group_by(ClaimItem.claim_id)).all()
    verdicts = list(db.scalars(select(Verdict).where(Verdict.approved_at >= since, Verdict.status == "approved")))
    return {"new": [{"id": c.id, "text": c.text[:200], "link": f"/claims/{c.id}"} for c in new],
            "new_count": db.scalar(select(func.count()).select_from(Claim).where(Claim.created_at >= since)),
            "returns": [{"id": cid, "text": db.get(Claim, cid).text[:200], "times": k, "link": f"/claims/{cid}"} for cid, k in returns],
            "verdicts": [{"claim_id": v.claim_id, "label": v.label, "grade": v.evidence_grade, "text": db.get(Claim, v.claim_id).text[:160],
                          "link": f"/claims/{v.claim_id}"} for v in verdicts]}


def _sources(db: Session) -> dict:
    rows = Counter(s for (s,) in db.execute(select(Source.status).where(Source.active.is_(True))).all())
    broken = [{"id": s.id, "title": s.title or s.url, "error": s.last_error[:160]}
              for s in db.scalars(select(Source).where(Source.active.is_(True), Source.status == "error").limit(10))]
    return {"ok": rows.get("ok", 0), "error": rows.get("error", 0), "new": rows.get("new", 0), "paused": rows.get("paused", 0),
            "total": sum(rows.values()), "broken": broken}


def build(db: Session, kind: str, now: datetime | None = None) -> dict:
    now = now or utcnow()
    since = now - (timedelta(days=7) if kind == "weekly" else timedelta(hours=24))
    items = db.scalar(select(func.count()).select_from(Item).where(Item.captured_at >= since)) or 0
    by_outlet = db.execute(select(Outlet.name, func.count(Item.id)).join(Item, Item.outlet_id == Outlet.id)
                           .where(Item.captured_at >= since).group_by(Outlet.name).order_by(func.count(Item.id).desc()).limit(8)).all()
    edits = db.scalar(select(func.count()).select_from(Item).where(Item.captured_at >= since, Item.status.in_(("edited", "deleted")))) or 0
    content = {"kind": kind, "period": {"start": since.isoformat(), "end": now.isoformat()}, "items": items, "edited_or_deleted": edits,
               "top_outlets": [{"name": n, "items": k} for n, k in by_outlet], "rising_stories": _rising(db, since),
               "claims": _claims(db, since), "sources": _sources(db),
               "alerts": [{"kind": n.kind, "text": n.text[:240], "at": n.created_at.isoformat()}
                          for n in db.scalars(select(Notification).where(Notification.created_at >= since, Notification.kind.in_(
                              ("rumor.return", "rumor.spike", "campaign"))).order_by(Notification.id.desc()).limit(15))]}
    if kind == "weekly":
        cost = db.scalar(select(func.coalesce(func.sum(EngineRun.cost_usd), 0.0)).where(EngineRun.created_at >= since)) if hasattr(EngineRun, "cost_usd") else None
        content["engine_cost_usd"] = round(float(cost or 0), 2) if cost is not None else None
    return content


def summary_text(c: dict) -> str:
    title = "الموجز الصباحي" if c["kind"] == "morning" else "التقرير الأسبوعي"
    lines = [f"{title} — مرصد التحقق", f"{c['items']} مادة جديدة، {c['claims']['new_count']} ادّعاء جديد، {len(c['claims']['verdicts'])} حكم معتمد."]
    if c["claims"]["returns"]:
        lines.append(f"عادت {len(c['claims']['returns'])} شائعة مكشوفة.")
    for s in c["rising_stories"][:3]:
        lines.append(f"• {s['title'][:90]} ({s['outlets']} مصادر)")
    if c["sources"]["error"]:
        lines.append(f"⚠️ {c['sources']['error']} مصدر متوقف.")
    return "\n".join(lines)


def generate(db: Session, kind: str, user: User | None = None, now: datetime | None = None) -> Report:
    now = now or utcnow()
    tz = ZoneInfo(schedule(db)["tz"])
    c = build(db, kind, now)
    r = Report(kind=kind, period_start=datetime.fromisoformat(c["period"]["start"]), period_end=now, content=c,
               local_date=now.astimezone(tz).date().isoformat(), auto=user is None, created_by=user.id if user else None)
    db.add(r)
    db.flush()
    db.add(Notification(kind=f"report.{kind}", text=summary_text(c) + f"\n/reports/{r.id}"))
    return r


def due(db: Session, now: datetime | None = None) -> list[str]:
    """التقارير التي حان موعدها اليوم ولم تُنشأ بعد (الإنشاء التلقائي مرة واحدة في اليوم أو الأسبوع)."""
    now = now or utcnow()
    sc = schedule(db)
    if not sc.get("enabled", True):
        return []
    tz = ZoneInfo(sc["tz"])
    local = now.astimezone(tz)
    out = []

    def at(hhmm: str) -> datetime:
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime.combine(local.date(), time(h, m), tz)

    if local >= at(sc["morning"]) and not db.scalars(select(Report.id).where(Report.kind == "morning", Report.auto.is_(True),
                                                                             Report.local_date == local.date().isoformat())).first():
        out.append("morning")
    if local.weekday() == int(sc["weekly_day"]) and local >= at(sc["weekly"]) and not db.scalars(
            select(Report.id).where(Report.kind == "weekly", Report.auto.is_(True), Report.local_date == local.date().isoformat())).first():
        out.append("weekly")
    return out


def dashboard(db: Session, user: User) -> dict:
    """بيانات بطاقات الرئيسية. كل بطاقة تعرض حالة فارغة صادقة إن لم تكن هناك بيانات."""
    from marsad.models.cases import Case, CaseMember, Draft
    from marsad.models.reports import Exercise, Submission
    from marsad.rbac.service import effective_permissions

    now = utcnow()
    perms = effective_permissions(user)
    out: dict = {}
    if "monitor.view" in perms:
        out["rising_stories"] = _rising(db, now - timedelta(hours=6), 6)
        cl = _claims(db, now - timedelta(hours=24))
        out["new_rumors"] = {"items": cl["new"][:6], "count": cl["new_count"], "returns": cl["returns"][:3]}
        out["sources_status"] = _sources(db)
        last = db.scalars(select(Report).where(Report.kind == "morning").order_by(Report.id.desc())).first()
        out["daily_brief"] = {"id": last.id, "created_at": last.created_at.isoformat(), "text": summary_text(last.content)} if last else None
    out["alerts"] = [{"id": n.id, "kind": n.kind, "text": n.text[:240], "at": n.created_at.isoformat(), "read": n.read_at is not None}
                     for n in db.scalars(select(Notification).where((Notification.user_id == user.id) | (Notification.user_id.is_(None)))
                                         .order_by(Notification.id.desc()).limit(8))]
    out["my_cases"] = [{"id": c.id, "title": c.title, "link": f"/cases/{c.id}"} for c in db.scalars(
        select(Case).join(CaseMember, CaseMember.case_id == Case.id).where(CaseMember.user_id == user.id).order_by(Case.updated_at.desc()).limit(5))]
    pend = []
    if "verdicts.approve" in perms:
        pend += [{"kind": "حكم", "text": db.get(Claim, v.claim_id).text[:120], "link": f"/claims/{v.claim_id}"}
                 for v in db.scalars(select(Verdict).where(Verdict.status == "proposed", Verdict.author_id != user.id).limit(5))]
    if "stories.approve" in perms:
        member_cases = select(CaseMember.case_id).where(CaseMember.user_id == user.id)
        pend += [{"kind": "مسودة", "text": d.title[:120], "link": f"/story-builder/{d.id}"}
                 for d in db.scalars(select(Draft).where(Draft.status != "approved", Draft.author_id != user.id, Draft.case_id.in_(member_cases)).limit(5))]
    out["pending_approvals"] = pend
    if "engines.manage" in perms or "engines.use" in perms:
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cost = db.scalar(select(func.coalesce(func.sum(EngineRun.cost_usd), 0.0)).where(EngineRun.created_at >= month)) if hasattr(EngineRun, "cost_usd") else 0
        out["engine_costs"] = {"month_usd": round(float(cost or 0), 2)}
    if perms & {"training.participate", "training.manage"}:
        done = {s.exercise_id for s in db.scalars(select(Submission).where(Submission.user_id == user.id))}
        ex = list(db.scalars(select(Exercise).where(Exercise.published.is_(True))))
        out["training"] = {"total": len(ex), "done": len(done & {e.id for e in ex}),
                           "next": next(({"id": e.id, "title": e.title, "link": f"/training/{e.id}"} for e in ex if e.id not in done), None)}
    return out
