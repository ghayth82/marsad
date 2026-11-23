import json

import pytest

from marsad.core.paths import ensure_storage, load_storage_config, resolve_data_root
from marsad.core.storage_config import (
    apply_pending,
    cancel_pending,
    prepare,
    request_change,
    storage_status,
)


@pytest.fixture
def env(tmp_path):
    return {"MARSAD_HOME": str(tmp_path / "app")}


def _seed(env):
    p = ensure_storage(env)
    (p.archive / "page.html").write_text("نسخة مؤرشفة", encoding="utf-8")
    (p.exports / "report.csv").write_text("a,b")
    return p


def test_ui_request_does_not_touch_files(env, tmp_path):
    _seed(env)
    new = tmp_path / "D" / "MarsadData"
    cfg = request_change(data_dir=str(new), requested_by="ghayth", env=env)
    assert cfg["pending"]["data_dir"] == str(new)
    assert not new.exists()
    assert storage_status(env)["restart_required"]
    assert resolve_data_root(env) == (tmp_path / "app" / "data").resolve()  # لم يتغير بعد


def test_apply_moves_data_and_keeps_old(env, tmp_path):
    old = _seed(env).root
    (tmp_path / "D").mkdir()
    new = tmp_path / "D" / "MarsadData"
    request_change(data_dir=str(new), env=env)
    msgs = apply_pending(env)
    assert "نُسخ" in msgs[0]
    assert (new / "archive" / "page.html").read_text(encoding="utf-8") == "نسخة مؤرشفة"
    assert (old / "archive" / "page.html").exists()  # القديم لم يُحذف
    cfg = load_storage_config(env)
    assert cfg["data_dir"] == str(new) and cfg["pending"] is None
    assert cfg["history"][-1]["from"]["data_dir"] == "./data"
    assert resolve_data_root(env) == new.resolve()


def test_missing_drive_keeps_old_location_and_reports(env, tmp_path):
    _seed(env)
    request_change(data_dir=str(tmp_path / "Z_unplugged" / "MarsadData"), env=env)
    msgs = apply_pending(env)
    assert "لم يُطبَّق" in msgs[0]
    cfg = load_storage_config(env)
    assert cfg["data_dir"] == "./data" and cfg["pending"] is None
    assert "غير موجود" in cfg["last_error"]["message"]


def test_refuses_foreign_non_empty_folder(env, tmp_path):
    _seed(env)
    other = tmp_path / "Documents"
    other.mkdir()
    (other / "thesis.docx").write_text("x")
    request_change(data_dir=str(other), env=env)
    apply_pending(env)
    assert load_storage_config(env)["data_dir"] == "./data"
    assert "ليست من مرصد" in load_storage_config(env)["last_error"]["message"]


def test_refuses_nested_target(env, tmp_path):
    old = _seed(env).root
    request_change(data_dir=str(old / "inner"), env=env)
    apply_pending(env)
    assert load_storage_config(env)["last_error"]


def test_start_fresh_without_moving(env, tmp_path):
    _seed(env)
    (tmp_path / "E").mkdir()
    new = tmp_path / "E" / "Fresh"
    request_change(data_dir=str(new), move_data=False, env=env)
    apply_pending(env)
    p = ensure_storage(env)
    assert p.root == new.resolve()
    assert not (p.archive / "page.html").exists()


def test_change_backup_only(env, tmp_path):
    _seed(env)
    (tmp_path / "USB").mkdir()
    request_change(backup_dir=str(tmp_path / "USB" / "MarsadBackups"), env=env)
    apply_pending(env)
    p = ensure_storage(env)
    assert p.backups == (tmp_path / "USB" / "MarsadBackups").resolve()
    assert (p.backups / "db").is_dir()


def test_same_location_rejected_and_cancel(env):
    with pytest.raises(ValueError):
        request_change(data_dir="./data", env=env)
    request_change(data_dir="./other", env=env)
    assert cancel_pending(env)["pending"] is None


def test_prepare_ignores_container_paths_and_writes_host_info(env, tmp_path, capsys):
    host_env = {**env, "MARSAD_DATA_DIR": "/data"}  # متغير الحاوية لا يؤثر على الجهاز
    assert prepare(host_env) == 0
    out = capsys.readouterr().out
    assert f"MARSAD_DATA_ROOT={(tmp_path / 'app' / 'data').resolve()}" in out
    info = json.loads((tmp_path / "app" / "config" / "host-info.json").read_text(encoding="utf-8"))
    assert info["data"]["free_gb"] >= 0 and info["drives"]
