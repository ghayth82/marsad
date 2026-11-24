"""سجل التصحيحات: كل تعديل لحكم معتمد يُسجَّل بما كان وما صار وسببه، وصفحة عامة اختيارية دون أسماء ودون تقييمات."""

from __future__ import annotations

from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.models.claims import Claim, Verdict
from marsad.models.org import Correction
from marsad.rbac.service import get_setting

PUBLIC_KEY = "corrections.public"


def record_correction(db: Session, c: Claim, old: Verdict, new: Verdict, reason: str, by: int | None) -> Correction:
    snap = lambda v: {"label": v.label, "grade": v.evidence_grade, "explanation": v.explanation,  # noqa: E731
                      "approved_at": v.approved_at.isoformat() if v.approved_at else None}
    k = Correction(claim_id=c.id, before=snap(old), after=snap(new), reason=reason.strip(), verdict_id=new.id, by=by)
    db.add(k)
    db.flush()
    return k


def view(db: Session, k: Correction, internal: bool = True) -> dict:
    c = db.get(Claim, k.claim_id)
    out = {"id": k.id, "claim_id": k.claim_id, "claim": c.text if c else "", "before": {x: k.before.get(x) for x in ("label", "grade", "explanation")},
           "after": {x: k.after.get(x) for x in ("label", "grade", "explanation")}, "reason": k.reason, "at": k.at.isoformat(),
           "public": k.public}
    if internal:
        out["by"] = k.by
    return out


def listing(db: Session, public_only: bool = False) -> list[Correction]:
    q = select(Correction).order_by(Correction.at.desc()).limit(500)
    if public_only:
        q = q.where(Correction.public.is_(True))
    return list(db.scalars(q).all())


def is_public(db: Session) -> bool:
    return bool(get_setting(db, PUBLIC_KEY, False))


def public_html(db: Session) -> str:
    org = get_setting(db, "org.name", "مرصد التحقق") or "مرصد التحقق"
    tz = ZoneInfo("Asia/Amman")
    rows = []
    for k in listing(db, public_only=True):
        c = db.get(Claim, k.claim_id)
        rows.append(f"""<article><time>{k.at.astimezone(tz).date().isoformat()}</time><h2>«{escape(c.text if c else '')}»</h2>
<p><b>كان الحكم:</b> {escape(k.before.get('label', ''))} · <b>صار:</b> {escape(k.after.get('label', ''))}</p>
<p><b>سبب التصحيح:</b> {escape(k.reason or '—')}</p>
<p class="m">{escape(k.after.get('explanation') or '')}</p></article>""")
    body = "".join(rows) or "<p>لا تصحيحات حتى الآن.</p>"
    return f"""<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>سجل التصحيحات — {escape(org)}</title>
<style>body{{font-family:system-ui,'Noto Sans Arabic',sans-serif;max-width:760px;margin:24px auto;padding:0 16px;line-height:1.8;color:#18202a}}
article{{border-bottom:1px solid #dde1e5;padding:14px 0}}h2{{font-size:17px;margin:4px 0}}time,.m{{color:#5b6673;font-size:14px}}</style>
<h1>سجل التصحيحات</h1><p class="m">{escape(org)} يصحّح أحكامه علنًا حين تظهر أدلة جديدة. كل تصحيح بما كان وما صار وسببه.</p>{body}</html>"""
