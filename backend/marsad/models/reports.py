"""التنبيهات المرسلة، والتقارير الدورية، والوضع التدريبي."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from marsad.db import Base, UTCDateTime, utcnow


class AlertDelivery(Base):
    """كل تنبيه أُرسل (أو تعذّر) لكل مستخدم على كل قناة، فلا يُرسل مرتين."""

    __tablename__ = "alert_deliveries"
    __table_args__ = (UniqueConstraint("notification_id", "user_id", "channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(10))  # sent | failed | skipped
    detail: Mapped[str] = mapped_column(String(300), default="")
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)  # morning | weekly
    period_start: Mapped[datetime] = mapped_column(UTCDateTime)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    local_date: Mapped[str] = mapped_column(String(10), index=True)  # يوم الموجز بالتوقيت المحلي، لمنع التكرار
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    auto: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Exercise(Base):
    """تمرين تحقق: مادة (نص أو صورة أو رابط) وسؤال الحكم ودرجة الدليل، مع حل نموذجي لا يُعرض قبل الإجابة."""

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    level: Mapped[str] = mapped_column(String(12), default="مبتدئ")
    instructions: Mapped[str] = mapped_column(Text, default="")
    material: Mapped[dict] = mapped_column(JSON, default=dict)  # {"text", "image_media_id", "url", "claimed_at"}
    answer: Mapped[dict] = mapped_column(JSON, default=dict)  # {"label", "grade", "key_points": [...], "explanation"}
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    feedback: Mapped[dict] = mapped_column(JSON, default=dict)
    trainer_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # تصحيح المدرّب يتقدّم على الآلي
    trainer_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
