"""الحالة 36: نسخة احتياطية ثم حذف قاعدة البيانات ثم استعادة — يعود كل شيء كما كان."""

import os
from pathlib import Path

from sqlalchemy import create_engine, text

from tests.conftest import ADMIN, Client


def test_case36_backup_delete_restore(admin, tmp_path, monkeypatch):
    from marsad import transfer
    from marsad.db import get_engine

    cid = admin.post("/api/claims", json={"text": "ادّعاء قبل الحذف: الأسعار ترتفع غدًا"}).json()["id"]
    admin.post(f"/api/claims/{cid}/evidence", json={"kind": "link", "title": "بيان رسمي", "url": "https://example.gov/b"})
    case = admin.post("/api/cases", json={"title": "قضية قبل الحذف"}).json()["id"]
    admin.post(f"/api/cases/{case}/documents", files=[("files", ("و.txt", "وثيقة سرية عن عقد بقيمة مليون دينار.".encode()))])
    admin.patch("/api/me/preferences", json={"pattern": "a"})
    r = admin.post("/api/admin/backups").json()
    assert r["name"].endswith(".marsad")
    assert [b["name"] for b in admin.get("/api/admin/backups").json()] == [r["name"]]
    backup = transfer.list_backups()[0]

    # حذف قاعدة البيانات كليًا
    url = os.environ["MARSAD_DATABASE_URL"]
    get_engine().dispose()
    if url.startswith("sqlite"):
        Path(url.replace("sqlite:///", "")).unlink()
    else:
        eng = create_engine(url)
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        eng.dispose()
    from marsad.db import init_engine, migrate

    eng = init_engine(url)
    migrate()
    assert transfer.restore_backup(eng, backup)["tables"]["claims"] == 1

    from marsad.main import create_app

    c = Client(create_app())
    c.__enter__()
    try:
        assert c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}).status_code == 200
        assert c.get("/api/me").json()["preferences"]["pattern"] == "a"
        cl = c.get(f"/api/claims/{cid}").json()
        assert cl["text"].startswith("ادّعاء قبل الحذف") and cl["evidence"][0]["title"] == "بيان رسمي"
        assert c.get(f"/api/cases/{case}/documents/1").json()["text"][0].startswith("وثيقة سرية")
        assert c.get(f"/api/cases/{case}/documents/1/file").status_code == 200  # الملف المشفّر يُفتح
        # الاستعادة من الواجهة: تأكيد مطلوب، ونسخة أمان من الحال الحالي قبلها
        assert c.post("/api/admin/backups/restore", json={"name": backup.name, "confirm": "نعم"}).status_code == 422
        c.post("/api/claims", json={"text": "ادّعاء بعد الاستعادة"})
        rr = c.post("/api/admin/backups/restore", json={"name": backup.name, "confirm": "استعادة"}).json()
        assert rr["restored"] == backup.name and rr["safety_copy"]
        assert len(transfer.list_backups()) == 2
        c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
        assert [x["text"] for x in c.get("/api/claims").json()] == ["ادّعاء قبل الحذف: الأسعار ترتفع غدًا"]
    finally:
        c.__exit__(None, None, None)
