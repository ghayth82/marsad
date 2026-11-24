"""صندوق بلاغات الجمهور عبر بوت تيليغرام نفسه.

قارئ واحد لرسائل البوت (getUpdates بمؤشر محفوظ) يخدم أمرين: رموز ربط حسابات الفريق (/start الرمز)،
وكل رسالة أخرى بلاغ له رقم متابعة. المحرّر يحوّل البلاغ إلى ادّعاء أو يرفضه، وحين يُعتمد الحكم
يصل صاحب البلاغ الرد إن اختار المحرّر ذلك. معرّف المحادثة يُحفظ مشفّرًا ويُمحى بعد 90 يومًا.
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.audit import record
from marsad.db import utcnow
from marsad.models import User
from marsad.models.claims import Claim
from marsad.models.engines import Notification
from marsad.models.tools import Tip
from marsad.rbac.service import get_setting, set_setting
from marsad.reports import alerts

OFFSET = "alerts.telegram_offset"
RETENTION_DAYS = 90
MAX_FILE = 20 * 1024 * 1024  # حد Bot API للتنزيل
URL_RE = re.compile(r"https?://\S+")

WELCOME = ("أهلًا بك في صندوق بلاغات «مرصد التحقق».\n"
           "أرسل الخبر أو الرابط أو الصورة أو التسجيل الذي تشك فيه، وسيصلك رقم متابعة.\n"
           "لا نحفظ منك إلا معرّف هذه المحادثة لنرسل لك النتيجة، ويُمحى بعد 90 يومًا.")


class TipError(Exception):
    pass


def _code(db: Session) -> str:
    while True:
        c = "T-" + secrets.token_hex(3).upper()
        if not db.scalar(select(Tip.id).where(Tip.code == c)):
            return c


def _download(token: str, file_id: str) -> tuple[bytes, str] | None:
    meta = alerts.tg_call(token, "getFile", file_id=file_id)
    path = (meta.get("result") or {}).get("file_path") if meta.get("ok") else None
    if not path or (meta["result"].get("file_size") or 0) > MAX_FILE:
        return None
    try:
        r = httpx.get(f"{alerts.tg_base()}/file/bot{token}/{path}", timeout=60)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    return r.content, path.rsplit("/", 1)[-1]


def _media_of(msg: dict) -> tuple[str, str] | None:
    if msg.get("photo"):
        return msg["photo"][-1]["file_id"], "image"
    for k, kind in (("video", "video"), ("voice", "audio"), ("audio", "audio"), ("video_note", "video")):
        if msg.get(k):
            return msg[k]["file_id"], kind
    doc = msg.get("document")
    if doc and (doc.get("mime_type") or "").split("/")[0] in ("image", "video", "audio"):
        return doc["file_id"], doc["mime_type"].split("/")[0]
    return None


def _store_tip(db: Session, token: str, msg: dict) -> Tip:
    text = (msg.get("text") or msg.get("caption") or "").strip()
    tip = Tip(code=_code(db), chat_ref=crypto.encrypt(str(msg["chat"]["id"])), text=text[:8000], urls=URL_RE.findall(text)[:10])
    media = _media_of(msg)
    if media:
        got = _download(token, media[0])
        if got:
            from marsad.labs import media as lab

            try:
                m = lab.ingest(db, got[0], got[1], origin="tip", run=False)
                tip.media_id, tip.media_kind = m.id, m.kind
            except lab.LabError:
                tip.note = "تعذّر قراءة الملف المرفق"
        else:
            tip.note = "الملف المرفق أكبر من المسموح أو تعذّر تنزيله"
    db.add(tip)
    db.flush()
    db.add(Notification(kind="tip.new", text=f"📨 بلاغ جديد {tip.code}: {(text or tip.media_kind or 'ملف')[:120]}\n/tips"))
    return tip


def poll(db: Session) -> dict:
    """يقرأ رسائل البوت الجديدة مرة واحدة. يعيد عدد البلاغات وعمليات الربط."""
    token = alerts.tg_token(db)
    if not token:
        return {"tips": 0, "linked": 0}
    offset = int(get_setting(db, OFFSET, 0) or 0)
    args = {"timeout": 0, "allowed_updates": ["message"]}
    if offset:
        args["offset"] = offset + 1
    upd = alerts.tg_call(token, "getUpdates", **args)
    tips = linked = 0
    last = offset
    links = dict(get_setting(db, alerts.LINKS, {}) or {})
    for u in upd.get("result", []) if upd.get("ok") else []:
        uid = int(u.get("update_id") or 0)
        if uid <= offset:
            continue
        last = max(last, uid)
        msg = u.get("message") or {}
        if not msg.get("chat"):
            continue
        chat = msg["chat"]["id"]
        parts = (msg.get("text") or "").split()
        if parts and parts[0] == "/start":
            if len(parts) == 2 and parts[1] in links:
                user_id = links.pop(parts[1])["user_id"]
                for c in [c for c, v in links.items() if v["user_id"] == user_id]:
                    links.pop(c)
                chats = dict(get_setting(db, alerts.CHATS, {}) or {})
                chats[str(user_id)] = chat
                set_setting(db, alerts.CHATS, chats)
                set_setting(db, alerts.LINKS, links)
                db.flush()
                alerts.tg_call(token, "sendMessage", chat_id=chat, text="رُبط حسابك في «مرصد التحقق». ستصلك التنبيهات هنا.")
                linked += 1
            else:
                alerts.tg_call(token, "sendMessage", chat_id=chat, text=WELCOME)
            continue
        if msg.get("chat", {}).get("type", "private") != "private":
            continue  # البلاغات من المحادثات الخاصة فقط
        if not (msg.get("text") or msg.get("caption") or _media_of(msg)):
            continue
        tip = _store_tip(db, token, msg)
        tips += 1
        alerts.tg_call(token, "sendMessage", chat_id=chat,
                       text=f"وصل بلاغك، ورقم متابعته {tip.code}.\nسنرسل لك النتيجة هنا حين ينتهي التحقق.")
    if last != offset:
        set_setting(db, OFFSET, last)
    db.flush()
    return {"tips": tips, "linked": linked}


# ---------- عمل المحرّر ----------

def to_claim(db: Session, user: User, tip: Tip, text: str, reply: bool = True) -> Claim:
    from marsad.claims.core import create_claim

    if tip.status not in ("new",):
        raise TipError("عولج هذا البلاغ من قبل")
    c = create_claim(db, user, text or tip.text, origin="tip")
    c.meta = {**(c.meta or {}), "tip": tip.code}
    if tip.media_id:
        from marsad.models.claims import Evidence

        db.add(Evidence(claim_id=c.id, kind="file", title=f"مرفق البلاغ {tip.code}", note="أرسله المُبلِّغ", added_by=user.id,
                        data={"media_id": tip.media_id}))
    for u in tip.urls:
        from marsad.models.claims import Evidence

        db.add(Evidence(claim_id=c.id, kind="link", title=f"رابط من البلاغ {tip.code}", url=u[:1000], added_by=user.id))
    tip.status, tip.claim_id, tip.reply_on_verdict, tip.handled_by = "claim", c.id, reply, user.id
    record(db, user, "tip.claim", "tip", tip.code, {"status": "new"}, {"claim_id": c.id, "reply": reply})
    return c


def reject(db: Session, user: User, tip: Tip, note: str = "", reply_text: str = "") -> Tip:
    if tip.status != "new":
        raise TipError("عولج هذا البلاغ من قبل")
    tip.status, tip.note, tip.handled_by = "rejected", note[:2000], user.id
    if reply_text.strip():
        _send(db, tip, reply_text.strip())
    record(db, user, "tip.reject", "tip", tip.code, {"status": "new"}, {"note": note})
    return tip


def _send(db: Session, tip: Tip, text: str) -> bool:
    token = alerts.tg_token(db)
    if not token or not tip.chat_ref:
        return False
    try:
        chat = crypto.decrypt(tip.chat_ref)
    except ValueError:
        return False
    r = alerts.tg_call(token, "sendMessage", chat_id=int(chat) if chat.lstrip("-").isdigit() else chat, text=text)
    if r.get("ok"):
        tip.reply_text, tip.replied_at = text, utcnow()
        return True
    return False


def answer_verdicts(db: Session) -> int:
    """يرد على أصحاب البلاغات التي اعتُمد حكم ادّعائها."""
    n = 0
    for tip in db.scalars(select(Tip).where(Tip.status == "claim", Tip.reply_on_verdict.is_(True), Tip.replied_at.is_(None))).all():
        c = db.get(Claim, tip.claim_id) if tip.claim_id else None
        v = next((v for v in reversed(c.verdicts) if v.status == "approved"), None) if c else None
        if not v:
            continue
        expl = (v.explanation or "").strip()
        text = (f"نتيجة التحقق من بلاغك {tip.code}:\n«{c.text[:300]}»\nالحكم: {v.label}"
                + (f"\n{expl[:700]}" if expl else "") + "\nشكرًا لمساعدتك.")
        if _send(db, tip, text):
            tip.status = "answered"
            n += 1
    return n


def purge(db: Session, now=None) -> int:
    """يمحو معرّفات المحادثات الأقدم من 90 يومًا (البلاغ نفسه يبقى دون صاحبه)."""
    cutoff = (now or utcnow()) - timedelta(days=RETENTION_DAYS)
    rows = db.scalars(select(Tip).where(Tip.received_at < cutoff, Tip.chat_ref.is_not(None))).all()
    for t in rows:
        t.chat_ref = None
    return len(rows)


def view(t: Tip) -> dict:
    return {"id": t.id, "code": t.code, "text": t.text, "urls": t.urls, "media_id": t.media_id, "media_kind": t.media_kind,
            "status": t.status, "claim_id": t.claim_id, "reply_on_verdict": t.reply_on_verdict, "replied_at": t.replied_at.isoformat() if t.replied_at else None,
            "reply_text": t.reply_text, "note": t.note, "can_reply": t.chat_ref is not None, "received_at": t.received_at.isoformat()}
