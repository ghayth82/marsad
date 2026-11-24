"""الادّعاءات والأحكام والأدلة. الحكم مُصدَّر بصيغة ClaimReview، وكل تعديل نسخة جديدة."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marsad.db import Base, UTCDateTime, utcnow


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    norm: Mapped[str] = mapped_column(Text, default="")
    speaker: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | assigned | investigating | proposed | verdict | dismissed | archived
    origin: Mapped[str] = mapped_column(String(12), default="manual")  # manual | auto | engine
    first_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    official_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    story_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # البصمة ونتائج المحركات
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    # سير العمل التحريري (البند 14)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # normal | high | urgent
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)

    appearances: Mapped[list["ClaimItem"]] = relationship(lazy="selectin", cascade="all, delete-orphan")
    verdicts: Mapped[list["Verdict"]] = relationship(lazy="selectin", order_by="Verdict.id", cascade="all, delete-orphan")
    evidence: Mapped[list["Evidence"]] = relationship(lazy="selectin", order_by="Evidence.id", cascade="all, delete-orphan")


class ClaimItem(Base):
    """ظهور الادّعاء في مادة مرصودة (أول ظهور، تكرار، عودة بكلمات أخرى)."""

    __tablename__ = "claim_items"
    __table_args__ = (UniqueConstraint("claim_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, default=1.0)
    kind: Mapped[str] = mapped_column(String(12), default="appearance")  # first | appearance | return
    parent_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # شجرة الانتشار
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Verdict(Base):
    """نسخة من الحكم. الحالي = آخر نسخة. لا يُعتمد إلا بقرار بشري، ويُسجَّل من اقترح ومن اعتمد."""

    __tablename__ = "verdicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(20))
    evidence_grade: Mapped[str] = mapped_column(String(12))
    explanation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="proposed")  # proposed | approved | rejected
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    engine_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Evidence(Base):
    """دليل: رابط أو مادة مرصودة أو ملف أو نتيجة فحص. الملفات ببصمة SHA-256 (سلسلة الحفظ في البند 8)."""

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=True, index=True)
    case_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(12))  # link | item | file | check | official
    title: Mapped[str] = mapped_column(String(400), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    file_path: Mapped[str] = mapped_column(String(500), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    grade: Mapped[str] = mapped_column(String(12), default="")  # قاطع | مؤشر قوي | لا يكفي
    note: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    is_conclusive: Mapped[bool] = mapped_column(Boolean, default=False)
