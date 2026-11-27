from pathlib import Path

import pytest

from marsad.core.paths import SUBDIRS, StorageError, ensure_storage, resolve_data_root


def test_default_is_data_beside_app(tmp_path):
    env = {"MARSAD_HOME": str(tmp_path)}
    assert resolve_data_root(env) == (tmp_path / "data").resolve()


def test_relative_path_follows_app_home(tmp_path):
    # نقل البرنامج إلى جهاز آخر = MARSAD_HOME مختلف، والبيانات تتبعه
    a, b = tmp_path / "pc1", tmp_path / "pc2"
    env = {"MARSAD_DATA_DIR": "./data"}
    assert resolve_data_root({**env, "MARSAD_HOME": str(a)}) == (a / "data").resolve()
    assert resolve_data_root({**env, "MARSAD_HOME": str(b)}) == (b / "data").resolve()


def test_creates_all_missing_dirs(tmp_path):
    root = tmp_path / "deep" / "not" / "existing"
    p = ensure_storage({"MARSAD_HOME": str(tmp_path), "MARSAD_DATA_DIR": str(root)})
    assert p.root == root.resolve()
    for name in SUBDIRS.values():
        assert (root / name).is_dir()
    assert (p.backups / "db").is_dir() and (p.backups / "archive").is_dir()
    assert p.exports == root.resolve() / "ملفات النقل" and p.cases == root.resolve() / "التحقيقات"


def test_idempotent(tmp_path):
    env = {"MARSAD_HOME": str(tmp_path)}
    ensure_storage(env)
    (tmp_path / "data" / "ملفات النقل" / "x.csv").write_text("a")
    ensure_storage(env)
    assert (tmp_path / "data" / "ملفات النقل" / "x.csv").read_text() == "a"


def test_old_english_folders_move_to_arabic_names_once(tmp_path):
    """مجلدات الإصدار السابق تُنقل محتوياتها إلى الأسماء العربية دون استبدال ملف موجود، ويُزال القديم إن فرغ."""
    env = {"MARSAD_HOME": str(tmp_path)}
    data = tmp_path / "data"
    (data / "backups" / "db").mkdir(parents=True)
    (data / "backups" / "db" / "marsad-20261120-010000.marsad").write_text("old")
    (data / "exports").mkdir()
    (data / "exports" / "marsad-20261121-120000.marsad").write_text("t")
    (data / "النسخ الاحتياطي" / "db").mkdir(parents=True)
    (data / "النسخ الاحتياطي" / "db" / "keep.marsad").write_text("new")
    p = ensure_storage(env)
    assert (p.backups / "db" / "marsad-20261120-010000.marsad").read_text() == "old"
    assert (p.backups / "db" / "keep.marsad").read_text() == "new"
    assert (p.exports / "marsad-20261121-120000.marsad").read_text() == "t"
    assert not (data / "backups").exists() and not (data / "exports").exists()


def test_file_names_say_what_is_inside(tmp_path, monkeypatch):
    from datetime import date

    from marsad.core import naming

    monkeypatch.setenv("MARSAD_HOME", str(tmp_path))
    n = naming.file_name("خبرني", 'تأجيل الامتحانات: "أسبوعين" / عاجل؟ <b>', "ab12cd34" + "0" * 56, date(2026, 11, 27), ".html.gz")
    assert n == "خبرني - تأجيل الامتحانات أسبوعين عاجل؟ b - ab12cd34 - 2026-11-27.html.gz"
    assert len(naming.clean("كلمة " * 60)) <= naming.TITLE_MAX and naming.clean("CON") == "CON_" and naming.clean(" a - b. ") == "a b"
    rel = naming.save("media", "2026-11", name="صورة - جسر - 9f3e11aa - 2026-11-27.jpg", raw=b"one")
    assert rel == "الصور والفيديو/2026-11/صورة - جسر - 9f3e11aa - 2026-11-27.jpg"
    assert naming.save("media", "2026-11", name="صورة - جسر - 9f3e11aa - 2026-11-27.jpg", raw=b"one") == rel  # المحتوى نفسه: ملف واحد
    other = naming.save("media", "2026-11", name="صورة - جسر - 9f3e11aa - 2026-11-27.jpg", raw=b"two")
    assert other.endswith("2026-11-27 (2).jpg")  # اسم مطابق ومحتوى مختلف: لا يُستبدل


def test_env_var_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_DRIVE", str(tmp_path / "drive"))
    p = ensure_storage({"MARSAD_HOME": str(tmp_path), "MARSAD_DATA_DIR": "$MY_DRIVE/Marsad"})
    assert p.root == (tmp_path / "drive" / "Marsad").resolve()


def test_external_backup_used_when_disk_present(tmp_path):
    disk = tmp_path / "usb"
    disk.mkdir()
    p = ensure_storage({"MARSAD_HOME": str(tmp_path), "MARSAD_BACKUP_DIR": str(disk / "MarsadBackups")})
    assert p.backups == (disk / "MarsadBackups").resolve()
    assert not p.backup_fallback


def test_backup_falls_back_when_disk_missing(tmp_path):
    missing = tmp_path / "unplugged_drive" / "MarsadBackups"
    p = ensure_storage({"MARSAD_HOME": str(tmp_path), "MARSAD_BACKUP_DIR": str(missing)})
    assert p.backup_fallback
    assert p.backups == (tmp_path / "data" / "النسخ الاحتياطي").resolve()
    assert not missing.parent.exists()  # لم نُنشئ «قرصًا» وهميًا
    assert p.warnings


def test_unwritable_root_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    with pytest.raises(StorageError):
        ensure_storage({"MARSAD_HOME": str(tmp_path), "MARSAD_DATA_DIR": str(blocker / "data")})
