"""رموز الوصول للأنظمة الخارجية وإشعارات Webhook الموقّعة.

الرمز: «mrs_» ثم 40 حرفًا عشوائيًا؛ يُعرض مرة واحدة ويُحفظ SHA-256 منه فقط.
التوقيع: X-Marsad-Signature: sha256=HMAC(السر، "<الطابع الزمني>.<جسم الطلب>")، والطابع في X-Marsad-Timestamp.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.audit import record
from marsad.db import utcnow
from marsad.models import User
from marsad.models.org import ApiToken, Webhook, WebhookDelivery

SCOPES = {"verdicts.read": "قراءة الأحكام المعتمدة", "claims.read": "قراءة الادّعاءات", "claims.write": "إنشاء ادّعاء"}
EVENTS = {"verdict.approved": "اعتماد حكم", "verdict.corrected": "تصحيح حكم معتمد"}
BACKOFF_MIN = [0, 1, 5, 30, 120, 720]  # دقائق بين المحاولات
PREFIX = "mrs_"


class ApiError_(ValueError):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(db: Session, actor: User, name: str, scopes: list[str], expires_days: int | None) -> tuple[ApiToken, str]:
    scopes = [s for s in dict.fromkeys(scopes) if s in SCOPES]
    if not scopes:
        raise ApiError_("اختر صلاحية واحدة على الأقل")
    if not name.strip():
        raise ApiError_("اسم الرمز مطلوب (مثل: نظام النشر)")
    raw = PREFIX + secrets.token_urlsafe(30)
    t = ApiToken(name=name.strip()[:120], prefix=raw[:10], token_hash=_hash(raw), scopes=scopes, created_by=actor.id,
                 expires_at=utcnow() + timedelta(days=expires_days) if expires_days else None)
    db.add(t)
    db.flush()
    record(db, actor, "api.token.create", "api_token", str(t.id), None, {"name": t.name, "scopes": scopes,
                                                                         "expires_at": t.expires_at.isoformat() if t.expires_at else None})
    return t, raw


def revoke(db: Session, actor: User, t: ApiToken) -> None:
    t.revoked_at = utcnow()
    record(db, actor, "api.token.revoke", "api_token", str(t.id), None, {"name": t.name})


def authenticate(db: Session, header: str | None, scope: str) -> ApiToken:
    """يعيد الرمز إن كان صالحًا ويملك الصلاحية، وإلا يرفع خطأ برسالة ورمز HTTP."""
    if not header or not header.lower().startswith("bearer "):
        raise PermissionError("401|أرسل الرمز في الترويسة Authorization: Bearer <الرمز>")
    t = db.scalar(select(ApiToken).where(ApiToken.token_hash == _hash(header[7:].strip())))
    now = utcnow()
    if t is None or t.revoked_at is not None:
        raise PermissionError("401|رمز غير صالح")
    exp = t.expires_at if (t.expires_at is None or t.expires_at.tzinfo) else t.expires_at.replace(tzinfo=now.tzinfo)
    if exp is not None and exp <= now:
        raise PermissionError("401|انتهت صلاحية الرمز")
    if scope not in (t.scopes or []):
        raise PermissionError("403|الرمز لا يملك هذه الصلاحية")
    t.last_used_at, t.uses = now, (t.uses or 0) + 1
    return t


def token_view(t: ApiToken) -> dict:
    now = utcnow()
    exp = t.expires_at
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "scopes": t.scopes, "expires_at": exp.isoformat() if exp else None,
            "revoked": t.revoked_at is not None, "expired": bool(exp and exp <= now), "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "uses": t.uses, "created_at": t.created_at.isoformat()}


# ---------- Webhook ----------

def create_webhook(db: Session, actor: User, url: str, events: list[str]) -> tuple[Webhook, str]:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ApiError_("الرابط يبدأ بـ https://")
    events = [e for e in dict.fromkeys(events) if e in EVENTS]
    if not events:
        raise ApiError_("اختر حدثًا واحدًا على الأقل")
    secret = secrets.token_hex(24)
    w = Webhook(url=url.strip()[:1000], secret_enc=crypto.encrypt(secret), events=events, created_by=actor.id)
    db.add(w)
    db.flush()
    record(db, actor, "api.webhook.create", "webhook", str(w.id), None, {"url": w.url, "events": events})
    return w, secret


def sign(secret: str, ts: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()


def emit(db: Session, event: str, payload: dict) -> int:
    """يضع الحدث في صندوق الصادر لكل Webhook مشترك؛ الإرسال في الخلفية (deliver)."""
    n = 0
    for w in db.scalars(select(Webhook).where(Webhook.active.is_(True))).all():
        if event in (w.events or []):
            db.add(WebhookDelivery(webhook_id=w.id, event=event, payload={"event": event, "created_at": utcnow().isoformat(), "data": payload}))
            n += 1
    return n


def deliver(db: Session, now: datetime | None = None, limit: int = 50) -> dict:
    now = now or utcnow()
    sent = failed = 0
    rows = db.scalars(select(WebhookDelivery).where(WebhookDelivery.status == "pending", WebhookDelivery.next_at <= now)
                      .order_by(WebhookDelivery.id).limit(limit)).all()
    for d in rows:
        w = db.get(Webhook, d.webhook_id)
        if w is None or not w.active:
            d.status = "failed"
            continue
        body = json.dumps({**d.payload, "delivery_id": d.id}, ensure_ascii=False).encode()
        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json; charset=utf-8", "X-Marsad-Event": d.event, "X-Marsad-Delivery": str(d.id),
                   "X-Marsad-Timestamp": ts, "X-Marsad-Signature": sign(crypto.decrypt(w.secret_enc), ts, body),
                   "User-Agent": "Marsad-Webhook/1"}
        d.attempts += 1
        try:
            r = httpx.post(w.url, content=body, headers=headers, timeout=15)
            d.last_code = r.status_code
            ok = 200 <= r.status_code < 300
            d.last_error = "" if ok else r.text[:300]
        except httpx.HTTPError as e:
            ok, d.last_code, d.last_error = False, 0, e.__class__.__name__
        if ok:
            d.status, d.sent_at = "sent", now
            sent += 1
        elif d.attempts >= len(BACKOFF_MIN):
            d.status = "failed"
            failed += 1
        else:
            d.next_at = now + timedelta(minutes=BACKOFF_MIN[d.attempts])
    return {"sent": sent, "failed": failed}


def webhook_view(db: Session, w: Webhook) -> dict:
    last = db.scalars(select(WebhookDelivery).where(WebhookDelivery.webhook_id == w.id).order_by(WebhookDelivery.id.desc()).limit(10)).all()
    return {"id": w.id, "url": w.url, "events": w.events, "active": w.active, "created_at": w.created_at.isoformat(),
            "deliveries": [{"id": d.id, "event": d.event, "status": d.status, "attempts": d.attempts, "last_code": d.last_code,
                            "last_error": d.last_error, "created_at": d.created_at.isoformat()} for d in last]}
