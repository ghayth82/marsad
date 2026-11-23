"""مختبرات التحقق: الملفات المفحوصة ونتائج كل فحص."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marsad.db import Base, UTCDateTime, utcnow


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # image | video | audio | keyframe
    mime: Mapped[str] = mapped_column(String(80), default="")
    filename: Mapped[str] = mapped_column(String(300), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(500))  # نسبةً لمجلد الأرشيف
    phash: Mapped[str] = mapped_column(String(16), default="", index=True)
    dhash: Mapped[str] = mapped_column(String(16), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    origin: Mapped[str] = mapped_column(String(12), default="upload")  # upload | url | item | keyframe
    url: Mapped[str] = mapped_column(String(1000), default="")
    source_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), nullable=True, index=True)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)  # أول مرة رأيناه
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # بصمة الصوت، اللحظة في الفيديو...

    checks: Mapped[list["MediaCheck"]] = relationship(lazy="selectin", order_by="MediaCheck.id", cascade="all, delete-orphan")


class MediaCheck(Base):
    __tablename__ = "media_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), index=True)
    check: Mapped[str] = mapped_column(String(30))  # hashes | exif | c2pa | ela | ocr | archive | keyframes | probe | audio ...
    grade: Mapped[str] = mapped_column(String(12), default="")  # قاطع | مؤشر قوي | مؤشر | لا يكفي | —
    summary: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
