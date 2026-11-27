"""باقات النسخ الاحتياطي: اختيار ما يُنسخ ومكانه وموعده، والاسترداد الانتقائي بطريقتيه، والتشفير."""
import gzip
from datetime import datetime as dt, timezone

import pytest


def _claim(admin, text):
    r = admin.post("/api/claims", json={"text": text, "speaker": ""})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _pkg(admin, dest, **kw):
    body = {"name": "أسبوعي", "items": ["db:claims", "files:claims"], "dest": str(dest),
            "schedule": {"kind": "manual"}, "keep": 3, "encrypt": False, **kw}
    r = admin.post("/api/admin/backup/packages", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_table_belongs_to_exactly_one_group():
    from marsad.backups import DB_GROUPS, SKIP_TABLES, _tables

    seen = [t for d in DB_GROUPS.values() for t in d["tables"]]
    assert len(seen) == len(set(seen)), "جدول في قسمين"
    missing = set(_tables()) - set(seen) - SKIP_TABLES
    assert not missing, f"جداول جديدة بلا قسم في backups.DB_GROUPS: {missing}"


def test_catalog_and_dependencies(admin):
    c = admin.get("/api/admin/backup/catalog").json()
    claims = next(r for r in c["db"] if r["id"] == "db:claims")
    assert claims["label"] == "الشائعات والادعاءات" and "db:monitor" in claims["needs"] and "db:accounts" in claims["needs"]
    assert {r["label"] for r in c["files"]} >= {"الرصد", "التحقيقات", "الصور والفيديو"}
    assert "فهرس البحث" in c["not_included"]


def test_package_validation(admin, tmp_path):
    from marsad.core.paths import ensure_storage

    bad = {"name": "س", "items": [], "dest": str(tmp_path), "schedule": {"kind": "manual"}}
    assert "اختر شيئًا" in admin.post("/api/admin/backup/packages", json=bad).json()["detail"]
    inside = {**bad, "items": ["db:claims"], "dest": str(ensure_storage().media)}
    assert "داخل مجلد البيانات" in admin.post("/api/admin/backup/packages", json=inside).json()["detail"]
    enc = {**bad, "items": ["db:claims"], "encrypt": True}
    assert "عبارة مرور" in admin.post("/api/admin/backup/packages", json=enc).json()["detail"]
    p = _pkg(admin, tmp_path)
    assert "passphrase_enc" not in p and p["has_passphrase"] is False
    assert admin.post("/api/admin/backup/packages", json={**bad, "name": "أسبوعي", "items": ["db:claims"]}).status_code == 422  # الاسم مكرر


def test_backup_then_selective_restore_merge_and_replace(admin, tmp_path):
    from marsad.core.paths import ensure_storage

    dest = tmp_path / "usb"
    dest.mkdir()
    # المحذوف ليس الأخير: SQLite يعيد استعمال أكبر رقم بعد حذفه (PostgreSQL لا يفعل)
    lost_id = _claim(admin, "ادعاء سيُحذف ثم يُسترد")
    keep_id = _claim(admin, "ادعاء يبقى")
    admin.get("/api/claims/export/csv")  # ملف في «الشائعات والادعاءات»
    p = _pkg(admin, dest)
    assert admin.post(f"/api/admin/backup/packages/{p['id']}/run").json() == {"started": True}
    p = next(x for x in admin.get("/api/admin/backup/packages").json() if x["id"] == p["id"])
    assert p["last_status"] == "ok", p
    store = dest / "مرصد التحقق - نسخ احتياطية" / "أسبوعي"
    assert list(store.glob("نسخة - أسبوعي - *.marsad-backup")) and any((store / "ملفات" / "الشائعات والادعاءات").iterdir())

    # بعد النسخ: حُذف ادعاء، وأُضيف آخر، وحُذف الملف المصدَّر
    from marsad.db import get_db
    from marsad.models.claims import Claim

    db = next(get_db())
    db.delete(db.get(Claim, lost_id))
    db.commit()
    db.close()
    new_id = _claim(admin, "ادعاء أُضيف بعد النسخة")
    for f in ensure_storage().claims.iterdir():
        f.unlink()

    found = admin.post("/api/admin/backup/list", json={"folder": str(dest)}).json()
    assert len(found) == 1 and found[0]["package"] == "أسبوعي" and found[0]["encrypted"] is False
    info = admin.post("/api/admin/backup/inspect", json={"path": found[0]["path"]}).json()
    ids = {c["id"]: c for c in info["contents"]}
    assert ids["db:monitor"]["auto"] is True and ids["db:claims"]["auto"] is False and info["same_device"] is True

    # أضف الناقص: يعود المحذوف ويبقى الجديد، ويعود الملف، وتُؤخذ نسخة أمان أولًا
    r = admin.post("/api/admin/backup/restore", json={"path": found[0]["path"], "items": ["db:claims", "files:claims"], "mode": "merge"}).json()
    assert r["summary"]["files"] == 1 and r["summary"]["removed"] == 0 and r["safety_backup"]
    db = next(get_db())
    texts = {c.text for c in db.query(Claim)}
    db.close()
    assert {"ادعاء يبقى", "ادعاء سيُحذف ثم يُسترد", "ادعاء أُضيف بعد النسخة"} <= texts
    assert any(ensure_storage().claims.iterdir())

    # استبدل: تعود الادّعاءات كما كانت تمامًا، فيختفي ما أُضيف بعد النسخة
    r = admin.post("/api/admin/backup/restore", json={"path": found[0]["path"], "items": ["db:claims"], "mode": "replace"}).json()
    assert r["summary"]["removed"] >= 1
    db = next(get_db())
    assert db.get(Claim, new_id) is None and db.get(Claim, keep_id) is not None and db.get(Claim, lost_id) is not None
    db.close()
    # ما ليس في النسخة يُرفض
    assert "لا تحوي" in admin.post("/api/admin/backup/restore", json={"path": found[0]["path"], "items": ["db:cases"]}).json()["detail"]


def test_encrypted_package_and_incremental_files(admin, tmp_path):
    from marsad.core.paths import ensure_storage

    dest = tmp_path / "usb"
    dest.mkdir()
    secret = b"%PDF-1.4 secret contract text"
    d = ensure_storage().cases / "عقود"
    d.mkdir(parents=True)
    (d / "وثيقة 01 - عقد - aaaaaaaa - 2026-11-27.pdf").write_bytes(secret)
    p = _pkg(admin, dest, name="مشفّرة", items=["files:cases"], encrypt=True, passphrase="correct horse 9")
    assert p["has_passphrase"] is True
    admin.post(f"/api/admin/backup/packages/{p['id']}/run")
    store = dest / "مرصد التحقق - نسخ احتياطية" / "مشفّرة"
    copies = list((store / "ملفات").rglob("*.enc"))
    assert len(copies) == 1 and secret not in copies[0].read_bytes()
    mtime = copies[0].stat().st_mtime_ns
    admin.post(f"/api/admin/backup/packages/{p['id']}/run")  # نسخة ثانية: الملف لا يُنسخ من جديد
    assert copies[0].stat().st_mtime_ns == mtime and len(list(store.glob("*.marsad-backup"))) == 2

    path = admin.post("/api/admin/backup/list", json={"folder": str(store)}).json()[0]["path"]
    assert "مشفّرة" in admin.post("/api/admin/backup/inspect", json={"path": path}).json()["detail"]
    assert "غير صحيحة" in admin.post("/api/admin/backup/inspect", json={"path": path, "passphrase": "wrong pass 1"}).json()["detail"]
    (d / "وثيقة 01 - عقد - aaaaaaaa - 2026-11-27.pdf").unlink()
    r = admin.post("/api/admin/backup/restore", json={"path": path, "items": ["files:cases"], "passphrase": "correct horse 9"})
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["summary"]["files"] == 1 and r["safety_backup"] is None  # استرداد ملفات فقط: لا حاجة لنسخة أمان
    assert (d / "وثيقة 01 - عقد - aaaaaaaa - 2026-11-27.pdf").read_bytes() == secret


def test_keep_limit_and_unplugged_disk(admin, tmp_path):
    from marsad.db import get_db
    from marsad.models.engines import Notification

    dest = tmp_path / "usb"
    dest.mkdir()
    p = _pkg(admin, dest, name="قليلة", items=["db:ratings"], keep=2)
    for _ in range(3):
        admin.post(f"/api/admin/backup/packages/{p['id']}/run")
    assert len(list((dest / "مرصد التحقق - نسخ احتياطية" / "قليلة").glob("*.marsad-backup"))) == 2
    gone = _pkg(admin, tmp_path / "unplugged" / "E", name="قرص مفصول", items=["db:ratings"])
    admin.post(f"/api/admin/backup/packages/{gone['id']}/run")
    row = next(x for x in admin.get("/api/admin/backup/packages").json() if x["id"] == gone["id"])
    assert row["last_status"] == "error" and "غير متاح" in row["last_message"]
    assert not (tmp_path / "unplugged").exists()  # لم يُنشأ «قرص» وهمي
    db = next(get_db())
    assert db.query(Notification).filter_by(kind="backup.failed").count() == 1
    db.close()


def test_schedule_slots():
    from zoneinfo import ZoneInfo

    from marsad.backups import _slot

    tz = ZoneInfo("Asia/Amman")
    now = dt(2026, 11, 27, 10, 0, tzinfo=tz)  # جمعة
    assert _slot({"schedule": {"kind": "manual"}}, now) is None
    assert _slot({"schedule": {"kind": "daily", "time": "03:00"}}, now) == dt(2026, 11, 27, 3, 0, tzinfo=tz)
    assert _slot({"schedule": {"kind": "daily", "time": "23:00"}}, now) == dt(2026, 11, 26, 23, 0, tzinfo=tz)
    assert _slot({"schedule": {"kind": "weekly", "time": "03:00", "weekday": 0}}, now) == dt(2026, 11, 23, 3, 0, tzinfo=tz)
    assert _slot({"schedule": {"kind": "monthly", "time": "03:00", "day": 28}}, now) == dt(2026, 10, 28, 3, 0, tzinfo=tz)


def test_due_runs_scheduled_package_once(admin, tmp_path):
    from marsad import backups
    from marsad.db import get_db

    dest = tmp_path / "usb"
    dest.mkdir()
    p = _pkg(admin, dest, name="يومية", items=["db:ratings"], schedule={"kind": "daily", "time": "03:00"})
    db = next(get_db())
    at = dt(2026, 11, 27, 4, 0, tzinfo=timezone.utc)
    assert backups.due(db, at) == [p["id"]]
    backups.run_package(db, p["id"])
    pk = next(x for x in backups.packages(db) if x["id"] == p["id"])
    assert pk["last_status"] == "ok"
    assert backups.due(db, at) == []  # نُفّذت بعد موعد اليوم: لا تُعاد حتى الموعد التالي
    assert backups.due(db, dt(2026, 11, 28, 4, 0, tzinfo=timezone.utc)) in ([], [p["id"]])
    db.close()


def test_download_original_page(admin):
    from marsad.db import get_db
    from marsad.models.monitoring import Item, ItemVersion, Outlet, Source
    from marsad.monitor.service import archive_html
    from urllib.parse import unquote

    db = next(get_db())
    o = Outlet(name="خبرني", country="الأردن")
    db.add(o)
    db.flush()
    s = Source(outlet_id=o.id, url="https://kh.example/", kind="rss", read_url="https://kh.example/rss")
    db.add(s)
    db.flush()
    raw = "<html><title>خبر</title><body>نص الخبر</body></html>".encode()
    cap = dt(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
    rel, sha = archive_html(raw, cap, o.name, "تأجيل الامتحانات")
    it = Item(source_id=s.id, outlet_id=o.id, url="https://kh.example/1", title="تأجيل الامتحانات", text="", captured_at=cap, content_hash="x")
    it.versions.append(ItemVersion(version=1, change="new", title=it.title, text="", content_hash="x", captured_at=cap, archive_path=rel, archive_sha256=sha))
    db.add(it)
    db.commit()
    iid = it.id
    db.close()
    r = admin.get(f"/api/items/{iid}/archive/1/download")
    assert r.status_code == 200 and r.content == raw
    assert unquote(r.headers["content-disposition"]).endswith(f"خبرني - تأجيل الامتحانات - {sha[:8]} - 2026-11-27.html")
    import hashlib
    assert hashlib.sha256(r.content).hexdigest() == r.headers["x-archive-sha256"] == sha
