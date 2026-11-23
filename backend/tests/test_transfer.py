"""الحالة 41: ملف نقل من الجهاز ثم استيراده على خادم جديد (بسر رئيسي مختلف): كل شيء موجود، والملفات المشفّرة تُفتح."""

import os

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import ADMIN, Client, invite_user

PASS = "عبارة-مرور-طويلة-2026"


def test_case41_transfer_bundle_to_new_server(admin, make_client, tmp_path, monkeypatch):
    from marsad import crypto, transfer
    from marsad.db import get_engine

    # ---- الجهاز: بيانات من كل نوع ----
    admin.patch("/api/me/preferences", json={"pattern": "b", "language": "ar"})
    j, jid = invite_user(admin, make_client, "j@example.com", ["journalist", "researcher"])
    cid = admin.post("/api/claims", json={"text": "ادّعاء للنقل: أسعار الخبز سترتفع غدًا بنسبة 50٪"}).json()["id"]
    admin.post(f"/api/claims/{cid}/evidence", json={"kind": "link", "title": "بيان وزارة الصناعة", "url": "https://example.gov/x"})
    case = admin.post("/api/cases", json={"title": "قضية للنقل", "summary": "ملخص سري"}).json()["id"]
    r = admin.post(f"/api/cases/{case}/documents", files=[("files", ("عقد.txt", "عقد سري بقيمة 2.4 مليون دينار مع شركة الأفق للمقاولات.".encode()))])
    assert r.json()["added"]
    e = admin.post("/api/engines", json={"name": "محرك متوافق", "provider": "openai_compatible", "model": "m1",
                                         "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-transfer-secret-1234",
                                         "price_in": 0.1, "price_out": 0.5})
    assert e.status_code == 200, e.text
    admin.put("/api/social/providers/x", json={"provider": "official", "credentials": {"bearer_token": "x-bearer-transfer"}})
    doc_sha = admin.get(f"/api/cases/{case}").json()["documents"][0]["sha256"]

    bundle = tmp_path / "نقل.marsad"
    with pytest.raises(transfer.TransferError):
        transfer.export_bundle(get_engine(), bundle, "قصيرة")
    m = transfer.export_bundle(get_engine(), bundle, PASS)
    assert m["tables"]["users"] == 2 and m["tables"]["claims"] == 1 and m["files"] >= 1
    assert b"sk-transfer-secret-1234" not in bundle.read_bytes() and "شركة الأفق".encode() not in bundle.read_bytes()
    old_secret = crypto.master_secret()

    # ---- الخادم الجديد: مجلد آخر، قاعدة أخرى، وسر رئيسي مختلف ----
    get_engine().dispose()
    url = os.environ.get("MARSAD_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'server.db'}"
    if url.startswith("postgresql"):
        eng = create_engine(url)
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        eng.dispose()
    monkeypatch.setenv("MARSAD_HOME", str(tmp_path / "server"))
    monkeypatch.setenv("MARSAD_DATABASE_URL", url)
    monkeypatch.setenv("MARSAD_SECRET_KEY", "server-secret-completely-different")
    from marsad.config import get_settings

    get_settings.cache_clear()
    assert crypto.master_secret() != old_secret
    from marsad.db import init_engine, migrate

    eng = init_engine(url)
    migrate()
    with pytest.raises(transfer.TransferError, match="عبارة المرور"):
        transfer.import_bundle(eng, bundle, "عبارة-خاطئة-تماما")
    r = transfer.import_bundle(eng, bundle, PASS)
    assert r["files"] >= 1
    with pytest.raises(transfer.TransferError, match="فيها حسابات"):
        transfer.import_bundle(eng, bundle, PASS)  # لا استيراد فوق بيانات قائمة

    from marsad.main import create_app

    c = Client(create_app())
    c.__enter__()
    try:
        assert c.get("/api/setup").json()["needs_setup"] is False
        assert c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}).status_code == 200
        me = c.get("/api/me").json()
        assert me["preferences"]["pattern"] == "b"
        claims = c.get("/api/claims").json()
        assert claims[0]["text"].startswith("ادّعاء للنقل")
        assert c.get(f"/api/claims/{cid}").json()["evidence"][0]["title"] == "بيان وزارة الصناعة"
        ov = c.get(f"/api/cases/{case}").json()
        assert ov["summary"] == "ملخص سري"
        assert c.get(f"/api/cases/{case}/documents/1").json()["text"][0].startswith("عقد سري")
        raw = c.get(f"/api/cases/{case}/documents/1/file").content
        import hashlib

        assert hashlib.sha256(raw).hexdigest() == doc_sha  # الملف المشفّر يُفتح بالسر الجديد
        assert c.get(f"/api/cases/{case}/custody").json()["verify"]["ok"] is True
        from marsad.db import get_db
        from marsad.models.engines import Engine
        from marsad.monitor import social

        db = next(get_db())
        assert crypto.decrypt(db.query(Engine).one().api_key_enc) == "sk-transfer-secret-1234"
        assert social.credentials(db, "x")[1]["bearer_token"] == "x-bearer-transfer"
        db.close()
        users = c.get("/api/admin/users").json()
        rows = users["users"] if isinstance(users, dict) else users
        j_row = next(u for u in rows if u["email"] == "j@example.com")
        assert {r["key"] for r in j_row["roles"]} == {"journalist", "researcher"}
        # الإضافات الجديدة على الخادم لا تتعارض مع المعرّفات المنقولة
        assert c.post("/api/claims", json={"text": "ادّعاء جديد على الخادم بعد النقل"}).status_code == 200
    finally:
        c.__exit__(None, None, None)


def test_transfer_export_from_ui(admin, make_client):
    assert admin.post("/api/admin/transfer/export", json={"passphrase": "123"}).status_code == 422
    r = admin.post("/api/admin/transfer/export", json={"passphrase": PASS}).json()
    assert r["records"] > 0 and r["name"].endswith(".marsad")
    assert admin.get(f"/api/admin/transfer/{r['name']}").status_code == 200
    assert admin.get("/api/admin/transfer/..%2Fsecret.key").status_code == 404
    j, _ = invite_user(admin, make_client, "j2@example.com", ["journalist"])
    assert j.post("/api/admin/transfer/export", json={"passphrase": PASS}).status_code == 403
