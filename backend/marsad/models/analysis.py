"""القصص والكيانات والتصريحات."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from marsad.db import Base, UTCDateTime, utcnow


class Story(Base):
    """مجموعة مواد عن الحدث نفسه."""

    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    first_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # عدّلها صحفي يدويًا: لا يغيّرها التجميع الآلي


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("norm", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    norm: Mapped[str] = mapped_column(String(300), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # person | org | place
    aliases: Mapped[list] = mapped_column(JSON, default=list)  # الأسماء البديلة بكل الكتابات
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)  # مؤسسة أو شخصية عامة فقط
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    __table_args__ = (UniqueConstraint("entity_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    tone: Mapped[float] = mapped_column(default=0.0)  # -1 سلبي … +1 إيجابي (مؤشر لغوي)
    count: Mapped[int] = mapped_column(Integer, default=1)


class Statement(Base):
    """اقتباس منسوب لكيان مع مصدره وتاريخه."""

    __tablename__ = "statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    quote: Mapped[str] = mapped_column(Text)
    said_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    is_promise: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
