"""باقات النسخ الاحتياطي: يختار المدير ما يُنسخ (أقسام قاعدة البيانات ومجلدات الملفات) ومكانه وموعده،
ويسترد من أي نسخة ما يختاره منها.

مكان الباقة على القرص:
    <المكان المختار>/مرصد التحقق - نسخ احتياطية/<اسم الباقة>/
        نسخة - <الباقة> - 2026-11-27 0330.marsad-backup   ملف لكل نسخة: جداول القاعدة وقائمة الملفات
        ملفات/                                              مخزن الملفات المشترك بين نسخ الباقة
        .marsad-backup-store                                 علامة المخزن (وملح التشفير إن وُجد)

ملفات المحتوى لا تتغيّر بعد حفظها، فالمخزن يُنسخ إليه الجديد فقط (نسخ تراكمي)، وكل نسخة تحمل قائمة ما كان
موجودًا وقتها. المخزن لا يُقلَّم حين تُحذف نسخة قديمة.

الاسترداد: «أضف الناقص» (الافتراضي) يعيد ما ليس موجودًا ولا يمس ما تغيّر؛ «استبدل» يعيد الأقسام المختارة كما
كانت في النسخة، ويحذف ما أُضيف بعدها (ومعه ما يرتبط به). قبل كل استرداد تُؤخذ نسخة أمان من الوضع الحالي.
الملفات لا تُحذف عند الاسترداد في أي من الوضعين: يُعاد الناقص فقط.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine, Table, and_, delete, func, insert, select, text, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.core import naming
from marsad.core.paths import SUBDIRS, disk_available, ensure_storage, expand_path
from marsad.transfer import ENCRYPTED_COLUMNS, _de, _rekey, _rekey_setting, _ser

log = logging.getLogger(__name__)

FORMAT = 1
ROOT_NAME = "مرصد التحقق - نسخ احتياطية"
STORE_NAME = "ملفات"
MARKER = ".marsad-backup-store"
EXT = ".marsad-backup"
SETTING = "backup.packages"
SAFETY_KEEP = 5

# ---------- ما يمكن نسخه ----------

DB_GROUPS: dict[str, dict] = {
    "accounts": {"label": "الحسابات والإعدادات", "hint": "المستخدمون وأدوارهم وتفضيلاتهم، المحركات ومفاتيحها، إعدادات البرنامج",
                 "tables": ["users", "roles", "role_permissions", "role_templates", "user_roles", "user_permissions", "user_preferences",
                            "invites", "system_settings", "engines", "api_tokens", "webhooks", "audit_log"]},
    "monitor": {"label": "المصادر والأخبار", "hint": "المواقع والقنوات، والأخبار المرصودة ونسخها",
                "tables": ["outlets", "sources", "items", "item_versions"]},
    "stories": {"label": "القصص والكيانات", "hint": "تجميع القصص، والأشخاص والجهات وتصريحاتهم ووعودهم",
                "tables": ["stories", "entities", "entity_mentions", "statements", "promises"]},
    "claims": {"label": "الشائعات والادعاءات", "hint": "الادّعاءات وأدلتها وأحكامها والتصحيحات",
               "tables": ["claims", "claim_items", "evidence", "verdicts", "corrections"]},
    "labs": {"label": "فحوص الصور والفيديو والصوت", "hint": "سجل ما فُحص ونتائج كل فحص",
             "tables": ["media_files", "media_checks"]},
    "tools": {"label": "أدوات التحقق", "hint": "الصفحات المحفوظة، البلاغات، الأرقام الرسمية",
              "tables": ["snapshots", "tips", "official_figures"]},
    "cases": {"label": "التحقيقات", "hint": "التحقيقات وأعضاؤها ووثائقها وسجلاتها ومسوداتها، وقوائم العقوبات",
              "tables": ["cases", "case_members", "case_documents", "case_records", "custody_log", "drafts", "sanction_entries"]},
    "ratings": {"label": "تقييم المواقع", "hint": "المنهجية والدرجات والوسوم وحق الرد",
                "tables": ["rating_methodologies", "rating_scores", "rating_labels", "rating_replies"]},
    "engines_log": {"label": "سجل تشغيل المحركات", "hint": "ما شُغّل من مهام الذكاء الاصطناعي ونتائجه وقرارات الدمج",
                    "tables": ["engine_batches", "engine_runs", "engine_decisions", "merge_runs"]},
    "reports": {"label": "التقارير والتنبيهات والتدريب", "hint": "الموجز والتقارير، التنبيهات وإرسالها، التمارين وإجاباتها",
                "tables": ["reports", "notifications", "alert_deliveries", "exercises", "submissions", "webhook_deliveries"]},
}
# جداول لا تُنسخ: جلسات الدخول (تنتهي وحدها)
SKIP_TABLES = {"sessions", "session_tokens", "alembic_version"}

FILE_GROUPS: dict[str, dict] = {
    "monitor": {"label": SUBDIRS["monitor"], "hint": "صفحات الأخبار المؤرشفة", "dirs": [SUBDIRS["monitor"], "archive/pages"]},
    "media": {"label": SUBDIRS["media"], "hint": "الصور والفيديو التي فُحصت", "dirs": [SUBDIRS["media"], "archive/media"]},
    "audio": {"label": SUBDIRS["audio"], "hint": "التسجيلات", "dirs": [SUBDIRS["audio"]]},
    "cases": {"label": SUBDIRS["cases"], "hint": "وثائق التحقيقات", "dirs": [SUBDIRS["cases"], "archive/cases"]},
    "claims": {"label": SUBDIRS["claims"], "hint": "ما صُدّر من الادّعاءات", "dirs": [SUBDIRS["claims"]]},
    "stories": {"label": SUBDIRS["stories"], "hint": "مسودات Word", "dirs": [SUBDIRS["stories"]]},
    "reports": {"label": SUBDIRS["reports"], "hint": "الموجز والتقارير المحفوظة", "dirs": [SUBDIRS["reports"]]},
    "tools": {"label": SUBDIRS["tools"], "hint": "الصفحات المحفوظة ولقطاتها", "dirs": [SUBDIRS["tools"], "archive/snapshots"]},
}


class BackupError(Exception):
    pass


def _tables() -> dict[str, Table]:
    import marsad.models  # noqa: F401
    from marsad.db import Base

    return {t.name: t for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES}


def _order() -> list[str]:
    import marsad.models  # noqa: F401
    from marsad.db import Base

    return [t.name for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES]


def table_group() -> dict[str, str]:
    return {t: g for g, d in DB_GROUPS.items() for t in d["tables"]}


def db_closure(groups: set[str]) -> set[str]:
    """الأقسام المختارة ومعها ما تعتمد عليه (الادّعاء يحتاج الخبر الذي يشير إليه، وكل شيء يحتاج الحسابات)."""
    tg, tables = table_group(), _tables()
    out, todo = set(), list(groups)
    while todo:
        g = todo.pop()
        if g in out or g not in DB_GROUPS:
            continue
        out.add(g)
        for tn in DB_GROUPS[g]["tables"]:
            t = tables.get(tn)
            for fk in (t.foreign_keys if t is not None else ()):
                pg = tg.get(fk.column.table.name)
                if pg and pg not in out:
                    todo.append(pg)
    return out


def _file_iter(root: Path, group: str):
    for d in FILE_GROUPS[group]["dirs"]:
        base = root / d
        if not base.is_dir():
            continue
        for dirpath, _dirs, names in os.walk(base):
            for n in names:
                p = Path(dirpath) / n
                yield p.relative_to(root).as_posix(), p


def catalog(db: Session) -> dict:
    """ما يمكن اختياره، بحجمه الحالي، وما يُضاف تلقائيًا مع كل قسم."""
    tables = _tables()
    db_rows = []
    for g, d in DB_GROUPS.items():
        n = sum(db.scalar(select(func.count()).select_from(tables[t])) or 0 for t in d["tables"] if t in tables)
        db_rows.append({"id": f"db:{g}", "label": d["label"], "hint": d["hint"], "rows": n,
                        "needs": [f"db:{x}" for x in sorted(db_closure({g}) - {g})]})
    root = ensure_storage().root
    file_rows = []
    for g, d in FILE_GROUPS.items():
        files = size = 0
        for _rel, p in _file_iter(root, g):
            try:
                size += p.stat().st_size
                files += 1
            except OSError:
                pass
        file_rows.append({"id": f"files:{g}", "label": d["label"], "hint": d["hint"], "files": files, "bytes": size})
    return {"db": db_rows, "files": file_rows,
            "not_included": "فهرس البحث (يُعاد بناؤه)، النماذج المحلية (تُنزَّل من جديد)، السجلات والملفات المؤقتة، وجلسات الدخول."}


def _split(items: list[str]) -> tuple[set[str], set[str]]:
    dbs = {x[3:] for x in items if x.startswith("db:") and x[3:] in DB_GROUPS}
    files = {x[6:] for x in items if x.startswith("files:") and x[6:] in FILE_GROUPS}
    return dbs, files


# ---------- التشفير ----------

def _key(passphrase: str, salt: bytes) -> Fernet:
    if len(passphrase) < 8:
        raise BackupError("عبارة المرور 8 أحرف على الأقل")
    k = hashlib.scrypt(passphrase.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return Fernet(base64.urlsafe_b64encode(k))


def _secret_id() -> str:
    return hashlib.sha256(("id:" + crypto.master_secret()).encode()).hexdigest()[:16]


def _store_marker(store_dir: Path, encrypted: bool) -> dict:
    """علامة مخزن الباقة. الملح يُنشأ مرة واحدة، فكل نسخ الباقة تُفتح بعبارة المرور نفسها."""
    m = store_dir / MARKER
    if m.exists():
        info = json.loads(m.read_text(encoding="utf-8"))
        if bool(info.get("salt")) != encrypted:
            raise BackupError("مكان هذه الباقة فيه نسخ " + ("مشفّرة" if info.get("salt") else "غير مشفّرة")
                              + ". غيّر اسم الباقة أو مكانها قبل تغيير التشفير.")
        return info
    info = {"format": FORMAT, "salt": base64.b64encode(os.urandom(16)).decode() if encrypted else ""}
    m.write_text(json.dumps(info), encoding="utf-8")
    return info


# ---------- إنشاء نسخة ----------

def package_dir(dest: str, name: str) -> Path:
    """مكان نسخ الباقة. دون مكان (النسخة اليومية افتراضيًا): داخل مجلد «النسخ الاحتياطي» الذي يحدده «التخزين»."""
    if not dest:
        return ensure_storage().backups / (naming.clean(name, 60) or "باقة")
    return expand_path(dest) / ROOT_NAME / (naming.clean(name, 60) or "باقة")


def create_backup(engine: Engine, items: list[str], store_dir: Path, name: str, passphrase: str | None = None,
                  keep: int = 0, now: datetime | None = None) -> dict:
    """ينشئ نسخة في مجلد الباقة. يُرجع ملخصها. القرص غير الموصول يرفع BackupError دون كتابة شيء."""
    from marsad.migrate import current_revision

    if not items:
        raise BackupError("اختر شيئًا واحدًا على الأقل لنسخه")
    if not disk_available(store_dir.parent.parent):
        raise BackupError(f"المكان {store_dir.parent.parent} غير متاح (القرص غير موصول؟)")
    dbs, file_groups = _split(items)
    dbs_all = db_closure(dbs)
    store_dir.mkdir(parents=True, exist_ok=True)
    info = _store_marker(store_dir, bool(passphrase))
    box = _key(passphrase, base64.b64decode(info["salt"])) if passphrase else None
    seal = (lambda b: box.encrypt(b)) if box else (lambda b: b)
    now = now or datetime.now()
    stem = f"نسخة - {naming.clean(name, 60) or 'باقة'} - {now:%Y-%m-%d %H%M%S}"
    out, n = store_dir / f"{stem}{EXT}", 1
    while out.exists() or out.with_name(out.name + ".part").exists():  # نسختان في الثانية نفسها: لا تُستبدل الأولى
        n += 1
        out = store_dir / f"{stem} ({n}){EXT}"
    tmp = out.with_name(out.name + ".part")
    counts: dict[str, int] = {}
    tables = _tables()
    files_meta: dict[str, int] = {}
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        with engine.connect() as conn:
            for g in sorted(dbs_all):
                for tn in DB_GROUPS[g]["tables"]:
                    if tn not in tables:
                        continue
                    rows = conn.execute(select(tables[tn])).mappings().all()
                    counts[tn] = len(rows)
                    body = "\n".join(json.dumps({k: _ser(v) for k, v in r.items()}, ensure_ascii=False) for r in rows)
                    z.writestr(f"tables/{tn}.jsonl", seal(body.encode()))
        root = ensure_storage().root
        lines = []
        store = store_dir / STORE_NAME
        for g in sorted(file_groups):
            n = 0
            for rel, p in _file_iter(root, g):
                if ".." in Path(rel).parts:
                    continue
                target = store / (rel + (".enc" if box else ""))
                try:
                    size = p.stat().st_size
                    if not target.exists() or (not box and target.stat().st_size != size):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        part = target.with_name(target.name + ".part")
                        if box:
                            part.write_bytes(box.encrypt(p.read_bytes()))
                        else:
                            shutil.copy2(p, part)
                        part.replace(target)
                except OSError as e:
                    log.warning("تعذّر نسخ %s: %s", rel, e)
                    continue
                lines.append(json.dumps({"g": g, "rel": rel, "size": size}, ensure_ascii=False))
                n += 1
            files_meta[g] = n
        z.writestr("files.jsonl", seal("\n".join(lines).encode()))
        if box:
            z.writestr("secret.enc", box.encrypt(crypto.master_secret().encode()))
        header = {"format": FORMAT, "app": "marsad", "created_at": datetime.now(timezone.utc).isoformat(), "package": name,
                  "revision": current_revision(engine), "encrypted": bool(box), "secret_id": _secret_id(),
                  "items": sorted([f"db:{g}" for g in dbs] + [f"files:{g}" for g in file_groups]),
                  "auto_added": sorted(f"db:{g}" for g in dbs_all - dbs), "tables": counts, "files": files_meta}
        z.writestr("header.json", json.dumps(header, ensure_ascii=False, indent=1))
    tmp.replace(out)
    if keep:
        olds = sorted((p for p in store_dir.glob(f"*{EXT}")), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in olds[keep:]:
            p.unlink(missing_ok=True)
    return {"file": str(out), "size": out.stat().st_size, "tables": sum(counts.values()), "files": sum(files_meta.values())}


# ---------- قراءة النسخ ----------

def list_backups(folder: str) -> list[dict]:
    """النسخ في المجلد المختار: المجلد نفسه، أو «مرصد التحقق - نسخ احتياطية» فيه، أو مجلد باقة."""
    base = expand_path(folder)
    if not base.is_dir():
        raise BackupError("المجلد غير موجود")
    hits: list[Path] = []
    for pattern in (f"*{EXT}", f"*/*{EXT}", f"*/*/*{EXT}"):
        hits += list(base.glob(pattern))
    out = []
    for p in sorted(set(hits), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append({"path": str(p), "name": p.name, "size": p.stat().st_size, **_header(p)})
        except BackupError:
            continue
    return out


def _header(p: Path) -> dict:
    try:
        with zipfile.ZipFile(p) as z:
            h = json.loads(z.read("header.json"))
    except (zipfile.BadZipFile, KeyError, OSError, json.JSONDecodeError):
        raise BackupError("ليس ملف نسخة احتياطية من «مرصد التحقق»") from None
    if h.get("app") != "marsad":
        raise BackupError("ليس ملف نسخة احتياطية من «مرصد التحقق»")
    return {k: h.get(k) for k in ("created_at", "package", "encrypted", "items", "auto_added", "tables", "files", "revision")}


def _open(p: Path, passphrase: str | None) -> tuple[zipfile.ZipFile, dict, Fernet | None]:
    if p.suffix != EXT or not p.is_file():
        raise BackupError("اختر ملف نسخة احتياطية (" + EXT + ")")
    z = zipfile.ZipFile(p)
    h = json.loads(z.read("header.json"))
    box = None
    if h.get("encrypted"):
        if not passphrase:
            z.close()
            raise BackupError("هذه النسخة مشفّرة: اكتب عبارة المرور")
        info = json.loads((p.parent / MARKER).read_text(encoding="utf-8")) if (p.parent / MARKER).exists() else {}
        if not info.get("salt"):
            z.close()
            raise BackupError("ملف علامة المخزن مفقود بجانب النسخة؛ لا يمكن فتحها")
        box = _key(passphrase, base64.b64decode(info["salt"]))
        try:
            box.decrypt(z.read("secret.enc"))
        except InvalidToken:
            z.close()
            raise BackupError("عبارة المرور غير صحيحة") from None
    return z, h, box


def inspect(path: str, passphrase: str | None = None) -> dict:
    p = expand_path(path)
    z, h, _box = _open(p, passphrase)
    z.close()
    tg = table_group()
    groups: dict[str, int] = {}
    for tn, n in (h.get("tables") or {}).items():
        g = tg.get(tn)
        if g:
            groups[g] = groups.get(g, 0) + n
    rows = [{"id": f"db:{g}", "label": DB_GROUPS[g]["label"], "rows": n, "auto": f"db:{g}" in (h.get("auto_added") or [])}
            for g, n in groups.items()]
    rows += [{"id": f"files:{g}", "label": FILE_GROUPS[g]["label"], "files": n} for g, n in (h.get("files") or {}).items() if g in FILE_GROUPS]
    return {"path": str(p), "created_at": h["created_at"], "package": h.get("package"), "encrypted": h.get("encrypted"),
            "same_device": h.get("secret_id") == _secret_id(), "contents": rows}


# ---------- الاسترداد ----------

def _pk(t: Table) -> list:
    return list(t.primary_key.columns)


def _key_of(t: Table, r: dict) -> tuple:
    return tuple(r[c.name] for c in _pk(t))


def _restore_table(conn, t: Table, rows: list[dict], replace: bool) -> dict:
    pk = _pk(t)
    existing = {tuple(x) for x in conn.execute(select(*pk))}
    added = updated = skipped = 0
    if replace and pk:  # الحذف جرى قبل الإضافة (من الأبناء إلى الآباء)؛ هنا تحديث الموجود فقط
        for r in rows:
            k = _key_of(t, r)
            if k in existing:
                cond = and_(*[c == v for c, v in zip(pk, k)])
                vals = {c: v for c, v in r.items() if c not in {x.name for x in pk}}
                if vals:
                    conn.execute(update(t).where(cond).values(**vals))
                updated += 1
    new = [r for r in rows if _key_of(t, r) not in existing]
    for chunk in _chunks(new, 400):
        try:
            with conn.begin_nested():
                conn.execute(insert(t), chunk)
            added += len(chunk)
        except IntegrityError:  # صف يتعارض مع صف أحدث (رابط مكرر مثلًا): يُتجاوز وحده
            for r in chunk:
                try:
                    with conn.begin_nested():
                        conn.execute(insert(t), [r])
                    added += 1
                except IntegrityError:
                    skipped += 1
    return {"added": added, "updated": updated, "removed": 0, "skipped": skipped}


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def restore(engine: Engine, path: str, items: list[str], mode: str = "merge", passphrase: str | None = None,
            safety: bool = True) -> dict:
    """يسترد من النسخة ما اختير منها. mode: merge (أضف الناقص) أو replace (استبدل الأقسام المختارة)."""
    from marsad.migrate import current_revision

    if mode not in ("merge", "replace"):
        raise BackupError("طريقة الاسترداد غير معروفة")
    p = expand_path(path)
    z, h, box = _open(p, passphrase)
    try:
        dbs, file_groups = _split(items)
        if not dbs and not file_groups:
            raise BackupError("اختر شيئًا واحدًا على الأقل لاسترداده")
        available = set(h.get("items") or []) | set(h.get("auto_added") or [])
        missing = [x for x in items if x not in available]
        if missing:
            raise BackupError("هذه النسخة لا تحوي: " + "، ".join(missing))
        if dbs and h.get("revision") != current_revision(engine):
            raise BackupError("النسخة من إصدار قاعدة بيانات مختلف عن هذا البرنامج. حدّث البرنامج أو استعمل ملف النقل.")
        rekey = None
        if dbs and h.get("secret_id") != _secret_id():
            if not box:
                raise BackupError("هذه النسخة من جهاز آخر وغير مشفّرة بعبارة مرور، فلا يمكن فتح بياناتها المشفّرة هنا. "
                                  "استعمل «ملف النقل» للانتقال بين الأجهزة، أو استرد الملفات وحدها.")
            old_secret = box.decrypt(z.read("secret.enc")).decode()
            rekey = _rekey(Fernet(crypto.derive(old_secret)), crypto.master_secret())
        unseal = (lambda b: box.decrypt(b)) if box else (lambda b: b)

        safety_file = None
        if safety and dbs:  # الملفات لا تُحذف ولا تُستبدل عند الاسترداد، فنسخة الأمان لقاعدة البيانات وحدها
            safety_file = create_backup(engine, [f"db:{g}" for g in dbs], ensure_storage().backups / "قبل الاسترداد",
                                        "أمان قبل الاسترداد", keep=SAFETY_KEEP)["file"]

        result: dict = {"tables": {}, "files": 0, "safety_backup": safety_file}
        if dbs:
            parents = db_closure(dbs) - dbs
            chosen_tables = {t for g in dbs for t in DB_GROUPS[g]["tables"]}
            parent_tables = {t for g in parents for t in DB_GROUPS[g]["tables"]}
            tables = _tables()
            names = set(z.namelist())
            order = [tn for tn in _order() if tn in chosen_tables | parent_tables]
            data: dict[str, list[dict]] = {}
            for tn in order:
                n = f"tables/{tn}.jsonl"
                if n not in names:
                    continue
                cols = {c.name for c in tables[tn].columns}
                rows = []
                for line in unseal(z.read(n)).decode().splitlines():
                    if not line.strip():
                        continue
                    r = {k: _de(v) for k, v in json.loads(line).items() if k in cols}
                    if rekey:
                        for (tname, col) in ENCRYPTED_COLUMNS:
                            if tname == tn and r.get(col):
                                r[col] = rekey(r[col])
                        if tn == "system_settings" and "key" in r:
                            r["value"] = _rekey_setting(r["key"], r.get("value"), rekey)
                    rows.append(r)
                data[tn] = rows
            removed: dict[str, int] = {}
            with engine.begin() as conn:
                if engine.dialect.name == "sqlite":
                    conn.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
                if mode == "replace":  # الحذف من الأبناء إلى الآباء، ثم الإضافة من الآباء إلى الأبناء
                    for tn in reversed(order):
                        if tn in chosen_tables and tn in data:
                            pk = _pk(tables[tn])
                            keep_keys = {_key_of(tables[tn], r) for r in data[tn]}
                            gone = {tuple(x) for x in conn.execute(select(*pk))} - keep_keys
                            for chunk in _chunks(sorted(gone, key=repr), 400):
                                if len(pk) == 1:
                                    conn.execute(delete(tables[tn]).where(pk[0].in_([k[0] for k in chunk])))
                                else:
                                    conn.execute(delete(tables[tn]).where(tuple_(*pk).in_(chunk)))
                                removed[tn] = removed.get(tn, 0) + len(chunk)
                for tn in order:
                    if tn in data:
                        result["tables"][tn] = _restore_table(conn, tables[tn], data[tn], mode == "replace" and tn in chosen_tables)
                        result["tables"][tn]["removed"] = removed.get(tn, 0)
                if engine.dialect.name == "postgresql":
                    for tn in order:
                        t = tables[tn]
                        if "id" in t.columns and t.columns["id"].primary_key and t.columns["id"].autoincrement is not False:
                            conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{tn}', 'id'), "
                                              f"COALESCE((SELECT MAX(id) FROM {tn}), 0) + 1, false)"))
            kinds = [k for g, k in (("monitor", "items"), ("claims", "claims"), ("stories", "entities"), ("stories", "stories")) if g in dbs]
            if kinds:
                _reindex(engine, kinds)

        if file_groups:
            root = ensure_storage().root
            store = p.parent / STORE_NAME
            for line in unseal(z.read("files.jsonl")).decode().splitlines():
                if not line.strip():
                    continue
                f = json.loads(line)
                rel = f["rel"]
                if f["g"] not in file_groups or ".." in Path(rel).parts or Path(rel).is_absolute():
                    continue
                dest = root / rel
                if dest.exists():
                    continue
                src = store / (rel + (".enc" if box else ""))
                if not src.exists():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                part = dest.with_name(dest.name + ".part")
                if box:
                    part.write_bytes(box.decrypt(src.read_bytes()))
                else:
                    shutil.copy2(src, part)
                part.replace(dest)
                result["files"] += 1
        return result
    finally:
        z.close()


def _reindex(engine: Engine, kinds: list[str] | None = None) -> None:
    try:
        from marsad.search import rebuild

        with Session(engine) as s:
            rebuild(s, kinds)
    except Exception:  # noqa: BLE001 — البحث يعود من القاعدة إن لم يكن Meilisearch متاحًا
        pass


# ---------- الباقات وجدولتها ----------

SCHEDULES = ("manual", "daily", "weekly", "monthly")


DAILY_ID = "daily"


def daily_default() -> dict:
    """النسخة اليومية: موجودة من البداية، قاعدة البيانات كاملة كل يوم في مجلد «النسخ الاحتياطي».
    يعدّلها المدير كأي باقة (ما يُنسخ، المكان، الموعد، العدد، التشفير)، ولا تُحذف."""
    return {"id": DAILY_ID, "builtin": True, "name": "النسخة اليومية", "items": sorted(f"db:{g}" for g in DB_GROUPS),
            "dest": "", "schedule": {"kind": "daily", "time": "03:23", "weekday": 4, "day": 1}, "keep": 14, "encrypt": False}


def ensure_daily(db: Session) -> bool:
    """يضيف النسخة اليومية إن لم تكن موجودة (أول تشغيل، أو ترقية من إصدار سابق). يُرجع True إن أضافها."""
    rows = packages(db)
    if any(r["id"] == DAILY_ID for r in rows):
        return False
    _save(db, [daily_default()] + rows)
    return True


def packages(db: Session) -> list[dict]:
    from marsad.rbac.service import get_setting

    return list(get_setting(db, SETTING, []) or [])


def _save(db: Session, rows: list[dict], actor=None) -> None:
    from marsad.rbac.service import set_setting

    set_setting(db, SETTING, rows, actor)


def public(pkg: dict) -> dict:
    """الباقة كما تُعرض: دون عبارة المرور."""
    where = str(expand_path(pkg["dest"])) if pkg.get("dest") else str(ensure_storage().backups)
    return {k: v for k, v in pkg.items() if k != "passphrase_enc"} | {"has_passphrase": bool(pkg.get("passphrase_enc")), "dest_path": where}


def validate(body: dict, old: dict | None = None) -> dict:
    builtin = bool(old and old.get("builtin"))
    name = old["name"] if builtin else naming.clean(body.get("name") or "", 60)
    if not name:
        raise BackupError("اكتب اسمًا للباقة")
    items = [x for x in body.get("items") or [] if isinstance(x, str)]
    dbs, files = _split(items)
    if not dbs and not files:
        raise BackupError("اختر شيئًا واحدًا على الأقل لنسخه")
    dest = (body.get("dest") or "").strip()
    if not dest and not builtin:
        raise BackupError("اختر مكان الحفظ")
    target = expand_path(dest) if dest else ensure_storage().backups
    root = ensure_storage().root
    if dest and (target == root or root in target.parents):
        if target != root / SUBDIRS["backups"] and (root / SUBDIRS["backups"]) not in target.parents:
            raise BackupError("لا تحفظ النسخ داخل مجلد البيانات (إلا مجلد «النسخ الاحتياطي»): ستُنسخ النسخ نفسها")
    sched = body.get("schedule") or {}
    kind = sched.get("kind", "manual")
    if kind not in SCHEDULES:
        raise BackupError("موعد غير معروف")
    time_s = sched.get("time") or "03:00"
    try:
        hh, mm = (int(x) for x in time_s.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except (ValueError, AssertionError):
        raise BackupError("الوقت بصيغة ساعة:دقيقة") from None
    weekday = int(sched.get("weekday", 4)) % 7  # 0 = الاثنين
    day = min(max(int(sched.get("day", 1)), 1), 28)
    keep = min(max(int(body.get("keep") or 7), 1), 365)
    encrypt = bool(body.get("encrypt"))
    pkg = {**(old or {}), "id": (old or {}).get("id") or uuid.uuid4().hex[:12], "name": name,
           "items": sorted({f"db:{g}" for g in dbs} | {f"files:{g}" for g in files}), "dest": dest,
           "schedule": {"kind": kind, "time": f"{hh:02d}:{mm:02d}", "weekday": weekday, "day": day},
           "keep": keep, "encrypt": encrypt}
    pp = body.get("passphrase")
    if encrypt:
        if pp:
            if len(pp) < 8:
                raise BackupError("عبارة المرور 8 أحرف على الأقل")
            if old and old.get("passphrase_enc") and old.get("encrypt") and crypto.decrypt(old["passphrase_enc"]) != pp \
                    and (package_dir(dest, name) / MARKER).exists():
                raise BackupError("لهذه الباقة نسخ بعبارة مرور أخرى. أنشئ باقة جديدة بعبارة جديدة.")
            pkg["passphrase_enc"] = crypto.encrypt(pp)
        elif not pkg.get("passphrase_enc"):
            raise BackupError("اكتب عبارة مرور للتشفير (8 أحرف على الأقل). احفظها: بدونها لا تُفتح النسخ على جهاز آخر.")
    else:
        pkg.pop("passphrase_enc", None)
    return pkg


def upsert(db: Session, body: dict, pid: str | None, actor=None) -> dict:
    rows = packages(db)
    old = next((r for r in rows if r["id"] == pid), None) if pid else None
    if pid and old is None:
        raise BackupError("الباقة غير موجودة")
    pkg = validate(body, old)
    if any(r["name"] == pkg["name"] and r["id"] != pkg["id"] for r in rows):
        raise BackupError("يوجد باقة بالاسم نفسه")
    rows = [pkg if r["id"] == pkg["id"] else r for r in rows] if old else rows + [pkg]
    _save(db, rows, actor)
    return pkg


def remove(db: Session, pid: str, actor=None) -> None:
    """يحذف الباقة من القائمة فقط. نسخها على القرص تبقى."""
    if pid == DAILY_ID:
        raise BackupError("النسخة اليومية لا تُحذف. لإيقافها اجعل موعدها «يدوي فقط».")
    _save(db, [r for r in packages(db) if r["id"] != pid], actor)


def _set_status(db: Session, pid: str, **kw) -> None:
    rows = packages(db)
    for r in rows:
        if r["id"] == pid:
            r.update(kw)
    _save(db, rows)
    db.commit()


def run_package(db: Session, pid: str) -> dict:
    """ينفّذ الباقة الآن، ويسجّل نتيجتها فيها. الفشل يُسجَّل وينبّه المدير ولا يرفع خطأ إلى المجدول."""
    from marsad.db import get_engine
    from marsad.models.engines import Notification

    pkg = next((r for r in packages(db) if r["id"] == pid), None)
    if pkg is None:
        raise BackupError("الباقة غير موجودة")
    started = datetime.now(timezone.utc).isoformat()
    _set_status(db, pid, last_status="running", last_started_at=started)
    try:
        pp = crypto.decrypt(pkg["passphrase_enc"]) if pkg.get("encrypt") and pkg.get("passphrase_enc") else None
        r = create_backup(get_engine(), pkg["items"], package_dir(pkg["dest"], pkg["name"]), pkg["name"], pp, keep=pkg.get("keep", 7))
        _set_status(db, pid, last_status="ok", last_run_at=started, last_file=r["file"], last_size=r["size"],
                    last_message=f"{r['tables']} سجل و{r['files']} ملف")
        return {"ok": True, **r}
    except Exception as e:  # noqa: BLE001
        db.rollback()
        msg = str(e) if isinstance(e, BackupError) else f"تعذّر النسخ: {e}"
        log.warning("فشلت باقة النسخ %s: %s", pkg["name"], msg)
        _set_status(db, pid, last_status="error", last_run_at=started, last_message=msg)
        db.add(Notification(kind="backup.failed", text=f"فشلت النسخة الاحتياطية «{pkg['name']}»: {msg}"))
        db.commit()
        return {"ok": False, "error": msg}


def _slot(pkg: dict, now_local: datetime) -> datetime | None:
    """آخر موعد كان يجب أن تعمل فيه الباقة حتى الآن (بالتوقيت المحلي)."""
    s = pkg.get("schedule") or {}
    kind = s.get("kind", "manual")
    if kind == "manual":
        return None
    hh, mm = (int(x) for x in (s.get("time") or "03:00").split(":"))
    today = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if kind == "daily":
        return today if today <= now_local else today - timedelta(days=1)
    if kind == "weekly":
        back = (now_local.weekday() - int(s.get("weekday", 4))) % 7
        slot = today - timedelta(days=back)
        return slot if slot <= now_local else slot - timedelta(days=7)
    day = int(s.get("day", 1))
    slot = today.replace(day=day)
    if slot > now_local:
        prev = (slot.replace(day=1) - timedelta(days=1)).replace(day=day)
        slot = prev
    return slot


def due(db: Session, now: datetime | None = None) -> list[str]:
    from marsad.reports.core import schedule

    tz = ZoneInfo(schedule(db)["tz"])
    now_local = (now or datetime.now(timezone.utc)).astimezone(tz)
    out = []
    for p in packages(db):
        slot = _slot(p, now_local)
        if slot is None:
            continue
        started = p.get("last_started_at")
        if p.get("last_status") == "running" and started and \
                datetime.fromisoformat(started) > (now or datetime.now(timezone.utc)) - timedelta(hours=6):
            continue  # تعمل الآن (وما توقف قبل ست ساعات يُعدّ منقطعًا ويُعاد)
        last = p.get("last_run_at")
        if not last or datetime.fromisoformat(last).astimezone(tz) < slot:
            out.append(p["id"])
    return out


def run_due(db: Session, now: datetime | None = None) -> list[dict]:
    return [run_package(db, pid) for pid in due(db, now)]
