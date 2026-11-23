"""مختبرات التحقق: الحالات 17–21 من دليل الفحص، وحاسبة الشمس، ومقارنة التسجيلات."""

import datetime as dt
import io
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

FIX = Path(__file__).parent / "fixtures"
need_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg غير مثبت")
need_tesseract = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract غير مثبت")


def scene(seed=1, size=(640, 420)) -> Image.Image:
    """صورة اصطناعية فيها أشكال وتدرج، كافية لبصمة إدراكية مميزة."""
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", size)
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[..., 0] = np.linspace(20, 200, size[0], dtype=np.uint8)[None, :]
    arr[..., 1] = np.linspace(180, 40, size[1], dtype=np.uint8)[:, None]
    arr[..., 2] = 90
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)
    for _ in range(14):
        x, y = int(rng.integers(0, size[0] - 80)), int(rng.integers(0, size[1] - 80))
        w, h = int(rng.integers(30, 160)), int(rng.integers(30, 160))
        d.ellipse((x, y, x + w, y + h), fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    return im.filter(ImageFilter.GaussianBlur(1))


def jpeg(im: Image.Image, q=92, exif=None) -> bytes:
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q, **({"exif": exif} if exif else {}))
    return b.getvalue()


def upload(c, raw: bytes, name: str, claimed: str = ""):
    return c.post("/api/labs/media", files={"file": (name, raw)}, data={"claimed_at": claimed})


def check(r, name):
    return next(x for x in r["checks"] if x["check"] == name)


# ---------- الحالة 17: C2PA ----------

def _c2pa_chain():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = dt.datetime.now(dt.timezone.utc)
    ca_key, leaf_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())

    def name(cn, o):
        return x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "JO"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, o),
                          x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    ca_n = name("Marsad Test Root CA", "Marsad Test")
    ca = (x509.CertificateBuilder().subject_name(ca_n).issuer_name(ca_n).public_key(ca_key.public_key()).serial_number(1001)
          .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    leaf = (x509.CertificateBuilder().subject_name(name("Test News Agency Signer", "Test News Agency")).issuer_name(ca_n)
            .public_key(leaf_key.public_key()).serial_number(1002)
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    pem = serialization.Encoding.PEM
    return (leaf.public_bytes(pem) + ca.public_bytes(pem),
            leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
            ca.public_bytes(pem).decode())


def c2pa_sign(raw: bytes, chain: bytes, key: bytes) -> bytes:
    c2pa = pytest.importorskip("c2pa")
    signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(alg=b"es256", sign_cert=chain, private_key=key, ta_url=None))
    manifest = {"claim_generator_info": [{"name": "Marsad Test", "version": "1"}], "title": "photo.jpg",
                "assertions": [{"label": "c2pa.actions", "data": {"actions": [{"action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture"}]}}]}
    out = io.BytesIO()
    c2pa.Builder(json.dumps(manifest)).sign(signer, "image/jpeg", io.BytesIO(raw), out)
    return out.getvalue()


def test_case17_c2pa_trusted_signer_is_conclusive(admin, monkeypatch):
    chain, key, ca = _c2pa_chain()
    signed = c2pa_sign(jpeg(scene(17)), chain, key)
    # دون قائمة ثقة: توقيع سليم لكنه ليس قاطعًا
    r = upload(admin, signed, "signed.jpg").json()
    assert check(r, "c2pa")["grade"] == "مؤشر قوي"
    assert "Test News Agency" in check(r, "c2pa")["summary"]
    # بعد إضافة جهة التوقيع إلى قائمة الثقة: قاطع، ويظهر الموقّع
    monkeypatch.setenv("MARSAD_C2PA_TRUST_ANCHORS", ca)
    r = admin.post(f"/api/labs/media/{r['id']}/recheck").json()
    c = check(r, "c2pa")
    assert c["grade"] == "قاطع" and c["result"]["state"] == "Trusted"
    assert r["overall"]["grade"] == "قاطع"
    # ملف عُدّل بعد توقيعه: التوقيع مكسور، ولا قاطع
    tampered = bytearray(signed)
    tampered[-200] ^= 0xFF
    r2 = upload(admin, bytes(tampered), "tampered.jpg").json()
    assert check(r2, "c2pa")["grade"] != "قاطع"


# ---------- الحالة 18: صورة معدّلة بلا توقيع ----------

def test_case18_edited_unsigned_image_never_conclusive(admin):
    base = scene(18)
    patch = scene(99).crop((0, 0, 200, 150))
    edited = Image.open(io.BytesIO(jpeg(base, q=60))).convert("RGB")
    edited.paste(patch, (300, 200))  # لصق منطقة بضغط مختلف
    exif = Image.Exif()
    exif[0x0131] = "Adobe Photoshop 25.0"
    r = upload(admin, jpeg(edited, q=95, exif=exif), "edited.jpg").json()
    assert r["overall"]["grade"] in ("مؤشر", "لا يكفي")
    assert all(c["grade"] != "قاطع" for c in r["checks"])
    assert "Photoshop" in check(r, "exif")["summary"]
    assert check(r, "c2pa")["result"]["present"] is False
    ela = check(r, "ela")
    assert ela["result"]["heatmap"] and "مؤشر فقط" in ela["summary"]
    sha = ela["result"]["heatmap"].split("/")[-1].split(".")[0]
    assert admin.get(f"/api/labs/files/{sha}").status_code == 200


# ---------- الحالة 19: نص عربي في صورة ----------

@need_tesseract
def test_case19_arabic_text_extracted(admin):
    r = upload(admin, (FIX / "arabic_text.png").read_bytes(), "statement.png").json()
    text = check(r, "ocr")["result"]["text"]
    for w in ("وزارة", "الصحة", "إغلاق", "المدارس", "بيان", "رسمي"):
        assert w in text


# ---------- البحث العكسي في الأرشيف وأقدم نسخة ----------

def test_reposted_old_image_found_in_archive(admin):
    old = jpeg(scene(7))
    first = upload(admin, old, "original.jpg").json()
    # نسخة مصغّرة ومعاد ضغطها، يُدّعى أنها التُقطت «اليوم» بعد عام
    again = Image.open(io.BytesIO(old)).resize((420, 276))
    claimed = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365)).isoformat()
    r = upload(admin, jpeg(again, q=70), "viral.jpg", claimed).json()
    a = check(r, "archive")
    assert a["grade"] == "قاطع" and a["result"]["matches"][0]["media_id"] == first["id"]
    # صورة مختلفة: لا تطابق
    r3 = upload(admin, jpeg(scene(8)), "other.jpg").json()
    assert check(r3, "archive")["grade"] == "لا يكفي"


# ---------- الحالة 20: فيديو قديم أعيد نشره ----------

@need_ffmpeg
def test_case20_old_video_keyframes_match_archive(admin, tmp_path):
    frames = [scene(s) for s in (31, 32, 33)]
    for n, f in enumerate(frames):
        f.save(tmp_path / f"f{n}.png")
    def make(out, scale="640:420"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1/3", "-i", str(tmp_path / "f%d.png"), "-vf", f"scale={scale},fps=10",
                        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", str(out)], check=True)
    make(tmp_path / "old.mp4")
    first = upload(admin, (tmp_path / "old.mp4").read_bytes(), "old.mp4").json()
    assert first["kind"] == "video" and check(first, "keyframes")["result"]["frames"]
    make(tmp_path / "repost.mp4", "480:316")
    later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=200)).isoformat()
    r = upload(admin, (tmp_path / "repost.mp4").read_bytes(), "repost.mp4", later).json()
    a = check(r, "archive")
    assert a["grade"] == "قاطع" and a["result"]["matches"][0]["media_id"] == first["id"]
    assert r["duration"] > 5


# ---------- الحالة 21 والصوت ----------

def _tone(path: Path, seed: int, seconds=8, splice_at=None):
    rng = np.random.default_rng(seed)
    rate = 16000
    t = np.arange(rate * seconds) / rate
    x = np.zeros_like(t)
    for k in range(6):  # «كلام» اصطناعي: نغمات تتبدل كل نصف ثانية
        f = rng.uniform(250, 1500, size=seconds * 2)
        x += 0.12 * np.sin(2 * np.pi * np.repeat(f, rate // 2)[: len(t)] * t + k)
    gate = np.tile(np.r_[np.ones(rate * 3 // 8), np.zeros(rate // 8)], seconds * 2)[: len(t)]  # وقفات قصيرة بين «الكلمات»
    x = x * gate + 0.003 * rng.standard_normal(len(t))
    if splice_at:
        i = int(splice_at * rate)
        x[i:] += 0.08 * rng.standard_normal(len(t) - i)  # ضجيج خلفية مختلف بعد نقطة اللصق
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


class _Sawti(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"segments": [{"start": 0.0, "end": 2.4, "speaker": "1", "text": "أعلنت الوزارة اليوم"},
                                        {"start": 2.4, "end": 5.1, "speaker": "2", "text": "تعليق الدوام في المدارس"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@need_ffmpeg
def test_case21_audio_transcribed_by_sawti_with_timestamps(admin, tmp_path, monkeypatch):
    _tone(tmp_path / "a.wav", 1)
    raw = (tmp_path / "a.wav").read_bytes()
    r = upload(admin, raw, "a.wav").json()
    assert r["kind"] == "audio"
    t = check(r, "transcript")
    assert t["result"]["available"] is False and "صوتي" in t["summary"]  # بلا اختراع تفريغ
    assert "لا يُعطى حكم" in check(r, "synthetic")["summary"]
    srv = HTTPServer(("127.0.0.1", 0), _Sawti)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("MARSAD_SAWTI_URL", f"http://127.0.0.1:{srv.server_port}")
    r = admin.post(f"/api/labs/media/{r['id']}/recheck").json()
    srv.shutdown()
    segs = check(r, "transcript")["result"]["segments"]
    assert len(segs) == 2 and segs[1]["start"] == 2.4 and "المدارس" in segs[1]["text"]


@need_ffmpeg
def test_audio_compare_and_splice(admin, tmp_path):
    _tone(tmp_path / "a.wav", 5)
    _tone(tmp_path / "b.wav", 6)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp_path / "a.wav"), "-ss", "1.3", "-b:a", "64k", str(tmp_path / "a2.mp3")], check=True)
    ids = [upload(admin, (tmp_path / n).read_bytes(), n).json()["id"] for n in ("a.wav", "a2.mp3", "b.wav")]
    same = admin.post("/api/labs/audio/compare", data={"a": ids[0], "b": ids[1]}).json()
    diff = admin.post("/api/labs/audio/compare", data={"a": ids[0], "b": ids[2]}).json()
    assert same["similarity"] >= 0.75 and abs(same["offset_s"] - 1.3) < 0.2
    assert diff["similarity"] < 0.62 and diff["grade"] == "لا يكفي"
    _tone(tmp_path / "s.wav", 9, seconds=10, splice_at=6.0)
    r = upload(admin, (tmp_path / "s.wav").read_bytes(), "s.wav").json()
    pts = check(r, "splice")["result"]["points"]
    assert any(abs(p["t"] - 6.0) < 1.0 for p in pts)


# ---------- الشمس، الإرفاق بالادّعاء، الصلاحيات، التحقق من الملف ----------

def test_sun_and_shadow(admin):
    # عمّان، 21 يونيو ظهرًا بالتوقيت المحلي: الشمس عالية جنوبًا، الظل قصير نحو الشمال
    r = admin.post("/api/labs/sun", json={"lat": 31.95, "lon": 35.93, "when": "2026-06-21T09:40:00Z"}).json()
    assert 78 < r["sun"]["elevation"] < 83 and r["sun"]["shadow_per_meter"] < 0.25
    bad = admin.post("/api/labs/sun", json={"lat": 31.95, "lon": 35.93, "when": "2026-06-21T09:40:00Z",
                                            "shadow_azimuth": 90, "shadow_ratio": 2.0}).json()
    assert bad["consistent"] is False and len(bad["notes"]) == 2
    night = admin.post("/api/labs/sun", json={"lat": 31.95, "lon": 35.93, "when": "2026-06-21T22:00:00Z"}).json()
    assert night["sun"]["daylight"] is False


def test_attach_result_as_claim_evidence_and_rules(admin, make_client):
    from tests.conftest import invite_user

    old = jpeg(scene(41))
    upload(admin, old, "o.jpg")
    later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=90)).isoformat()
    m = upload(admin, jpeg(Image.open(io.BytesIO(old)).resize((300, 200)), q=60), "v.jpg", later).json()
    cid = admin.post("/api/claims", json={"text": "صورة لحريق في سوق المدينة اليوم"}).json()["id"]
    e = admin.post(f"/api/labs/media/{m['id']}/attach", json={"claim_id": cid}).json()
    assert e["grade"] == "قاطع"
    # الدليل القاطع من المختبر يسمح بحكم قاطع
    assert admin.post(f"/api/claims/{cid}/verdict", json={"label": "مضلل", "evidence_grade": "قاطع",
                                                          "explanation": "الصورة في أرشيفنا قبل التاريخ المدّعى."}).status_code == 200
    # ملف ليس صورة
    assert upload(admin, b"not an image at all" * 10, "x.jpg").status_code == 422
    # المتدرب لا يملك المختبر
    tr, _ = invite_user(admin, make_client, "tr@example.com", ["trainee"])
    assert tr.post("/api/labs/sun", json={"lat": 0, "lon": 0, "when": "2026-01-01T00:00:00Z"}).status_code == 403
