"""أدوات النص العربي: توحيد الكتابة للمقارنة والبحث (الهمزات، التاء المربوطة، التشكيل...)."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # تشكيل وتطويل
_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي",
                      "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"})
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_ar(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = _DIACRITICS.sub("", t).translate(_MAP).lower()
    t = _PUNCT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_ar(a), normalize_ar(b)).ratio()
