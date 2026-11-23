"""تفضيلات كل مستخدم، وقوالب الواجهة لكل دور."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from marsad.db import Base, UTCDateTime, utcnow


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class RoleTemplate(Base):
    """الواجهة الافتراضية لدور: يحددها المدير، وكل مستخدم يعدّل نسخته."""

    __tablename__ = "role_templates"

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
