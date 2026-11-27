"""غرفة التحقيق: قضايا مشفّرة، وثائق بنصّها المستخرج، كيانات وصلات وخط زمني وتتبّع مال، وسلسلة حفظ.

التشفير: لكل قضية مفتاح Fernet عشوائي، مخزّن مشفّرًا بالمفتاح الرئيسي (crypto.py). الملفات ونصوصها
والملاحظات والمسودات مشفّرة على القرص وفي قاعدة البيانات؛ العنوان وحده ظاهر في قائمة القضايا.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.analysis.core import extract_entities
from marsad.core.paths import data_file
from marsad.db import utcnow
from marsad.models import User
from marsad.models.cases import Case, CaseDocument, CaseMember, CaseRecord, CustodyLog, Draft, SanctionEntry
from marsad.text import normalize_ar, similar

MAX_DOC = 200 * 1024 * 1024
LEVEL = {"view": 1, "edit": 2, "owner": 3}


class CaseError(Exception):
    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


# ---------- التشفير ----------

def _fernet(c: Case) -> Fernet:
    return Fernet(crypto.decrypt(c.key_wrapped).encode())


def enc(c: Case, obj) -> str:
    return _fernet(c).encrypt(json.dumps(obj, ensure_ascii=False).encode()).decode() if obj not in (None, "") else ""


def dec(c: Case, token: str, default=None):
    if not token:
        return default
    return json.loads(_fernet(c).decrypt(token.encode()))


# ---------- القضايا والعضوية ----------

def create_case(db: Session, user: User, title: str, summary: str = "") -> Case:
    if not title.strip():
        raise CaseError("اكتب عنوان القضية")
    c = Case(title=title.strip()[:300], key_wrapped=crypto.encrypt(Fernet.generate_key().decode()), owner_id=user.id)
    db.add(c)
    db.flush()
    c.summary_enc = enc(c, summary.strip())
    db.add(CaseMember(case_id=c.id, user_id=user.id, access="owner", added_by=user.id))
    custody(db, c, user, "create", detail="أُنشئت القضية")
    return c


def member(db: Session, c: Case, user: User) -> CaseMember | None:
    return db.scalars(select(CaseMember).where(CaseMember.case_id == c.id, CaseMember.user_id == user.id)).first()


def require_access(db: Session, c: Case | None, user: User, need: str = "view") -> Case:
    """القضية لأعضائها فقط، ولو كان المستخدم مديرًا للنظام: سرية التحقيقات."""
    if c is None:
        raise CaseError("القضية غير موجودة", 404)
    m = member(db, c, user)
    if m is None:
        raise CaseError("القضية غير موجودة", 404)  # لا نكشف وجودها
    if LEVEL[m.access] < LEVEL[need]:
        raise CaseError("صلاحيتك في هذه القضية للقراءة فقط" if need == "edit" else "هذا لمالك القضية", 403)
    return c


def user_cases(db: Session, user: User) -> list[tuple[Case, str]]:
    rows = db.execute(select(Case, CaseMember.access).join(CaseMember, CaseMember.case_id == Case.id)
                      .where(CaseMember.user_id == user.id).order_by(Case.updated_at.desc())).all()
    return [(c, a) for c, a in rows]


def set_member(db: Session, c: Case, actor: User, target: User, access: str | None) -> None:
    if access not in (None, "view", "edit", "owner"):
        raise CaseError("مستوى وصول غير صحيح")
    m = db.scalars(select(CaseMember).where(CaseMember.case_id == c.id, CaseMember.user_id == target.id)).first()
    owners = db.scalars(select(CaseMember).where(CaseMember.case_id == c.id, CaseMember.access == "owner")).all()
    if m and m.access == "owner" and access != "owner" and len(owners) == 1:
        raise CaseError("لا يمكن إزالة المالك الوحيد للقضية؛ أضف مالكًا آخر أولًا")
    if access is None:
        if m:
            db.delete(m)
    elif m:
        m.access = access
    else:
        db.add(CaseMember(case_id=c.id, user_id=target.id, access=access, added_by=actor.id))
    custody(db, c, actor, "member", detail=f"{target.email}: {access or 'أُزيل'}")


def touch(c: Case) -> None:
    c.updated_at = utcnow()


# ---------- سلسلة الحفظ ----------

def _entry_hash(prev: str, e: CustodyLog) -> str:
    raw = "|".join([prev, str(e.case_id), str(e.doc_id or ""), str(e.user_id or ""), e.action, e.detail, e.sha256,
                    e.at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")])
    return hashlib.sha256(raw.encode()).hexdigest()


def custody(db: Session, c: Case, user: User | None, action: str, doc: CaseDocument | None = None, detail: str = "", sha: str = "") -> None:
    last = db.scalars(select(CustodyLog).where(CustodyLog.case_id == c.id).order_by(CustodyLog.id.desc())).first()
    e = CustodyLog(case_id=c.id, doc_id=doc.id if doc else None, user_id=user.id if user else None, action=action,
                   detail=detail[:300], sha256=sha or (doc.sha256 if doc else ""), prev_hash=last.entry_hash if last else "",
                   at=utcnow())
    e.entry_hash = _entry_hash(e.prev_hash, e)
    db.add(e)
    db.flush()


def verify_custody(db: Session, c: Case) -> dict:
    prev = ""
    rows = list(db.scalars(select(CustodyLog).where(CustodyLog.case_id == c.id).order_by(CustodyLog.id)))
    for n, e in enumerate(rows):
        if e.prev_hash != prev or _entry_hash(prev, e) != e.entry_hash:
            return {"ok": False, "entries": len(rows), "broken_at": n, "note": "سجل الحفظ عُدّل أو حُذف منه بعد كتابته"}
        prev = e.entry_hash
    return {"ok": True, "entries": len(rows), "note": "سلسلة الحفظ سليمة"}


# ---------- الوثائق ----------

KINDS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".txt": "text", ".csv": "text", ".md": "text",
         ".jpg": "image", ".jpeg": "image", ".png": "image", ".tif": "image", ".tiff": "image", ".webp": "image", ".bmp": "image",
         ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio", ".opus": "audio", ".mp4": "audio", ".aac": "audio"}


def _kind(raw: bytes, filename: str) -> str:
    k = KINDS.get(Path(filename).suffix.lower())
    head = raw[:8]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK") and k in ("docx", "xlsx"):
        return k
    if k == "image":
        from PIL import Image

        try:
            with Image.open(io.BytesIO(raw)) as im:
                im.verify()
            return "image"
        except Exception:
            raise CaseError("الملف ليس صورة صالحة") from None
    if k in ("text", "audio"):
        return k
    raise CaseError("نوع الملف غير مدعوم: PDF أو Word أو Excel أو صورة أو تسجيل أو نص")


ENC_SETTING = "cases.encrypt_files"  # إعداد المدير: تشفير ملفات وثائق التحقيقات على القرص (الافتراضي: لا)
ENC_SUFFIXES = (".enc", ".bin")  # ‎.bin صيغة الإصدارات السابقة


def encrypt_files(db: Session) -> bool:
    from marsad.rbac.service import get_setting

    return bool(get_setting(db, ENC_SETTING, False))


def case_folder(db: Session, c: Case) -> str:
    """مجلد التحقيق باسمه؛ وإن تكرر الاسم في تحقيق أقدم أُلحق رقمه."""
    from marsad.core import naming

    name = naming.clean(c.title, 80) or f"تحقيق {c.id}"
    twins = [o for o in db.scalars(select(Case).where(Case.id < c.id)) if (naming.clean(o.title, 80) or "") == name]
    return f"{name} ({c.id})" if twins else name


def doc_name(number: int, filename: str, sha: str, when: datetime | None, encrypted: bool) -> str:
    from marsad.core import naming

    ext = Path(filename).suffix.lower()[:10]
    return naming.file_name(f"وثيقة {number:02d}", Path(filename).stem or "بدون اسم", sha, when, ext) + (".enc" if encrypted else "")


def write_doc_file(db: Session, c: Case, number: int, filename: str, sha: str, when: datetime | None, raw: bytes) -> str:
    """يكتب ملف الوثيقة في «التحقيقات/اسم التحقيق» ويُرجع مساره النسبي. يُشفَّر إن فعّل المدير التشفير."""
    from marsad.core import naming

    on = encrypt_files(db)
    return naming.save("cases", case_folder(db, c), name=doc_name(number, filename, sha, when, on),
                       raw=_fernet(c).encrypt(raw) if on else raw)


def doc_file(d: CaseDocument) -> Path:
    return data_file(d.path)


def add_document(db: Session, c: Case, user: User, raw: bytes, filename: str) -> CaseDocument:
    if not raw:
        raise CaseError("الملف فارغ")
    if len(raw) > MAX_DOC:
        raise CaseError("الملف أكبر من 200 ميغابايت")
    kind = _kind(raw, filename)
    sha = hashlib.sha256(raw).hexdigest()
    dup = db.scalars(select(CaseDocument).where(CaseDocument.case_id == c.id, CaseDocument.sha256 == sha)).first()
    if dup:
        raise CaseError(f"الوثيقة نفسها موجودة في القضية (وثيقة {dup.number})")
    n = (db.scalars(select(CaseDocument.number).where(CaseDocument.case_id == c.id).order_by(CaseDocument.number.desc())).first() or 0) + 1
    rel = write_doc_file(db, c, n, filename, sha, utcnow(), raw)
    d = CaseDocument(case_id=c.id, number=n, filename_enc=enc(c, Path(filename).name[:300]), kind=kind, size=len(raw), sha256=sha,
                     path=rel, added_by=user.id)
    db.add(d)
    db.flush()
    custody(db, c, user, "upload", d, detail=f"وثيقة {n} ({kind})")
    touch(c)
    return d


def read_document(c: Case, d: CaseDocument) -> bytes:
    raw = doc_file(d).read_bytes()
    if d.path.endswith(ENC_SUFFIXES):
        raw = _fernet(c).decrypt(raw)
    if hashlib.sha256(raw).hexdigest() != d.sha256:
        raise CaseError("بصمة الوثيقة لا تطابق المحفوظة: الملف تغيّر على القرص", 409)
    return raw


def _extract(kind: str, raw: bytes, filename: str) -> tuple[list[str], str]:
    """نص كل صفحة (أو ورقة) وطريقة الاستخراج."""
    if kind == "pdf":
        import pypdfium2 as pdfium

        from marsad.labs.media import ocr_text

        pdf = pdfium.PdfDocument(raw)
        pages, used_ocr, used_text = [], False, False
        for i in range(len(pdf)):
            page = pdf[i]
            t = page.get_textpage().get_text_range().strip()
            if len(t) < 25:  # صفحة ممسوحة: نرسمها ونقرأها
                img = page.render(scale=2.5).to_pil()
                t = ocr_text(img, thorough=False)
                used_ocr = True
            else:
                used_text = True
            pages.append(t)
        return pages, "mixed" if used_ocr and used_text else "ocr" if used_ocr else "text"
    if kind == "docx":
        import docx

        doc = docx.Document(io.BytesIO(raw))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for tbl in doc.tables:
            for row in tbl.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return ["\n".join(parts)], "text"
    if kind == "xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheets = []
        for ws in wb.worksheets:
            lines = [f"[{ws.title}]"]
            for row in ws.iter_rows(values_only=True):
                if any(v not in (None, "") for v in row):
                    lines.append(" | ".join("" if v is None else str(v) for v in row))
            sheets.append("\n".join(lines))
        return sheets, "text"
    if kind == "image":
        from PIL import Image

        from marsad.labs.media import ocr_text

        with Image.open(io.BytesIO(raw)) as im:
            return [ocr_text(im)], "ocr"
    if kind == "audio":
        import tempfile

        from marsad.labs import sawti

        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as t:
            t.write(raw)
            t.flush()
            r = sawti.transcribe(Path(t.name))
        if not r["available"]:
            raise CaseError(r["summary"])
        return ["\n".join(f"[{s['start']}] {s.get('speaker', '')}: {s['text']}" for s in r["segments"])], "sawti"
    for enc_ in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return [raw.decode(enc_)], "text"
        except UnicodeDecodeError:
            continue
    return [""], "text"


ORG_START = re.compile(r"^(?:" + "|".join(normalize_ar(w) for w in "شركة وزارة هيئة مؤسسة بنك البنك جامعة بلدية مجلس نقابة حزب دائرة سلطة مديرية جمعية".split()) + r")(?:\s|$)")


def _light(text: str) -> str:
    """توحيد الحروف والأرقام دون حذف الترقيم (تبقى الشرطة والخط المائل والفاصلة العشرية)."""
    import unicodedata

    from marsad.text import _DIACRITICS, _MAP

    return re.sub(r"\s+", " ", _DIACRITICS.sub("", unicodedata.normalize("NFKC", text or "")).translate(_MAP)).strip()
MONTHS = {**{normalize_ar(m): i for i, m in enumerate(["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب",
                                                         "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول"], 1)},
          **{normalize_ar(m): i for i, m in enumerate(["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
                                                         "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"], 1)}}
_MONTH_RE = "|".join(re.escape(m) for m in sorted(MONTHS, key=len, reverse=True))
DATE_RE = re.compile(rf"(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})|(\d{{4}})-(\d{{1,2}})-(\d{{1,2}})|(\d{{1,2}})/(\d{{1,2}})/(\d{{4}})")
MONEY_RE = re.compile(r"(\d+(?:[.,]\d+)*)\s*(مليون|مليار|الف)?\s*(دينار|دولار|يورو|ريال|درهم|جنيه|ليره|شيكل)")
MULT = {"مليون": 1e6, "مليار": 1e9, "الف": 1e3}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!؟?])\s+|\n+", text) if len(s.strip()) > 8]


def _entities(text: str) -> list[dict]:
    out = {}
    for e in extract_entities(text):
        kind = "org" if ORG_START.match(e["norm"]) else e["kind"]
        out[e["norm"]] = {"name": e["name"], "norm": e["norm"], "kind": kind}
    # الأقصر الذي هو بداية لأطول من النوع نفسه مكرر («شركة الأفق» داخل «شركة الأفق للمقاولات»)
    keys = list(out)
    for k in keys:
        if any(o != k and o.startswith(k + " ") and out[o]["kind"] == out[k]["kind"] for o in keys):
            out.pop(k, None)
    return list(out.values())


def analyze_text(pages: list[str]) -> dict:
    ents: dict[str, dict] = {}
    pairs: dict[tuple[str, str], dict] = {}
    dates, money = [], []
    for pno, page in enumerate(pages, 1):
        for s in _sentences(page):
            se = _entities(s)
            for e in se:
                x = ents.setdefault(e["norm"], {**e, "count": 0, "pages": []})
                x["count"] += 1
                if pno not in x["pages"]:
                    x["pages"].append(pno)
            for a, b in combinations(sorted({e["norm"] for e in se}), 2):
                pairs.setdefault((a, b), {"a": a, "b": b, "snippet": s[:300], "page": pno})
            ns = _light(s)
            for m in DATE_RE.finditer(ns):
                try:
                    if m.group(1):
                        d = datetime(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), tzinfo=timezone.utc)
                    elif m.group(4):
                        d = datetime(int(m.group(4)), int(m.group(5)), int(m.group(6)), tzinfo=timezone.utc)
                    else:
                        d = datetime(int(m.group(9)), int(m.group(8)), int(m.group(7)), tzinfo=timezone.utc)
                except (ValueError, KeyError):
                    continue
                dates.append({"date": d.date().isoformat(), "sentence": s[:300], "page": pno})
            for m in MONEY_RE.finditer(ns):
                v = m.group(1)
                v = v.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", v) else v.replace(",", ".")
                try:
                    amount = float(v) * MULT.get(m.group(2) or "", 1)
                except ValueError:
                    continue
                money.append({"amount": amount, "currency": m.group(3), "sentence": s[:300], "page": pno,
                              "parties": [e["name"] for e in se if e["kind"] != "place"]})
    return {"entities": sorted(ents.values(), key=lambda e: -e["count"]), "pairs": list(pairs.values()), "dates": dates, "money": money}


def process_document(db: Session, c: Case, d: CaseDocument) -> CaseDocument:
    try:
        pages, method = _extract(d.kind, read_document(c, d), dec(c, d.filename_enc, ""))
    except CaseError as e:
        d.status, d.error = "failed", str(e)
        return d
    except Exception as e:  # ملف تالف أو محمي بكلمة سر
        d.status, d.error = "failed", f"تعذّرت قراءة الملف: {e.__class__.__name__}"
        return d
    meta = analyze_text(pages)
    d.text_enc, d.meta_enc, d.pages, d.method, d.status = enc(c, pages), enc(c, meta), len(pages), method, "ready"
    names = {e["norm"]: e for e in meta["entities"]}
    existing = {}
    for r in db.scalars(select(CaseRecord).where(CaseRecord.case_id == c.id, CaseRecord.kind == "link")):
        b = dec(c, r.body_enc, {})
        existing[(b.get("a_norm"), b.get("b_norm"))] = (r, b)
    for p in meta["pairs"]:
        key = (p["a"], p["b"])
        src = {"doc": d.number, "page": p["page"], "snippet": p["snippet"]}
        if key in existing:
            r, b = existing[key]
            if all(s["doc"] != d.number for s in b.get("sources", [])):
                b["sources"].append(src)
                r.body_enc = enc(c, b)
            continue
        body = {"a": names[p["a"]]["name"], "a_norm": p["a"], "a_kind": names[p["a"]]["kind"], "b": names[p["b"]]["name"],
                "b_norm": p["b"], "b_kind": names[p["b"]]["kind"], "relation": "ذُكرا معًا", "sources": [src]}
        r = CaseRecord(case_id=c.id, kind="link", status="suggested", doc_id=d.id, body_enc=enc(c, body))
        db.add(r)
        existing[key] = (r, body)
    for x in meta["dates"]:
        db.add(CaseRecord(case_id=c.id, kind="event", status="suggested", doc_id=d.id,
                          at_date=datetime.fromisoformat(x["date"]).replace(tzinfo=timezone.utc),
                          body_enc=enc(c, {"title": x["sentence"][:160], "detail": x["sentence"], "page": x["page"]})))
    for x in meta["money"]:
        db.add(CaseRecord(case_id=c.id, kind="money", status="suggested", doc_id=d.id, amount=x["amount"],
                          body_enc=enc(c, {"from": x["parties"][0] if x["parties"] else "", "to": x["parties"][1] if len(x["parties"]) > 1 else "",
                                           "currency": x["currency"], "purpose": x["sentence"][:200], "page": x["page"]})))
    custody(db, c, None, "extract", d, detail=f"استُخرج النص ({method}، {len(pages)} صفحة، {len(meta['entities'])} كيانًا)")
    touch(c)
    return d


def doc_view(c: Case, d: CaseDocument, text: bool = False) -> dict:
    meta = dec(c, d.meta_enc, {}) or {}
    v = {"id": d.id, "number": d.number, "filename": dec(c, d.filename_enc, ""), "kind": d.kind, "size": d.size, "sha256": d.sha256,
         "status": d.status, "method": d.method, "pages": d.pages, "error": d.error, "added_at": d.added_at.isoformat(),
         "entities": meta.get("entities", [])[:40], "entity_count": len(meta.get("entities", []))}
    if text:
        v["text"] = dec(c, d.text_enc, [])
    return v


# ---------- السجلات (ملاحظات، مهام، أحداث، صلات، مال) ----------

def record_view(c: Case, r: CaseRecord, docs: dict[int, int]) -> dict:
    return {"id": r.id, "kind": r.kind, "status": r.status, "date": r.at_date.date().isoformat() if r.at_date else None,
            "amount": r.amount, "doc": docs.get(r.doc_id) if r.doc_id else None, "author_id": r.author_id,
            "assignee_id": r.assignee_id, "updated_at": r.updated_at.isoformat(), **(dec(c, r.body_enc, {}) or {})}


def graph(c: Case, links: list[dict], include_suggested: bool = True) -> dict:
    nodes: dict[str, dict] = {}
    edges = []
    for l in links:
        if l["status"] == "rejected" or (l["status"] == "suggested" and not include_suggested):
            continue
        for side in ("a", "b"):
            n = nodes.setdefault(l[f"{side}_norm"], {"id": l[f"{side}_norm"], "name": l[side], "kind": l.get(f"{side}_kind", ""), "degree": 0})
            n["degree"] += 1
        edges.append({"id": l["id"], "a": l["a_norm"], "b": l["b_norm"], "relation": l.get("relation", ""), "status": l["status"],
                      "sources": l.get("sources", [])})
    return {"nodes": sorted(nodes.values(), key=lambda n: -n["degree"]), "edges": edges}


# ---------- العقوبات والأشخاص ذوو النفوذ ----------

def import_sanctions(db: Session, list_name: str, raw: bytes) -> int:
    """يقبل ملف OpenSanctions «targets.simple.csv» أو ملفًا بسيطًا بأعمدة name,aliases,countries,program."""
    import csv

    text = raw.decode("utf-8-sig", "replace")
    rows = csv.DictReader(io.StringIO(text))
    if not rows.fieldnames or "name" not in rows.fieldnames:
        raise CaseError("الملف يحتاج عمود name على الأقل")
    for old in db.scalars(select(SanctionEntry).where(SanctionEntry.list_name == list_name)):
        db.delete(old)
    n = 0
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        aliases = [a.strip() for a in re.split(r"[;|]", r.get("aliases") or "") if a.strip()]
        topics = (r.get("sanctions") or r.get("program") or "")
        db.add(SanctionEntry(list_name=list_name[:100], ext_id=(r.get("id") or "")[:120], schema=(r.get("schema") or "")[:30],
                             name=name[:400], norm=normalize_ar(name)[:400], aliases="|".join(normalize_ar(a) for a in aliases)[:20000],
                             countries=(r.get("countries") or "")[:200], programs=topics[:5000],
                             is_pep="role.pep" in (r.get("topics") or "") or "pep" in list_name.lower()))
        n += 1
    db.flush()
    return n


def _name_match(q: str, cand: str) -> float:
    if not q or not cand:
        return 0.0
    if q == cand:
        return 1.0
    qt, ct = set(q.split()), set(cand.split())
    if len(qt) >= 2 and qt <= ct or len(ct) >= 2 and ct <= qt:
        return 0.92
    return similar(q, cand)


def match_sanctions(db: Session, names: list[str], threshold: float = 0.9) -> list[dict]:
    if not names:
        return []
    out = []
    entries = list(db.scalars(select(SanctionEntry)))
    for name in names:
        q = normalize_ar(name)
        best = []
        for e in entries:
            s = max([_name_match(q, e.norm)] + [_name_match(q, a) for a in e.aliases.split("|") if a])
            if s >= threshold:
                best.append({"name": name, "match": e.name, "list": e.list_name, "score": round(s, 2), "countries": e.countries,
                             "programs": e.programs[:300], "pep": e.is_pep, "ext_id": e.ext_id})
        out += sorted(best, key=lambda x: -x["score"])[:5]
    return out


# ---------- بناء القصة ----------

CITE = re.compile(r"\[(وثيقة|دليل|مادة)\s*(\d+)(?:\s*ص\s*(\d+))?\]")
FACTUAL = re.compile(r"\d|«|\"|" + "|".join(["قال", "أكد", "اكد", "أعلن", "اعلن", "بلغ", "بلغت", "حصل", "حصلت", "وقع", "وقّع", "دفع", "تبين", "تبيّن", "كشف", "كشفت"]))
CHECKLIST = [
    ("sourced", "كل معلومة لها مصدر", "auto"),
    ("right_of_reply", "حق الرد أُرسل للأطراف المذكورة", "manual"),
    ("balance", "عُرضت رواية كل طرف", "manual"),
    ("legal", "مراجعة قانونية", "manual"),
    ("editor", "اعتماد المحرّر", "approve"),
]


def _ref_exists(db: Session, docs: dict, kind: str, num: int) -> bool:
    from marsad.models.claims import Evidence
    from marsad.models.monitoring import Item

    if kind == "وثيقة":
        return num in docs
    if kind == "مادة":
        return db.get(Item, num) is not None
    return db.get(Evidence, num) is not None


def draft_check(db: Session, c: Case, body: str) -> dict:
    """كل جملة فيها معلومة (رقم، اقتباس، فعل إخبار) بلا إحالة إلى دليل تُعلَّم؛ والإحالات إلى أدلة غير موجودة كذلك."""
    docs = {d.number: d for d in db.scalars(select(CaseDocument).where(CaseDocument.case_id == c.id))}
    sentences, unsourced, broken, cited = [], [], [], set()
    for s in _sentences(body):
        refs = CITE.findall(s)
        for kind, num, _page in refs:
            if not _ref_exists(db, docs, kind, int(num)):
                broken.append(f"[{kind} {num}]")
            elif kind == "وثيقة":
                cited.add(int(num))
        needs = bool(FACTUAL.search(CITE.sub("", s)))
        ok = bool(refs) or not needs
        sentences.append({"text": s, "sourced": ok, "needs_source": needs})
        if not ok:
            unsourced.append(s)
    return {"sentences": sentences, "unsourced": unsourced, "broken_refs": sorted(set(broken)), "cited_docs": sorted(cited),
            "all_sourced": not unsourced and not broken and bool(sentences)}


def skeleton(db: Session, c: Case) -> dict:
    """هيكل القصة من القضية: الأطراف المؤكدة، الخط الزمني المؤكد، حركة المال، والأسئلة المفتوحة (المهام غير المنجزة)."""
    docs = {d.id: d.number for d in db.scalars(select(CaseDocument).where(CaseDocument.case_id == c.id))}
    recs = [record_view(c, r, docs) for r in db.scalars(select(CaseRecord).where(CaseRecord.case_id == c.id))]
    links = [r for r in recs if r["kind"] == "link" and r["status"] == "confirmed"]
    parties = sorted({x for l in links for x in (l["a"], l["b"])})
    events = sorted([r for r in recs if r["kind"] == "event" and r["status"] == "confirmed"], key=lambda r: r["date"] or "")
    money = [r for r in recs if r["kind"] == "money" and r["status"] == "confirmed"]
    questions = [r.get("title", "") for r in recs if r["kind"] == "task" and r["status"] != "done"]
    lines = []
    for e in events:
        lines.append(f"في {e['date']}: {e.get('title', '')} [وثيقة {e['doc']}" + (f" ص {e['page']}" if e.get("page") else "") + "]" if e["doc"] else
                     f"في {e['date']}: {e.get('title', '')}")
    for m in money:
        lines.append(f"{m.get('from') or 'طرف'} → {m.get('to') or 'طرف'}: {m['amount']:,.0f} {m.get('currency', '')}" + (f" [وثيقة {m['doc']}]" if m["doc"] else ""))
    return {"parties": parties, "timeline": events, "money": money, "questions": questions, "suggested_body": "\n".join(lines)}


def export_docx(db: Session, c: Case, d: Draft, author: User) -> bytes:
    """مسودة Word باتجاه عربي، وكل إحالة مرتبطة بدليلها في قائمة المصادر: اسم الوثيقة وصفحتها وبصمتها."""
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    content = dec(c, d.body_enc, {}) or {}
    docs = {x.number: x for x in db.scalars(select(CaseDocument).where(CaseDocument.case_id == c.id))}
    out = docx.Document()
    st = out.styles["Normal"]
    st.font.name = "Arial"
    st.font.size = Pt(12)
    st.element.rPr.rFonts.set(qn("w:cs"), "Arial")

    def rtl(p):
        pPr = p._p.get_or_add_pPr()
        b = OxmlElement("w:bidi")
        b.set(qn("w:val"), "1")
        pPr.append(b)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for r in p.runs:
            rPr = r._r.get_or_add_rPr()
            x = OxmlElement("w:rtl")
            x.set(qn("w:val"), "1")
            rPr.append(x)
        return p

    rtl(out.add_heading(d.title or c.title, level=1))
    if content.get("angle"):
        rtl(out.add_paragraph(f"الزاوية: {content['angle']}"))
    check = draft_check(db, c, content.get("body", ""))
    order: list[tuple[str, int, str | None]] = []
    for para in [p for p in content.get("body", "").split("\n") if p.strip()]:
        def num(m):
            key = (m.group(1), int(m.group(2)), m.group(3))
            if key not in order:
                order.append(key)
            return f"[{order.index(key) + 1}]"

        rtl(out.add_paragraph(CITE.sub(num, para)))
    if check["unsourced"]:
        p = rtl(out.add_paragraph(f"تنبيه: {len(check['unsourced'])} جملة فيها معلومة بلا مصدر."))
        p.runs[0].bold = True
    rtl(out.add_heading("المصادر", level=2))
    for n, (kind, number, page) in enumerate(order, 1):
        if kind == "وثيقة" and number in docs:
            x = docs[number]
            line = f"[{n}] وثيقة {number}: {dec(c, x.filename_enc, '')}" + (f"، ص {page}" if page else "") + f" — SHA-256: {x.sha256}"
        else:
            line = f"[{n}] {kind} {number}" + (f"، ص {page}" if page else "")
        rtl(out.add_paragraph(line))
    if content.get("questions"):
        rtl(out.add_heading("أسئلة مفتوحة", level=2))
        for q in content["questions"]:
            rtl(out.add_paragraph(q, style="List Bullet"))
    rtl(out.add_paragraph(f"مسودة داخلية · الإصدار {d.version} · {author.full_name or author.email} · {utcnow().strftime('%Y-%m-%d %H:%M')} UTC"))
    buf = io.BytesIO()
    out.save(buf)
    return buf.getvalue()
