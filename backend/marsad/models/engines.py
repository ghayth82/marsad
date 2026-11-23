"""المحركات وتشغيلاتها: كل تشغيل يُحفظ بمدخله ومخرجه وكلفته ونسخة التعليمات والنموذج، لإعادة إنتاجه."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marsad.db import Base, UTCDateTime, utcnow


class Engine(Base):
    __tablename__ = "engines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(32))  # anthropic | openai | gemini | openai_compatible | ollama | fake
    model: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(300), default="")
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_hint: Mapped[str] = mapped_column(String(20), default="")
    local: Mapped[bool] = mapped_column(Boolean, default=False)  # النص لا يغادر الجهاز
    price_in: Mapped[float | None] = mapped_column(Float, nullable=True)  # دولار لكل مليون رمز مُدخل
    price_out: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_limit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EngineBatch(Base):
    """طلب واحد من الصحفي: مهمة على محرك أو أكثر، ثم دمج اختياري، ثم قراره."""

    __tablename__ = "engine_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(60))
    input: Mapped[dict] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(10))  # single | multi
    engine_ids: Mapped[list] = mapped_column(JSON)
    merge_engine_id: Mapped[int | None] = mapped_column(ForeignKey("engines.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | running | done
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    runs: Mapped[list["EngineRun"]] = relationship(back_populates="batch", order_by="EngineRun.id", lazy="selectin")
    merges: Mapped[list["MergeRun"]] = relationship(back_populates="batch", order_by="MergeRun.id", lazy="selectin")


class EngineRun(Base):
    __tablename__ = "engine_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("engine_batches.id", ondelete="CASCADE"), index=True)
    engine_id: Mapped[int | None] = mapped_column(ForeignKey("engines.id", ondelete="SET NULL"), nullable=True)
    engine_name: Mapped[str] = mapped_column(String(120))
    task: Mapped[str] = mapped_column(String(60))
    prompt_id: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(160))
    model_version: Mapped[str] = mapped_column(String(160), default="")
    request: Mapped[dict] = mapped_column(JSON)  # التعليمات والمدخل كما أُرسلا
    output_text: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(12))  # ok | error | invalid | limit
    error: Mapped[str] = mapped_column(Text, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    batch: Mapped[EngineBatch] = relationship(back_populates="runs")


class MergeRun(Base):
    """دمج مخرجات المحركات بمحرك دمج. يمكن إعادة الدمج بمحرك آخر ومقارنة النتيجتين."""

    __tablename__ = "merge_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("engine_batches.id", ondelete="CASCADE"), index=True)
    engine_run_id: Mapped[int | None] = mapped_column(ForeignKey("engine_runs.id", ondelete="SET NULL"), nullable=True)
    merge_engine_name: Mapped[str] = mapped_column(String(120))
    source_run_ids: Mapped[list] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(12))
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    batch: Mapped[EngineBatch] = relationship(back_populates="merges")


class EngineDecision(Base):
    """قرار الصحفي: لا يُعتمد أي مخرج دونه، ويُسجَّل من اعتمده ومتى."""

    __tablename__ = "engine_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("engine_batches.id", ondelete="CASCADE"), unique=True)
    output: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(40))  # run:<id> | merge:<id> | manual
    note: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Notification(Base):
    """تنبيه داخل البرنامج (حد الإنفاق، تعطّل محرك...). قنوات البريد وتيليغرام تأتي في البند 10."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # فارغ = المدراء
    kind: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
