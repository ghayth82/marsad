"""ترحيلات قاعدة البيانات: تُطبَّق تلقائيًا عند بدء الخادم، فلا يحتاج المستخدم أي أمر."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Engine

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def _config(connection) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["connection"] = connection
    return cfg


def upgrade(engine: Engine) -> None:
    with engine.begin() as conn:
        command.upgrade(_config(conn), "head")


def revision(engine: Engine, message: str) -> None:
    """للمطوّر: python -m marsad.migrate "وصف التغيير" يولّد ترحيلًا من الفرق بين النماذج والقاعدة."""
    with engine.begin() as conn:
        command.revision(_config(conn), message=message, autogenerate=True)


def pending_diff(engine: Engine) -> list:
    """الفرق بين النماذج والقاعدة بعد الترحيل؛ يجب أن يكون فارغًا (يُفحص في الاختبارات)."""
    from alembic.autogenerate import compare_metadata

    import marsad.models  # noqa: F401
    from marsad.db import Base

    with engine.connect() as conn:
        mc = MigrationContext.configure(conn, opts={"compare_type": True})
        return compare_metadata(mc, Base.metadata)


if __name__ == "__main__":
    import sys

    from marsad.db import init_engine

    revision(init_engine(), sys.argv[1] if len(sys.argv) > 1 else "تغيير")
