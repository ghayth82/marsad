"""مسارات التخزين في «مرصد التحقق».

كل ما ينتجه البرنامج يُحفظ تحت «جذر بيانات» واحد. أولوية تحديده:
1. المتغير MARSAD_DATA_DIR (تستخدمه الحاويات: /data).
2. ملف config/storage.json الذي يعدّله المدير من واجهة البرنامج.
3. الافتراضي: المجلد data/ بجانب البرنامج.

المسار النسبي يُحسب نسبةً إلى مجلد البرنامج (MARSAD_HOME)، فإذا نُقل
البرنامج إلى جهاز آخر انتقلت معه بياناته دون تعديل أي إعداد.

كل المجلدات الفرعية تُنشأ تلقائيًا عند التشغيل إن لم تكن موجودة.

مجلد النسخ الاحتياطي قد يكون على قرص خارجي. إن لم يكن القرص موصولًا
(المجلد الأب غير موجود) فلا نُنشئ المسار على القرص الداخلي بالخطأ، بل
نرجع إلى data/backups ونرفع تنبيهًا.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

SUBDIRS: dict[str, str] = {
    "archive": "archive",  # أرشيف MinIO: الصفحات المؤرشفة والصور والفيديو والوثائق
    "exports": "exports",  # تصدير Word وCSV وClaimReview
    "reports": "reports",  # الموجز الصباحي والتقرير الأسبوعي
    "backups": "backups",  # النسخ الاحتياطي الافتراضي (إن لم يُحدَّد قرص خارجي)
    "logs": "logs",  # سجلات التشغيل
    "uploads": "uploads",  # ملفات يرفعها المستخدم قبل معالجتها
    "tmp": "tmp",  # ملفات مؤقتة تُمسح دوريًا
}
BACKUP_SUBDIRS = ("db", "archive")
DEFAULT_DATA_DIR = "./data"
ROOT_MARKER = ".marsad-data"  # يميّز مجلد بيانات مرصد عن أي مجلد آخر


class StorageError(RuntimeError):
    """جذر البيانات غير قابل للإنشاء أو الكتابة."""


@dataclass(frozen=True)
class StoragePaths:
    root: Path
    dirs: dict[str, Path]
    backups: Path
    backup_fallback: bool = False
    warnings: list[str] = field(default_factory=list)

    def __getattr__(self, name: str) -> Path:  # paths.exports, paths.archive ...
        dirs = object.__getattribute__(self, "dirs")
        if name in dirs:
            return dirs[name]
        raise AttributeError(name)


# ---------- مجلد البرنامج والإعدادات ----------

def app_home(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    home = env.get("MARSAD_HOME")
    if home:
        return Path(home).expanduser().resolve()
    return Path(__file__).resolve().parents[3]  # backend/marsad/core/paths.py


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get("MARSAD_CONFIG_DIR")
    return Path(raw).expanduser().resolve() if raw else app_home(env) / "config"


def load_storage_config(env: Mapping[str, str] | None = None) -> dict:
    defaults = {"data_dir": DEFAULT_DATA_DIR, "backup_dir": "", "pending": None,
                "last_error": None, "history": []}
    path = config_dir(env) / "storage.json"
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return defaults
    return {**defaults, **data}


def save_storage_config(cfg: dict, env: Mapping[str, str] | None = None) -> Path:
    d = config_dir(env)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "storage.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # كتابة ذرّية: لا ملف نصف مكتوب
    return path


def expand_path(raw: str, env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    expanded = os.path.expandvars(raw.strip().strip('"').strip("'"))
    p = Path(expanded).expanduser()
    if not p.is_absolute():
        p = app_home(env) / p
    return p.resolve()


# ---------- التحديد والإنشاء ----------

def resolve_data_root(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get("MARSAD_DATA_DIR") or load_storage_config(env).get("data_dir") or DEFAULT_DATA_DIR
    return expand_path(raw, env)


def ensure_writable(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".write-test-", delete=True):
            pass
    except OSError as exc:
        raise StorageError(f"لا يمكن إنشاء المجلد أو الكتابة فيه: {path} ({exc})") from exc


def disk_available(target: Path) -> bool:
    """القرص موصول إن كان المجلد أو أبوه موجودًا. لا نُنشئ «قرصًا» من العدم."""
    return target.exists() or target.parent.exists()


def _resolve_backups(env: Mapping[str, str], root: Path) -> tuple[Path, bool, list[str]]:
    default = root / SUBDIRS["backups"]
    raw = env.get("MARSAD_BACKUP_DIR")
    if raw is None:
        raw = load_storage_config(env).get("backup_dir") or ""
    if not raw:
        return default, False, []
    target = expand_path(raw, env)
    if disk_available(target):
        try:
            ensure_writable(target)
            return target, False, []
        except StorageError as exc:
            return default, True, [f"تعذّرت الكتابة في مجلد النسخ الاحتياطي ({exc})؛ استُخدم {default}"]
    return default, True, [
        f"مجلد النسخ الاحتياطي {target} غير متاح (القرص غير موصول؟)؛ استُخدم مؤقتًا {default}"
    ]


def ensure_storage(env: Mapping[str, str] | None = None) -> StoragePaths:
    """يحدد جذر البيانات ويُنشئ كل المجلدات الناقصة. يُستدعى عند بدء كل خدمة."""
    env = os.environ if env is None else env
    root = resolve_data_root(env)
    ensure_writable(root)
    (root / ROOT_MARKER).touch(exist_ok=True)

    dirs = {}
    for key, name in SUBDIRS.items():
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        dirs[key] = d

    backups, fallback, warnings = _resolve_backups(env, root)
    for sub in BACKUP_SUBDIRS:
        (backups / sub).mkdir(parents=True, exist_ok=True)
    dirs["backups"] = backups

    return StoragePaths(root=root, dirs=dirs, backups=backups,
                        backup_fallback=fallback, warnings=warnings)
