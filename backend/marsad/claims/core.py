"""الشائعات: سجل الادّعاءات والأحكام، عودة شائعة مكشوفة، الرادار، شجرة الانتشار، ClaimReview."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.analysis.core import _stem, _tokens, cosine, signature
from marsad.audit import record
from marsad.db import utcnow
from marsad.engines.prompts import EVIDENCE_GRADES, VERDICT_LABELS
from marsad.models import User
from marsad.models.claims import Claim, ClaimItem, Evidence, Verdict
from marsad.models.engines import Notification
from marsad.models.monitoring import Item, Outlet
from marsad.rbac.service import PermissionError_, check_can_approve, has_permission
from marsad.text import normalize_ar, similar

# معايَرة على tests/gold/rumors.json: كل إعادة صياغة ≥ 0.385، وأقرب خبر غير متعلق 0.337
RETURN_ALERT = 0.36
RETURN_SUGGEST = 0.28
DEBUNKED = {"مضلل", "مفبرك", "صحيح جزئيًا"}
RUMOR_MARKERS = re.compile(r"(متداول|يتداول|تداول|انتشر|ينتشر|شاهد|عاجل|صوره متداوله|فيديو متداول|حقيقه|شائعه|اشاعه|نفي|ينفي)")


class ClaimError(Exception):
    pass


def claim_sig(c: Claim) -> dict:
    sig = (c.meta or {}).get("sig")
    if not sig:
        sig = signature(c.text, "")
        c.meta = {**(c.meta or {}), "sig": sig}
    return sig


def current_verdict(c: Claim, approved_only: bool = False) -> Verdict | None:
    vs = [v for v in c.verdicts if v.status == "approved" or (not approved_only and v.status == "proposed")]
    return vs[-1] if vs else None


# ---------- إنشاء الادّعاء وظهوره ----------

def create_claim(db: Session, user: User | None, text: str, item: Item | None = None, speaker: str = "",
                 origin: str = "manual", tags: list[str] | None = None) -> Claim:
    text = " ".join(text.split())
    if len(text) < 10:
        raise ClaimError("نص الادّعاء قصير جدًا")
    c = Claim(text=text, norm=normalize_ar(text), speaker=speaker, origin=origin, tags=tags or [],
              created_by=user.id if user else None, first_item_id=item.id if item else None,
              first_seen_at=(item.published_at or item.captured_at) if item else utcnow(),
              story_id=item.story_id if item else None)
    db.add(c)
    db.flush()
    claim_sig(c)
    if item:
        db.add(ClaimItem(claim_id=c.id, item_id=item.id, kind="first", score=1.0))
    record(db, user, "claim.create", "claim", str(c.id), None, {"text": text, "origin": origin})
    db.flush()
    return c


def add_appearance(db: Session, c: Claim, item: Item, score: float, kind: str = "appearance") -> ClaimItem | None:
    if db.scalar(select(ClaimItem.id).where(ClaimItem.claim_id == c.id, ClaimItem.item_id == item.id)):
        return None
    ci = ClaimItem(claim_id=c.id, item_id=item.id, score=round(score, 3), kind=kind)
    db.add(ci)
    t = item.published_at or item.captured_at
    if c.first_seen_at is None or (t and t < c.first_seen_at):
        c.first_seen_at, c.first_item_id = t, item.id
    db.flush()
    return ci


def match_item(db: Session, item: Item) -> list[dict]:
    """يقارن مادة جديدة بالادّعاءات المسجّلة. عودة شائعة مكشوفة = تنبيه فوري برابط التحقق السابق."""
    sig = signature(item.title, item.text)
    out = []
    for c in db.scalars(select(Claim).where(Claim.status != "archived")):
        s = cosine(sig, claim_sig(c))
        if s < RETURN_SUGGEST:
            continue
        v = current_verdict(c, approved_only=True)
        debunked = bool(v and v.label in DEBUNKED)
        level = "alert" if s >= RETURN_ALERT else "suggest"
        kind = "return" if debunked else "appearance"
        if level == "alert":
            ci = add_appearance(db, c, item, s, kind)
            if ci and debunked:
                db.add(Notification(kind="rumor.return", text=f"عادت شائعة مكشوفة ({v.label}): «{c.text[:120]}» — في «{item.title[:120]}». "
                                                               f"التحقق السابق: /claims/{c.id}"))
        else:
            c.meta = {**(c.meta or {}), "suggestions": sorted({*(c.meta or {}).get("suggestions", []), item.id})[-50:]}
        out.append({"claim_id": c.id, "score": round(s, 3), "level": level, "debunked": debunked})
    return out


def auto_extract(db: Session, item: Item) -> list[Claim]:
    """ادّعاءات تلقائية من مواد مواقع التواصل والمواد التي تحمل علامات الشائعة (متداول، شاهد...).
    الاستخراج الكامل لأي مادة يتم بالمحركات من بطاقة الادّعاء أو شاشة المحركات."""
    if match_item(db, item):  # كل مادة تُقارن بالسجل: ظهور ادّعاء معروف أو عودة شائعة مكشوفة
        return []
    src_kind = item.source.kind if item.source else ""
    text = f"{item.title}. {item.text}"
    if src_kind not in ("telegram", "social") and not RUMOR_MARKERS.search(normalize_ar(text[:600])):
        return []
    first = re.split(r"(?<=[.!؟?])\s+|\n", (item.title or item.text).strip())[0][:400]
    if len(first) < 15 or not (re.search(r"\d", first) or re.search(r"(صوره|فيديو|قرار|اعلن|تعلن|وفاه|مقتل|اغلاق|تعطيل|رفع|خفض)", normalize_ar(first))):
        return []
    return [create_claim(db, None, first, item, origin="auto")]


# ---------- الأحكام ----------

def propose_verdict(db: Session, user: User, c: Claim, label: str, grade: str, explanation: str,
                    engine_batch_id: int | None = None, correction_reason: str = "") -> Verdict:
    if not has_permission(user, "verdicts.propose"):
        raise PermissionError_("لا تملك صلاحية اقتراح حكم")
    if label not in VERDICT_LABELS or grade not in EVIDENCE_GRADES:
        raise ClaimError("الحكم أو درجة الدليل غير معروفين")
    if grade == "قاطع" and not any(e.is_conclusive or e.grade == "قاطع" for e in c.evidence):
        raise ClaimError("لا حكم بدرجة «قاطع» دون دليل قاطع مرفق (مثل توقيع C2PA أو نسخة أصلية أقدم)")
    if len(explanation.strip()) < 10:
        raise ClaimError("اكتب شرحًا للحكم")
    before = current_verdict(c)
    if current_verdict(c, approved_only=True) is not None and len(correction_reason.strip()) < 5:
        raise ClaimError("لهذا الادّعاء حكم معتمد؛ تعديله تصحيح يُسجَّل علنًا، فاكتب سبب التصحيح")
    v = Verdict(claim_id=c.id, label=label, evidence_grade=grade, explanation=explanation.strip(),
                author_id=user.id, engine_batch_id=engine_batch_id)
    if correction_reason.strip():
        c.meta = {**(c.meta or {}), "pending_correction": {"verdict_id": None, "reason": correction_reason.strip()}}
    db.add(v)
    c.status = "proposed"
    db.flush()
    if correction_reason.strip():
        c.meta = {**(c.meta or {}), "pending_correction": {"verdict_id": v.id, "reason": correction_reason.strip()}}
    record(db, user, "verdict.propose", "claim", str(c.id),
           None if before is None else {"label": before.label, "grade": before.evidence_grade, "status": before.status},
           {"label": label, "grade": grade, "verdict_id": v.id})
    return v


def approve_verdict(db: Session, user: User, c: Claim, approve: bool = True, note: str = "") -> Verdict:
    v = current_verdict(c)
    if v is None or v.status != "proposed":
        raise ClaimError("لا يوجد حكم مقترح بانتظار الاعتماد")
    check_can_approve(db, user, v.author_id, "verdicts.approve")
    from marsad.org import workflow

    if approve and workflow.in_workflow(c) and v.author_id is not None and v.author_id == user.id:
        raise PermissionError_("هذا الادّعاء في سير العمل التحريري: يعتمده مراجع ثانٍ غير كاتب الحكم")
    previous = current_verdict(c, approved_only=True)
    v.status = "approved" if approve else "rejected"
    v.approved_by, v.approved_at = user.id, utcnow()
    c.status = "verdict" if approve else "investigating"
    record(db, user, "verdict.approve" if approve else "verdict.reject", "claim", str(c.id),
           {"status": "proposed"}, {"status": v.status, "verdict_id": v.id, "note": note})
    pending = (c.meta or {}).get("pending_correction") or {}
    if pending.get("verdict_id") == v.id:
        c.meta = {k: val for k, val in (c.meta or {}).items() if k != "pending_correction"}
    if approve:
        from marsad.org import corrections, public_api

        if previous is not None and previous.id != v.id:
            corrections.record_correction(db, c, previous, v, pending.get("reason", "") if pending.get("verdict_id") == v.id else "", user.id)
            event = "verdict.corrected"
        else:
            event = "verdict.approved"
        public_api.emit(db, event, verdict_payload(c, v, previous if event == "verdict.corrected" else None))
    return v


def verdict_payload(c: Claim, v: Verdict, previous: Verdict | None = None) -> dict:
    """الحكم كما يراه نظام خارجي (Webhook والواجهة البرمجية): دون أسماء الصحفيين."""
    out = {"claim_id": c.id, "claim": c.text, "speaker": c.speaker, "label": v.label, "evidence_grade": v.evidence_grade,
           "explanation": v.explanation, "approved_at": v.approved_at.isoformat() if v.approved_at else None,
           "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else None}
    if previous is not None:
        out["previous"] = {"label": previous.label, "evidence_grade": previous.evidence_grade}
    return out


# ---------- شجرة الانتشار ----------

def spread_tree(db: Session, c: Claim) -> dict:
    rows = db.execute(select(ClaimItem, Item, Outlet).join(Item, Item.id == ClaimItem.item_id)
                      .join(Outlet, Outlet.id == Item.outlet_id).where(ClaimItem.claim_id == c.id)).all()
    nodes = sorted(rows, key=lambda r: r[1].published_at or r[1].captured_at)
    out = []
    for k, (ci, it, o) in enumerate(nodes):
        parent = None
        if k:
            earlier = nodes[:k]
            # الأب: أقرب سابق بالنص؛ مع تيليغرام يُفضَّل منشور سابق يذكره بالاسم
            named = [e for e in earlier if normalize_ar(e[2].name) in normalize_ar(it.text)]
            parent = (named or [max(earlier, key=lambda e: similar(e[1].text[:1500], it.text[:1500]))])[0][1].id
        out.append({"item_id": it.id, "parent_item_id": parent, "title": it.title, "outlet": o.name, "url": it.url,
                    "time": (it.published_at or it.captured_at).isoformat(), "kind": ci.kind, "score": ci.score,
                    "source_kind": it.source.kind})
    coordinated = coordination(out)
    return {"nodes": out, "coordination": coordinated}


def coordination(nodes: list[dict], window_min: int = 30, min_sources: int = 3) -> list[dict]:
    """مؤشر حملة منسّقة: 3 مصادر مختلفة أو أكثر تنشر النص نفسه تقريبًا خلال 30 دقيقة. مؤشر لا حكم."""
    out = []
    times = [(datetime.fromisoformat(n["time"]), n) for n in nodes]
    for i, (t0, n0) in enumerate(times):
        group = [n for t, n in times[i:] if t - t0 <= timedelta(minutes=window_min)]
        outlets = {n["outlet"] for n in group}
        if len(outlets) >= min_sources and not any(set(x["outlets"]) >= outlets for x in out):
            out.append({"start": t0.isoformat(), "outlets": sorted(outlets), "count": len(group),
                        "note": f"{len(outlets)} مصادر خلال {window_min} دقيقة"})
    return out


# ---------- الرادار ----------

def radar(db: Session, hours: int = 3, baseline_days: int = 7, top: int = 15, now: datetime | None = None) -> list[dict]:
    """المواضيع التي تتصاعد فجأة: تكرار الكلمة في آخر ساعات مقارنة بمعدلها في الأيام السابقة."""
    now = now or utcnow()
    recent_from, base_from = now - timedelta(hours=hours), now - timedelta(days=baseline_days)
    recent, base = Counter(), Counter()
    samples: dict[str, list[int]] = {}
    for it in db.scalars(select(Item).where(Item.captured_at >= base_from)):
        terms = {_stem(t) for t in _tokens(it.title) if len(t) > 2}
        toks = [_stem(t) for t in _tokens(it.title)]
        terms |= {f"{a} {b}" for a, b in zip(toks, toks[1:])}
        bucket = recent if it.captured_at >= recent_from else base
        for t in terms:
            bucket[t] += 1
            if bucket is recent:
                samples.setdefault(t, []).append(it.id)
    base_hours = max(1.0, (recent_from - base_from).total_seconds() / 3600)
    out = []
    for term, n in recent.items():
        if n < 3:
            continue
        expected = base[term] / base_hours * hours
        score = (n - expected) / math.sqrt(expected + 1)
        if score >= 2:
            out.append({"term": term, "count": n, "expected": round(expected, 2), "score": round(score, 2),
                        "items": samples[term][:10]})
    out.sort(key=lambda x: (-x["score"], -len(x["term"]), x["term"]))  # ترتيب ثابت عند التعادل
    # إزالة الكلمة المفردة إن ظهرت ضمن ثنائية أعلى منها
    final = []
    for x in out:
        if not any(x["term"] in y["term"] and x["term"] != y["term"] and y["count"] >= x["count"] * 0.8 for y in final):
            final.append(x)
    return final[:top]


# ---------- ClaimReview ----------

RATING = {"صحيح": 5, "صحيح جزئيًا": 3, "مضلل": 2, "مفبرك": 1}


def claimreview(db: Session, c: Claim, base_url: str, org_name: str) -> dict | None:
    v = current_verdict(c, approved_only=True)
    if v is None:
        return None
    apps = db.execute(select(Item).join(ClaimItem, ClaimItem.item_id == Item.id).where(ClaimItem.claim_id == c.id)).scalars().all()
    rating = {"@type": "Rating", "alternateName": v.label, "bestRating": 5, "worstRating": 1}
    if v.label in RATING:
        rating["ratingValue"] = RATING[v.label]
    return {
        "@context": "https://schema.org", "@type": "ClaimReview",
        "url": f"{base_url.rstrip('/')}/claims/{c.id}", "datePublished": v.approved_at.date().isoformat(),
        "claimReviewed": c.text,
        "author": {"@type": "Organization", "name": org_name},
        "reviewRating": rating,
        "itemReviewed": {"@type": "Claim", "datePublished": c.first_seen_at.date().isoformat() if c.first_seen_at else None,
                         **({"author": {"@type": "Person", "name": c.speaker}} if c.speaker else {}),
                         "appearance": [{"@type": "CreativeWork", "url": i.url} for i in apps]},
        "description": v.explanation,
        "inLanguage": "ar",
    }


def official_suggestions(db: Session, c: Claim, limit: int = 5) -> list[dict]:
    """بيانات رسمية محتملة تنفي الادّعاء أو تؤكده: مواد من جهات رسمية أو مؤسسات، قريبة من النص."""
    sig = claim_sig(c)
    out = []
    q = select(Item, Outlet).join(Outlet, Outlet.id == Item.outlet_id).where(Outlet.kind.in_(["official", "institution"]))
    if c.first_seen_at:
        q = q.where(Item.captured_at >= c.first_seen_at - timedelta(days=3))
    for it, o in db.execute(q.limit(2000)).all():
        s = cosine(sig, signature(it.title, it.text))
        if s >= 0.2:
            neg = bool(re.search(r"(نفي|تنفي|ينفي|غير صحيح|عار عن الصحه|لا صحه|شائعه|اشاعه)", normalize_ar(f"{it.title} {it.text[:800]}")))
            out.append({"item_id": it.id, "title": it.title, "outlet": o.name, "score": round(s, 3), "denial": neg, "url": it.url})
    return sorted(out, key=lambda x: (-x["denial"], -x["score"]))[:limit]
