"""تفريغ المؤتمرات والتسجيلات: التفريغ بمحركات «صوتي» (مختبر الصوت)، وإبراز الجمل القابلة للتحقق بقواعد ثابتة،
وتحويل أي جملة إلى ادّعاء بنقرة مع توقيتها دليلًا. البث المباشر خارج هذا البند."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.models import User
from marsad.models.claims import Claim, Evidence
from marsad.models.labs import MediaCheck, MediaFile
from marsad.text import normalize_ar

# قواعد شفافة: لكل قاعدة سبب يظهر للصحفي
RULES: list[tuple[str, re.Pattern]] = [
    ("رقم", re.compile(r"\d")),
    ("نسبة", re.compile(r"(بالميه|بالمايه|في الميه|في المايه|بالمئه|بالمائه|%|٪)")),
    ("مقارنة", re.compile(r"(اكثر من|اقل من|ارتفع|ارتفعت|ارتفاع|انخفض|انخفضت|انخفاض|تضاعف|ضعف|اعلي|ادني|زياده|تراجع)")),
    ("أعداد بالكلمات", re.compile(r"(مليون|مليار|الف|الاف|عشرات|مئات|نصف|ربع|ثلث)")),
    ("أول أو أكبر", re.compile(r"(لاول مره|الاول من نوعه|الاكبر|الاعلي|الوحيد|غير مسبوق)")),
    ("واقعة منسوبة", re.compile(r"(بلغ|بلغت|سجل|سجلت|تم انجاز|انجزنا|افتتحنا|خصصنا|وفرنا|انفقنا|اعلنا|وقعنا)")),
    ("تاريخ", re.compile(r"(عام \d|منذ|خلال العام|الشهر الماضي|العام الماضي|حتي الان)")),
]
OPINION = re.compile(r"(نامل|نتمني|نعتقد|اري|ارجو|شكرا|اهلا|السلام عليكم|نرحب)")


def checkable(text: str) -> list[str]:
    n = normalize_ar(text)
    if len(n.split()) < 4 or (OPINION.search(n) and not re.search(r"\d", n)):
        return []
    return [name for name, rx in RULES if rx.search(n) or (name == "نسبة" and rx.search(text))]


def _audio_from_video(path: Path) -> Path:
    out = Path(tempfile.mkdtemp()) / "audio.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(out)],
                   check=True, timeout=1800)
    return out


def transcribe(db: Session, m: MediaFile) -> MediaCheck:
    """يفرّغ تسجيلًا صوتيًا أو فيديو (يُستخرج صوته أولًا). تفريغ سابق ناجح يُعاد كما هو."""
    from marsad.labs import media as lab
    from marsad.labs import sawti

    old = _transcript(db, m)
    if old is not None and (old.result or {}).get("available"):
        return old
    if m.kind not in ("audio", "video"):
        raise ValueError("التفريغ للتسجيلات الصوتية والفيديو فقط")
    src = lab.abs_path(m)
    path = _audio_from_video(src) if m.kind == "video" else src
    t = sawti.transcribe(path)
    if old is not None:
        old.summary, old.result = t["summary"], t
        return old
    return lab._add(db, m, "transcript", "—", t["summary"], t)


def _transcript(db: Session, m: MediaFile) -> MediaCheck | None:
    return db.scalars(select(MediaCheck).where(MediaCheck.media_id == m.id, MediaCheck.check == "transcript")
                      .order_by(MediaCheck.id.desc())).first()


def view(db: Session, m: MediaFile) -> dict:
    t = _transcript(db, m)
    res = (t.result if t else None) or {}
    segs = [{**s, "i": i, "reasons": checkable(s.get("text", ""))} for i, s in enumerate(res.get("segments", []))]
    return {"media_id": m.id, "kind": m.kind, "filename": m.filename, "available": bool(res.get("available")),
            "summary": t.summary if t else "لم يُفرَّغ بعد", "segments": segs,
            "checkable": sum(1 for s in segs if s["reasons"])}


def _ts(sec) -> str:
    sec = int(sec or 0)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def to_claim(db: Session, user: User, m: MediaFile, i: int, text: str | None = None, speaker: str = "") -> Claim:
    from marsad.claims.core import create_claim

    segs = ((_transcript(db, m) or MediaCheck(result={})).result or {}).get("segments", [])
    if not 0 <= i < len(segs):
        raise ValueError("الجملة غير موجودة في التفريغ")
    s = segs[i]
    c = create_claim(db, user, text or s.get("text", ""), speaker=speaker or s.get("speaker", ""), origin="manual")
    c.meta = {**(c.meta or {}), "transcript": {"media_id": m.id, "segment": i, "start": s.get("start"), "end": s.get("end")}}
    db.add(Evidence(claim_id=c.id, kind="check", title=f"التسجيل {m.filename or m.id} عند {_ts(s.get('start'))}",
                    note=f"«{s.get('text', '')}» ({_ts(s.get('start'))}–{_ts(s.get('end'))})", sha256=m.sha256,
                    added_by=user.id, data={"media_id": m.id, "start": s.get("start"), "end": s.get("end")}))
    db.flush()
    return c
