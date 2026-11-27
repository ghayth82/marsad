"""مختبر الصور والفيديو والصوت. كل نتيجة بدرجة دليل واضحة:

- «قاطع»: يحسم المسألة بذاته — شهادة C2PA موقّعة من جهة موثوقة، أو نسخة أقدم في أرشيفنا قبل التاريخ المدّعى.
- «مؤشر قوي»: يرجّح ولا يحسم — توقيع سليم لجهة غير مدرجة في قائمة الثقة، أو توقيع مكسور (عُدّل بعده).
- «مؤشر»: إشارة تحتاج غيرها — بيانات وصفية، تحليل الضغط، برنامج تحرير.
- «لا يكفي»: لا شيء يمكن البناء عليه.
لا حكم قاطع دون دليل قاطع: تحليل الضغط والبيانات الوصفية لا يصلان إلى «قاطع» أبدًا.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image, ImageChops, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.core.paths import data_file, ensure_storage
from marsad.db import utcnow
from marsad.models.labs import MediaCheck, MediaFile

IMAGE_MAX = 30 * 1024 * 1024
VIDEO_MAX = 600 * 1024 * 1024
HAMMING_MATCH = 10  # من 64: تطابق بصري رغم إعادة الضغط والتصغير
MEDIA_CONTAINERS = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm", "avi", "mp3", "wav", "ogg", "flac", "aac",
                    "mpegts", "flv", "asf", "amr", "opus", "caf", "aiff", "mpeg", "w64"}
GRADE_ORDER = {"قاطع": 4, "مؤشر قوي": 3, "مؤشر": 2, "لا يكفي": 1, "—": 0, "": 0}


class LabError(Exception):
    pass


# ---------- البصمات ----------

def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    m[0] /= np.sqrt(2)
    return m * np.sqrt(2 / n)


_D32 = _dct_matrix(32)


def phash(img: Image.Image) -> str:
    """بصمة إدراكية 64 بت: تبقى متقاربة بعد إعادة الضغط والتصغير وتعديل الألوان الخفيف."""
    g = np.asarray(ImageOps.exif_transpose(img).convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
    d = _D32 @ g @ _D32.T
    block = d[:8, :8].flatten()[1:]
    bits = block > np.median(block)
    return f"{int(''.join('1' if b else '0' for b in [False, *bits]), 2):016x}"


def dhash(img: Image.Image) -> str:
    g = np.asarray(img.convert("L").resize((9, 8), Image.Resampling.LANCZOS), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1") if a and b else 64


# ---------- التخزين ----------

def _store(raw: bytes, ext: str) -> tuple[str, str]:
    """ملف مشتق داخلي (لقطة من فيديو، خريطة تحليل الضغط): يُحفظ ببصمته في archive ولا يتصفحه المستخدم."""
    sha = hashlib.sha256(raw).hexdigest()
    rel = f"media/{sha[:2]}/{sha}{ext}"
    p = ensure_storage().archive / rel
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    return rel, sha


KIND_LABEL = {"image": "صورة", "video": "فيديو", "audio": "تسجيل"}


def user_name(kind: str, filename: str, sha: str, when: datetime | None, ext: str) -> tuple[str, str, str]:
    """(مجلد الوظيفة، مجلد الشهر، اسم الملف) لملف رفعه المستخدم أو جُلب من خبر."""
    from marsad.core import naming

    when = when or utcnow()
    title = Path(filename).stem if filename else ""
    return ("audio" if kind == "audio" else "media", f"{when:%Y-%m}",
            naming.file_name(KIND_LABEL.get(kind, "ملف"), title or "بدون اسم", sha, when, ext))


def _store_original(raw: bytes, kind: str, filename: str, ext: str, when: datetime | None) -> tuple[str, str]:
    """أصل رفعه المستخدم: يُحفظ في «الصور والفيديو» أو «الصوت» باسم يدل عليه."""
    from marsad.core import naming

    sha = hashlib.sha256(raw).hexdigest()
    key, month, name = user_name(kind, filename, sha, when, ext)
    return naming.save(key, month, name=name, raw=raw), sha


def abs_path(m: MediaFile) -> Path:
    return data_file(m.path)


def _ffprobe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        raise LabError("الملف ليس صورة ولا فيديو ولا صوتًا صالحًا")
    return json.loads(r.stdout or b"{}")


def sniff(raw: bytes, filename: str) -> tuple[str, str, str]:
    """النوع من محتوى الملف نفسه لا من اسمه: (kind، mime، الامتداد)."""
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").lower()
            if fmt in ("jpeg", "png", "webp", "gif", "tiff", "bmp", "heif", "mpo"):
                return "image", f"image/{'jpeg' if fmt in ('jpeg', 'mpo') else fmt}", ".jpg" if fmt in ("jpeg", "mpo") else f".{fmt}"
    except Exception:
        pass
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix[:8]) as t:
        t.write(raw)
        t.flush()
        info = _ffprobe(Path(t.name))
    fmt = set(str(info.get("format", {}).get("format_name", "")).split(","))
    if not fmt & MEDIA_CONTAINERS:  # ffprobe يقبل أي ملف تقريبًا بحسب امتداده؛ نقبل الحاويات المعروفة فقط
        raise LabError("الملف ليس صورة ولا فيديو ولا صوتًا صالحًا")
    streams = info.get("streams", [])
    has_v = any(s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1 for s in streams)
    has_a = any(s.get("codec_type") == "audio" for s in streams)
    ext = Path(filename).suffix.lower()[:8] or (".mp4" if has_v else ".m4a")
    if has_v:
        return "video", "video/" + (ext.strip(".") or "mp4"), ext
    if has_a:
        return "audio", "audio/" + (ext.strip(".") or "mpeg"), ext
    raise LabError("الملف ليس صورة ولا فيديو ولا صوتًا صالحًا")


def ingest(db: Session, raw: bytes, filename: str = "", *, origin: str = "upload", url: str = "", user_id: int | None = None,
           item_id: int | None = None, seen_at: datetime | None = None, run: bool = True) -> MediaFile:
    kind, mime, ext = sniff(raw, filename)
    if len(raw) > (IMAGE_MAX if kind == "image" else VIDEO_MAX):
        raise LabError("الملف أكبر من المسموح")
    rel, sha = _store_original(raw, kind, filename, ext, seen_at)
    m = MediaFile(sha256=sha, kind=kind, mime=mime, filename=Path(filename).name[:300], size=len(raw), path=rel, origin=origin,
                  url=url, uploaded_by=user_id, source_item_id=item_id, seen_at=seen_at or utcnow())
    if kind == "image":
        with Image.open(io.BytesIO(raw)) as im:
            m.width, m.height = im.size
            m.phash, m.dhash = phash(im), dhash(im)
    db.add(m)
    db.flush()
    if run:
        analyze(db, m)
    return m


# ---------- الفحوص ----------

def _add(db: Session, m: MediaFile, check: str, grade: str, summary: str, result: dict) -> MediaCheck:
    c = MediaCheck(media_id=m.id, check=check, grade=grade, summary=summary, result=result)
    m.checks.append(c)
    return c


def check_hashes(db: Session, m: MediaFile) -> None:
    _add(db, m, "hashes", "—", "بصمات الملف لسلسلة الحفظ والبحث العكسي",
         {"sha256": m.sha256, "phash": m.phash, "dhash": m.dhash, "size": m.size})


def check_exif(db: Session, m: MediaFile, im: Image.Image) -> None:
    exif = im.getexif()
    tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
    try:
        sub = exif.get_ifd(0x8769)
        tags.update({ExifTags.TAGS.get(k, str(k)): v for k, v in sub.items()})
    except Exception:
        pass
    gps = {}
    try:
        g = exif.get_ifd(0x8825)

        def deg(v):
            return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600

        if g.get(2) and g.get(4):
            lat, lon = deg(g[2]), deg(g[4])
            gps = {"lat": round(lat * (-1 if g.get(1) == "S" else 1), 6), "lon": round(lon * (-1 if g.get(3) == "W" else 1), 6)}
    except Exception:
        pass
    keep = {k: str(v)[:200] for k, v in tags.items() if k in (
        "Make", "Model", "Software", "DateTime", "DateTimeOriginal", "DateTimeDigitized", "Artist", "Copyright",
        "LensModel", "ImageDescription", "OffsetTimeOriginal")}
    notes = []
    sw = keep.get("Software", "")
    if any(x in sw.lower() for x in ("photoshop", "gimp", "lightroom", "snapseed", "canva", "picsart", "facetune")):
        notes.append(f"حُفظت ببرنامج تحرير: {sw}")
    if keep.get("DateTimeOriginal") and keep.get("DateTime") and keep["DateTimeOriginal"] != keep["DateTime"]:
        notes.append("تاريخ الالتقاط يختلف عن تاريخ آخر حفظ")
    if not keep:
        summary, grade = "لا بيانات وصفية (أغلب المنصات تحذفها عند الرفع)، فلا يُبنى عليها", "لا يكفي"
    else:
        summary = "؛ ".join(notes) or f"التقاط: {keep.get('DateTimeOriginal', 'غير مذكور')}، جهاز: {keep.get('Make', '')} {keep.get('Model', '')}".strip()
        grade = "مؤشر"  # البيانات الوصفية تُعدَّل بسهولة: مؤشر فقط
    _add(db, m, "exif", grade, summary, {"tags": keep, "gps": gps, "notes": notes})


def c2pa_trust_anchors(db: Session) -> str:
    from marsad.rbac.service import get_setting

    return get_setting(db, "c2pa.trust_anchors", "") or os.environ.get("MARSAD_C2PA_TRUST_ANCHORS", "")


def check_c2pa(db: Session, m: MediaFile) -> None:
    try:
        import c2pa
    except ImportError:
        _add(db, m, "c2pa", "—", "مكتبة C2PA غير متاحة في هذا التثبيت", {})
        return
    anchors = c2pa_trust_anchors(db)
    try:
        ctx = None
        if anchors:
            ctx = c2pa.Context(c2pa.Settings.from_json(json.dumps({"verify": {"verify_trust": True}, "trust": {"trust_anchors": anchors}})))
        with open(abs_path(m), "rb") as f:
            r = c2pa.Reader(m.mime, f, context=ctx) if ctx else c2pa.Reader(m.mime, f)
            state = r.get_validation_state()
            manifest = r.get_active_manifest() or {}
            results = r.get_validation_results() or {}
    except Exception as e:
        name = type(e).__name__
        if "NotSupported" in name or "ManifestNotFound" in name or "JumbfNotFound" in name or "not found" in str(e).lower():
            _add(db, m, "c2pa", "لا يكفي", "لا توجد شهادة محتوى (C2PA) في الملف — وهذا شائع ولا يدل على تلاعب", {"present": False})
        else:
            _add(db, m, "c2pa", "مؤشر قوي", f"شهادة محتوى تالفة أو غير مقروءة: {str(e)[:120]}", {"present": True, "error": str(e)[:300]})
        return
    sig = manifest.get("signature_info") or {}
    actions = []
    for a in manifest.get("assertions", []):
        if str(a.get("label", "")).startswith("c2pa.actions"):
            actions += a.get("data", {}).get("actions", [])
    ai = any("trainedAlgorithmicMedia" in str(x.get("digitalSourceType", "")) or "algorithmic" in str(x.get("digitalSourceType", "")).lower()
             for x in actions)
    signer = sig.get("issuer") or sig.get("common_name") or "غير معروف"
    failures = [f.get("code") for f in (results.get("activeManifest") or {}).get("failure", [])]
    if state == "Trusted":
        grade = "قاطع"
        summary = f"شهادة محتوى موقّعة من جهة موثوقة: {signer}" + ("؛ ويصرّح أنه مولّد بالذكاء الاصطناعي" if ai else "")
    elif state == "Valid":
        grade = "مؤشر قوي"
        summary = f"توقيع سليم من «{signer}» لكنه غير مدرج في قائمة الثقة" + ("؛ ويصرّح أنه مولّد بالذكاء الاصطناعي" if ai else "")
    else:
        grade = "مؤشر قوي"
        summary = "شهادة محتوى مكسورة: عُدّل الملف بعد توقيعه أو التوقيع غير صالح"
    _add(db, m, "c2pa", grade, summary, {"present": True, "state": state, "signer": signer, "signature": sig,
                                         "generator": manifest.get("claim_generator") or manifest.get("claim_generator_info"),
                                         "actions": actions[:20], "ai_generated": ai, "failures": failures, "title": manifest.get("title")})


def check_ela(db: Session, m: MediaFile, im: Image.Image) -> None:
    """تحليل مستوى الضغط: المناطق المُلصقة أو المعدّلة تظهر بخطأ ضغط مختلف. مؤشر بصري فقط."""
    if m.mime != "image/jpeg":
        _add(db, m, "ela", "—", "تحليل الضغط يخص صور JPEG", {})
        return
    rgb = im.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=90)
    diff = ImageChops.difference(rgb, Image.open(io.BytesIO(buf.getvalue())))
    arr = np.asarray(diff, dtype=np.float32).max(axis=2)
    scale = 255.0 / max(1.0, float(arr.max()))
    heat = Image.fromarray(np.clip(arr * scale, 0, 255).astype(np.uint8)).convert("L")
    out = io.BytesIO()
    ImageOps.colorize(heat, "#000000", "#ffcc00").save(out, "PNG")
    rel, _ = _store(out.getvalue(), ".png")
    h, w = arr.shape
    blocks = arr[: h // 16 * 16, : w // 16 * 16].reshape(h // 16, 16, w // 16, 16).mean(axis=(1, 3)) if h >= 16 and w >= 16 else arr
    # لا درجة آلية: الحواف الحادة والمساحات المسطحة تعطي فروقًا كبيرة في صور سليمة تمامًا،
    # فالخريطة أداة نظر للصحفي، والدرجة «لا يكفي» دائمًا.
    ratio = float(np.percentile(blocks, 99) / (blocks.mean() + 1e-6)) if blocks.size else 0.0
    grade = "لا يكفي"
    summary = "خريطة حرارية لمستوى الضغط: ابحث عن منطقة تختلف بوضوح عن محيطها المشابه لها — تحليل الضغط مؤشر فقط ولا يثبت تعديلًا وحده"
    _add(db, m, "ela", grade, summary, {"heatmap": rel, "ratio": round(ratio, 2)})


def ocr_text(im: Image.Image, thorough: bool = True) -> str:
    """نص الصورة بأسطره. يعيد "" إن لم يكن Tesseract مثبّتًا."""
    if not shutil.which("tesseract"):
        return ""
    g = ImageOps.exif_transpose(im).convert("L")

    def run(img: Image.Image, psm: str) -> str:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "in.png"
            ImageOps.expand(img, 40, 255).save(p)  # هامش أبيض: Tesseract يُسقط أحيانًا السطر الملاصق للحافة
            r = subprocess.run(["tesseract", str(p), "stdout", "-l", "ara+eng", "--psm", psm], capture_output=True, timeout=180)
        return "\n".join(" ".join(line.split()) for line in r.stdout.decode("utf-8", "replace").splitlines() if line.strip())

    # تحليل التخطيط في Tesseract يُسقط أحيانًا سطرًا عربيًا كاملًا، ويختلف ذلك بين إصداراته؛
    # فنجرّب أكثر من وضع (وحجم للصور الصغيرة) ونأخذ القراءة الأكثر كلمات؛ عند التساوي الأولى (الحجم الأصلي).
    candidates = [run(g, "3"), run(g, "6")]
    if thorough and max(g.size) < 1600:
        big = g.resize((g.width * 2, g.height * 2), Image.Resampling.LANCZOS)
        candidates += [run(big, "3"), run(big, "6")]
    return max(candidates, key=lambda t: len(t.split()))


def check_ocr(db: Session, m: MediaFile, im: Image.Image) -> None:
    if not shutil.which("tesseract"):
        _add(db, m, "ocr", "—", "قارئ النص (OCR) غير مثبّت", {})
        return
    text = " ".join(ocr_text(im).split())
    _add(db, m, "ocr", "—", (f"النص في الصورة: {text[:200]}" if text else "لا نص مقروء في الصورة"), {"text": text})


def check_archive(db: Session, m: MediaFile, claimed: datetime | None = None) -> None:
    """البحث العكسي في أرشيفنا: صور ولقطات فيديو متطابقة بصريًا رصدناها من قبل."""
    hashes = [m.phash] if m.phash else []
    if m.kind == "video":
        hashes = [k.phash for k in db.scalars(select(MediaFile).where(MediaFile.parent_id == m.id)) if k.phash]
    if not hashes:
        return
    matches = {}
    for other in db.scalars(select(MediaFile).where(MediaFile.phash != "", MediaFile.id != m.id)):
        if other.parent_id == m.id:
            continue
        d = min(hamming(h, other.phash) for h in hashes)
        if d <= HAMMING_MATCH:
            root = db.get(MediaFile, other.parent_id) if other.parent_id else other
            if root.id == m.id:
                continue
            prev = matches.get(root.id)
            if prev is None or d < prev["distance"]:
                matches[root.id] = {"media_id": root.id, "distance": d, "seen_at": root.seen_at.isoformat(), "url": root.url,
                                    "item_id": root.source_item_id, "kind": root.kind, "exact": root.sha256 == m.sha256}
    rows = sorted(matches.values(), key=lambda x: x["seen_at"])
    claimed = claimed or m.seen_at
    older = [r for r in rows if datetime.fromisoformat(r["seen_at"]) < claimed]
    if older:
        o = older[0]
        grade, summary = "قاطع", f"نسخة أقدم في أرشيفنا رُصدت في {o['seen_at'][:16].replace('T', ' ')} (UTC) — قبل التاريخ المدّعى"
    elif rows:
        grade, summary = "مؤشر", f"{len(rows)} نسخة مشابهة في الأرشيف، ليست أقدم من التاريخ المدّعى"
    else:
        grade, summary = "لا يكفي", "لا نسخة مطابقة في أرشيفنا (جرّب البحث العكسي في المحركات العامة)"
    _add(db, m, "archive", grade, summary, {"matches": rows[:20], "claimed": claimed.isoformat()})


def video_keyframes(db: Session, m: MediaFile, limit: int = 12) -> list[MediaFile]:
    src = abs_path(m)
    info = _ffprobe(src)
    m.duration = float(info.get("format", {}).get("duration") or 0)
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    m.width, m.height = int(vs.get("width") or 0), int(vs.get("height") or 0)
    tags = {**info.get("format", {}).get("tags", {}), **vs.get("tags", {})}
    _add(db, m, "probe", "مؤشر" if tags.get("creation_time") else "لا يكفي",
         f"المدة {m.duration:.1f} ث، {m.width}×{m.height}" + (f"، تاريخ الإنشاء في الملف {tags['creation_time']}" if tags.get("creation_time") else ""),
         {"tags": {k: str(v)[:200] for k, v in tags.items()}, "codec": vs.get("codec_name")})
    frames: list[MediaFile] = []
    with tempfile.TemporaryDirectory() as d:
        step = max(1.0, m.duration / limit) if m.duration else 2.0
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps=1/{step:.3f},scale=480:-2", "-frames:v", str(limit),
                        str(Path(d) / "k%03d.jpg")], capture_output=True, timeout=300)
        for n, f in enumerate(sorted(Path(d).glob("k*.jpg"))):
            raw = f.read_bytes()
            rel, sha = _store(raw, ".jpg")
            with Image.open(io.BytesIO(raw)) as im:
                k = MediaFile(sha256=sha, kind="keyframe", mime="image/jpeg", filename=f"{m.filename}#{n}", size=len(raw), path=rel,
                              phash=phash(im), dhash=dhash(im), width=im.width, height=im.height, origin="keyframe",
                              parent_id=m.id, seen_at=m.seen_at, data={"t": round(n * step, 2)})
            db.add(k)
            frames.append(k)
    db.flush()
    _add(db, m, "keyframes", "—", f"{len(frames)} لقطة مفتاحية للبحث العكسي", {"frames": [{"id": f.id, "t": f.data["t"]} for f in frames]})
    return frames


# ---------- الصوت ----------

FP_HOP = 256  # 16 مللي ثانية: أدق في الإزاحة وأثبت بعد ضغط MP3


def _pcm(path: Path, rate: int = 16000) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], capture_output=True, timeout=600)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def audio_fingerprint(x: np.ndarray, rate: int = 16000) -> np.ndarray:
    """بصمة على طريقة Haitsma-Kalker: فروق طاقة 17 نطاقًا ترددياً بين إطارات متتالية (بت لكل فرق)."""
    n, hop = 2048, FP_HOP
    if len(x) < n * 2:
        return np.zeros((0, 16), dtype=bool)
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(n, 1 / rate)
    edges = np.geomspace(300, 2000, 18)
    bands = np.stack([spec[:, (freqs >= a) & (freqs < b)].sum(axis=1) for a, b in zip(edges[:-1], edges[1:])], axis=1) + 1e-9
    e = np.log(bands)
    d = (e[1:, :-1] - e[1:, 1:]) - (e[:-1, :-1] - e[:-1, 1:])
    return d > 0


def compare_fingerprints(a: np.ndarray, b: np.ndarray, max_shift: int = 3750) -> dict:
    """أفضل إزاحة بين بصمتين (حتى دقيقة تقريبًا) ونسبة البتات المتطابقة عندها.
    التداخل لا يقل عن نصف الأقصر، كي لا يصنع تداخل قصير تطابقًا بالصدفة."""
    if not len(a) or not len(b):
        return {"similarity": 0.0, "offset_s": 0.0}
    best = (1.0, 0)
    min_overlap = max(60, min(len(a), len(b)) // 2)
    for s in range(-min(max_shift, len(b) - 1), min(max_shift, len(a) - 1) + 1):
        aa, bb = (a[s:], b) if s >= 0 else (a, b[-s:])
        L = min(len(aa), len(bb))
        if L < min_overlap:
            continue
        ber = float(np.mean(aa[:L] != bb[:L]))
        if ber < best[0]:
            best = (ber, s)
    return {"similarity": round(1 - best[0], 3), "offset_s": round(best[1] * FP_HOP / 16000, 2)}


def splice_points(x: np.ndarray, rate: int = 16000) -> list[dict]:
    """نقاط قص أو تركيب محتملة: صمت رقمي تام داخل التسجيل، أو قفزة مفاجئة في ضجيج الخلفية. مؤشر للمراجعة."""
    win = rate // 20
    if len(x) < win * 10:
        return []
    frames = x[: len(x) // win * win].reshape(-1, win)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    db_ = 20 * np.log10(rms)
    out = []
    zero = np.where((np.abs(frames).max(axis=1) == 0))[0]
    for z in zero:
        if 5 < z < len(frames) - 5:
            out.append({"t": round(z * win / rate, 2), "reason": "صمت رقمي تام في وسط التسجيل"})
    floor = np.array([np.percentile(db_[max(0, i - 20):i], 10) if i >= 5 else db_[i] for i in range(len(db_))])
    after = np.array([np.percentile(db_[i:i + 20], 10) if i < len(db_) - 5 else db_[i] for i in range(len(db_))])
    jumps = np.where(np.abs(after - floor) > 12)[0]
    last = -100
    for j in jumps:
        if j - last > 20 and 5 < j < len(db_) - 5:
            out.append({"t": round(j * win / rate, 2), "reason": "تغيّر مفاجئ في ضجيج الخلفية"})
            last = j
    return sorted({o["t"]: o for o in out}.values(), key=lambda o: o["t"])[:20]


def analyze_audio(db: Session, m: MediaFile) -> None:
    x = _pcm(abs_path(m))
    m.duration = round(len(x) / 16000, 2)
    fp = audio_fingerprint(x)
    m.data = {**(m.data or {}), "fp": np.packbits(fp, axis=None).tobytes().hex() if fp.size else "", "fp_rows": int(fp.shape[0])}
    pts = splice_points(x)
    peaks = [round(float(np.abs(c).max()), 3) for c in np.array_split(x, 240) if len(c)] if len(x) else []
    _add(db, m, "splice", "مؤشر" if pts else "لا يكفي",
         f"{len(pts)} نقطة قص أو تركيب محتملة للمراجعة بالاستماع" if pts else "لا نقاط قص ظاهرة", {"points": pts, "peaks": peaks})
    from marsad.labs import sawti

    t = sawti.transcribe(abs_path(m))
    _add(db, m, "transcript", "—", t["summary"], t)
    _add(db, m, "synthetic", "—", "كشف الصوت المولّد يحتاج محركًا متخصصًا (وهو أضعف في العربية)؛ لا يُعطى حكم هنا", {})


def fingerprint_of(m: MediaFile) -> np.ndarray:
    hexs, rows = (m.data or {}).get("fp", ""), (m.data or {}).get("fp_rows", 0)
    if not hexs or not rows:
        return np.zeros((0, 16), dtype=bool)
    return np.unpackbits(np.frombuffer(bytes.fromhex(hexs), dtype=np.uint8))[: rows * 16].reshape(rows, 16).astype(bool)


# ---------- التشغيل والدرجة النهائية ----------

def analyze(db: Session, m: MediaFile, claimed: datetime | None = None) -> MediaFile:
    for c in list(m.checks):
        m.checks.remove(c)
    db.flush()
    check_hashes(db, m)
    if m.kind == "image":
        with Image.open(abs_path(m)) as im:
            im.load()
            check_exif(db, m, im)
            check_c2pa(db, m)
            check_ela(db, m, im)
            check_ocr(db, m, im)
        check_archive(db, m, claimed)
    elif m.kind == "video":
        video_keyframes(db, m)
        check_c2pa(db, m)
        check_archive(db, m, claimed)
    elif m.kind == "audio":
        analyze_audio(db, m)
    db.flush()
    return m


def overall(m: MediaFile) -> dict:
    """أعلى درجة بين الفحوص، مع الفحص الذي أعطاها. لا «قاطع» إلا من فحص قاطع بطبيعته."""
    graded = [c for c in m.checks if c.grade in GRADE_ORDER and GRADE_ORDER[c.grade] > 0]
    if not graded:
        return {"grade": "لا يكفي", "because": []}
    top = max(GRADE_ORDER[c.grade] for c in graded)
    return {"grade": next(k for k, v in GRADE_ORDER.items() if v == top),
            "because": [{"check": c.check, "summary": c.summary} for c in graded if GRADE_ORDER[c.grade] == top]}


def reverse_search_links(url: str) -> list[dict]:
    from urllib.parse import quote

    if not url.startswith("http"):
        return []
    u = quote(url, safe="")
    return [{"name": "Google Lens", "url": f"https://lens.google.com/uploadbyurl?url={u}"},
            {"name": "Yandex", "url": f"https://yandex.com/images/search?rpt=imageview&url={u}"},
            {"name": "TinEye", "url": f"https://tineye.com/search?url={u}"},
            {"name": "Bing", "url": f"https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{u}"}]
