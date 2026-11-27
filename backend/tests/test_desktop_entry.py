"""نقطة تشغيل نسخة الجهاز تطبع المسارات العربية حتى لو كان ترميز المخرجات cp1252 (ويندوز مع التحويل إلى ملف)."""
import os
import subprocess
import sys


def test_prepare_prints_arabic_paths_under_cp1252(tmp_path):
    env = {**os.environ, "MARSAD_HOME": str(tmp_path), "MARSAD_CONFIG_DIR": str(tmp_path / "config"),
           "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    env.pop("MARSAD_DATA_DIR", None)
    env.pop("MARSAD_BACKUP_DIR", None)
    r = subprocess.run([sys.executable, "-m", "marsad.desktop", "prepare"], env=env, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    out = r.stdout.decode("utf-8")
    assert "MARSAD_BACKUP_ROOT=" in out and "النسخ الاحتياطي" in out
