"""التنبيهات: داخل البرنامج دائمًا، وعلى تيليغرام لمن ربط حسابه.

مسار التنبيه: حدث (عودة شائعة، شائعة تنتشر بسرعة، مؤشر حملة، مصدر توقف، ما تتابعه) ← Notification ←
الموزّع (كل دقيقة) يرسل لكل مستخدم يحق له رؤيته وفعّل القناة، خارج ساعات الهدوء، مرة واحدة فقط.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.db import utcnow
from marsad.models import User
from marsad.models.engines import Notification
from marsad.models.reports import AlertDelivery
from marsad.rbac.service import effective_permissions, get_setting, set_setting

URGENT = {"rumor.return", "rumor.spike", "campaign", "follow"}
AUDIENCE = {"rumor": "monitor.view", "campaign": "monitor.view", "follow": None, "source": "sources.manage",
            "engine": "engines.manage", "report": "monitor.view", "story": "monitor.view"}
TG_SETTING, CHATS, LINKS = "alerts.telegram", "alerts.telegram_chats", "alerts.telegram_links"
TZ = "Asia/Amman"
ICON = {"rumor.return": "🔁", "rumor.spike": "🚨", "campaign": "🕸", "follow": "🔔", "source.error": "⚠️", "report.morning": "☀️",
        "report.weekly": "📊"}


def tg_base() -> str:
    return os.environ.get("MARSAD_TELEGRAM_API", "https://api.telegram.org").rstrip("/")


def tg_token(db: Session) -> str | None:
    enc = (get_setting(db, TG_SETTING, {}) or {}).get("token")
    if not enc:
        return None
    try:
        return crypto.decrypt(enc)
    except ValueError:
        return None


def tg_call(token: str, method: str, **payload) -> dict:
    try:
        r = httpx.post(f"{tg_base()}/bot{token}/{method}", json=payload, timeout=20)
        d = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "description": f"تعذّر الاتصال بتيليغرام: {e.__class__.__name__}"}
    return d if isinstance(d, dict) else {"ok": False}


def set_bot(db: Session, token: str | None, actor: User) -> dict:
    if not token:
        set_setting(db, TG_SETTING, {}, actor)
        return {"ok": True, "bot": None}
    me = tg_call(token.strip(), "getMe")
    if not me.get("ok"):
        raise ValueError(me.get("description") or "رمز البوت مرفوض")
    username = me["result"].get("username", "")
    set_setting(db, TG_SETTING, {"token": crypto.encrypt(token.strip()), "username": username, "masked": crypto.mask(token.strip())}, actor)
    return {"ok": True, "bot": username}


def bot_info(db: Session) -> dict:
    s = get_setting(db, TG_SETTING, {}) or {}
    return {"configured": bool(s.get("token")), "username": s.get("username"), "masked": s.get("masked")}


def link_code(db: Session, user: User) -> dict:
    """رمز ربط: يرسله المستخدم إلى البوت (/start الرمز)، ثم «تحقّق» يلتقط معرّف المحادثة."""
    links = dict(get_setting(db, LINKS, {}) or {})
    code = secrets.token_hex(4)
    links[code] = {"user_id": user.id, "at": utcnow().isoformat()}
    set_setting(db, LINKS, links)
    info = bot_info(db)
    return {"code": code, "bot": info["username"], "link": f"https://t.me/{info['username']}?start={code}" if info["username"] else None}


def check_link(db: Session, user: User) -> dict:
    token = tg_token(db)
    if not token:
        raise ValueError("لم يُضف بوت تيليغرام بعد (الإدارة ← التنبيهات)")
    links = dict(get_setting(db, LINKS, {}) or {})
    mine = {c for c, v in links.items() if v["user_id"] == user.id}
    upd = tg_call(token, "getUpdates", timeout=0, allowed_updates=["message"])
    for u in upd.get("result", []) if upd.get("ok") else []:
        msg = u.get("message") or {}
        parts = (msg.get("text") or "").split()
        if len(parts) == 2 and parts[0] == "/start" and parts[1] in mine:
            chats = dict(get_setting(db, CHATS, {}) or {})
            chats[str(user.id)] = msg["chat"]["id"]
            set_setting(db, CHATS, chats)
            for c in mine:
                links.pop(c, None)
            set_setting(db, LINKS, links)
            tg_call(token, "sendMessage", chat_id=msg["chat"]["id"], text="رُبط حسابك في «مرصد التحقق». ستصلك التنبيهات هنا.")
            return {"linked": True}
    return {"linked": False, "note": "لم تصل رسالة الربط بعد. افتح الرابط واضغط «ابدأ» في تيليغرام، ثم أعد المحاولة."}


def chat_of(db: Session, user: User) -> int | None:
    return (get_setting(db, CHATS, {}) or {}).get(str(user.id))


def unlink(db: Session, user: User) -> None:
    chats = dict(get_setting(db, CHATS, {}) or {})
    chats.pop(str(user.id), None)
    set_setting(db, CHATS, chats)


# ---------- التوزيع ----------

def _audience(db: Session, n: Notification) -> list[User]:
    if n.user_id:
        u = db.get(User, n.user_id)
        return [u] if u and u.is_active else []
    need = AUDIENCE.get(n.kind.split(".")[0], "monitor.view")
    return [u for u in db.scalars(select(User).where(User.is_active.is_(True))) if need is None or need in effective_permissions(u)]


def _quiet(prefs: dict, now: datetime) -> bool:
    q = (prefs.get("alerts") or {}).get("quiet_hours")
    if not q:
        return False
    h = now.astimezone(ZoneInfo(TZ)).hour
    a, b = q
    return a <= h < b if a < b else (h >= a or h < b)


def dispatch(db: Session, now: datetime | None = None, max_age_hours: int = 6) -> dict:
    """يرسل التنبيهات الجديدة على تيليغرام. التنبيه داخل البرنامج موجود أصلًا."""
    from marsad.preferences import effective_preferences

    now = now or utcnow()
    token = tg_token(db)
    out = {"sent": 0, "skipped": 0, "failed": 0}
    if not token:
        return out
    since = now - timedelta(hours=max_age_hours)
    for n in db.scalars(select(Notification).where(Notification.created_at >= since).order_by(Notification.id)):
        for u in _audience(db, n):
            if db.scalars(select(AlertDelivery.id).where(AlertDelivery.notification_id == n.id, AlertDelivery.user_id == u.id,
                                                       AlertDelivery.channel == "telegram")).first():
                continue
            prefs = effective_preferences(db, u)
            a = prefs.get("alerts") or {}
            chat = chat_of(db, u)
            if "telegram" not in a.get("channels", []) or not chat:
                continue
            if a.get("urgent_only") and n.kind not in URGENT:
                continue
            if _quiet(prefs, now) and n.kind not in ("rumor.spike", "rumor.return"):
                continue  # ساعات الهدوء: يُؤجَّل (يُرسل حين تنتهي، ما دام أحدث من 6 ساعات)
            r = tg_call(token, "sendMessage", chat_id=chat, text=f"{ICON.get(n.kind, '•')} {n.text}"[:4000], disable_web_page_preview=True)
            ok = bool(r.get("ok"))
            db.add(AlertDelivery(notification_id=n.id, user_id=u.id, channel="telegram", status="sent" if ok else "failed",
                                 detail="" if ok else str(r.get("description", ""))[:300]))
            out["sent" if ok else "failed"] += 1
    db.flush()
    return out


# ---------- مولّدات التنبيه ----------

def scan(db: Session, now: datetime | None = None, window_min: int = 60) -> int:
    """كل دقيقة: شائعة تنتشر بسرعة (3 مصادر مختلفة أو أكثر خلال ساعة)، ومؤشرات الحملات، وما يتابعه كل مستخدم."""
    from marsad.models.claims import Claim, ClaimItem
    from marsad.models.monitoring import Item, Source
    from marsad.monitor import social
    from marsad.preferences import effective_preferences
    from marsad.text import normalize_ar

    now = now or utcnow()
    since = now - timedelta(minutes=window_min)
    made = 0
    seen_keys = {n.text for n in db.scalars(select(Notification).where(Notification.created_at >= now - timedelta(days=2)))}

    def notify(kind: str, text: str, user_id: int | None = None):
        nonlocal made
        if text in seen_keys:
            return
        seen_keys.add(text)
        db.add(Notification(kind=kind, text=text, user_id=user_id))
        made += 1

    # شائعة تنتشر بسرعة
    recent = db.execute(select(ClaimItem.claim_id, Item.outlet_id).join(Item, Item.id == ClaimItem.item_id)
                        .where(ClaimItem.added_at >= since)).all()
    by_claim: dict[int, set] = {}
    for cid, oid in recent:
        by_claim.setdefault(cid, set()).add(oid)
    for cid, outlets in by_claim.items():
        if len(outlets) >= 3:
            c = db.get(Claim, cid)
            notify("rumor.spike", f"شائعة تنتشر بسرعة: «{c.text[:160]}» في {len(outlets)} مصادر خلال ساعة. البطاقة: /claims/{cid}")

    # مؤشرات الحملات المنسّقة
    items = list(db.scalars(select(Item).join(Source, Source.id == Item.source_id).where(Source.kind.in_(("social", "telegram")),
                                                                                          Item.captured_at >= now - timedelta(hours=3))))
    for c in social.campaigns(items):
        notify("campaign", f"مؤشر حملة منسّقة ({c['kind']}): {len(c['accounts'])} حساب خلال {round(c['span_minutes'])} دقيقة، بدءًا من «{c['items'][0]['title'][:100]}»")

    # ما يتابعه كل مستخدم (مواضيع وكيانات)
    new_items = list(db.scalars(select(Item).where(Item.captured_at >= now - timedelta(minutes=5))))
    if new_items:
        for u in db.scalars(select(User).where(User.is_active.is_(True))):
            f = effective_preferences(db, u).get("follows") or {}
            terms = [(t, normalize_ar(t)) for t in (f.get("topics") or []) + (f.get("entities") or []) if t.strip()]
            for it in new_items:
                hay = normalize_ar(f"{it.title} {it.text[:3000]}")
                hit = next((t for t, nt in terms if nt and nt in hay), None)
                if hit:
                    notify("follow", f"«{hit}» في مادة جديدة: {it.title[:160]} — {it.url}", u.id)
    db.flush()
    return made
