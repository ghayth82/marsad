"""الدخول: كلمات مرور Argon2، قفل مؤقت بعد محاولات خاطئة، تحقق بخطوتين، جلسات، ودعوات."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.audit import record
from marsad.config import get_settings
from marsad.db import utcnow
from marsad.models import Invite, SessionToken, User

_ph = PasswordHasher()
MIN_PASSWORD = 10


class AuthError(Exception):
    """رسالة آمنة للعرض: لا تكشف هل البريد موجود أم لا."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"كلمة المرور قصيرة: {MIN_PASSWORD} أحرف على الأقل")
    return _ph.hash(password)


def normalize_email(email: str) -> str:
    return email.strip().lower()


# ---------- الدخول ----------

def authenticate(db: Session, email: str, password: str, totp_code: str | None = None,
                 ip: str = "", now: datetime | None = None) -> User:
    s = get_settings()
    now = now or utcnow()
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    generic = AuthError("البريد أو كلمة المرور غير صحيحة")
    if user is None or not user.password_hash:
        _ph.hash("timing-equalizer")  # لا نكشف وجود الحساب بفرق الوقت
        record(db, None, "login.failed", "email", normalize_email(email), ip=ip)
        db.commit()
        raise generic
    if user.locked_until and user.locked_until > now:
        mins = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        record(db, user, "login.locked", "user", str(user.id), ip=ip)
        db.commit()
        raise AuthError(f"الحساب مقفل مؤقتًا بسبب محاولات خاطئة. حاول بعد {mins} دقيقة.")
    if not user.is_active:
        raise generic
    try:
        _ph.verify(user.password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        user.failed_logins += 1
        if user.failed_logins >= s.max_failed_logins:
            user.locked_until = now + timedelta(minutes=s.lockout_minutes)
            user.failed_logins = 0
            record(db, user, "login.lockout", "user", str(user.id), ip=ip)
        else:
            record(db, user, "login.failed", "user", str(user.id), ip=ip)
        db.commit()
        raise generic
    if user.totp_enabled:
        if not totp_code:
            raise AuthError("أدخل رمز التحقق بخطوتين")
        if not pyotp.TOTP(user.totp_secret).verify(totp_code.strip(), valid_window=1):
            user.failed_logins += 1
            record(db, user, "login.totp_failed", "user", str(user.id), ip=ip)
            db.commit()
            raise AuthError("رمز التحقق بخطوتين غير صحيح")
    if _ph.check_needs_rehash(user.password_hash):
        user.password_hash = _ph.hash(password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    record(db, user, "login.success", "user", str(user.id), ip=ip)
    return user


def create_session(db: Session, user: User, ip: str = "", user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    db.add(SessionToken(token_hash=_hash_token(token), user_id=user.id,
                        expires_at=utcnow() + timedelta(hours=get_settings().session_hours),
                        ip=ip[:64], user_agent=user_agent[:300]))
    return token


def user_from_session(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    st = db.scalar(select(SessionToken).where(SessionToken.token_hash == _hash_token(token)))
    if st is None or st.expires_at <= utcnow():
        return None
    user = db.get(User, st.user_id)
    return user if user and user.is_active else None


def end_session(db: Session, token: str | None) -> None:
    if token:
        st = db.scalar(select(SessionToken).where(SessionToken.token_hash == _hash_token(token)))
        if st:
            db.delete(st)


def end_all_sessions(db: Session, user: User) -> None:
    for st in db.scalars(select(SessionToken).where(SessionToken.user_id == user.id)):
        db.delete(st)


# ---------- التحقق بخطوتين ----------

def start_totp(user: User) -> str:
    user.totp_secret = pyotp.random_base32()
    user.totp_enabled = False
    return pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name="Marsad")


def confirm_totp(db: Session, user: User, code: str) -> None:
    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(code.strip(), valid_window=1):
        raise AuthError("الرمز غير صحيح؛ تأكد من وقت جهازك وحاول مجددًا")
    user.totp_enabled = True
    record(db, user, "totp.enabled", "user", str(user.id))


def disable_totp(db: Session, actor: User, user: User) -> None:
    user.totp_enabled = False
    user.totp_secret = None
    record(db, actor, "totp.disabled", "user", str(user.id))


# ---------- الدعوات ----------

def create_invite(db: Session, actor: User, user: User, days: int = 7) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Invite(token_hash=_hash_token(token), user_id=user.id, created_by=actor.id,
                  expires_at=utcnow() + timedelta(days=days)))
    record(db, actor, "invite.create", "user", str(user.id))
    return token


def accept_invite(db: Session, token: str, password: str) -> User:
    inv = db.scalar(select(Invite).where(Invite.token_hash == _hash_token(token)))
    if inv is None or inv.used_at is not None or inv.expires_at <= utcnow():
        raise AuthError("رابط الدعوة غير صالح أو منتهٍ؛ اطلب رابطًا جديدًا من المدير")
    user = db.get(User, inv.user_id)
    user.password_hash = hash_password(password)
    inv.used_at = utcnow()
    record(db, user, "invite.accepted", "user", str(user.id))
    return user


def change_password(db: Session, user: User, old: str, new: str) -> None:
    try:
        _ph.verify(user.password_hash or "", old)
    except (VerifyMismatchError, InvalidHashError):
        raise AuthError("كلمة المرور الحالية غير صحيحة") from None
    user.password_hash = hash_password(new)
    record(db, user, "password.changed", "user", str(user.id))
