"""غرفة التحقيق وبناء القصة: الحالتان 30 و31، والتشفير، وسلسلة الحفظ، والسرية، والعقوبات، والعمل المشترك على المسودة."""

import io
import shutil
from pathlib import Path

import pytest
from PIL import Image

from tests.conftest import invite_user

LINES = Path(__file__).parent / "fixtures" / "case_lines"
need_ocr = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract غير مثبت")


def scanned_pdf(line_idx: list[int], mark: int = 0) -> bytes:
    """PDF ممسوح: صفحة صورة بلا طبقة نص (mark: نقطة صغيرة تجعل كل ملف فريدًا كما في المسح الحقيقي)."""
    lines = [Image.open(LINES / f"l{i}.png") for i in range(1, 6)]
    im = Image.new("L", (1500, 900), 255)
    y = 80
    for i in line_idx:
        im.paste(lines[i], (1500 - lines[i].width - 20, y))
        y += 150
    im.putpixel((5 + mark, 5), 0)
    b = io.BytesIO()
    im.convert("RGB").save(b, "PDF", resolution=150)
    return b.getvalue()


def new_case(c, title="عقود صيانة الطرق"):
    r = c.post("/api/cases", json={"title": title, "summary": "تتبّع عقود الصيانة والشركات المرتبطة"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def upload(c, cid, files):
    r = c.post(f"/api/cases/{cid}/documents", files=[("files", (n, b)) for n, b in files])
    assert r.status_code == 200, r.text
    return r.json()


@need_ocr
def test_case30_twenty_scanned_pdfs(admin):
    cid = new_case(admin)
    combos = [[k % 5, (k + 1) % 5] for k in range(20)]
    res = upload(admin, cid, [(f"scan_{k:02d}.pdf", scanned_pdf(cb, k)) for k, cb in enumerate(combos)])
    assert len(res["added"]) == 20 and not res["errors"]
    ov = admin.get(f"/api/cases/{cid}").json()
    assert all(d["status"] == "ready" and d["method"] == "ocr" for d in ov["documents"])
    d1 = admin.get(f"/api/cases/{cid}/documents/1").json()
    assert "وزارة الأشغال العامة" in d1["text"][0] and "شركة الأفق للمقاولات" in d1["text"][0]
    ents = {e["name"]: e for e in admin.get(f"/api/cases/{cid}/entities").json()}
    for name in ("وزارة الأشغال العامة", "شركة الأفق للمقاولات", "شركة النخيل للتجارة", "سامي الحسن", "محافظة الكرك"):
        assert name in ents, (name, list(ents))
    assert ents["وزارة الأشغال العامة"]["kind"] == "org" and len(ents["وزارة الأشغال العامة"]["docs"]) >= 8
    g = admin.get(f"/api/cases/{cid}/graph").json()
    names = {n["name"] for n in g["nodes"]}
    assert {"وزارة الأشغال العامة", "شركة الأفق للمقاولات", "شركة النخيل للتجارة"} <= names
    edge = next(e for e in g["edges"] if {e["a"], e["b"]} == {"وزاره الاشغال العامه", "شركه الافق للمقاولات"})
    assert edge["status"] == "suggested" and len(edge["sources"]) >= 4  # الصلة المقترحة تحمل كل الوثائق التي ذكرتها
    ev = admin.get(f"/api/cases/{cid}/records?kind=event").json()
    assert any(e["date"] == "2024-03-12" for e in ev)
    money = admin.get(f"/api/cases/{cid}/records?kind=money").json()
    assert any(m["amount"] == 2400000 for m in money) and any(m["amount"] == 150000 for m in money)


def test_encryption_at_rest_and_custody_chain(admin):
    from marsad.core.paths import data_file
    from marsad.db import get_db
    from marsad.models.cases import CaseDocument, CustodyLog

    cid = new_case(admin, "قضية سرية")
    secret = "عقد سري بين شركة الأفق للمقاولات ووزارة الأشغال العامة بقيمة 2.4 مليون دينار بتاريخ 2024-03-12."
    upload(admin, cid, [("note.txt", secret.encode())])
    db = next(get_db())
    d = db.query(CaseDocument).filter_by(case_id=cid).one()
    # الافتراضي (قرار غيث): الوثيقة مقروءة من ويندوز في «التحقيقات/اسم التحقيق» باسم يدل عليها
    assert d.path.startswith("التحقيقات/قضية سرية/وثيقة 01 - note - ") and d.path.endswith(".txt")
    assert d.sha256[:8] in d.path
    assert data_file(d.path).read_bytes() == secret.encode()
    # وما في قاعدة البيانات يبقى مشفّرًا
    assert "الأفق" not in d.text_enc and "الأفق" not in d.meta_enc and "note.txt" not in d.filename_enc
    db.close()
    # المدير يفعّل التشفير: الملف نفسه يصير مشفّرًا باسمه المفهوم، ويُزال المقروء
    plain = data_file(d.path)
    r = admin.put("/api/admin/storage/case-encryption", json={"on": True}).json()
    assert r == {"encrypt_case_files": True, "converted": 1}
    db = next(get_db())
    d = db.query(CaseDocument).filter_by(case_id=cid).one()
    assert d.path.endswith(".txt.enc") and not plain.exists()
    on_disk = data_file(d.path).read_bytes()
    assert secret.encode() not in on_disk and "الأفق".encode() not in on_disk
    assert admin.get("/api/admin/storage/folders").json()["encrypt_case_files"] is True
    path = d.path
    db.close()  # SQLite: لا نُبقي قراءة مفتوحة أثناء كتابات الخادم
    # الفتح والتنزيل يُسجَّلان، والملف المنزّل مطابق لبصمته
    assert admin.get(f"/api/cases/{cid}/documents/1").json()["text"][0] == secret
    raw = admin.get(f"/api/cases/{cid}/documents/1/file").content
    assert raw == secret.encode()
    cu = admin.get(f"/api/cases/{cid}/custody").json()
    assert cu["verify"]["ok"] is True
    actions = [r["action"] for r in cu["rows"]]
    assert {"create", "upload", "extract", "open", "download"} <= set(actions)
    # التلاعب بسجل الحفظ يُكشف
    from marsad.cases.core import _fernet
    from marsad.models.cases import Case

    db = next(get_db())
    row = db.query(CustodyLog).filter_by(case_id=cid, action="open").one()
    row.detail = "لم يفتحها أحد"
    db.commit()
    key = _fernet(db.get(Case, cid))
    db.close()
    assert admin.get(f"/api/cases/{cid}/custody").json()["verify"]["ok"] is False
    # تغيير الملف على القرص يُكشف عند القراءة
    data_file(path).write_bytes(key.encrypt(b"tampered"))
    assert admin.get(f"/api/cases/{cid}/documents/1/file").status_code == 409
    # إلغاء التشفير يعيد الوثائق مقروءة (والملف المعبوث به يوقف التحويل برسالة)
    assert admin.put("/api/admin/storage/case-encryption", json={"on": False}).status_code == 422


def test_docx_xlsx_and_privacy(admin, make_client):
    import docx
    import openpyxl

    cid = new_case(admin)
    w = docx.Document()
    w.add_paragraph("وقعت وزارة الأشغال العامة عقدا مع شركة الأفق للمقاولات بتاريخ 2024-03-12.")
    t = w.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "المبلغ", "2400000 دينار"
    bw = io.BytesIO()
    w.save(bw)
    wb = openpyxl.Workbook()
    wb.active.append(["الشركة", "المبلغ"])
    wb.active.append(["شركة النخيل للتجارة", 150000])
    bx = io.BytesIO()
    wb.save(bx)
    res = upload(admin, cid, [("contract.docx", bw.getvalue()), ("ledger.xlsx", bx.getvalue()), ("bad.exe", b"MZ....")])
    assert len(res["added"]) == 2 and res["errors"][0]["file"] == "bad.exe"
    docs = admin.get(f"/api/cases/{cid}").json()["documents"]
    assert [d["status"] for d in docs] == ["ready", "ready"]
    assert "2400000 دينار" in admin.get(f"/api/cases/{cid}/documents/1").json()["text"][0]
    assert "شركة النخيل للتجارة | 150000" in admin.get(f"/api/cases/{cid}/documents/2").json()["text"][0]
    # الوثيقة نفسها مرتين
    assert upload(admin, cid, [("again.docx", bw.getvalue())])["errors"]
    # السرية: صحفي آخر لا يرى القضية حتى يُضاف، ثم بقراءة فقط
    j, _ = invite_user(admin, make_client, "j@example.com", ["journalist"])
    assert j.get(f"/api/cases/{cid}").status_code == 404
    assert all(c["id"] != cid for c in j.get("/api/cases").json())
    assert admin.post(f"/api/cases/{cid}/members", json={"email": "j@example.com", "access": "view"}).status_code == 200
    assert j.get(f"/api/cases/{cid}").status_code == 200
    assert j.post(f"/api/cases/{cid}/records", json={"kind": "note", "data": {"text": "x"}}).status_code == 403
    assert j.post(f"/api/cases/{cid}/members", json={"email": "j@example.com", "access": "owner"}).status_code == 403
    # المدير نفسه لا يرى قضية ليس عضوًا فيها
    jc = new_case(j, "قضية الصحفي")
    assert admin.get(f"/api/cases/{jc}").status_code == 404
    # لا يمكن إزالة المالك الوحيد
    me = admin.get("/api/me").json()["email"]
    assert admin.post(f"/api/cases/{cid}/members", json={"email": me, "access": None}).status_code == 422


def test_sanctions_import_and_match(admin):
    cid = new_case(admin)
    upload(admin, cid, [("n.txt", "حولت شركة النخيل للتجارة مبلغ 150000 دينار إلى الوزير سامي الحسن بتاريخ 2024-05-01.".encode())])
    csv = ("id,schema,name,aliases,countries,sanctions,topics\n"
           "os-1,Person,Sami Al-Hassan,سامي الحسن;Sami Hasan,jo,Test Sanctions Programme,sanction\n"
           "os-2,Company,Unrelated Trading LLC,,ae,Other,sanction\n").encode()
    assert admin.post("/api/sanctions/import", data={"list_name": "قائمة اختبار"}, files={"file": ("t.csv", csv)}).json()["entries"] == 2
    r = admin.get(f"/api/cases/{cid}/sanctions").json()
    assert r["lists"][0]["entries"] == 2
    m = [x for x in r["matches"] if x["name"] == "سامي الحسن"]
    assert m and m[0]["match"] == "Sami Al-Hassan" and m[0]["score"] == 1.0
    assert not [x for x in r["matches"] if x["match"] == "Unrelated Trading LLC"]
    assert "مؤشر لا دليل" in r["note"]


def test_records_graph_money_and_timeline(admin):
    cid = new_case(admin)
    upload(admin, cid, [("c.txt", "وقعت وزارة الأشغال العامة عقدا مع شركة الأفق للمقاولات بقيمة 2.4 مليون دينار بتاريخ 12 آذار 2024.".encode())])
    links = admin.get(f"/api/cases/{cid}/records?kind=link").json()
    l0 = next(x for x in links if {x["a"], x["b"]} == {"وزارة الأشغال العامة", "شركة الأفق للمقاولات"})
    admin.patch(f"/api/cases/{cid}/records/{l0['id']}", json={"kind": "link", "status": "confirmed", "data": {"relation": "منحت عقدًا"}})
    added = admin.post(f"/api/cases/{cid}/records", json={"kind": "link", "data": {"a": "شركة الأفق للمقاولات", "a_kind": "org",
                                                                                   "b": "خالد العمري", "b_kind": "person", "relation": "مدير"}}).json()
    assert added["status"] == "confirmed"
    g = admin.get(f"/api/cases/{cid}/graph?suggested=false").json()
    assert {n["name"] for n in g["nodes"]} == {"وزارة الأشغال العامة", "شركة الأفق للمقاولات", "خالد العمري"}
    assert next(n for n in g["nodes"] if n["name"] == "شركة الأفق للمقاولات")["degree"] == 2
    admin.post(f"/api/cases/{cid}/records", json={"kind": "money", "amount": 150000, "date": "2024-05-01", "doc": 1,
                                                  "data": {"from": "شركة الأفق للمقاولات", "to": "شركة النخيل للتجارة", "currency": "دينار"}})
    admin.post(f"/api/cases/{cid}/records", json={"kind": "money", "amount": 50000, "date": "2024-06-01",
                                                  "data": {"from": "شركة الأفق للمقاولات", "to": "شركة النخيل للتجارة", "currency": "دينار"}})
    flows = admin.get(f"/api/cases/{cid}/money").json()["flows"]
    assert flows[0]["total"] == 200000 and flows[0]["count"] == 2 and flows[0]["docs"] == [1]
    ev = admin.get(f"/api/cases/{cid}/records?kind=event").json()
    admin.patch(f"/api/cases/{cid}/records/{ev[0]['id']}", json={"kind": "event", "status": "confirmed", "data": {"title": "توقيع العقد"}})
    t = admin.post(f"/api/cases/{cid}/records", json={"kind": "task", "data": {"title": "طلب نسخة محضر الإحالة"}}).json()
    assert t["status"] == "open"
    sk = admin.get(f"/api/cases/{cid}/skeleton").json()
    assert "خالد العمري" in sk["parties"] and sk["questions"] == ["طلب نسخة محضر الإحالة"]
    assert "في 2024-03-12: توقيع العقد [وثيقة 1 ص 1]" in sk["suggested_body"]
    assert "شركة الأفق للمقاولات → شركة النخيل للتجارة: 150,000 دينار [وثيقة 1]" in sk["suggested_body"]


def test_case31_story_to_word_with_linked_sources(admin, make_client):
    import docx

    cid = new_case(admin)
    upload(admin, cid, [("العقد.txt", "وقعت وزارة الأشغال العامة عقدا مع شركة الأفق للمقاولات بقيمة 2.4 مليون دينار.".encode()),
                        ("السجل.txt", "شركة الأفق للمقاولات شريكة لشركة النخيل للتجارة منذ 2024-02-27.".encode())])
    body = ("حصلت شركة الأفق للمقاولات على عقد صيانة بقيمة 2.4 مليون دينار [وثيقة 1].\n"
            "وجاء ذلك بعد أسبوعين من شراكتها مع شركة النخيل للتجارة [وثيقة 2].\n"
            "وقال مسؤول إن العقد أُحيل دون مناقصة.")
    d = admin.post(f"/api/cases/{cid}/drafts", json={"title": "عقود الصيانة", "angle": "الإحالة دون مناقصة", "body": body}).json()
    assert d["check"]["unsourced"] == ["وقال مسؤول إن العقد أُحيل دون مناقصة."]
    assert next(x for x in d["checklist"] if x["key"] == "sourced")["done"] is False and d["ready"] is False
    # الحفظ بإصدار: زميل حفظ أولًا ← حفظي يُرفض ولا يمحو تعديله
    ed, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    admin.post(f"/api/cases/{cid}/members", json={"email": "ed@example.com", "access": "edit"})
    v = d["version"]
    fixed = body.replace("وقال مسؤول إن العقد أُحيل دون مناقصة.", "وقال مسؤول إن العقد أُحيل دون مناقصة [وثيقة 9].")
    assert ed.put(f"/api/drafts/{d['id']}", json={"title": "عقود الصيانة", "angle": "الإحالة دون مناقصة", "body": fixed, "version": v}).status_code == 200
    assert admin.put(f"/api/drafts/{d['id']}", json={"title": "x", "body": body, "version": v}).status_code == 409
    d = admin.get(f"/api/drafts/{d['id']}").json()
    assert d["check"]["broken_refs"] == ["[وثيقة 9]"]  # إحالة إلى وثيقة غير موجودة
    good = fixed.replace("[وثيقة 9]", "[وثيقة 1 ص 1]")
    d = admin.put(f"/api/drafts/{d['id']}", json={"title": "عقود الصيانة", "angle": "الإحالة دون مناقصة", "body": good, "version": d["version"]}).json()
    assert d["check"]["all_sourced"] is True and [s["doc"] for s in d["sources"]] == [1, 2]
    # لا اعتماد قبل بنود القائمة، ولا يعتمد الكاتب مسودته حين تُفعَّل العينان الأربع
    assert ed.post(f"/api/drafts/{d['id']}/approve").status_code == 422
    for k in ("right_of_reply", "balance", "legal"):
        admin.post(f"/api/drafts/{d['id']}/checklist", json={"key": k, "done": True})
    assert admin.post(f"/api/drafts/{d['id']}/checklist", json={"key": "sourced", "done": True}).status_code == 422
    admin.put("/api/admin/settings/four-eyes", json={"enabled": True})
    assert admin.post(f"/api/drafts/{d['id']}/approve").status_code == 403
    ap = ed.post(f"/api/drafts/{d['id']}/approve").json()
    assert ap["status"] == "approved" and ap["ready"] is True
    # تصدير Word: كل إحالة مرقّمة ومربوطة بدليلها (اسم الوثيقة وصفحتها وبصمتها)
    r = admin.get(f"/api/drafts/{d['id']}/export.docx")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    doc = docx.Document(io.BytesIO(r.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "[1]" in text and "[2]" in text and "[3]" in text and "[وثيقة" not in text
    ov = admin.get(f"/api/cases/{cid}").json()
    shas = {x["number"]: x["sha256"] for x in ov["documents"]}
    assert f"[1] وثيقة 1: العقد.txt — SHA-256: {shas[1]}" in text
    assert f"[2] وثيقة 2: السجل.txt — SHA-256: {shas[2]}" in text
    assert f"[3] وثيقة 1: العقد.txt، ص 1 — SHA-256: {shas[1]}" in text
    assert doc.paragraphs[0]._p.pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}bidi") is not None
    # تعديل بعد الاعتماد يعيدها للمراجعة
    d2 = admin.put(f"/api/drafts/{d['id']}", json={"title": "عقود الصيانة", "body": good + "\nسطر جديد.", "version": ap["version"]}).json()
    assert d2["status"] == "draft"
    actions = [x["action"] for x in admin.get(f"/api/cases/{cid}/custody").json()["rows"]]
    assert "export" in actions and "approve" in actions
