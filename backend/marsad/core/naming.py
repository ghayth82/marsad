"""تسمية الملفات المحفوظة بأسماء يفهمها المستخدم قبل فتحها.

الصيغة (قرار غيث): النوع أو المصدر - عنوان مختصر - 8 خانات من البصمة - التاريخ.الامتداد
مثال: «خبرني - تأجيل الامتحانات الوزارية - ab12cd34 - 2026-11-27.html.gz»
البصمة الكاملة (SHA-256) محفوظة في قاعدة البيانات؛ الخانات الثماني في الاسم للمطابقة بالعين.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from marsad.core.paths import SUBDIRS, ensure_storage

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f\u200e\u200f\u202a-\u202e\u2066-\u2069]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
TITLE_MAX = 60


def clean(text: str, limit: int = TITLE_MAX) -> str:
    """نص صالح اسمًا لملف أو مجلد على ويندوز: بلا رموز ممنوعة، بمسافات مفردة، وبطول محدود."""
    t = unicodedata.normalize("NFC", text or "")
    t = _BAD.sub(" ", t).replace(" - ", " ")  # الفاصل « - » محجوز بين أجزاء الاسم
    t = " ".join(t.split()).strip(" .-_")
    if len(t) > limit:
        cut = t[:limit]
        t = (cut[:cut.rfind(" ")] if " " in cut[limit // 2:] else cut).strip(" .-_")
    if t.upper() in _RESERVED:
        t = f"{t}_"
    return t


def _day(d: datetime | date | None) -> str:
    return (d or datetime.now()).strftime("%Y-%m-%d")


def file_name(label: str, title: str, sha: str, when: datetime | date | None, ext: str) -> str:
    parts = [clean(label, 40) or "ملف", clean(title)]
    if sha:
        parts.append(sha[:8])
    parts.append(_day(when))
    return " - ".join(p for p in parts if p) + ext


def place(key: str, *folders: str, name: str, raw: bytes | None = None) -> tuple[str, Path]:
    """يحدد مكان الملف تحت مجلد الوظيفة ويُرجع (المسار النسبي لجذر البيانات، المسار الكامل).
    إن وُجد ملف بالاسم نفسه ومحتوى مختلف أُضيف رقم؛ وإن كان المحتوى نفسه أُعيد المسار دون كتابة."""
    root = ensure_storage().root
    rel_dir = "/".join([SUBDIRS[key], *[clean(f, 80) or "بدون اسم" for f in folders]])
    d = root / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    stem, ext = _split(name)
    n, cand = 1, name
    while (d / cand).exists():
        if raw is None or ((d / cand).stat().st_size == len(raw) and (d / cand).read_bytes() == raw):
            break  # الاسم يحمل خانات من البصمة: الاسم نفسه يعني المحتوى نفسه
        n += 1
        cand = f"{stem} ({n}){ext}"
    return f"{rel_dir}/{cand}", d / cand


def _split(name: str) -> tuple[str, str]:
    for double in (".html.gz",):
        if name.endswith(double):
            return name[: -len(double)], double
    p = Path(name)
    return p.stem, p.suffix


def save(key: str, *folders: str, name: str, raw: bytes) -> str:
    """يحفظ الملف ويُرجع مساره النسبي. فشل الكتابة يُرفع كما هو."""
    rel, path = place(key, *folders, name=name, raw=raw)
    if not path.exists():
        path.write_bytes(raw)
    return rel


def save_copy(key: str, *folders: str, name: str, raw: bytes) -> str | None:
    """نسخة تلقائية مما يصدّره المستخدم. اسم اليوم نفسه يُستبدل، وتعذّر الكتابة لا يوقف التنزيل."""
    try:
        root = ensure_storage().root
        d = root / "/".join([SUBDIRS[key], *[clean(f, 80) or "بدون اسم" for f in folders]])
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(raw)
        return f"{d.relative_to(root).as_posix()}/{name}"
    except OSError:
        return None


def attachment(name: str) -> dict[str, str]:
    """ترويسة تنزيل باسم عربي."""
    from urllib.parse import quote

    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}


def export(key: str, name: str, raw: bytes | str, *folders: str) -> dict[str, str]:
    """يحفظ نسخة مما يُصدَّر في مجلد وظيفته، ويُرجع ترويسة التنزيل بالاسم نفسه (فيه تاريخ اليوم)."""
    save_copy(key, *folders, name=name, raw=raw.encode("utf-8") if isinstance(raw, str) else raw)
    return attachment(name)


def today() -> str:
    return _day(None)
