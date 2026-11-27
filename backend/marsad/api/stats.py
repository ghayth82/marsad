"""البند 12: صفحة «الإحصاءات». كل رقم يُفتح على ما حُسب منه عبر /api/stats/rows."""

from __future__ import annotations

import csv
import io
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from marsad.analytics import core
from marsad.api.deps import require
from marsad.db import get_db
from marsad.models import User
from marsad.models.claims import Claim
from marsad.rbac.service import has_permission

router = APIRouter(prefix="/api/stats", tags=["stats"])
view = require("stats.view")


def _period(days, start, end):
    try:
        return core.period(days, start, end)
    except ValueError:
        raise HTTPException(422, "التاريخ بصيغة 2026-11-01") from None


@router.get("/options")
def options(_: User = Depends(view)):
    return core.options()


@router.get("")
def dashboards(days: int = 30, start: str | None = None, end: str | None = None, topic: str | None = None,
               platform: str | None = None, user: User = Depends(view), db: Session = Depends(get_db)):
    s, e = _period(days, start, end)
    out = core.all_dashboards(db, s, e, topic or None, platform or None, has_permission(user, "stats.team"))
    out["can_team"] = has_permission(user, "stats.team")
    return out


@router.get("/spread/{cid}")
def spread(cid: int, _: User = Depends(view), db: Session = Depends(get_db)):
    c = db.get(Claim, cid)
    if c is None:
        raise HTTPException(404, "غير موجود")
    return core.spread(db, c)


@router.get("/rows")
def rows(kind: str, ids: str = Query(""), _: User = Depends(view), db: Session = Depends(get_db)):
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
        return {"rows": core.rows(db, kind, id_list)}
    except ValueError:
        raise HTTPException(422, "قائمة غير صحيحة") from None


def _impact(days, start, end, db):
    s, e = _period(days, start, end)
    return s, e, core.impact(db, s, e), core.verification(db, s, e)


@router.get("/impact.csv")
def impact_csv(days: int = 30, start: str | None = None, end: str | None = None,
               _: User = Depends(require("stats.view", "data.export")), db: Session = Depends(get_db)):
    s, e, imp, ver = _impact(days, start, end, db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["المؤشر", "القيمة", "المعرّفات"])
    rows_ = [("بداية الفترة", s.date().isoformat(), ""), ("نهاية الفترة", e.date().isoformat(), ""),
             ("ادّعاءات ظهرت", ver["claims"]["n"], ver["claims"]["drill"]["ids"]),
             ("تحققات معتمدة", imp["verified"]["n"], imp["verified"]["drill"]["ids"]),
             ("أحكام غير «صحيح»", imp["not_true"]["n"], imp["not_true"]["drill"]["ids"]),
             ("صحّحه ناشره بعد التحقق", imp["publisher_corrected"]["n"], imp["publisher_corrected"]["drill"]["ids"]),
             ("نسبة ما صحّحه ناشره ٪", imp["publisher_corrected"]["pct"], ""),
             ("قيس انتشاره قبل الحكم وبعده", imp["spread_measured"]["n"], imp["spread_measured"]["drill"]["ids"]),
             ("هبط انتشاره بعد التصحيح", imp["spread_dropped"]["n"], imp["spread_dropped"]["drill"]["ids"]),
             ("وسيط زمن التحقق (ساعة)", ver["time_to_verdict_hours"]["median"], "")]
    for k, v, ids in rows_:
        w.writerow([k, "" if v is None else v, " ".join(map(str, ids)) if ids else ""])
    w.writerow([])
    w.writerow(["الطريقة", imp["method"], ""])
    from marsad.core import naming

    body = "﻿" + buf.getvalue()
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers=naming.export("reports", f"تصدير - أثر التحقق - {naming.today()}.csv", body))


@router.get("/impact/print")
def impact_print(days: int = 30, start: str | None = None, end: str | None = None,
                 _: User = Depends(view), db: Session = Depends(get_db)):
    s, e, imp, ver = _impact(days, start, end, db)
    pct = lambda v: "—" if v is None else f"{v}٪"  # noqa: E731
    t = ver["time_to_verdict_hours"]
    labels = "".join(f"<tr><td>{escape(x['label'])}</td><td>{x['n']}</td></tr>" for x in ver["labels"])
    html = f"""<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>تقرير الأثر</title>
<style>body{{font-family:system-ui,'Noto Sans Arabic',sans-serif;max-width:820px;margin:24px auto;line-height:1.7}}
.k{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.k div{{border:1px solid #ddd;border-radius:10px;padding:10px}}
.k b{{font-size:26px;display:block}}table{{border-collapse:collapse}}td{{border:1px solid #ddd;padding:4px 10px}}
@media print{{button{{display:none}}}}</style><button onclick="print()">طباعة أو حفظ PDF</button>
<h1>تقرير الأثر</h1><p>من {s.date().isoformat()} إلى {e.date().isoformat()}</p>
<div class="k"><div><b>{imp['verified']['n']}</b>تحقق معتمد</div>
<div><b>{pct(imp['publisher_corrected']['pct'])}</b>صحّحه ناشره بعد التحقق ({imp['publisher_corrected']['n']})</div>
<div><b>{imp['spread_dropped']['n']}</b>شائعة هبط انتشارها بعد التصحيح (من {imp['spread_measured']['n']} قيس انتشارها)</div>
<div><b>{ver['claims']['n']}</b>ادّعاء ظهر في الفترة</div>
<div><b>{'—' if t['median'] is None else t['median']}</b>ساعة وسيط زمن التحقق</div>
<div><b>{imp['not_true']['n']}</b>حكم غير «صحيح»</div></div>
<h2>توزيع الأحكام</h2><table>{labels}</table>
<h2>الطريقة</h2><p>{escape(imp['method'])} كل رقم يُتتبع إلى مواده من صفحة «الإحصاءات» في البرنامج.</p></html>"""
    return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"})
