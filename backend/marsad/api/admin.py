"""الإدارة: المستخدمون وأدوارهم المتعددة، الصلاحيات الفردية، الأدوار، القوالب، التخزين، السجل."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad import preferences as prefs
from marsad.api.deps import require
from marsad.auth import service as auth
from marsad.core import storage_config
from marsad.db import get_db
from marsad.models import AuditLog, Role, User
from marsad.rbac import service as rbac
from marsad.rbac.permissions import PERMISSIONS

router = APIRouter(prefix="/api/admin", tags=["admin"])
manage_users = require("users.manage")
manage_system = require("system.manage")


def _fail(e: Exception, code: int = 409):
    raise HTTPException(code, str(e)) from None


def _role(db: Session, key: str) -> Role:
    role = db.scalar(select(Role).where(Role.key == key))
    if role is None:
        raise HTTPException(404, f"لا يوجد دور: {key}")
    return role


def _user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "المستخدم غير موجود")
    return user


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "is_active": u.is_active,
            "totp_enabled": u.totp_enabled, "has_password": bool(u.password_hash),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "locked": bool(u.locked_until), **rbac.explain(u)}


def role_out(r: Role) -> dict:
    return {"key": r.key, "id": r.id, "name_ar": r.name_ar, "name_en": r.name_en,
            "description": r.description, "builtin": r.builtin, "priority": r.priority,
            "permissions": sorted(rp.permission for rp in r.permissions)}


# ---------- الصلاحيات والأدوار ----------

@router.get("/permissions")
def permissions(_: User = Depends(manage_users)):
    return [{"key": k, **v} for k, v in PERMISSIONS.items()]


@router.get("/roles")
def roles(_: User = Depends(manage_users), db: Session = Depends(get_db)):
    return [role_out(r) for r in db.scalars(select(Role).order_by(Role.priority, Role.id))]


class RoleIn(BaseModel):
    key: str
    name_ar: str
    name_en: str = ""
    description: str = ""
    permissions: list[str]
    priority: int = 100


@router.post("/roles")
def create_role(body: RoleIn, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    try:
        role = rbac.create_role(db, actor, body.key, body.name_ar, body.permissions,
                                body.description, body.name_en, body.priority)
    except rbac.PermissionError_ as e:
        _fail(e)
    db.commit()
    return role_out(role)


class PermsIn(BaseModel):
    permissions: list[str]


@router.put("/roles/{key}/permissions")
def set_role_perms(key: str, body: PermsIn, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    role = _role(db, key)
    try:
        rbac.set_role_permissions(db, actor, role, body.permissions)
    except rbac.PermissionError_ as e:
        _fail(e)
    db.commit()
    return role_out(_role(db, key))


@router.delete("/roles/{key}")
def delete_role(key: str, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    try:
        rbac.delete_role(db, actor, _role(db, key))
    except rbac.PermissionError_ as e:
        _fail(e)
    db.commit()
    return {"ok": True}


@router.get("/roles/{key}/template")
def get_template(key: str, _: User = Depends(manage_users), db: Session = Depends(get_db)):
    from marsad.models import RoleTemplate

    tpl = db.get(RoleTemplate, _role(db, key).id)
    return tpl.data if tpl else {}


@router.put("/roles/{key}/template")
def put_template(key: str, data: dict, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    try:
        out = prefs.set_role_template(db, actor, _role(db, key).id, data)
    except ValueError as e:
        _fail(e, 422)
    db.commit()
    return out


# ---------- المستخدمون ----------

class RoleAssign(BaseModel):
    key: str
    expires_at: datetime | None = None


class UserIn(BaseModel):
    email: str
    full_name: str = ""
    roles: list[RoleAssign]


@router.get("/users")
def list_users(_: User = Depends(manage_users), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users")
def create_user(body: UserIn, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    email = auth.normalize_email(body.email)
    if "@" not in email:
        raise HTTPException(422, "البريد غير صحيح")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "يوجد مستخدم بهذا البريد")
    if not body.roles:
        raise HTTPException(422, "اختر دورًا واحدًا على الأقل")
    user = User(email=email, full_name=body.full_name)
    db.add(user)
    db.flush()
    for ra in body.roles:
        rbac.assign_role(db, actor, user, _role(db, ra.key), ra.expires_at)
    token = auth.create_invite(db, actor, user)
    db.commit()
    # الرابط يُعرض للمدير ليرسله بنفسه؛ البرنامج لا يرسل بريدًا باسمه
    return {"user": user_out(user), "invite_token": token}


@router.post("/users/{user_id}/invite")
def reinvite(user_id: int, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    user = _user(db, user_id)
    token = auth.create_invite(db, actor, user)
    db.commit()
    return {"invite_token": token}


class RolesSet(BaseModel):
    roles: list[RoleAssign]


@router.put("/users/{user_id}/roles")
def set_roles(user_id: int, body: RolesSet, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    user = _user(db, user_id)
    try:
        rbac.set_user_roles(db, actor, user, [(_role(db, r.key), r.expires_at) for r in body.roles])
    except rbac.PermissionError_ as e:
        _fail(e)
    db.commit()
    return user_out(_user(db, user_id))


class OverrideIn(BaseModel):
    permission: str
    effect: str | None  # grant | deny | null لإزالة الاستثناء
    expires_at: datetime | None = None


@router.put("/users/{user_id}/permissions")
def set_override(user_id: int, body: OverrideIn, actor: User = Depends(manage_users),
                 db: Session = Depends(get_db)):
    user = _user(db, user_id)
    try:
        rbac.set_override(db, actor, user, body.permission, body.effect, body.expires_at)
    except rbac.PermissionError_ as e:
        _fail(e)
    db.commit()
    return user_out(_user(db, user_id))


class ActiveIn(BaseModel):
    active: bool


@router.put("/users/{user_id}/active")
def set_active(user_id: int, body: ActiveIn, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    user = _user(db, user_id)
    try:
        rbac.set_user_active(db, actor, user, body.active)
        if not body.active:
            auth.end_all_sessions(db, user)
    except rbac.PermissionError_ as e:
        _fail(e)
    db.commit()
    return user_out(user)


@router.post("/users/{user_id}/unlock")
def unlock(user_id: int, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    user = _user(db, user_id)
    user.locked_until, user.failed_logins = None, 0
    from marsad.audit import record

    record(db, actor, "user.unlock", "user", str(user.id))
    db.commit()
    return user_out(user)


@router.delete("/users/{user_id}/totp")
def reset_totp(user_id: int, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    user = _user(db, user_id)
    auth.disable_totp(db, actor, user)
    db.commit()
    return user_out(user)


# ---------- الإعدادات ----------

class FourEyesIn(BaseModel):
    enabled: bool


@router.get("/settings/four-eyes")
def get_four_eyes(_: User = Depends(manage_users), db: Session = Depends(get_db)):
    return {"enabled": bool(rbac.get_setting(db, rbac.FOUR_EYES_KEY, False))}


@router.put("/settings/four-eyes")
def put_four_eyes(body: FourEyesIn, actor: User = Depends(manage_users), db: Session = Depends(get_db)):
    rbac.set_setting(db, rbac.FOUR_EYES_KEY, body.enabled, actor)
    db.commit()
    return {"enabled": body.enabled}


# ---------- التخزين ----------

@router.get("/storage")
def storage_status(_: User = Depends(manage_system)):
    return storage_config.storage_status()


class StorageIn(BaseModel):
    data_dir: str | None = None
    backup_dir: str | None = None
    move_data: bool = True


@router.post("/storage")
def storage_request(body: StorageIn, actor: User = Depends(manage_system), db: Session = Depends(get_db)):
    try:
        cfg = storage_config.request_change(data_dir=body.data_dir, backup_dir=body.backup_dir,
                                            move_data=body.move_data, requested_by=actor.email)
    except ValueError as e:
        _fail(e, 422)
    from marsad.audit import record

    record(db, actor, "storage.request", "storage", "", None, cfg["pending"])
    db.commit()
    return storage_config.storage_status()


@router.delete("/storage/pending")
def storage_cancel(actor: User = Depends(manage_system), db: Session = Depends(get_db)):
    storage_config.cancel_pending()
    from marsad.audit import record

    record(db, actor, "storage.cancel", "storage")
    db.commit()
    return storage_config.storage_status()


# ---------- سجل التدقيق ----------

@router.get("/audit")
def audit(limit: int = 200, _: User = Depends(require("audit.view")), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000)))
    return [{"id": a.id, "at": a.at.isoformat(), "actor_id": a.actor_id, "action": a.action,
             "target_type": a.target_type, "target_id": a.target_id, "before": a.before,
             "after": a.after, "ip": a.ip} for a in rows]


# ---------- ملف النقل ----------

class TransferIn(BaseModel):
    passphrase: str


@router.post("/transfer/export")
def transfer_export(body: TransferIn, actor: User = Depends(require("system.manage")), db: Session = Depends(get_db)):
    """ملف واحد بكل البيانات والملفات، محمي بعبارة مرور، لنقل النسخة إلى خادم أو جهاز آخر."""
    from datetime import datetime as _dt

    from marsad import transfer
    from marsad.core.paths import ensure_storage
    from marsad.db import get_engine

    name = f"marsad-{_dt.now().strftime('%Y%m%d-%H%M%S')}.marsad"
    out = ensure_storage().exports / name
    try:
        m = transfer.export_bundle(get_engine(), out, body.passphrase)
    except transfer.TransferError as e:
        raise HTTPException(422, str(e)) from None
    from marsad.audit import record

    record(db, actor, "transfer.export", "file", name, after={"tables": sum(m["tables"].values()), "files": m["files"]})
    db.commit()
    return {"name": name, "path": str(out), "size": out.stat().st_size, "records": sum(m["tables"].values()), "files": m["files"]}


@router.get("/transfer/{name}")
def transfer_download(name: str, _: User = Depends(require("system.manage"))):
    import re

    from fastapi.responses import FileResponse

    from marsad.core.paths import ensure_storage

    if not re.fullmatch(r"marsad-\d{8}-\d{6}\.marsad", name):
        raise HTTPException(404, "غير موجود")
    p = ensure_storage().exports / name
    if not p.exists():
        raise HTTPException(404, "غير موجود")
    return FileResponse(p, filename=name, media_type="application/octet-stream")


# ---------- النسخ الاحتياطي والاستعادة ----------

@router.get("/backups")
def backups(_: User = Depends(require("system.manage"))):
    from marsad.transfer import list_backups

    return [{"name": p.name, "size": p.stat().st_size, "at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()} for p in list_backups()]


@router.post("/backups")
def backup_now(actor: User = Depends(require("system.manage")), db: Session = Depends(get_db)):
    from marsad.audit import record
    from marsad.db import get_engine
    from marsad.transfer import backup_now as _b

    p = _b(get_engine())
    record(db, actor, "backup.create", "file", p.name)
    db.commit()
    return {"name": p.name, "size": p.stat().st_size}


class RestoreIn(BaseModel):
    name: str
    confirm: str


@router.post("/backups/restore")
def restore(body: RestoreIn, actor: User = Depends(require("system.manage")), db: Session = Depends(get_db)):
    """يستبدل كل البيانات الحالية بالنسخة المختارة. يتطلب كتابة «استعادة» تأكيدًا، ويأخذ نسخة من الحال الحالي أولًا."""
    from marsad.db import get_engine
    from marsad.transfer import TransferError, backup_now as _b, list_backups, restore_backup

    if body.confirm.strip() != "استعادة":
        raise HTTPException(422, "اكتب «استعادة» للتأكيد")
    match = [p for p in list_backups() if p.name == body.name]
    if not match:
        raise HTTPException(404, "النسخة غير موجودة")
    db.close()
    safety = _b(get_engine())  # لا يضيع الحال الحالي إن كانت الاستعادة خطأ
    try:
        r = restore_backup(get_engine(), match[0])
    except TransferError as e:
        raise HTTPException(422, str(e)) from None
    from marsad.db import get_db as _g

    s = next(_g())
    from marsad.audit import record

    record(s, None, "backup.restore", "file", body.name, after={"by": actor.email, "safety_copy": safety.name})
    s.commit()
    s.close()
    return {"restored": body.name, "records": sum(r["tables"].values()), "safety_copy": safety.name,
            "note": "استُعيدت البيانات. سجّل الدخول من جديد إن طُلب منك."}
