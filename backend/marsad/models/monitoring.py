"""الجهات والمصادر والمواد ونسخها. مبدأ أساسي: لا يُحذف شيء رُصد، بل تُضاف نسخ جديدة."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marsad.db import Base, UTCDateTime, utcnow


class Outlet(Base):
    """جهة: مؤسسة إعلامية أو رسمية أو شخصية عامة. موقعها وصفحاتها على المنصات = جهة واحدة."""

    __tablename__ = "outlets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="news")  # news | official | party | public_figure | institution | other
    country: Mapped[str] = mapped_column(String(60), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    logo_url: Mapped[str] = mapped_column(String(500), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    transparency: Mapped[dict] = mapped_column(JSON, default=dict)  # بنود JTI المعلنة (البند 7)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    sources: Mapped[list["Source"]] = relationship(back_populates="outlet", lazy="selectin")


class Source(Base):
    """رابط واحد يُرصد: موقع (RSS أو خريطة موقع أو صفحة)، قناة تيليغرام، قناة يوتيوب، استعلام GDELT..."""

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlets.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(800))
    kind: Mapped[str] = mapped_column(String(20))  # rss | sitemap | page | telegram | youtube | gdelt | social | manual
    read_url: Mapped[str] = mapped_column(String(800), default="")  # العنوان الفعلي للقراءة (رابط الخلاصة مثلًا)
    title: Mapped[str] = mapped_column(String(300), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    check_minutes: Mapped[int] = mapped_column(Integer, default=15)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(12), default="new")  # new | ok | error | paused
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_item_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # etag، last_modified، channel_id، استعلام...
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    outlet: Mapped[Outlet] = relationship(back_populates="sources")


class Item(Base):
    """مادة مرصودة: خبر أو منشور أو فيديو، بآخر نسخة منها. النسخ كلها في ItemVersion."""

    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("source_id", "url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlets.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(300), default="")
    language: Mapped[str] = mapped_column(String(10), default="")
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)  # المعلن
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)  # وقت رصدنا
    media: Mapped[list] = mapped_column(JSON, default=list)  # [{"type": "image", "url": ...}]
    status: Mapped[str] = mapped_column(String(10), default="live")  # live | edited | deleted
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    norm: Mapped[str] = mapped_column(Text, default="")  # نص موحّد للبحث العربي
    story_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # البند 4
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    source: Mapped[Source] = relationship(lazy="selectin")
    versions: Mapped[list["ItemVersion"]] = relationship(order_by="ItemVersion.version", lazy="selectin",
                                                         cascade="all, delete-orphan")


class ItemVersion(Base):
    __tablename__ = "item_versions"
    __table_args__ = (UniqueConstraint("item_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    change: Mapped[str] = mapped_column(String(10))  # new | edit | delete | restore
    title: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    archive_path: Mapped[str] = mapped_column(String(500), default="")  # نسخة الصفحة المؤرشفة (نسبةً لمجلد الأرشيف)
    archive_sha256: Mapped[str] = mapped_column(String(64), default="")
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
