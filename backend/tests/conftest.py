"""اختبارات الخادم تعمل على SQLite افتراضيًا، وعلى PostgreSQL حين يُضبط
MARSAD_TEST_DATABASE_URL (كما في GitHub Actions)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARSAD_HOME", str(tmp_path / "app"))
    monkeypatch.delenv("MARSAD_DATA_DIR", raising=False)
    monkeypatch.delenv("MARSAD_BACKUP_DIR", raising=False)
    url = os.environ.get("MARSAD_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("MARSAD_DATABASE_URL", url)
    from marsad.config import get_settings

    get_settings.cache_clear()
    if url.startswith("postgresql"):
        from sqlalchemy import create_engine

        import marsad.models  # noqa: F401
        from marsad.db import Base

        eng = create_engine(url)
        Base.metadata.drop_all(eng)
        eng.dispose()
    yield
    get_settings.cache_clear()


class Client(TestClient):
    """عميل يضيف ترويسة الواجهة تلقائيًا (حماية CSRF)."""

    def request(self, method, url, **kw):
        headers = dict(kw.pop("headers", None) or {})
        headers.setdefault("X-Marsad", "1")
        return super().request(method, url, headers=headers, **kw)


@pytest.fixture
def make_client(app_env):
    from marsad.main import create_app

    app = create_app()
    clients = []

    def _make():
        c = Client(app)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


ADMIN = {"email": "ghayth@example.com", "full_name": "غيث", "password": "correct-horse-1"}


@pytest.fixture
def admin(make_client):
    c = make_client()
    r = c.post("/api/setup", json=ADMIN)
    assert r.status_code == 200, r.text
    return c


def invite_user(admin_client, make_client, email, roles, password="user-password-1"):
    r = admin_client.post("/api/admin/users", json={"email": email, "full_name": email.split("@")[0],
                                                    "roles": [{"key": k} for k in roles]})
    assert r.status_code == 200, r.text
    c = make_client()
    r2 = c.post("/api/invite/accept", json={"token": r.json()["invite_token"], "password": password})
    assert r2.status_code == 200, r2.text
    return c, r.json()["user"]["id"]
