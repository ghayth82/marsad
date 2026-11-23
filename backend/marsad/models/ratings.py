"""تقييم المواقع: المنهجية بإصداراتها، والمؤشرات المحسوبة، والمراجعة البشرية، وحق الرد."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from marsad.db import Base, UTCDateTime, utcnow


class Methodology(Base):
    """كل تغيير في الأوزان أو الحدود إصدار جديد برقم وتاريخ ومن غيّره ولماذا."""

    __tablename__ = "rating_methodologies"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    min_sample: Mapped[int] = mapped_column(Integer, default=30)
    period_days: Mapped[int] = mapped_column(Integer, default=90)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Score(Base):
    """لقطة محفوظة لمؤشرات جهة في فترة، بإصدار المنهجية الذي حُسبت به."""

    __tablename__ = "rating_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlets.id", ondelete="CASCADE"), index=True)
    methodology_version: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime] = mapped_column(UTCDateTime)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    indicators: Mapped[dict] = mapped_column(JSON, default=dict)
    composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | approved
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ReviewLabel(Base):
    """حكم بشري على مادة في مؤشر لغوي (الإثارة، الرأي، مطابقة العنوان)، لقياس الاتفاق مع الآلة وبين المقيّمين."""

    __tablename__ = "rating_labels"
    __table_args__ = (UniqueConstraint("item_id", "indicator", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    indicator: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    value: Mapped[bool] = mapped_column(Boolean)  # True = المادة «مخالفة» في هذا المؤشر (مثيرة، فيها رأي، العنوان لا يطابق)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Reply(Base):
    """حق الرد: اعتراض جهة على مادة محددة في مؤشر، ونتيجته."""

    __tablename__ = "rating_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlets.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    indicator: Mapped[str] = mapped_column(String(20), default="")
    text: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(60), default="")  # بريد، رسالة رسمية، اتصال...
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | accepted | rejected
    resolution: Mapped[str] = mapped_column(Text, default="")
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
