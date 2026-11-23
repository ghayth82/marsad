"""طابور المهام والمجدول داخل PostgreSQL (Procrastinate)، دون Redis.

- على الجهاز: العامل يعمل داخل عملية الخادم نفسها (MARSAD_EMBEDDED_WORKER=1)، فلا عملية إضافية.
- على الخادم: عامل مستقل `python -m marsad.worker`، ويمكن تشغيل أكثر من واحد.
- مع SQLite (التطوير والاختبار فقط): طابور في الذاكرة.

كل قسم يضيف مهامه هنا (أو في blueprint خاص به يُضاف في build_app).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import procrastinate
from sqlalchemy import text
from sqlalchemy.engine import Engine

from marsad.config import get_settings

bp = procrastinate.Blueprint()


def conninfo(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def build_app(url: str | None = None) -> procrastinate.App:
    url = url if url is not None else get_settings().database_url
    if url and url.startswith("postgresql"):
        connector = procrastinate.PsycopgConnector(conninfo=conninfo(url))
    else:
        from procrastinate.testing import InMemoryConnector

        connector = InMemoryConnector()
    app = procrastinate.App(connector=connector)
    app.add_tasks_from(bp, namespace="")
    return app


def ensure_queue_schema(engine: Engine) -> bool:
    """ينشئ جداول الطابور في PostgreSQL إن لم تكن موجودة. يعيد True إن أنشأها."""
    if engine.dialect.name != "postgresql":
        return False
    with engine.begin() as conn:
        if conn.execute(text("SELECT to_regclass('procrastinate_jobs')")).scalar():
            return False
        # تنفيذ مباشر دون معاملات: نص المخطط فيه علامات % ليست متغيرات
        with conn.connection.dbapi_connection.cursor() as cur:
            cur.execute(procrastinate.schema.SchemaManager.get_schema())
    return True


# ---------- مهام النظام ----------

HEARTBEAT_KEY = "worker.heartbeat"


@bp.periodic(cron="* * * * *", periodic_id="heartbeat")
@bp.task(name="system.heartbeat", queue="system")
def heartbeat(timestamp: int) -> str:
    """نبضة كل دقيقة: تُظهر في لوحة النظام أن العامل يعمل."""
    from marsad.db import get_db
    from marsad.models import SystemSetting

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db = next(get_db())
    try:
        row = db.get(SystemSetting, HEARTBEAT_KEY)
        if row is None:
            db.add(SystemSetting(key=HEARTBEAT_KEY, value=now))
        else:
            row.value = now
        db.commit()
    finally:
        db.close()
    return now


@bp.periodic(cron="17 3 * * *", periodic_id="cleanup-tmp")
@bp.task(name="storage.cleanup_tmp", queue="system")
def cleanup_tmp(timestamp: int, max_age_hours: int = 24) -> int:
    """يمسح ملفات البرنامج المؤقتة القديمة في مجلد tmp فقط."""
    from marsad.core.paths import ensure_storage

    tmp = ensure_storage().tmp
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in tmp.rglob("*"):
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
