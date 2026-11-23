from marsad.db import init_engine
from marsad.migrate import pending_diff, upgrade


def test_migrations_match_models(app_env):
    """أي تعديل في النماذج دون ترحيل يُكشف هنا: python -m marsad.migrate "الوصف"."""
    engine = init_engine()
    upgrade(engine)
    assert pending_diff(engine) == []
    upgrade(engine)  # تطبيقها مرتين لا يضر
