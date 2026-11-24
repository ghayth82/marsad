"""الأرقام الرسمية: جدول يديره المحرّر، ومقارنة كل رقم في ادّعاء أو مادة بآخر قيمة رسمية للمؤشر نفسه.

لا حكم آلي: المقارنة دليل يقرّه الصحفي. الأرقام المكتوبة بالحروف (ثلاثين) لا تُلتقط.
"""

from __future__ import annotations

import csv
import io
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.models import User
from marsad.models.tools import OfficialFigure
import unicodedata

from marsad.text import _DIACRITICS, _MAP, normalize_ar

NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:[.٫](\d+))?(?![\w])")
WINDOW = 8  # كلمات بين كلمة المؤشر والرقم
COLUMNS = ["indicator", "value", "unit", "as_of", "agency", "url", "keywords", "note"]
AR_COLUMNS = {"المؤشر": "indicator", "القيمة": "value", "الوحدة": "unit", "التاريخ": "as_of", "الجهة": "agency",
              "الرابط": "url", "الكلمات": "keywords", "ملاحظة": "note"}


class FigureError(ValueError):
    pass


def _norm(text: str) -> str:
    """توحيد عربي يُبقي الفاصلة والنقطة العشرية بين الأرقام (normalize_ar يحذفهما)."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _DIACRITICS.sub("", t).translate(_MAP).lower().replace("٫", ".").replace("٬", ",")
    t = re.sub(r"[^\w\s.,]", " ", t)
    t = re.sub(r"(?<!\d)[.,]|[.,](?!\d)", " ", t)
    t = re.sub(r"(\d)([^\d\s.,])", r"\1 \2", t)
    t = re.sub(r"([^\d\s.,])(\d)", r"\1 \2", t)
    return re.sub(r"\s+", " ", t).strip()


def _kw(f: OfficialFigure) -> list[str]:
    words = [normalize_ar(k) for k in (f.keywords or []) if k.strip()]
    return words or [normalize_ar(f.indicator)]


def _date(s: str) -> str:
    """التاريخ بدقته كما نُشر: سنة، أو سنة وشهر، أو يوم كامل (الترتيب النصي يبقى زمنيًا)."""
    s = (s or "").strip()
    if not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", s):
        raise FigureError("التاريخ بصيغة 2026 أو 2026-09 أو 2026-09-30")
    return s


def save(db: Session, user: User, data: dict, fig: OfficialFigure | None = None) -> OfficialFigure:
    try:
        value = float(str(data.get("value", "")).replace(",", "").replace("٫", "."))
    except ValueError:
        raise FigureError("القيمة رقم") from None
    ind = (data.get("indicator") or "").strip()
    if not ind:
        raise FigureError("اسم المؤشر مطلوب")
    kws = data.get("keywords") or []
    if isinstance(kws, str):
        kws = [k.strip() for k in re.split(r"[،,|]", kws) if k.strip()]
    f = fig or OfficialFigure(created_by=user.id)
    f.indicator, f.value, f.unit, f.as_of = ind[:200], value, (data.get("unit") or "")[:40], _date(data.get("as_of", ""))
    f.agency, f.url, f.note, f.keywords = (data.get("agency") or "")[:200], (data.get("url") or "")[:1000], data.get("note") or "", kws[:20]
    db.add(f)
    db.flush()
    return f


def import_csv(db: Session, user: User, raw: bytes) -> dict:
    text = raw.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(text))
    added, errors = 0, []
    for i, row in enumerate(rd, start=2):
        row = {AR_COLUMNS.get((k or "").strip(), (k or "").strip()): v for k, v in row.items()}
        try:
            save(db, user, row)
            added += 1
        except FigureError as e:
            errors.append(f"السطر {i}: {e}")
    return {"added": added, "errors": errors[:50]}


def latest(db: Session) -> list[OfficialFigure]:
    """آخر قيمة لكل مؤشر."""
    out: dict[str, OfficialFigure] = {}
    for f in db.scalars(select(OfficialFigure).order_by(OfficialFigure.as_of, OfficialFigure.id)).all():
        out[normalize_ar(f.indicator)] = f
    return list(out.values())


def _numbers(tokens: list[str]) -> list[tuple[int, float, str]]:
    out = []
    for i, t in enumerate(tokens):
        m = NUM.fullmatch(t)
        if m:
            whole = m.group(1).replace(",", "")
            out.append((i, float(f"{whole}.{m.group(2)}" if m.group(2) else whole), t))
    return out


def match(db: Session, text: str) -> list[dict]:
    """لكل مؤشر تُذكر كلمته في النص ومعها رقم قريب: الرقم المذكور، والقيمة الرسمية، والفرق بالنسبة المئوية."""
    tokens = _norm(text).split()
    nums = _numbers(tokens)
    if not nums:
        return []
    out = []
    for f in latest(db):
        hits = []
        for kw in _kw(f):
            kt = kw.split()
            for i in range(len(tokens) - len(kt) + 1):
                if [re.sub(r"^(و|ب|ل|ف)?(ال)?", "", t) for t in tokens[i:i + len(kt)]] == [re.sub(r"^(ال)?", "", k) for k in kt] \
                        or tokens[i:i + len(kt)] == kt:
                    hits.append(i)
        if not hits:
            continue
        best = None
        for pos in hits:
            for j, val, raw in nums:
                dist = abs(j - pos)
                if dist <= WINDOW and (best is None or dist < best[0]):
                    best = (dist, val, j)
        if best is None:
            continue
        _, val, j = best
        diff = None if f.value == 0 else round(100 * (val - f.value) / abs(f.value), 1)
        snippet = " ".join(tokens[max(0, j - 6): j + 6])
        out.append({"figure_id": f.id, "indicator": f.indicator, "official": f.value, "unit": f.unit, "as_of": f.as_of,
                    "agency": f.agency, "url": f.url, "claimed": val, "diff_pct": diff, "snippet": snippet,
                    "same": diff is not None and abs(diff) < 0.5})
    return out


def view(f: OfficialFigure) -> dict:
    return {"id": f.id, "indicator": f.indicator, "value": f.value, "unit": f.unit, "as_of": f.as_of, "agency": f.agency,
            "url": f.url, "keywords": f.keywords, "note": f.note}
