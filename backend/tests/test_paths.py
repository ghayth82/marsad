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
    assert p.exports == root.resolve() / "exports"


def test_idempotent(tmp_path):
    env = {"MARSAD_HOME": str(tmp_path)}
    ensure_storage(env)
    (tmp_path / "data" / "exports" / "x.csv").write_text("a")
    ensure_storage(env)
    assert (tmp_path / "data" / "exports" / "x.csv").read_text() == "a"


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
    assert p.backups == (tmp_path / "data" / "backups").resolve()
    assert not missing.parent.exists()  # لم نُنشئ «قرصًا» وهميًا
    assert p.warnings


def test_unwritable_root_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    with pytest.raises(StorageError):
        ensure_storage({"MARSAD_HOME": str(tmp_path), "MARSAD_DATA_DIR": str(blocker / "data")})
