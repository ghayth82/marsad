"""موصلات التواصل (إعدادها من الإدارة) ومؤشرات الحملات المنسّقة."""

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
from marsad.models.monitoring import Item, Source
from marsad.monitor import social

router = APIRouter(prefix="/api/social", tags=["social"])
manage = require("system.manage")
view = require("monitor.view")


@router.get("/providers")
def providers(_: User = Depends(manage), db: Session = Depends(get_db)):
    waiting = {}
    for s in db.scalars(select(Source).where(Source.kind == "social")):
        p = (s.meta or {}).get("platform")
        waiting[p] = waiting.get(p, 0) + 1
    return {"platforms": [{**x, "sources": waiting.get(x["platform"], 0)} for x in social.status(db)],
            "providers": {k: v["ar"] for k, v in social.PROVIDERS.items()},
            "note": "لا يشترك البرنامج في أي خدمة ولا ينفق شيئًا: المفاتيح تُضاف هنا يدويًا وتُحفظ مشفّرة."}


class ProviderIn(BaseModel):
    provider: str | None
    credentials: dict[str, str] = {}


@router.put("/providers/{platform}")
def set_provider(platform: str, body: ProviderIn, user: User = Depends(manage), db: Session = Depends(get_db)):
    try:
        st = social.save_config(db, platform, body.provider, body.credentials, user)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    record(db, user, "social.provider", "platform", platform, after={"provider": body.provider})  # المفتاح لا يُسجَّل
    db.commit()
    return st


class TestIn(BaseModel):
    handle: str
    url: str = ""


@router.post("/providers/{platform}/test")
def test_provider(platform: str, body: TestIn, _: User = Depends(manage), db: Session = Depends(get_db)):
    """يقرأ حسابًا واحدًا دون حفظ شيء، للتأكد أن المفتاح يعمل."""
    try:
        entries, _meta = social.read_social(db, body.url or f"https://{platform}.com/{body.handle}", {"platform": platform, "handle": body.handle})
    except social.SocialError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "count": len(entries), "sample": [{"url": e["url"], "title": e["title"], "published_at": e["published_at"].isoformat() if e["published_at"] else None}
                                                          for e in entries[:5]]}


@router.get("/campaigns")
def campaigns(hours: int = 24, _: User = Depends(view), db: Session = Depends(get_db)):
    hours = max(1, min(hours, 24 * 14))
    since = utcnow() - timedelta(hours=hours)
    kinds = ("social", "telegram")
    items = list(db.scalars(select(Item).join(Source, Source.id == Item.source_id).where(Source.kind.in_(kinds), Item.captured_at >= since)))
    return {"hours": hours, "items": len(items), "clusters": social.campaigns(items),
            "note": "مؤشرات على تنسيق محتمل: نص متطابق من حسابات عدة، الرابط نفسه، وسم يتفجّر. ليست حكمًا؛ افحص الحسابات وتاريخها قبل أي استنتاج."}
