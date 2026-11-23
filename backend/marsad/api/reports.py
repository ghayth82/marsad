"""التنبيهات والتقارير والرئيسية والتدريب (الشاشة 14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.api.deps import current_user, require
from marsad.audit import record
from marsad.db import get_db
from marsad.engines.prompts import EVIDENCE_GRADES, VERDICT_LABELS
from marsad.models import User
from marsad.models.reports import Exercise, Report, Submission
from marsad.rbac.service import effective_permissions, set_setting
from marsad.reports import alerts, core, training

router = APIRouter(prefix="/api", tags=["reports"])


# ---------- الرئيسية ----------

@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return core.dashboard(db, user)


# ---------- التنبيهات ----------

@router.get("/alerts/telegram")
def telegram_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {**alerts.bot_info(db), "linked": alerts.chat_of(db, user) is not None}


class BotIn(BaseModel):
    token: str | None = None


@router.put("/alerts/telegram/bot")
def set_bot(body: BotIn, user: User = Depends(require("system.manage")), db: Session = Depends(get_db)):
    try:
        r = alerts.set_bot(db, body.token, user)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    record(db, user, "alerts.bot", "telegram", r.get("bot") or "", after={"bot": r.get("bot")})
    db.commit()
    return r


@router.post("/alerts/telegram/link")
def link(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not alerts.bot_info(db)["configured"]:
        raise HTTPException(422, "لم يُضف بوت تيليغرام بعد. يضيفه المدير من الإدارة ← التخزين والإعدادات.")
    r = alerts.link_code(db, user)
    db.commit()
    return r


@router.post("/alerts/telegram/check")
def check(user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        r = alerts.check_link(db, user)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if r["linked"]:
        # من ربط حسابه يريد التنبيهات على تيليغرام: نضيف القناة إلى تفضيلاته
        from marsad.preferences import effective_preferences, update_preferences

        p = effective_preferences(db, user)
        ch = list(dict.fromkeys([*(p.get("alerts") or {}).get("channels", []), "telegram"]))
        update_preferences(db, user, {"alerts": {**(p.get("alerts") or {}), "channels": ch}})
    db.commit()
    return r


@router.delete("/alerts/telegram/link")
def unlink(user: User = Depends(current_user), db: Session = Depends(get_db)):
    alerts.unlink(db, user)
    db.commit()
    return {"ok": True}


@router.post("/alerts/test")
def test_alert(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from marsad.models.engines import Notification

    db.add(Notification(kind="follow", text="تنبيه تجريبي من «مرصد التحقق»: القناة تعمل.", user_id=user.id))
    db.flush()
    r = alerts.dispatch(db)
    db.commit()
    return r


# ---------- التقارير ----------

def _report(r: Report, full: bool = False) -> dict:
    d = {"id": r.id, "kind": r.kind, "local_date": r.local_date, "created_at": r.created_at.isoformat(), "auto": r.auto,
         "summary": core.summary_text(r.content)}
    if full:
        d["content"] = r.content
    return d


@router.get("/reports")
def reports(_: User = Depends(require("monitor.view")), db: Session = Depends(get_db)):
    return {"schedule": core.schedule(db), "rows": [_report(r) for r in db.scalars(select(Report).order_by(Report.id.desc()).limit(60))]}


@router.post("/reports/{kind}")
def generate(kind: str, user: User = Depends(require("monitor.view")), db: Session = Depends(get_db)):
    if kind not in ("morning", "weekly"):
        raise HTTPException(404, "نوع غير معروف")
    r = core.generate(db, kind, user)
    db.commit()
    return _report(r, True)


@router.get("/reports/{rid}")
def report(rid: int, _: User = Depends(require("monitor.view")), db: Session = Depends(get_db)):
    r = db.get(Report, rid)
    if r is None:
        raise HTTPException(404, "غير موجود")
    return _report(r, True)


@router.get("/reports/{rid}/print")
def print_report(rid: int, _: User = Depends(require("monitor.view")), db: Session = Depends(get_db)):
    from html import escape

    r = db.get(Report, rid)
    if r is None:
        raise HTTPException(404, "غير موجود")
    c = r.content
    li = lambda rows, f: "".join(f"<li>{f(x)}</li>" for x in rows) or "<li>لا شيء</li>"  # noqa: E731
    title = "الموجز الصباحي" if r.kind == "morning" else "التقرير الأسبوعي"
    html = f"""<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>{title} {r.local_date}</title>
<style>body{{font-family:system-ui,'Noto Sans Arabic',sans-serif;max-width:820px;margin:24px auto;line-height:1.7}}h2{{margin-top:22px}}
@media print{{button{{display:none}}}}</style><button onclick="print()">طباعة أو حفظ PDF</button>
<h1>{title} · {escape(r.local_date)}</h1><p>{c['items']} مادة جديدة · {c['claims']['new_count']} ادّعاء · {len(c['claims']['verdicts'])} حكم معتمد ·
{c['edited_or_deleted']} مادة عُدّلت أو حُذفت</p>
<h2>القصص الصاعدة</h2><ul>{li(c['rising_stories'], lambda s: f"{escape(s['title'])} — {s['outlets']} مصادر")}</ul>
<h2>شائعات عادت</h2><ul>{li(c['claims']['returns'], lambda x: escape(x['text']))}</ul>
<h2>أحكام معتمدة</h2><ul>{li(c['claims']['verdicts'], lambda v: f"{escape(v['label'])} ({escape(v['grade'])}): {escape(v['text'])}")}</ul>
<h2>ادّعاءات جديدة</h2><ul>{li(c['claims']['new'], lambda x: escape(x['text']))}</ul>
<h2>المصادر</h2><p>{c['sources']['ok']} تعمل · {c['sources']['error']} متوقفة</p><ul>{li(c['sources']['broken'], lambda s: f"{escape(s['title'])}: {escape(s['error'])}")}</ul>
</html>"""
    return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"})


class ScheduleIn(BaseModel):
    morning: str = "07:00"
    weekly_day: int = 0
    weekly: str = "08:00"
    enabled: bool = True


@router.put("/reports-schedule")
def set_schedule(body: ScheduleIn, user: User = Depends(require("system.manage")), db: Session = Depends(get_db)):
    import re

    if not (re.fullmatch(r"\d{2}:\d{2}", body.morning) and re.fullmatch(r"\d{2}:\d{2}", body.weekly) and 0 <= body.weekly_day <= 6):
        raise HTTPException(422, "الوقت بصيغة 07:00 واليوم من 0 (الاثنين) إلى 6")
    set_setting(db, core.SCHEDULE_KEY, {**core.schedule(db), **body.model_dump()}, user)
    db.commit()
    return core.schedule(db)


# ---------- التدريب ----------

def _trainer(user: User) -> bool:
    return "training.manage" in effective_permissions(user)


def _participant(user: User = Depends(current_user)) -> User:
    if not ({"training.participate", "training.manage"} & effective_permissions(user)):
        raise HTTPException(403, "لا تملك صلاحية لهذه الصفحة. اطلبها من المدير.")
    return user


def _ex(e: Exercise, show_answer: bool) -> dict:
    d = {"id": e.id, "title": e.title, "level": e.level, "instructions": e.instructions, "material": e.material, "published": e.published,
         "labels": VERDICT_LABELS, "grades": EVIDENCE_GRADES}
    if show_answer:
        d["answer"] = e.answer
    return d


def _sub(s: Submission) -> dict:
    return {"id": s.id, "exercise_id": s.exercise_id, "user_id": s.user_id, "attempt": s.attempt, "response": s.response, "score": s.score,
            "final_score": training.final_score(s), "feedback": s.feedback, "trainer_score": s.trainer_score, "trainer_note": s.trainer_note,
            "created_at": s.created_at.isoformat()}


@router.get("/training")
def exercises(user: User = Depends(_participant), db: Session = Depends(get_db)):
    if training.seed(db):
        db.commit()
    trainer = _trainer(user)
    stmt = select(Exercise).order_by(Exercise.id)
    if not trainer:
        stmt = stmt.where(Exercise.published.is_(True))
    mine = {}
    for s in db.scalars(select(Submission).where(Submission.user_id == user.id).order_by(Submission.id)):
        mine[s.exercise_id] = training.final_score(s)
    return [{"id": e.id, "title": e.title, "level": e.level, "published": e.published, "my_score": mine.get(e.id)} for e in db.scalars(stmt)]


@router.get("/training/{eid}")
def exercise(eid: int, user: User = Depends(_participant), db: Session = Depends(get_db)):
    e = db.get(Exercise, eid)
    if e is None or (not e.published and not _trainer(user)):
        raise HTTPException(404, "غير موجود")
    subs = list(db.scalars(select(Submission).where(Submission.exercise_id == eid, Submission.user_id == user.id).order_by(Submission.id)))
    # الحل النموذجي بعد أول إجابة فقط (وللمدرّب دائمًا)
    return {**_ex(e, _trainer(user) or bool(subs)), "submissions": [_sub(s) for s in subs]}


class AnswerIn(BaseModel):
    label: str
    grade: str
    reasoning: str = ""


@router.post("/training/{eid}/submit")
def submit(eid: int, body: AnswerIn, user: User = Depends(_participant), db: Session = Depends(get_db)):
    e = db.get(Exercise, eid)
    if e is None or not e.published:
        raise HTTPException(404, "غير موجود")
    s = training.submit(db, user, e, body.model_dump())
    db.commit()
    return {"submission": _sub(s), "answer": e.answer}


class ExerciseIn(BaseModel):
    title: str
    level: str = "مبتدئ"
    instructions: str = ""
    material: dict = {}
    answer: dict
    published: bool = True


@router.post("/training")
def create_exercise(body: ExerciseIn, user: User = Depends(require("training.manage")), db: Session = Depends(get_db)):
    try:
        ans = training.validate_answer(body.answer)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if not body.title.strip():
        raise HTTPException(422, "اكتب عنوان التمرين")
    e = Exercise(title=body.title.strip(), level=body.level, instructions=body.instructions, material=body.material, answer=ans,
                 published=body.published, created_by=user.id)
    db.add(e)
    db.commit()
    return _ex(e, True)


@router.get("/training/{eid}/submissions")
def all_submissions(eid: int, _: User = Depends(require("training.manage")), db: Session = Depends(get_db)):
    users = {u.id: u.full_name or u.email for u in db.scalars(select(User))}
    return [{**_sub(s), "user": users.get(s.user_id)} for s in db.scalars(select(Submission).where(Submission.exercise_id == eid).order_by(Submission.id.desc()))]


class RegradeIn(BaseModel):
    score: float
    note: str = ""


@router.post("/training/submissions/{sid}/grade")
def regrade(sid: int, body: RegradeIn, user: User = Depends(require("training.manage")), db: Session = Depends(get_db)):
    s = db.get(Submission, sid)
    if s is None:
        raise HTTPException(404, "غير موجود")
    if not 0 <= body.score <= 100:
        raise HTTPException(422, "الدرجة من 0 إلى 100")
    before = {"score": training.final_score(s)}
    s.trainer_score, s.trainer_note = body.score, body.note.strip()
    record(db, user, "training.grade", "submission", s.id, before=before, after={"score": body.score})
    db.commit()
    return _sub(s)
