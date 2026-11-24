"""منطق الأدوار والصلاحيات.

الصلاحيات الفعلية للمستخدم =
    (مجموع صلاحيات أدواره السارية) + (ما مُنح له فرديًا) − (ما سُحب منه فرديًا)
السحب يغلب دائمًا. الدور أو الصلاحية المنتهية لا تُحسب.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.audit import record
from marsad.db import utcnow
from marsad.models import Role, RolePermission, SystemSetting, User, UserPermission, UserRole
from marsad.rbac.permissions import ADMIN_PERMISSION, BUILTIN_ROLES, LEGACY_PERMISSIONS, PERMISSIONS


class PermissionError_(Exception):
    """رفض بسبب الصلاحيات أو قاعدة حماية. الرسالة تُعرض للمستخدم كما هي."""


def _active(expires_at: datetime | None, now: datetime) -> bool:
    return expires_at is None or expires_at > now


# ---------- القراءة ----------

def active_roles(user: User, now: datetime | None = None) -> list[Role]:
    now = now or utcnow()
    return sorted((ur.role for ur in user.roles if _active(ur.expires_at, now)), key=lambda r: r.priority)


def effective_permissions(user: User, now: datetime | None = None) -> set[str]:
    if not user.is_active:
        return set()
    now = now or utcnow()
    perms: set[str] = set()
    for role in active_roles(user, now):
        perms.update(rp.permission for rp in role.permissions)
    denied = set()
    for up in user.permissions:
        if not _active(up.expires_at, now):
            continue
        (perms if up.effect == "grant" else denied).add(up.permission)
    return perms - denied


def has_permission(user: User, permission: str) -> bool:
    return permission in effective_permissions(user)


def explain(user: User) -> dict:
    """للواجهة: الأدوار وصلاحيات كل دور، والمنح والسحب الفردي، والنتيجة."""
    now = utcnow()
    return {
        "roles": [{
            "key": ur.role.key, "name_ar": ur.role.name_ar,
            "expires_at": ur.expires_at.isoformat() if ur.expires_at else None,
            "active": _active(ur.expires_at, now),
            "permissions": sorted(rp.permission for rp in ur.role.permissions),
        } for ur in sorted(user.roles, key=lambda x: x.role.priority)],
        "overrides": [{
            "permission": up.permission, "effect": up.effect,
            "expires_at": up.expires_at.isoformat() if up.expires_at else None,
            "active": _active(up.expires_at, now),
        } for up in user.permissions],
        "effective": sorted(effective_permissions(user, now)),
    }


# ---------- الإعدادات العامة ----------

def get_setting(db: Session, key: str, default=None):
    row = db.get(SystemSetting, key)
    return default if row is None else row.value


def set_setting(db: Session, key: str, value, actor: User | None = None) -> None:
    row = db.get(SystemSetting, key)
    before = None if row is None else row.value
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    record(db, actor, "setting.change", "setting", key, {"value": before}, {"value": value})


# ---------- حماية آخر مدير ----------

def _admins(db: Session) -> list[User]:
    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    return [u for u in users if ADMIN_PERMISSION in effective_permissions(u)]


def _guard_last_admin(db: Session, change) -> None:
    """يطبّق التغيير ثم يتحقق أن مديرًا واحدًا على الأقل باقٍ، وإلا يتراجع."""
    had_admin = bool(_admins(db))
    savepoint = db.begin_nested()
    change()
    db.flush()
    db.expire_all()  # إعادة القراءة من القاعدة بعد التغيير (حذف دور مثلًا)
    if had_admin and not _admins(db):
        savepoint.rollback()
        db.expire_all()
        raise PermissionError_("لا يمكن تنفيذ هذا: سيبقى البرنامج دون مدير. أضف مديرًا آخر أولًا.")
    savepoint.commit()


# ---------- الأدوار ----------

KNOWN_PERMISSIONS_KEY = "rbac.known_permissions"


def seed_builtin_roles(db: Session) -> None:
    known = set(get_setting(db, KNOWN_PERMISSIONS_KEY) or LEGACY_PERMISSIONS)
    new_perms = set(PERMISSIONS) - known
    for spec in BUILTIN_ROLES:
        role = db.scalar(select(Role).where(Role.key == spec["key"]))
        if role is None:
            role = Role(key=spec["key"], name_ar=spec["name_ar"], name_en=spec["name_en"],
                        description=spec["description"], builtin=True, priority=spec["priority"])
            db.add(role)
            db.flush()
            for p in spec["permissions"]:
                db.add(RolePermission(role_id=role.id, permission=p))
        elif role.key == "admin":
            # دور المدير يحمل كل الصلاحيات دائمًا، حتى ما يُضاف في إصدارات لاحقة
            have = {rp.permission for rp in role.permissions}
            for p in PERMISSIONS:
                if p not in have:
                    db.add(RolePermission(role_id=role.id, permission=p))
        else:
            # صلاحية جديدة في إصدار لاحق تدخل الدور الجاهز الذي يذكرها، مرة واحدة فقط
            have = {rp.permission for rp in role.permissions}
            for p in spec["permissions"]:
                if p in new_perms and p not in have:
                    db.add(RolePermission(role_id=role.id, permission=p))
    if new_perms or get_setting(db, KNOWN_PERMISSIONS_KEY) is None:
        set_setting(db, KNOWN_PERMISSIONS_KEY, sorted(PERMISSIONS))
    db.flush()


def _check_perms(perms: list[str]) -> list[str]:
    unknown = [p for p in perms if p not in PERMISSIONS]
    if unknown:
        raise PermissionError_(f"صلاحيات غير معروفة: {', '.join(unknown)}")
    return sorted(set(perms))


def create_role(db: Session, actor: User, key: str, name_ar: str, permissions: list[str],
                description: str = "", name_en: str = "", priority: int = 100) -> Role:
    if db.scalar(select(Role).where(Role.key == key)):
        raise PermissionError_("يوجد دور بهذا المفتاح")
    role = Role(key=key, name_ar=name_ar, name_en=name_en, description=description,
                builtin=False, priority=priority)
    db.add(role)
    db.flush()
    for p in _check_perms(permissions):
        db.add(RolePermission(role_id=role.id, permission=p))
    record(db, actor, "role.create", "role", key, None, {"permissions": sorted(permissions)})
    db.flush()
    db.refresh(role)
    return role


def set_role_permissions(db: Session, actor: User, role: Role, permissions: list[str]) -> Role:
    if role.key == "admin":
        raise PermissionError_("صلاحيات دور المدير ثابتة (كل الصلاحيات)")
    new = _check_perms(permissions)
    old = sorted(rp.permission for rp in role.permissions)

    def change():
        role.permissions.clear()
        db.flush()
        for p in new:
            role.permissions.append(RolePermission(permission=p))

    _guard_last_admin(db, change)
    record(db, actor, "role.permissions", "role", role.key, {"permissions": old}, {"permissions": new})
    return role


def delete_role(db: Session, actor: User, role: Role) -> None:
    if role.builtin:
        raise PermissionError_("الأدوار الجاهزة لا تُحذف، ويمكن تعديل صلاحياتها")
    key = role.key
    _guard_last_admin(db, lambda: db.delete(role))
    record(db, actor, "role.delete", "role", key)


# ---------- إسناد الأدوار والصلاحيات للمستخدم ----------

def assign_role(db: Session, actor: User | None, user: User, role: Role,
                expires_at: datetime | None = None) -> UserRole:
    existing = next((ur for ur in user.roles if ur.role_id == role.id), None)
    if existing:
        existing.expires_at = expires_at
        ur = existing
    else:
        ur = UserRole(role_id=role.id, granted_by=actor.id if actor else None, expires_at=expires_at)
        ur.role = role
        user.roles.append(ur)
    record(db, actor, "user.role.assign", "user", str(user.id), None,
           {"role": role.key, "expires_at": expires_at.isoformat() if expires_at else None})
    db.flush()
    return ur


def remove_role(db: Session, actor: User, user: User, role: Role) -> None:
    ur = next((x for x in user.roles if x.role_id == role.id), None)
    if ur is None:
        return
    _guard_last_admin(db, lambda: user.roles.remove(ur))
    record(db, actor, "user.role.remove", "user", str(user.id), {"role": role.key}, None)


def set_user_roles(db: Session, actor: User, user: User, roles: list[tuple[Role, datetime | None]]) -> None:
    """يستبدل أدوار المستخدم كلها دفعة واحدة (شاشة المستخدم في الإدارة)."""
    old = sorted(ur.role.key for ur in user.roles)

    def change():
        wanted = {r.id: exp for r, exp in roles}
        for ur in list(user.roles):
            if ur.role_id not in wanted:
                user.roles.remove(ur)
        for r, exp in roles:
            cur = next((ur for ur in user.roles if ur.role_id == r.id), None)
            if cur:
                cur.expires_at = exp
            else:
                ur = UserRole(role_id=r.id, granted_by=actor.id, expires_at=exp)
                ur.role = r
                user.roles.append(ur)

    _guard_last_admin(db, change)
    record(db, actor, "user.roles.set", "user", str(user.id), {"roles": old},
           {"roles": sorted(r.key for r, _ in roles)})


def set_override(db: Session, actor: User, user: User, permission: str, effect: str | None,
                 expires_at: datetime | None = None) -> None:
    """effect: grant أو deny، أو None لإزالة الاستثناء الفردي."""
    _check_perms([permission])
    if effect not in (None, "grant", "deny"):
        raise PermissionError_("القيمة يجب أن تكون منح أو سحب")
    cur = next((up for up in user.permissions if up.permission == permission), None)
    before = None if cur is None else {"effect": cur.effect}

    def change():
        nonlocal cur
        if effect is None:
            if cur is not None:
                user.permissions.remove(cur)
        elif cur is None:
            user.permissions.append(UserPermission(
                permission=permission, effect=effect, granted_by=actor.id, expires_at=expires_at))
        else:
            cur.effect, cur.expires_at = effect, expires_at

    _guard_last_admin(db, change)
    record(db, actor, "user.permission", "user", str(user.id), before,
           None if effect is None else {"permission": permission, "effect": effect,
                                        "expires_at": expires_at.isoformat() if expires_at else None})


def set_user_active(db: Session, actor: User, user: User, active: bool) -> None:
    def change():
        user.is_active = active

    _guard_last_admin(db, change)
    record(db, actor, "user.activate" if active else "user.deactivate", "user", str(user.id))


# ---------- العينان الأربع ----------

FOUR_EYES_KEY = "four_eyes"


def check_can_approve(db: Session, approver: User, author_id: int | None, permission: str) -> None:
    """يُستدعى قبل اعتماد حكم أو قصة أو تقييم."""
    if not has_permission(approver, permission):
        raise PermissionError_("لا تملك صلاحية الاعتماد")
    if get_setting(db, FOUR_EYES_KEY, False) and author_id is not None and author_id == approver.id:
        raise PermissionError_("قاعدة «العينان الأربع» مفعّلة: لا تعتمد عملًا كتبته بنفسك؛ يعتمده محرّر آخر")
