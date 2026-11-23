"""بيئة Alembic: تُشغَّل من الكود (marsad.migrate) لا من سطر الأوامر."""

from alembic import context

import marsad.models  # noqa: F401  تسجيل كل الجداول
from marsad.db import Base

config = context.config
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """جداول الطابور تديرها مكتبته، لا ترحيلاتنا."""
    return not (type_ == "table" and reflected and compare_to is None and name.startswith("procrastinate"))


def run() -> None:
    connectable = config.attributes.get("connection")
    is_sqlite = connectable.dialect.name == "sqlite"
    context.configure(connection=connectable, target_metadata=target_metadata,
                      render_as_batch=is_sqlite, compare_type=True,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


run()
