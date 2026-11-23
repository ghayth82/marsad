"""غرفة التحقيق وبناء القصة. محتوى القضية مشفّر بمفتاح خاص بها، ومفتاحها مشفّر بالمفتاح الرئيسي."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from marsad.db import Base, UTCDateTime, utcnow


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))  # العنوان ظاهر في القائمة؛ ما عداه مشفّر
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    key_wrapped: Mapped[str] = mapped_column(Text)
    summary_enc: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CaseMember(Base):
    __tablename__ = "case_members"
    __table_args__ = (UniqueConstraint("case_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    access: Mapped[str] = mapped_column(String(8), default="edit")  # owner | edit | view
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CaseDocument(Base):
    __tablename__ = "case_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)  # «وثيقة 3» داخل القضية
    filename_enc: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10))  # pdf | docx | xlsx | image | audio | text
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)  # بصمة الأصل قبل التشفير
    path: Mapped[str] = mapped_column(String(500))  # الملف المشفّر نسبةً للأرشيف
    status: Mapped[str] = mapped_column(String(12), default="processing")  # processing | ready | failed
    method: Mapped[str] = mapped_column(String(20), default="")  # text | ocr | mixed | sawti
    pages: Mapped[int] = mapped_column(Integer, default=0)
    text_enc: Mapped[str] = mapped_column(Text, default="")  # النص المستخرج بصفحاته (JSON مشفّر)
    meta_enc: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CaseRecord(Base):
    """عناصر القضية الأخرى بنوع واحد مرن: ملاحظة، مهمة، حدث في الخط الزمني، صلة في الخريطة، حركة مال، طرف.
    المحتوى كله مشفّر في body_enc (JSON)، والحقول الظاهرة للترتيب والتصفية فقط."""

    __tablename__ = "case_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)  # note | task | event | link | money | party
    status: Mapped[str] = mapped_column(String(12), default="")  # task: open|done ; link/event/party: suggested|confirmed|rejected
    at_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # للأحداث والمال والمهام
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    doc_id: Mapped[int | None] = mapped_column(ForeignKey("case_documents.id", ondelete="SET NULL"), nullable=True)
    body_enc: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CustodyLog(Base):
    """سلسلة الحفظ: كل رفع وفتح وتنزيل وتعديل، بسلسلة بصمات تكشف أي حذف أو تعديل في السجل نفسه."""

    __tablename__ = "custody_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(String(300), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    entry_hash: Mapped[str] = mapped_column(String(64), default="")
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Draft(Base):
    """مسودة القصة: الهيكل والنص (مشفّران) وقائمة ما قبل النشر."""

    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    body_enc: Mapped[str] = mapped_column(Text, default="")  # {"angle", "body", "questions"}
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | review | approved
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SanctionEntry(Base):
    """قوائم العقوبات والأشخاص ذوي النفوذ السياسي (تُستورد من ملف، مثل OpenSanctions)."""

    __tablename__ = "sanction_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_name: Mapped[str] = mapped_column(String(100), index=True)
    ext_id: Mapped[str] = mapped_column(String(120), default="")
    schema: Mapped[str] = mapped_column(String(30), default="")  # Person | Organization | Company ...
    name: Mapped[str] = mapped_column(String(400))
    norm: Mapped[str] = mapped_column(String(400), index=True)
    aliases: Mapped[str] = mapped_column(Text, default="")  # موحّدة، مفصولة بـ |
    countries: Mapped[str] = mapped_column(String(200), default="")
    programs: Mapped[str] = mapped_column(Text, default="")
    is_pep: Mapped[bool] = mapped_column(default=False)
