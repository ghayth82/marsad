"""الحسابات، الأدوار المتعددة، الصلاحيات الفردية، الجلسات، الإعدادات، وسجل التدقيق."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marsad.db import Base, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # فارغ حتى قبول الدعوة
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
        foreign_keys="UserRole.user_id", lazy="selectin")
    permissions: Mapped[list["UserPermission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
        foreign_keys="UserPermission.user_id", lazy="selectin")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)  # admin, editor ... أو مخصص
    name_ar: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # الأصغر أولًا عند اختيار قالب الواجهة

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    permission: Mapped[str] = mapped_column(String(64))

    role: Mapped[Role] = relationship(back_populates="permissions")


class UserRole(Base):
    """إسناد دور لمستخدم. المستخدم الواحد يحمل أدوارًا كثيرة."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(lazy="selectin")


class UserPermission(Base):
    """صلاحية فردية فوق الأدوار: منح (grant) أو سحب (deny). السحب يغلب."""

    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    permission: Mapped[str] = mapped_column(String(64))
    effect: Mapped[str] = mapped_column(String(8))  # grant | deny
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="permissions", foreign_keys=[user_id])


class SessionToken(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    """سجل كل عملية حساسة: من، متى، ماذا، وما كان قبلها. لا يُعدَّل ولا يُحذف."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(40), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
