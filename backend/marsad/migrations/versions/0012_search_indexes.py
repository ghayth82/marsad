"""search indexes: stories.norm and trigram indexes for text search in PostgreSQL

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-27 12:00:00

بحث «يحتوي على» في القاعدة (حين لا يكون Meilisearch متاحًا، وللادّعاءات والكيانات والقصص) يقرأ الجدول كله
دون فهرس. فهرس الثلاثيات (pg_trgm) يجعله سريعًا مع ملايين الصفوف. إن لم يتوفر الامتداد يُتخطى الفهرس دون خطأ.
"""

import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

TRGM = [("ix_items_norm_trgm", "items"), ("ix_claims_norm_trgm", "claims"),
        ("ix_entities_norm_trgm", "entities"), ("ix_stories_norm_trgm", "stories")]


def upgrade() -> None:
    op.add_column('stories', sa.Column('norm', sa.Text(), nullable=False, server_default=''))
    bind = op.get_bind()
    from marsad.text import normalize_ar

    stories = sa.table('stories', sa.column('id', sa.Integer), sa.column('title', sa.Text), sa.column('norm', sa.Text))
    last = 0
    while True:
        rows = bind.execute(sa.select(stories.c.id, stories.c.title).where(stories.c.id > last).order_by(stories.c.id).limit(2000)).all()
        if not rows:
            break
        for sid, title in rows:
            bind.execute(stories.update().where(stories.c.id == sid).values(norm=normalize_ar(title or "")))
        last = rows[-1][0]

    if bind.dialect.name != "postgresql":
        return
    if not bind.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'")).first():
        return
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except Exception:  # noqa: BLE001 — صلاحية ناقصة: يبقى البحث يعمل دون الفهرس
        return
    for name, table in TRGM:
        bind.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (norm gin_trgm_ops)"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name, _table in TRGM:
            bind.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
    op.drop_column('stories', 'norm')
