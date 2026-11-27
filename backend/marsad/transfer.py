"""ملف النقل: كل شيء من جهاز إلى خادم (أو جهاز آخر) في ملف واحد محمي بعبارة مرور.

يحمل: كل الجداول (الحسابات والأدوار والتفضيلات والمصادر والمواد والقصص والادّعاءات والأحكام والقضايا والتقييم والتدريب...)،
وملفات الأرشيف والرفع والتقارير، والسر الرئيسي القديم مشفّرًا بعبارة المرور.
عند الاستيراد: كل ما شُفّر بالسر القديم (مفاتيح المحركات، مفاتيح القضايا، رموز المنصات وتيليغرام) يُعاد تشفيره بسر الخادم الجديد،
فتُفتح الملفات المشفّرة دون نقل السر القديم إلى إعدادات الخادم.

الاستخدام:
    python -m marsad.transfer export ملف.marsad      (عبارة المرور من MARSAD_TRANSFER_PASSPHRASE أو تُطلب)
    python -m marsad.transfer import ملف.marsad      (على نسخة جديدة لم يُنشأ فيها حساب بعد)
    python -m marsad.transfer backup                 نسخة احتياطية في مجلد النسخ (يوميًا تلقائيًا على الجهاز)
    python -m marsad.transfer restore [ملف]          استعادة آخر نسخة (أو المذكورة)
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import shutil
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.core.paths import ensure_storage
from marsad.db import Base

FORMAT = 1
SKIP_TABLES = {"session_tokens", "alembic_version"}
# مفاتيح مجلدات المحتوى (الأسماء على القرص من paths.SUBDIRS)؛ archive يشمل ملفات إصدارات سابقة لم تُرتَّب
FILE_DIRS = ("archive", "uploads", "reports", "monitor", "media", "audio", "cases", "claims", "stories", "tools")
# الحقول المشفّرة بالسر الرئيسي: (الجدول، العمود)، وإعدادات النظام بمفاتيحها
ENCRYPTED_COLUMNS = {("engines", "api_key_enc"), ("cases", "key_wrapped")}


class TransferError(Exception):
    pass


def _pass_key(passphrase: str, salt: bytes) -> Fernet:
    if len(passphrase) < 8:
        raise TransferError("عبارة المرور 8 أحرف على الأقل")
    k = hashlib.scrypt(passphrase.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return Fernet(base64.urlsafe_b64encode(k))


def _ser(v):
    if isinstance(v, datetime):
        return {"$dt": (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()}
    if isinstance(v, date):
        return {"$d": v.isoformat()}
    if isinstance(v, bytes):
        return {"$b": base64.b64encode(v).decode()}
    return v


def _de(v):
    if isinstance(v, dict) and len(v) == 1:
        if "$dt" in v:
            return datetime.fromisoformat(v["$dt"])
        if "$d" in v:
            return date.fromisoformat(v["$d"])
        if "$b" in v:
            return base64.b64decode(v["$b"])
    return v


def _tables():
    import marsad.models  # noqa: F401  يسجّل كل الجداول

    return [t for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES]


def export_bundle(engine: Engine, out: Path, passphrase: str, include_files: bool = True) -> dict:
    from marsad.migrate import current_revision

    salt = os.urandom(16)
    box = _pass_key(passphrase, salt)
    paths = ensure_storage()
    counts = {}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        with engine.connect() as conn:
            for t in _tables():
                rows = conn.execute(select(t)).mappings().all()
                counts[t.name] = len(rows)
                z.writestr(f"tables/{t.name}.jsonl", "\n".join(json.dumps({k: _ser(v) for k, v in r.items()}, ensure_ascii=False) for r in rows))
        files = 0
        for d in FILE_DIRS if include_files else ():
            base = paths.dirs[d]
            for p in base.rglob("*"):
                if p.is_file():
                    z.write(p, f"files/{d}/{p.relative_to(base).as_posix()}")
                    files += 1
        z.writestr("secret.enc", box.encrypt(crypto.master_secret().encode()))
        manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(), "revision": current_revision(engine),
                    "salt": base64.b64encode(salt).decode(), "tables": counts, "files": files}
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    tmp.replace(out)
    return manifest


def _rekey(old: Fernet, new_secret: str):
    new = Fernet(crypto.derive(new_secret))

    def f(token: str | None):
        if not token:
            return token
        try:
            return new.encrypt(old.decrypt(token.encode())).decode()
        except InvalidToken:
            raise TransferError("تعذّر فك تشفير بيانات في الملف: الملف تالف أو من إصدار مختلف") from None

    return f


def _rekey_setting(key: str, value, f):
    if key == "social.providers" and isinstance(value, dict):
        return {p: {**c, "secret": f(c.get("secret"))} for p, c in value.items()}
    if key == "alerts.telegram" and isinstance(value, dict) and value.get("token"):
        return {**value, "token": f(value["token"])}
    return value


def import_bundle(engine: Engine, src: Path, passphrase: str, force: bool = False) -> dict:
    from marsad.migrate import current_revision

    with zipfile.ZipFile(src) as z:
        try:
            manifest = json.loads(z.read("manifest.json"))
        except KeyError:
            raise TransferError("ليس ملف نقل من «مرصد التحقق»") from None
        if manifest.get("format") != FORMAT:
            raise TransferError("صيغة ملف النقل غير مدعومة في هذا الإصدار")
        try:
            old_secret = _pass_key(passphrase, base64.b64decode(manifest["salt"])).decrypt(z.read("secret.enc")).decode()
        except InvalidToken:
            raise TransferError("عبارة المرور غير صحيحة") from None
        here = current_revision(engine)
        if manifest["revision"] != here:
            raise TransferError(f"الملف من إصدار قاعدة بيانات «{manifest['revision']}» وهذه النسخة «{here}». حدّث الأقدم منهما أولًا.")
        from marsad.models import User

        with Session(engine) as s:
            if s.scalar(select(func.count()).select_from(User)) and not force:
                raise TransferError("هذه النسخة فيها حسابات. الاستيراد على نسخة جديدة فقط (قبل إنشاء أول حساب).")
        rekey = _rekey(Fernet(crypto.derive(old_secret)), crypto.master_secret())
        names = set(z.namelist())
        with engine.begin() as conn:
            if force:
                for t in reversed(_tables()):
                    conn.execute(t.delete())
            else:
                for t in reversed(_tables()):  # بيانات أولية من الترحيل (الأدوار الجاهزة...) تُستبدل بما في الملف
                    conn.execute(t.delete())
            for t in _tables():
                name = f"tables/{t.name}.jsonl"
                if name not in names:
                    continue
                cols = {c.name for c in t.columns}
                rows = []
                for line in z.read(name).decode().splitlines():
                    if not line.strip():
                        continue
                    r = {k: _de(v) for k, v in json.loads(line).items() if k in cols}
                    for (tn, col) in ENCRYPTED_COLUMNS:
                        if tn == t.name and r.get(col):
                            r[col] = rekey(r[col])
                    if t.name == "system_settings" and "key" in r:
                        r["value"] = _rekey_setting(r["key"], r.get("value"), rekey)
                    rows.append(r)
                for k in range(0, len(rows), 500):
                    conn.execute(insert(t), rows[k:k + 500])
            if engine.dialect.name == "postgresql":
                for t in _tables():
                    if "id" in t.columns and t.columns["id"].autoincrement is not False and t.columns["id"].primary_key:
                        conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), "
                                          f"COALESCE((SELECT MAX(id) FROM {t.name}), 0) + 1, false)"))
        paths = ensure_storage()
        files = 0
        for n in names:
            if n.startswith("files/") and not n.endswith("/"):
                _, d, rel = n.split("/", 2)
                if d not in FILE_DIRS or ".." in Path(rel).parts:
                    continue
                dest = paths.dirs[d] / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    with z.open(n) as fsrc, open(dest, "wb") as fdst:
                        shutil.copyfileobj(fsrc, fdst)
                    files += 1
    try:  # فهرس البحث يُعاد بناؤه إن كان Meilisearch مضبوطًا
        from marsad.search import rebuild

        with Session(engine) as s:
            rebuild(s)
    except Exception:
        pass
    return {"tables": manifest["tables"], "files": files, "from": manifest["created_at"]}


# ---------- النسخ الاحتياطي (الجهاز) ----------

KEEP = 14


def _backup_pass() -> str:
    """النسخة المحلية تُفتح بسر البرنامج نفسه، فتُستعاد على الجهاز دون سؤال؛ وعلى جهاز آخر تحتاج ملف السر أو ملف نقل."""
    return "backup:" + crypto.master_secret()


def backup_now(engine: Engine) -> Path:
    """نسخة من قاعدة البيانات في مجلد النسخ (الأرشيف لا يُنسخ هنا: ملفاته لا تُحذف ولا تتغيّر، ويُنسخ مع ملف النقل)."""
    d = ensure_storage().backups / "db"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out, n = d / f"marsad-{stamp}.marsad", 1
    while out.exists():  # نسختان في الثانية نفسها: لا تُستبدل الأولى أبدًا
        n += 1
        out = d / f"marsad-{stamp}-{n}.marsad"
    export_bundle(engine, out, _backup_pass(), include_files=False)
    for old in sorted(d.glob("marsad-*.marsad"), reverse=True)[KEEP:]:
        old.unlink(missing_ok=True)
    return out


def list_backups() -> list[Path]:
    d = ensure_storage().backups / "db"
    return sorted(d.glob("marsad-*.marsad"), reverse=True) if d.exists() else []


def restore_backup(engine: Engine, path: Path) -> dict:
    """يستبدل كل ما في قاعدة البيانات بالنسخة. للاستعادة بعد عطل أو حذف."""
    return import_bundle(engine, path, _backup_pass(), force=True)


def main(argv: list[str] | None = None) -> int:
    from marsad.db import init_engine, migrate

    argv = argv if argv is not None else sys.argv[1:]
    if argv[:1] == ["backup"]:
        engine = init_engine()
        migrate()
        print(f"النسخة: {backup_now(engine)}")
        return 0
    if argv[:1] == ["restore"]:
        engine = init_engine()
        migrate()
        files = list_backups()
        path = Path(argv[1]) if len(argv) > 1 else (files[0] if files else None)
        if path is None:
            print("لا توجد نسخة احتياطية", file=sys.stderr)
            return 1
        r = restore_backup(engine, path)
        print(f"استُعيدت {sum(r['tables'].values())} سجلًا من {path.name}")
        return 0
    if len(argv) != 2 or argv[0] not in ("export", "import"):
        print(__doc__)
        return 2
    passphrase = os.environ.get("MARSAD_TRANSFER_PASSPHRASE") or getpass.getpass("عبارة المرور: ")
    engine = init_engine()
    migrate()
    try:
        if argv[0] == "export":
            m = export_bundle(engine, Path(argv[1]), passphrase)
            print(f"صُدّر: {sum(m['tables'].values())} سجلًا و{m['files']} ملفًا ← {argv[1]}")
        else:
            r = import_bundle(engine, Path(argv[1]), passphrase)
            print(f"استُورد: {sum(r['tables'].values())} سجلًا و{r['files']} ملفًا (من نسخة {r['from']})")
    except TransferError as e:
        print(f"خطأ: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
