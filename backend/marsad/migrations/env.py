"""بيئة Alembic: تُشغَّل من الكود (marsad.migrate) لا من سطر الأوامر."""

from alembic import context

import marsad.models  # noqa: F401  تسجيل كل الجداول
from marsad.db import Base

config = context.config
target_metadata = Base.metadata


def run() -> None:
    connectable = config.attributes.get("connection")
    is_sqlite = connectable.dialect.name == "sqlite"
    context.configure(connection=connectable, target_metadata=target_metadata,
                      render_as_batch=is_sqlite, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run()
