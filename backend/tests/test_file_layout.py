"""مكان الملفات وأسماؤها: مجلد عربي لكل وظيفة، واسم يدل على ما في الملف قبل فتحه،
وحفظ تلقائي لما يُصدَّر وللتقارير، وإعادة ترتيب ملفات الإصدار السابق."""
import gzip
import hashlib
import io
from datetime import datetime as dt, timezone

from PIL import Image


def _jpeg(color=(200, 30, 30)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(b, "JPEG")
    return b.getvalue()


def _outlet_item(db, raw: bytes, legacy: bool):
    from marsad.core.paths import ensure_storage
    from marsad.models.monitoring import Item, ItemVersion, Outlet, Source
    from marsad.monitor.service import archive_html

    o = Outlet(name="خبرني", country="الأردن")
    db.add(o)
    db.flush()
    s = Source(outlet_id=o.id, url="https://kh.example/", kind="rss", read_url="https://kh.example/rss")
    db.add(s)
    db.flush()
    cap = dt(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
    sha = hashlib.sha256(raw).hexdigest()
    if legacy:
        rel = f"pages/2026/11/{sha}.html.gz"
        p = ensure_storage().archive / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(gzip.compress(raw))
    else:
        rel, sha = archive_html(raw, cap, o.name, "تأجيل الامتحانات الوزارية")
    it = Item(source_id=s.id, outlet_id=o.id, url="https://kh.example/1", title="تأجيل الامتحانات الوزارية", text="", captured_at=cap,
              content_hash="x", version=2)
    for n in (1, 2):  # نسختان بالمحتوى نفسه تشتركان في ملف واحد
        it.versions.append(ItemVersion(version=n, change="new" if n == 1 else "edit", title=it.title, text="", content_hash="x",
                                       captured_at=cap, archive_path=rel, archive_sha256=sha))
    db.add(it)
    db.commit()
    return it, sha


def test_new_files_go_to_function_folders_with_readable_names(admin):
    from marsad.core.paths import data_file, ensure_storage
    from marsad.db import get_db

    db = next(get_db())
    raw = "<html><title>خبر</title><body>نص</body></html>".encode()
    it, sha = _outlet_item(db, raw, legacy=False)
    rel = it.versions[0].archive_path
    assert rel == f"الرصد/2026-11/خبرني/خبرني - تأجيل الامتحانات الوزارية - {sha[:8]} - 2026-11-27.html.gz"
    assert gzip.decompress(data_file(rel).read_bytes()) == raw
    assert admin.get(f"/api/items/{it.id}/archive/1").content == raw
    db.close()
    # صورة مرفوعة: «الصور والفيديو/الشهر/صورة - اسمها - البصمة - التاريخ»
    img = _jpeg()
    r = admin.post("/api/labs/media", files={"file": ("جسر الطريق الصحراوي.jpg", img)}, data={"claimed_at": ""})
    assert r.status_code == 200, r.text
    h = hashlib.sha256(img).hexdigest()
    hits = list((ensure_storage().media).rglob(f"صورة - جسر الطريق الصحراوي - {h[:8]} - *.jpg"))
    assert len(hits) == 1 and hits[0].read_bytes() == img
    assert admin.get(f"/api/labs/files/{h}").content == img  # الواجهة ما زالت تجلبه ببصمته


def test_exports_and_reports_are_saved_with_dated_names(admin):
    from datetime import date
    from urllib.parse import unquote

    from marsad.core.paths import ensure_storage

    today = date.today().isoformat()
    p = ensure_storage()
    r = admin.get("/api/claims/export/csv")
    assert f"تصدير - الادعاءات - {today}.csv" in unquote(r.headers["content-disposition"])
    assert (p.claims / f"تصدير - الادعاءات - {today}.csv").read_bytes() == r.content
    r = admin.get("/api/claims/export/claimreview")
    assert r.json() == [] and (p.claims / f"تصدير - ClaimReview - {today}.json").exists()
    r = admin.get("/api/sources/export")
    assert (p.monitor / f"تصدير - المصادر - {today}.csv").read_bytes() == r.content
    # التقرير يُحفظ ملفًا عند توليده
    m = admin.post("/api/reports/morning").json()
    f = p.reports / f"الموجز الصباحي - {m['local_date']}.html"
    assert f.exists() and "الموجز الصباحي" in f.read_text(encoding="utf-8")
    w = admin.post("/api/reports/weekly").json()
    assert any(x.name.startswith("التقرير الأسبوعي - ") and x.name.endswith(f"إلى {w['local_date']}.html") for x in p.reports.iterdir())
    # «أين ملفاتي؟» تعدّ ما حُفظ
    rows = {x["key"]: x for x in admin.get("/api/admin/storage/folders").json()["folders"]}
    assert rows["claims"]["name"] == "الشائعات والادعاءات" and rows["claims"]["files"] == 2 and rows["reports"]["files"] == 2


def test_old_hashed_files_are_renamed_and_moved(admin):
    from cryptography.fernet import Fernet

    from marsad import crypto
    from marsad.cases import core as cases
    from marsad.core.paths import data_file, ensure_storage
    from marsad.db import get_db
    from marsad.models.cases import Case, CaseDocument
    from marsad.models.claims import Claim, Evidence
    from marsad.models.labs import MediaFile
    from marsad.models.tools import Snapshot
    from marsad.storage_upgrade import pending, reorganize

    db = next(get_db())
    arc = ensure_storage().archive
    raw = b"<html>old page</html>"
    it, sha = _outlet_item(db, raw, legacy=True)
    # صورة قديمة بالبصمة، ودليل يشير إليها
    img = _jpeg((10, 120, 10))
    ih = hashlib.sha256(img).hexdigest()
    (arc / "media" / ih[:2]).mkdir(parents=True)
    (arc / "media" / ih[:2] / f"{ih}.jpg").write_bytes(img)
    seen = dt(2026, 11, 20, tzinfo=timezone.utc)
    m = MediaFile(sha256=ih, kind="image", mime="image/jpeg", filename="مظاهرة.jpg", size=len(img), path=f"media/{ih[:2]}/{ih}.jpg", origin="upload", seen_at=seen)
    c = Claim(text="ادّعاء", norm="ادعاء")
    db.add_all([m, c])
    db.flush()
    db.add(Evidence(claim_id=c.id, kind="check", title="فحص", file_path=m.path, sha256=ih, grade="لا يكفي"))
    # وثيقة تحقيق قديمة مشفّرة ‎.bin
    case = Case(title="عقود التوريد", key_wrapped=crypto.encrypt(Fernet.generate_key().decode()))
    db.add(case)
    db.flush()
    doc = b"%PDF-1.4 secret contract"
    dh = hashlib.sha256(doc).hexdigest()
    (arc / "cases" / str(case.id)).mkdir(parents=True)
    (arc / "cases" / str(case.id) / f"{dh}.bin").write_bytes(cases._fernet(case).encrypt(doc))
    d = CaseDocument(case_id=case.id, number=3, filename_enc=cases.enc(case, "عقد التوريد.pdf"), kind="pdf", size=len(doc), sha256=dh,
                     path=f"cases/{case.id}/{dh}.bin", added_at=seen)
    # صفحة محفوظة قديمة
    sh = hashlib.sha256(b"snap").hexdigest()
    (arc / "snapshots" / "2026" / "11").mkdir(parents=True)
    (arc / "snapshots" / "2026" / "11" / f"{sh}.html").write_bytes(b"snap")
    s = Snapshot(url="https://moe.example/news/1", final_url="https://moe.example/news/1", title="بيان الوزارة", html_path=f"snapshots/2026/11/{sh}.html",
                 sha256=sh, created_at=seen)
    db.add_all([d, s])
    db.commit()

    assert pending(db) is True
    assert reorganize(db) == {"pages": 1, "media": 1, "cases": 1, "snapshots": 1}
    assert pending(db) is False
    for x in (it, m, d, s):
        db.refresh(x)
    page_rel = f"الرصد/2026-11/خبرني/خبرني - تأجيل الامتحانات الوزارية - {sha[:8]} - 2026-11-27.html.gz"
    assert [v.archive_path for v in it.versions] == [page_rel, page_rel]
    assert gzip.decompress(data_file(page_rel).read_bytes()) == raw
    assert m.path == f"الصور والفيديو/2026-11/صورة - مظاهرة - {ih[:8]} - 2026-11-20.jpg" and data_file(m.path).read_bytes() == img
    assert db.query(Evidence).one().file_path == m.path
    assert d.path == f"التحقيقات/عقود التوريد/وثيقة 03 - عقد التوريد - {dh[:8]} - 2026-11-20.pdf"
    assert data_file(d.path).read_bytes() == doc  # مقروءة من ويندوز (الافتراضي)
    assert s.html_path == f"أدوات التحقق/صفحات محفوظة/2026-11/صفحة - بيان الوزارة - {sh[:8]} - 2026-11-20.html"
    # لا يبقى شيء في الأماكن القديمة، والمجلدات الفارغة أُزيلت
    assert not (arc / "pages").exists() and not (arc / "cases").exists() and not (arc / "snapshots").exists()
    assert not (arc / "media" / ih[:2] / f"{ih}.jpg").exists()
    assert reorganize(db) == {"pages": 0, "media": 0, "cases": 0, "snapshots": 0}  # إعادة التشغيل لا تغيّر شيئًا
    db.close()
    assert admin.get(f"/api/items/{it.id}/archive/1").content == raw
    assert admin.get(f"/api/labs/files/{ih}").content == img
