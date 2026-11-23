"""تغيير مكان التخزين من واجهة البرنامج.

الخدمات تعمل داخل Docker ولا ترى مسارات الجهاز، لذلك يجري التغيير على خطوتين:

1. الواجهة (الإدارة ← التخزين) تستدعي request_change(): يُحفظ «طلب تغيير»
   في config/storage.json دون لمس أي ملف.
2. عند إعادة التشغيل من الاختصار، يستدعي سكربت التشغيل على الجهاز نفسه
   apply_pending() قبل بدء الخدمات: يتحقق من المسار، يُنشئ المجلدات،
   ينسخ البيانات ويتحقق من النسخ، ثم يعتمد المكان الجديد.
   المجلد القديم لا يُحذف أبدًا؛ يحذفه المستخدم بنفسه إن أراد.

ويكتب السكربت config/host-info.json (الأقراص ومساحتها) لتعرضه الواجهة.

تشغيل من سطر الأوامر (يستخدمه start.sh):
    python -m marsad.core.storage_config prepare
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from marsad.core.paths import (
    ROOT_MARKER,
    StorageError,
    config_dir,
    disk_available,
    ensure_storage,
    ensure_writable,
    expand_path,
    load_storage_config,
    resolve_data_root,
    save_storage_config,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _host_env(env: Mapping[str, str] | None) -> dict:
    """على الجهاز نفسه نتجاهل مسارات الحاوية (/data) ونعتمد ملف الإعدادات."""
    env = dict(os.environ if env is None else env)
    env.pop("MARSAD_DATA_DIR", None)
    env.pop("MARSAD_BACKUP_DIR", None)
    return env


def _check_text(raw: str | None, label: str) -> str | None:
    if raw is None:
        return None
    raw = raw.strip()
    if any(ord(c) < 32 for c in raw):
        raise ValueError(f"{label}: المسار يحتوي رموزًا غير مسموحة")
    if len(raw) > 400:
        raise ValueError(f"{label}: المسار أطول من اللازم")
    return raw


# ---------- من الواجهة (داخل الحاوية) ----------

def request_change(*, data_dir: str | None = None, backup_dir: str | None = None,
                   move_data: bool = True, requested_by: str = "",
                   env: Mapping[str, str] | None = None) -> dict:
    """يسجّل طلب تغيير المكان. لا يلمس أي ملف؛ التنفيذ عند إعادة التشغيل."""
    data_dir = _check_text(data_dir, "مجلد البيانات")
    backup_dir = _check_text(backup_dir, "مجلد النسخ الاحتياطي")
    if data_dir == "":
        raise ValueError("مجلد البيانات لا يكون فارغًا")
    cfg = load_storage_config(env)
    if data_dir in (None, cfg["data_dir"]) and backup_dir in (None, cfg["backup_dir"]):
        raise ValueError("المكان المطلوب هو المكان الحالي نفسه")
    cfg["pending"] = {
        "data_dir": data_dir, "backup_dir": backup_dir, "move_data": bool(move_data),
        "requested_by": requested_by, "requested_at": _now(),
    }
    cfg["last_error"] = None
    save_storage_config(cfg, env)
    return cfg


def cancel_pending(env: Mapping[str, str] | None = None) -> dict:
    cfg = load_storage_config(env)
    cfg["pending"] = None
    save_storage_config(cfg, env)
    return cfg


def storage_status(env: Mapping[str, str] | None = None) -> dict:
    """ما تعرضه شاشة «التخزين»: المكان الحالي، الطلب المعلّق، آخر خطأ، الأقراص."""
    cfg = load_storage_config(env)
    info_path = config_dir(env) / "host-info.json"
    try:
        host = json.loads(info_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        host = None
    return {**cfg, "host": host, "restart_required": cfg.get("pending") is not None}


# ---------- على الجهاز (سكربت التشغيل) ----------

def _tree_stats(path: Path) -> tuple[int, int]:
    files = size = 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            size += p.stat().st_size
    return files, size


def _is_within(a: Path, b: Path) -> bool:
    try:
        a.relative_to(b)
        return True
    except ValueError:
        return False


def _move_data(old: Path, new: Path) -> str:
    if _is_within(new, old) or _is_within(old, new):
        raise StorageError("لا يمكن أن يكون المكان الجديد داخل القديم أو العكس")
    if not disk_available(new):
        raise StorageError(f"القرص أو المجلد الأب غير موجود: {new.parent}")
    ensure_writable(new)
    has_content = any(p.name not in (ROOT_MARKER,) for p in new.iterdir())
    if has_content and not (new / ROOT_MARKER).exists():
        raise StorageError(f"المجلد {new} فيه ملفات ليست من مرصد؛ اختر مجلدًا فارغًا")
    if not old.exists():
        return "لا توجد بيانات سابقة للنسخ"
    files, size = _tree_stats(old)
    free = shutil.disk_usage(new).free
    if size > free * 0.95:
        raise StorageError(
            f"المساحة غير كافية: البيانات {size / 2**30:.1f} غيغابايت والمتاح {free / 2**30:.1f}")
    shutil.copytree(old, new, dirs_exist_ok=True)
    new_files, new_size = _tree_stats(new)
    if new_files < files or new_size < size:
        raise StorageError("النسخ لم يكتمل (عدد الملفات أو حجمها أقل من الأصل)؛ لم يُعتمد المكان الجديد")
    return f"نُسخ {files} ملفًا ({size / 2**20:.1f} ميغابايت). المجلد القديم {old} باقٍ ولم يُحذف"


def apply_pending(env: Mapping[str, str] | None = None) -> list[str]:
    """ينفّذ طلب التغيير إن وُجد. عند أي خطأ يبقى المكان القديم ويُسجَّل الخطأ للواجهة."""
    env = _host_env(env)
    cfg = load_storage_config(env)
    pending = cfg.get("pending")
    if not pending:
        return []
    messages: list[str] = []
    try:
        if pending.get("data_dir") and pending["data_dir"] != cfg["data_dir"]:
            old = resolve_data_root(env)
            new = expand_path(pending["data_dir"], env)
            if pending.get("move_data", True):
                messages.append(_move_data(old, new))
            else:
                if not disk_available(new):
                    raise StorageError(f"القرص أو المجلد الأب غير موجود: {new.parent}")
                ensure_writable(new)
                messages.append(f"بدأ مجلد بيانات جديد فارغ في {new}؛ القديم {old} باقٍ كما هو")
        if pending.get("backup_dir") is not None and pending["backup_dir"] != cfg["backup_dir"]:
            if pending["backup_dir"]:
                target = expand_path(pending["backup_dir"], env)
                if not disk_available(target):
                    raise StorageError(f"قرص النسخ الاحتياطي غير موصول: {target.parent}")
                ensure_writable(target)
            messages.append(f"مجلد النسخ الاحتياطي الجديد: {pending['backup_dir'] or 'data/backups'}")
    except (StorageError, OSError) as exc:
        cfg["pending"] = None
        cfg["last_error"] = {"message": str(exc), "at": _now(), "request": pending}
        save_storage_config(cfg, env)
        return [f"لم يُطبَّق تغيير المكان: {exc}"]

    cfg["history"] = (cfg.get("history") or []) + [{
        "from": {"data_dir": cfg["data_dir"], "backup_dir": cfg["backup_dir"]},
        "to": {"data_dir": pending.get("data_dir") or cfg["data_dir"],
               "backup_dir": cfg["backup_dir"] if pending.get("backup_dir") is None else pending["backup_dir"]},
        "requested_by": pending.get("requested_by", ""), "applied_at": _now(),
    }]
    if pending.get("data_dir"):
        cfg["data_dir"] = pending["data_dir"]
    if pending.get("backup_dir") is not None:
        cfg["backup_dir"] = pending["backup_dir"]
    cfg["pending"] = None
    cfg["last_error"] = None
    save_storage_config(cfg, env)
    return messages


def _drive_candidates() -> list[Path]:
    seen, out = set(), []
    cands = [Path("/"), Path.home()]
    for base in ("/mnt", "/media", "/srv", "/Volumes"):
        b = Path(base)
        if b.is_dir():
            cands += [p for p in b.iterdir() if p.is_dir()]
            cands += [q for p in b.iterdir() if p.is_dir() for q in p.iterdir()
                      if base == "/media" and q.is_dir()]
    for p in cands:
        try:
            dev = os.stat(p).st_dev
        except OSError:
            continue
        if dev not in seen:
            seen.add(dev)
            out.append(p)
    return out


def write_host_info(paths, env: Mapping[str, str] | None = None) -> Path:
    def usage(p: Path) -> dict:
        u = shutil.disk_usage(p)
        return {"path": str(p), "free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1)}

    drives = []
    for p in _drive_candidates():
        try:
            drives.append(usage(p))
        except OSError:
            pass
    info = {
        "generated_at": _now(), "os": platform.system(),
        "data": usage(paths.root), "backups": usage(paths.backups),
        "backup_fallback": paths.backup_fallback, "warnings": paths.warnings,
        "drives": drives,
    }
    d = config_dir(env)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "host-info.json"
    out.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def prepare(env: Mapping[str, str] | None = None) -> int:
    """خطوة ما قبل التشغيل: تطبيق الطلب المعلّق، إنشاء المجلدات، كتابة معلومات الأقراص."""
    env = _host_env(env)
    for m in apply_pending(env):
        print(m, file=sys.stderr)
    try:
        paths = ensure_storage(env)
    except StorageError as exc:
        print(f"خطأ: {exc}", file=sys.stderr)
        return 1
    for w in paths.warnings:
        print(f"تنبيه: {w}", file=sys.stderr)
    write_host_info(paths, env)
    print(f"MARSAD_DATA_ROOT={paths.root}")
    print(f"MARSAD_BACKUP_ROOT={paths.backups}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "prepare":
        raise SystemExit(prepare())
    print("الاستخدام: python -m marsad.core.storage_config prepare", file=sys.stderr)
    raise SystemExit(2)
