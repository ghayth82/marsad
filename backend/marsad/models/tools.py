"""البند 13: أدوات الصحفيين — البلاغات، الأرقام الرسمية، الوعود، الأرشفة الفورية."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from marsad.db import Base, UTCDateTime, utcnow


class Tip(Base):
    """بلاغ من الجمهور عبر بوت تيليغرام. لا يُحفظ من المُبلِّغ إلا معرّف المحادثة للرد، ويُمحى بعد 90 يومًا."""

    __tablename__ = "tips"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)  # رقم المتابعة
    channel: Mapped[str] = mapped_column(String(12), default="telegram")
    chat_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)  # معرّف المحادثة مشفّرًا
    text: Mapped[str] = mapped_column(Text, default="")
    urls: Mapped[list] = mapped_column(JSON, default=list)
    media_id: Mapped[int | None] = mapped_column(ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True)
    media_kind: Mapped[str] = mapped_column(String(12), default="")
    status: Mapped[str] = mapped_column(String(12), default="new", index=True)  # new | claim | rejected | answered
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True)
    reply_on_verdict: Mapped[bool] = mapped_column(Boolean, default=True)
    reply_text: Mapped[str] = mapped_column(Text, default="")
    replied_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class OfficialFigure(Base):
    """رقم رسمي منشور: المؤشر وقيمته ووحدته وتاريخه وجهته ورابطه."""

    __tablename__ = "official_figures"

    id: Mapped[int] = mapped_column(primary_key=True)
    indicator: Mapped[str] = mapped_column(String(200), index=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)  # كلمات تدل على المؤشر في الأخبار
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40), default="")  # ٪، مليون نسمة، دينار...
    as_of: Mapped[str] = mapped_column(String(10), index=True)  # تاريخ القيمة (سنة-شهر-يوم)
    agency: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Promise(Base):
    """وعد أو تصريح يُتابع: نصه ومن قاله ومتى وموعده وحالته بدليل."""

    __tablename__ = "promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    statement_id: Mapped[int | None] = mapped_column(ForeignKey("statements.id", ondelete="SET NULL"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    said_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="tracking")  # tracking | kept | partial | broken
    evidence_url: Mapped[str] = mapped_column(String(1000), default="")
    evidence_note: Mapped[str] = mapped_column(Text, default="")
    reminded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    history: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Snapshot(Base):
    """أرشفة فورية لرابط: نسخة HTML ونص ولقطة اختيارية، ببصمة SHA-256، وطلب اختياري إلى Wayback Machine."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(1000), index=True)
    final_url: Mapped[str] = mapped_column(String(1000), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    html_path: Mapped[str] = mapped_column(String(500), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    screenshot_path: Mapped[str] = mapped_column(String(500), default="")
    screenshot_sha256: Mapped[str] = mapped_column(String(64), default="")
    http_status: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="ok")  # ok | error
    error: Mapped[str] = mapped_column(Text, default="")
    wayback_url: Mapped[str] = mapped_column(String(1000), default="")
    wayback_status: Mapped[str] = mapped_column(String(20), default="")  # "" | requested | ok | failed | off
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True)
    case_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
