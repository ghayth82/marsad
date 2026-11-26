"""مختبر الصور والفيديو (الشاشة 7) ومختبر الصوت (الشاشة 8) وحاسبة الشمس."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.api.deps import require
from marsad.audit import record
from marsad.core.paths import ensure_storage
from marsad.db import get_db
from marsad.labs import media as lab  # noqa: E402
from marsad.labs import sun
from marsad.models import User
from marsad.models.claims import Claim, Evidence
from marsad.models.labs import MediaFile

router = APIRouter(prefix="/api/labs", tags=["labs"])
use = require("labs.use")


def _parse_when(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "صيغة التاريخ غير صحيحة") from None
    if d.tzinfo is None:
        from datetime import timezone

        d = d.replace(tzinfo=timezone.utc)
    return d


def view(m: MediaFile) -> dict:
    return {"id": m.id, "kind": m.kind, "mime": m.mime, "filename": m.filename, "size": m.size, "sha256": m.sha256,
            "phash": m.phash, "width": m.width, "height": m.height, "duration": m.duration, "origin": m.origin, "url": m.url,
            "seen_at": m.seen_at.isoformat(), "overall": lab.overall(m),
            "checks": [{"id": c.id, "check": c.check, "label": LABELS.get(c.check, c.check), "grade": c.grade, "summary": c.summary, "result": c.result} for c in m.checks],
            "reverse_links": lab.reverse_search_links(m.url)}


def _get(db: Session, mid: int) -> MediaFile:
    m = db.get(MediaFile, mid)
    if m is None or m.kind == "keyframe":
        raise HTTPException(404, "غير موجود")
    return m


@router.post("/media")
async def upload(file: UploadFile | None = File(None), url: str = Form(""), claimed_at: str = Form(""),
                 user: User = Depends(use), db: Session = Depends(get_db)):
    claimed = _parse_when(claimed_at)
    if file is not None:
        raw = await file.read(lab.VIDEO_MAX + 1)
        name = file.filename or ""
    elif url.startswith(("http://", "https://")):
        from marsad.monitor.fetch import FetchError, get

        try:
            r = get(url, check_robots=False)  # رابط يضعه الصحفي بنفسه لفحصه، لا زحف
        except FetchError as e:
            raise HTTPException(422, str(e)) from None
        if r.status_code >= 400:
            raise HTTPException(422, f"الرابط أعاد الرمز {r.status_code}")
        raw, name = r.content, url.split("?")[0].rsplit("/", 1)[-1]
    else:
        raise HTTPException(422, "ارفع ملفًا أو ضع رابطًا")
    if not raw:
        raise HTTPException(422, "الملف فارغ")
    try:
        m = lab.ingest(db, raw, name, origin="upload" if file is not None else "url", url=url, user_id=user.id, run=False)
        lab.analyze(db, m, claimed)
    except lab.LabError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from None
    record(db, user, "labs.check", "media", m.id, after={"sha256": m.sha256, "kind": m.kind})
    db.commit()
    return view(m)


def _sample_image() -> bytes:
    """صورة تجريبية مرسومة (ليست صورة حقيقية) فيها بيانات وصفية، ليرى المستخدم الجديد كيف تظهر نتائج الفحص."""
    import io

    from PIL import Image, ImageDraw

    im = Image.new("RGB", (1200, 800), (135, 190, 235))
    d = ImageDraw.Draw(im)
    d.ellipse((930, 80, 1050, 200), fill=(255, 220, 90))
    d.rectangle((0, 560, 1200, 800), fill=(120, 160, 90))
    d.polygon([(150, 560), (420, 300), (690, 560)], fill=(170, 150, 130))
    d.rectangle((760, 420, 1010, 560), fill=(235, 235, 235), outline=(60, 60, 60), width=4)
    d.text((790, 470), "MARSAD DEMO", fill=(40, 40, 40))
    ex = Image.Exif()
    ex[0x010F], ex[0x0110], ex[0x0131] = "Marsad Demo", "Sample Camera", "Marsad sample generator"
    ex[0x0132] = "2026:01:15 10:30:00"
    ifd = ex.get_ifd(0x8769)
    ifd[0x9003] = "2026:01:15 10:30:00"
    gps = ex.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (31.0, 57.0, 0.0), "E", (35.0, 55.0, 48.0)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88, exif=ex)
    return out.getvalue()


@router.post("/media/sample")
def sample(user: User = Depends(use), db: Session = Depends(get_db)):
    """«جرّب بمثال»: يفحص صورة تجريبية جاهزة كأي ملف مرفوع."""
    try:
        m = lab.ingest(db, _sample_image(), "مثال-تجريبي.jpg", origin="upload", user_id=user.id, run=False)
        lab.analyze(db, m, None)
    except lab.LabError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from None
    db.commit()
    return view(m)


@router.get("/media")
def recent(kind: str | None = None, limit: int = 30, _: User = Depends(use), db: Session = Depends(get_db)):
    stmt = select(MediaFile).where(MediaFile.kind != "keyframe").order_by(MediaFile.id.desc()).limit(min(limit, 100))
    if kind:
        stmt = stmt.where(MediaFile.kind == kind)
    return [{"id": m.id, "kind": m.kind, "filename": m.filename, "seen_at": m.seen_at.isoformat(), "grade": lab.overall(m)["grade"]}
            for m in db.scalars(stmt)]


@router.get("/media/{mid}")
def one(mid: int, _: User = Depends(use), db: Session = Depends(get_db)):
    return view(_get(db, mid))


@router.post("/media/{mid}/recheck")
def recheck(mid: int, claimed_at: str = Form(""), user: User = Depends(use), db: Session = Depends(get_db)):
    m = _get(db, mid)
    lab.analyze(db, m, _parse_when(claimed_at))
    db.commit()
    return view(m)


@router.get("/files/{sha}")
def raw_file(sha: str, _: User = Depends(use), db: Session = Depends(get_db)):
    """ملف من الأرشيف (الأصل، أو لقطة، أو خريطة تحليل الضغط) ببصمته."""
    if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
        raise HTTPException(404, "غير موجود")
    root = ensure_storage().archive / "media" / sha[:2]
    hits = list(root.glob(f"{sha}.*")) if root.exists() else []
    if not hits:
        raise HTTPException(404, "غير موجود")
    return FileResponse(hits[0], headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})


@router.post("/audio/compare")
def compare(a: int = Form(...), b: int = Form(...), _: User = Depends(use), db: Session = Depends(get_db)):
    ma, mb = _get(db, a), _get(db, b)
    if ma.kind not in ("audio", "video") or mb.kind not in ("audio", "video"):
        raise HTTPException(422, "المقارنة بين تسجيلين صوتيين")
    fa, fb = lab.fingerprint_of(ma), lab.fingerprint_of(mb)
    if not len(fa) or not len(fb):
        raise HTTPException(422, "أحد التسجيلين قصير جدًا للمقارنة")
    r = lab.compare_fingerprints(fa, fb)
    s = r["similarity"]
    r["verdict"] = ("التسجيلان من المصدر نفسه على الأرجح" if s >= 0.75 else
                    "تشابه جزئي: ربما مقطع مشترك أو إعادة تسجيل" if s >= 0.62 else "تسجيلان مختلفان")
    r["grade"] = "مؤشر قوي" if s >= 0.75 else "مؤشر" if s >= 0.62 else "لا يكفي"
    return r


class SunIn(BaseModel):
    lat: float
    lon: float
    when: str
    shadow_azimuth: float | None = None
    shadow_ratio: float | None = None


@router.post("/sun")
def sun_calc(body: SunIn, _: User = Depends(use)):
    if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
        raise HTTPException(422, "إحداثيات غير صحيحة")
    return sun.check_shadow(body.lat, body.lon, _parse_when(body.when), body.shadow_azimuth, body.shadow_ratio)


class AttachIn(BaseModel):
    claim_id: int
    note: str = ""


@router.post("/media/{mid}/attach")
def attach(mid: int, body: AttachIn, user: User = Depends(require("labs.use", "claims.create")), db: Session = Depends(get_db)):
    """يضيف نتيجة المختبر دليلًا في بطاقة الادّعاء، بدرجتها كما هي."""
    m = _get(db, mid)
    c = db.get(Claim, body.claim_id)
    if c is None:
        raise HTTPException(404, "الادّعاء غير موجود")
    o = lab.overall(m)
    because = "؛ ".join(b["summary"] for b in o["because"])
    e = Evidence(claim_id=c.id, kind="check", title=f"فحص {m.filename or m.kind}: {because}"[:400], url=m.url,
                 file_path=m.path, sha256=m.sha256, grade="لا يكفي" if o["grade"] == "مؤشر" else o["grade"],  # المؤشر وحده لا يكفي للحكم (درجات الخطة الثلاث)
                 note=body.note, added_by=user.id, is_conclusive=o["grade"] == "قاطع",
                 data={"media_id": m.id, "checks": [{"check": k.check, "grade": k.grade, "summary": k.summary} for k in m.checks]})
    db.add(e)
    record(db, user, "labs.attach", "claim", c.id, after={"media_id": m.id, "grade": e.grade})
    db.commit()
    return {"evidence_id": e.id, "grade": e.grade}


@router.get("/media/{mid}/report")
def report(mid: int, user: User = Depends(use), db: Session = Depends(get_db)):
    """تقرير التحقق: صفحة للطباعة أو الحفظ PDF من المتصفح. داخلي للفريق، لا يُنشر."""
    from html import escape

    from fastapi.responses import HTMLResponse

    m = _get(db, mid)
    o = lab.overall(m)
    rows = "".join(f"<tr><td>{escape(LABELS.get(c.check, c.check))}</td><td>{escape(c.summary)}</td><td><b>{escape(c.grade)}</b></td></tr>"
                   for c in m.checks if c.check not in ("hashes",))
    html = f"""<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>تقرير تحقق #{m.id}</title>
<style>body{{font-family:system-ui,'Noto Sans Arabic',sans-serif;max-width:820px;margin:24px auto;color:#111;line-height:1.6}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px 8px;text-align:right;vertical-align:top}}
.g{{font-size:20px;font-weight:700}} .mu{{color:#666;font-size:12px}} @media print{{button{{display:none}}}}</style>
<button onclick="print()">طباعة أو حفظ PDF</button>
<h1>تقرير تحقق — {escape(m.filename or m.kind)}</h1>
<p class="mu">داخلي للفريق · أعدّه {escape(user.full_name or user.email)} · {escape(lab.utcnow().strftime('%Y-%m-%d %H:%M'))} UTC</p>
<p class="g">النتيجة: {escape(o['grade'])}</p>
<p>{escape('؛ '.join(b['summary'] for b in o['because']))}</p>
<p class="mu">لا تُصدر الأداة حكمًا قاطعًا دون دليل قاطع. تحليل الضغط والبيانات الوصفية مؤشرات فقط.</p>
<table><tr><th>الفحص</th><th>النتيجة</th><th>الدرجة</th></tr>{rows}</table>
<h3>سلسلة الحفظ</h3><p class="mu">SHA-256: {m.sha256}<br>أول رصد: {m.seen_at.isoformat()}<br>المصدر: {escape(m.url or 'رفع يدوي')}</p>
</html>"""
    return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"})


LABELS = {"exif": "البيانات الوصفية", "c2pa": "توقيع المصدر (C2PA)", "ela": "تحليل مستوى الضغط", "ocr": "النص في الصورة",
          "archive": "البحث العكسي في الأرشيف", "probe": "بيانات الفيديو", "keyframes": "اللقطات المفتاحية", "splice": "علامات القص واللصق",
          "transcript": "التفريغ («صوتي»)", "synthetic": "مؤشر توليد الصوت"}
