import os

import pytest


def test_heartbeat_and_cleanup_in_memory(app_env, tmp_path):
    from marsad.core.paths import ensure_storage
    from marsad.db import get_db, init_engine, migrate
    from marsad.models import SystemSetting
    from marsad.tasks import HEARTBEAT_KEY, build_app, cleanup_tmp, heartbeat

    init_engine()
    migrate()
    tmp = ensure_storage().tmp
    old = tmp / "old.bin"
    old.write_bytes(b"x")
    os.utime(old, (1, 1))
    fresh = tmp / "fresh.bin"
    fresh.write_bytes(b"x")

    app = build_app("")  # طابور في الذاكرة
    with app.open():
        heartbeat.defer(timestamp=0)
        cleanup_tmp.defer(timestamp=0)
        app.run_worker(wait=False)
    db = next(get_db())
    assert db.get(SystemSetting, HEARTBEAT_KEY).value
    db.close()
    assert not old.exists() and fresh.exists()


@pytest.mark.skipif(not (os.environ.get("MARSAD_TEST_DATABASE_URL") or "").startswith("postgresql"),
                    reason="يحتاج PostgreSQL")
def test_queue_on_postgres(app_env):
    from marsad.db import get_db, get_engine, init_engine, migrate
    from marsad.migrate import pending_diff
    from marsad.models import SystemSetting
    from marsad.tasks import HEARTBEAT_KEY, build_app, ensure_queue_schema, heartbeat

    init_engine()
    migrate()
    assert ensure_queue_schema(get_engine()) is True
    assert ensure_queue_schema(get_engine()) is False  # مرة واحدة فقط
    assert pending_diff(get_engine()) == []  # جداول الطابور لا تُربك الترحيلات
    app = build_app()
    with app.open():
        heartbeat.defer(timestamp=0)
        app.run_worker(wait=False, queues=["system"])
    db = next(get_db())
    assert db.get(SystemSetting, HEARTBEAT_KEY).value
    db.close()


def test_health_reports_worker(make_client):
    c = make_client()
    assert c.get("/api/health").json() == {"ok": True, "worker_heartbeat": None}
