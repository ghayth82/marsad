"""إعادة ترتيب الملفات المحفوظة من إصدارات سابقة (أسماء بالبصمة داخل archive) إلى المجلدات العربية
حسب الوظيفة وبأسماء مفهومة. تُجرى مرة واحدة في الخلفية بعد الترقية، وتُستكمل إن قُطعت.

لا يُحذف أي محتوى: الملف يُنقل باسمه الجديد، ووثائق التحقيقات تُكتب بصيغتها الجديدة ثم يُزال ملفها القديم
بعد التحقق من البصمة. المجلدات القديمة تُزال فقط إن فرغت.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.core import naming
from marsad.core.paths import data_file, ensure_storage

log = logging.getLogger(__name__)
STORAGE_REV = 2
BATCH = 300


def _move(old: Path, new: Path) -> bool:
    if new.exists():
        return True
    if not old.exists():
        return False
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(new))
    return True


def _pages(db: Session) -> int:
    from marsad.models.monitoring import Item, ItemVersion

    done, moved = 0, {}
    ids = list(db.scalars(select(ItemVersion.id).where(ItemVersion.archive_path.like("pages/%"))))
    for n, vid in enumerate(ids, 1):
        v = db.get(ItemVersion, vid)
        item = db.get(Item, v.item_id)
        if v.archive_path in moved:  # نسختان بالمحتوى نفسه تشتركان في ملف واحد
            v.archive_path = moved[v.archive_path]
        else:
            outlet = naming.clean(item.source.outlet.name if item and item.source and item.source.outlet else "", 40) or "مصدر غير معروف"
            rel, new = naming.place("monitor", f"{v.captured_at:%Y-%m}", outlet,
                                    name=naming.file_name(outlet, v.title or (item.title if item else "") or "بدون عنوان",
                                                          v.archive_sha256, v.captured_at, ".html.gz"))
            if _move(data_file(v.archive_path), new):
                moved[v.archive_path] = rel
                v.archive_path = rel
                done += 1
        if n % BATCH == 0:
            db.commit()
    db.commit()
    return done


def _media(db: Session) -> int:
    from marsad.labs import media as lab
    from marsad.models.claims import Evidence
    from marsad.models.labs import MediaFile

    done = 0
    ids = list(db.scalars(select(MediaFile.id).where(MediaFile.path.like("media/%"), MediaFile.kind.in_(("image", "video", "audio")))))
    for n, mid in enumerate(ids, 1):
        m = db.get(MediaFile, mid)
        old_rel = m.path
        key, month, name = lab.user_name(m.kind, m.filename, m.sha256, m.seen_at or m.created_at, Path(old_rel).suffix)
        rel, new = naming.place(key, month, name=name)
        if _move(data_file(old_rel), new):
            m.path = rel
            for e in db.scalars(select(Evidence).where(Evidence.file_path == old_rel)):
                e.file_path = rel
            done += 1
        if n % BATCH == 0:
            db.commit()
    db.commit()
    return done


def _cases(db: Session) -> int:
    from marsad.cases import core
    from marsad.models.cases import Case, CaseDocument

    done = 0
    for d in list(db.scalars(select(CaseDocument).where(CaseDocument.path.like("cases/%")))):
        c = db.get(Case, d.case_id)
        old = data_file(d.path)
        if c is None or not old.exists():
            continue
        try:
            raw = core.read_document(c, d)  # يفك التشفير ويتحقق من البصمة
            filename = core.dec(c, d.filename_enc, "") or f"وثيقة {d.number}"
            d.path = core.write_doc_file(db, c, d.number, filename, d.sha256, d.added_at, raw)
            db.commit()
            if hashlib.sha256(core.read_document(c, d)).hexdigest() == d.sha256:
                old.unlink()
            done += 1
        except Exception:  # noqa: BLE001 — وثيقة تالفة تبقى مكانها ولا توقف البقية
            db.rollback()
            log.warning("تعذّر ترتيب وثيقة %s في التحقيق %s", d.number, d.case_id, exc_info=True)
    return done


def _snapshots(db: Session) -> int:
    from marsad.models.tools import Snapshot
    from marsad.tools.snapshots import SNAP_DIR, snap_name

    done = 0
    for s in list(db.scalars(select(Snapshot).where(Snapshot.html_path.like("snapshots/%") | Snapshot.screenshot_path.like("snapshots/%")))):
        for attr, sha, ext in (("html_path", s.sha256, ".html"), ("screenshot_path", s.screenshot_sha256, ".png")):
            old_rel = getattr(s, attr)
            if not old_rel.startswith("snapshots/"):
                continue
            rel, new = naming.place("tools", SNAP_DIR, f"{s.created_at:%Y-%m}", name=snap_name(s, sha, ext))
            if _move(data_file(old_rel), new):
                setattr(s, attr, rel)
                done += 1
    db.commit()
    return done


def _prune_empty(base: Path) -> None:
    """يزيل المجلدات الفارغة فقط (من الأعمق إلى الأعلى)."""
    if not base.is_dir():
        return
    for d in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        base.rmdir()
    except OSError:
        pass


def pending(db: Session) -> bool:
    """هل في القاعدة ملفات بمسارات الإصدارات السابقة؟"""
    from marsad.models.cases import CaseDocument
    from marsad.models.labs import MediaFile
    from marsad.models.monitoring import ItemVersion
    from marsad.models.tools import Snapshot

    return any(db.scalar(q.limit(1)) is not None for q in (
        select(ItemVersion.id).where(ItemVersion.archive_path.like("pages/%")),
        select(MediaFile.id).where(MediaFile.path.like("media/%"), MediaFile.kind.in_(("image", "video", "audio"))),
        select(CaseDocument.id).where(CaseDocument.path.like("cases/%")),
        select(Snapshot.id).where(Snapshot.html_path.like("snapshots/%") | Snapshot.screenshot_path.like("snapshots/%"))))


def reorganize(db: Session) -> dict:
    out = {"pages": _pages(db), "media": _media(db), "cases": _cases(db), "snapshots": _snapshots(db)}
    archive = ensure_storage().archive
    for sub in ("pages", "cases", "snapshots"):
        _prune_empty(archive / sub)
    return out


def set_case_encryption(db: Session, on: bool) -> int:
    """يحوّل ملفات وثائق التحقيقات كلها إلى مشفّرة أو مقروءة حسب إعداد المدير. يُرجع عدد ما حُوّل."""
    from marsad.cases import core
    from marsad.models.cases import Case, CaseDocument
    from marsad.rbac.service import set_setting

    set_setting(db, core.ENC_SETTING, bool(on))
    db.flush()
    done = 0
    for d in list(db.scalars(select(CaseDocument))):
        if d.path.endswith(core.ENC_SUFFIXES) == bool(on) and not d.path.startswith("cases/"):
            continue
        c = db.get(Case, d.case_id)
        old = data_file(d.path)
        if c is None or not old.exists():
            continue
        raw = core.read_document(c, d)
        filename = core.dec(c, d.filename_enc, "") or f"وثيقة {d.number}"
        d.path = core.write_doc_file(db, c, d.number, filename, d.sha256, d.added_at, raw)
        db.flush()
        if data_file(d.path) != old and hashlib.sha256(core.read_document(c, d)).hexdigest() == d.sha256:
            old.unlink()
        done += 1
    return done
