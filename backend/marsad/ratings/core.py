"""حساب مؤشرات تقييم المواقع من موادها المنشورة فعلًا.

القواعد (من المنهجية في الخطة):
1. حد أدنى للعيّنة، وكل نسبة بهامش ثقة (فترة ويلسون 95٪).
2. كل رقم بأمثلته: البسط والمقام قائمتا مواد يمكن فتحها.
3. المؤشرات اللغوية تُراجَع على عيّنة بشرية ويُقاس الاتفاق (كوهين كابا).
4. الأوزان منشورة، وكل تغيير إصدار جديد.
5. المعايير نفسها على كل الجهات.
6. حق الرد: الرد المقبول على مادة يُخرجها من المؤشر الذي اعتُرض فيه.
7. لا نشر علني دون اعتماد بشري ومراجعة قانونية.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.analysis.core import NEGW, POS, story_view
from marsad.db import utcnow
from marsad.models import User
from marsad.models.analysis import Statement
from marsad.models.claims import Claim, ClaimItem
from marsad.models.monitoring import Item, ItemVersion, Outlet
from marsad.models.ratings import Methodology, ReviewLabel, Reply, Score
from marsad.text import normalize_ar

INDICATORS: dict[str, dict] = {
    "accuracy": {"ar": "الدقة", "how": "نسبة المواد التي لم يثبت خطؤها، من موادها التي فُحصت في سجل الادّعاءات بحكم معتمد"},
    "corrections": {"ar": "التصحيح", "how": "نسبة التعديلات المعلنة (بإشارة «تصحيح» أو «تحديث») من كل تعديلات موادها؛ التعديل الصامت يخفض المؤشر"},
    "attribution": {"ar": "الإسناد", "how": "نسبة المواد التي تذكر مصدرها بوضوح؛ والمصادر المجهولة تُعرض منفصلة"},
    "originality": {"ar": "الأصالة", "how": "في القصص التي غطتها أكثر من جهة: نسبة موادها التي ليست نسخًا دون نسبة"},
    "headline": {"ar": "مطابقة العنوان للمتن", "how": "نسبة العناوين التي يرد معظم كلماتها الجوهرية في متن الخبر"},
    "sensational": {"ar": "خلو العناوين من الإثارة", "how": "نسبة العناوين الخالية من التهويل وعبارات «النقر» (شاهد، لن تصدق، صادم...)"},
    "balance": {"ar": "التوازن", "how": "من المواد التي تنقل تصريحات: نسبة ما ينقل عن طرفين أو أكثر"},
    "opinion": {"ar": "الفصل بين الخبر والرأي", "how": "نسبة المواد الخبرية الخالية من كثافة اللغة التقييمية"},
    "transparency": {"ar": "الشفافية", "how": "بنود JTI المعلنة: الملكية، هيئة التحرير، سياسة التصحيح، التواصل، التمويل"},
}
LINGUISTIC = ("headline", "sensational", "opinion")
JTI_ITEMS = {"ownership": "الملكية", "editorial_team": "هيئة التحرير", "corrections_policy": "سياسة التصحيح",
             "contact": "معلومات التواصل", "funding": "مصادر التمويل"}
DEFAULT_WEIGHTS = {"accuracy": 25, "corrections": 10, "attribution": 15, "originality": 10, "headline": 10, "sensational": 10,
                   "balance": 5, "opinion": 5, "transparency": 10}
WRONG = {"مضلل", "مفبرك"}

def _alt(words: str) -> re.Pattern:
    """عبارات مفصولة بـ | تُوحَّد كتابتها كما يُوحَّد النص الذي تُطبَّق عليه."""
    return re.compile("|".join(re.escape(normalize_ar(w)) for w in words.split("|") if normalize_ar(w)))


SENSATIONAL = _alt("شاهد|بالفيديو|لن تصدق|صادم|صدمة|فضيحة|كارثة|عاجل جدا|مفاجأة|بالصور|انظر ماذا|ماذا حدث|السر وراء|لا يفوتك|"
                   "خطير جدا|زلزال|نارية|يهز|تهز|يشعل|تشعل|ضجة|ذهول|رعب|مرعب|صاعقة|قنبلة")
SENSATIONAL_PUNCT = re.compile(r"!{2,}|[?؟]!|![?؟]")
OPINION = set(normalize_ar("للاسف مع_الاسف للأسف وقاحه مهزله مخزي مخزيه مشين فاشل فاشله عبقري رائع مذهل بائس "
                           "المفترض يجب ينبغي نعتقد نرى برايي بلا_شك لا_شك ").replace("_", " ").split()) | POS | NEGW
CORRECTION_MARK = _alt("تصحيح|تنويه|تحديث|تم تعديل|عدل هذا الخبر|استدراك|اعتذار|نعتذر|ورد خطأ")
DENIAL = _alt("لا صحة|غير صحيح|عار عن الصحة|شائعة|شائعات|تنفي|ينفي|نفت|نفى|مضلل|مفبرك|زائف|كاذب")
SPEECH = _alt("قال|قالت|صرح|أكد|أكدت|أوضح|أعلن|أعلنت|بيان|في تصريح|وفقا ل|نقلا عن|بحسب|حسب|ذكرت|أفادت")
ANON = _alt("مصدر مطلع|مصدر مسؤول|مصدر رفيع|مصدر خاص|مصادر مطلعة|مصادر خاصة|مصادر لم تسمها|فضل عدم الكشف عن اسمه")
STOPW = set(normalize_ar("في من على إلى الى عن مع أن ان إن كان التي الذي هذا هذه ذلك ما لا لم لن قد و ثم أو او بعد قبل خلال عند حول بين").split())


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """معامل كوهين كابا لتقييمين ثنائيين على المواد نفسها."""
    n = len(pairs)
    if n < 5:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else round((po - pe) / (1 - pe), 3)


# ---------- المنهجية ----------

def current_methodology(db: Session) -> Methodology:
    m = db.scalars(select(Methodology).order_by(Methodology.version.desc())).first()
    if m is None:
        m = Methodology(version=1, weights=DEFAULT_WEIGHTS, min_sample=30, period_days=90,
                        note="الإصدار الأول: أوزان مقترحة تُعرض على لجنة مراجعة المنهجية قبل اعتماد أي تقييم")
        db.add(m)
        db.flush()
    return m


def new_methodology(db: Session, user: User, weights: dict, min_sample: int, period_days: int, note: str) -> Methodology:
    if set(weights) - set(INDICATORS) or any((not isinstance(v, (int, float))) or v < 0 for v in weights.values()):
        raise ValueError("أوزان غير صحيحة")
    if not note.strip():
        raise ValueError("اكتب سبب تغيير المنهجية؛ يُحفظ مع رقم الإصدار")
    if not (5 <= min_sample <= 1000 and 7 <= period_days <= 730):
        raise ValueError("الحد الأدنى للعيّنة بين 5 و1000، والفترة بين 7 و730 يومًا")
    cur = current_methodology(db)
    m = Methodology(version=cur.version + 1, weights={k: float(weights.get(k, 0)) for k in INDICATORS}, min_sample=min_sample,
                    period_days=period_days, note=note.strip(), created_by=user.id)
    db.add(m)
    db.flush()
    return m


# ---------- التصنيف الآلي لكل مادة ----------

def _words(s: str) -> list[str]:
    return [w for w in normalize_ar(s).split() if len(w) > 2 and w not in STOPW]


def is_sensational(i: Item) -> bool:
    return bool(SENSATIONAL.search(normalize_ar(i.title)) or SENSATIONAL_PUNCT.search(i.title))


def headline_mismatch(i: Item) -> bool | None:
    tw, body = _words(i.title), set(_words(i.text[:6000]))
    if len(tw) < 3 or len(body) < 30:
        return None  # لا متن كافٍ للحكم
    return sum(w in body or any(w[:4] == b[:4] for b in body if len(b) >= 4 and len(w) >= 4) for w in tw) / len(tw) < 0.5


def has_opinion(i: Item) -> bool | None:
    toks = normalize_ar(i.text[:6000]).split()
    if len(toks) < 40:
        return None
    hits = sum(t in OPINION for t in toks) + sum(" ".join(p) in OPINION for p in zip(toks, toks[1:]))
    return hits / len(toks) > 0.02


def has_attribution(i: Item) -> bool:
    return bool(SPEECH.search(normalize_ar(i.text[:6000])))


def is_anonymous(i: Item) -> bool:
    return bool(ANON.search(normalize_ar(i.text)))


def machine_label(i: Item, indicator: str) -> bool | None:
    return {"sensational": lambda: is_sensational(i), "headline": lambda: headline_mismatch(i), "opinion": lambda: has_opinion(i)}[indicator]()


# ---------- الحساب ----------

def _row(i: Item, note: str = "") -> dict:
    return {"item_id": i.id, "title": i.title[:200], "url": i.url, "time": (i.published_at or i.captured_at).isoformat(), "note": note}


def _indicator(key: str, good: list, bad: list, min_sample: int, extra: dict | None = None, cap: int = 50) -> dict:
    n = len(good) + len(bad)
    lo, hi = wilson(len(good), n)
    enough = n >= min_sample
    return {"key": key, "ar": INDICATORS[key]["ar"], "how": INDICATORS[key]["how"], "sample": n, "min_sample": min_sample,
            "enough": enough, "value": round(len(good) / n, 3) if n and enough else None, "ci": [lo, hi] if enough else None,
            "good": len(good), "bad": len(bad), "examples_bad": bad[:cap], "examples_good": good[:cap], **(extra or {})}


def compute(db: Session, outlet: Outlet, end: datetime | None = None, meth: Methodology | None = None, full: bool = False) -> dict:
    """full=True: كل المواد خلف كل رقم دون اختصار (لتتبّع الرقم كاملًا)."""
    cap = 10**9 if full else 50
    meth = meth or current_methodology(db)
    end = end or utcnow()
    start = end - timedelta(days=meth.period_days)
    items = list(db.scalars(select(Item).where(Item.outlet_id == outlet.id, Item.captured_at >= start, Item.captured_at < end)
                            .order_by(Item.captured_at)))
    ids = {i.id for i in items}
    accepted = {(r.item_id, r.indicator) for r in db.scalars(select(Reply).where(Reply.outlet_id == outlet.id, Reply.status == "accepted"))}
    human = {}
    for lab in db.scalars(select(ReviewLabel).where(ReviewLabel.item_id.in_(ids))) if ids else []:
        human.setdefault((lab.item_id, lab.indicator), []).append(lab.value)

    def excluded(i: Item, key: str) -> bool:
        return (i.id, key) in accepted or (i.id, "") in accepted

    out: dict[str, dict] = {}
    ms = meth.min_sample

    # الدقة: المواد التي ظهرت في ادّعاء بحكم معتمد (والمادة تنقله لا تنفيه)
    good, bad = [], []
    if ids:
        rows = db.execute(select(ClaimItem.item_id, Claim.id).join(Claim, Claim.id == ClaimItem.claim_id).where(ClaimItem.item_id.in_(ids))).all()
        claims = {c.id: c for c in db.scalars(select(Claim).where(Claim.id.in_({r[1] for r in rows})))} if rows else {}
        by_item = {i.id: i for i in items}
        seen = set()
        for item_id, cid in rows:
            from marsad.claims.core import current_verdict

            v = current_verdict(claims[cid])
            i = by_item[item_id]
            if not v or v.status != "approved" or item_id in seen or excluded(i, "accuracy"):
                continue
            if v.label in WRONG and DENIAL.search(normalize_ar(f"{i.title} {i.text[:3000]}")):
                continue  # مادة تنفي الشائعة لا تنشرها
            seen.add(item_id)
            (bad if v.label in WRONG else good).append(_row(i, f"الادّعاء #{cid}: {v.label}"))
    out["accuracy"] = _indicator("accuracy", good, bad, ms, cap=cap)

    # التصحيح: كل تعديل أو حذف، معلن أم صامت
    good, bad = [], []
    if ids:
        for v in db.scalars(select(ItemVersion).where(ItemVersion.item_id.in_(ids), ItemVersion.change.in_(("edit", "delete")))
                            .order_by(ItemVersion.captured_at)):
            i = next(x for x in items if x.id == v.item_id)
            if excluded(i, "corrections"):
                continue
            if v.change == "delete":
                bad.append(_row(i, "حُذفت المادة دون إشارة"))
            elif CORRECTION_MARK.search(normalize_ar(f"{v.title} {v.text[:4000]}")):
                good.append(_row(i, f"تعديل معلن (الإصدار {v.version})"))
            else:
                bad.append(_row(i, f"تعديل صامت (الإصدار {v.version})"))
    out["corrections"] = _indicator("corrections", good, bad, max(5, ms // 3), cap=cap)

    # الإسناد والمصادر المجهولة
    texted = [i for i in items if len(i.text) > 200 and not excluded(i, "attribution")]
    good = [_row(i) for i in texted if has_attribution(i)]
    bad = [_row(i, "لا مصدر واضح") for i in texted if not has_attribution(i)]
    anon = [_row(i, "مصدر مجهول") for i in texted if is_anonymous(i)]
    out["attribution"] = _indicator("attribution", good, bad, ms, {"anonymous": len(anon), "examples_anonymous": anon[:cap],
                                                                   "anonymous_share": round(len(anon) / len(texted), 3) if texted else None}, cap=cap)

    # الأصالة: من علاقات القصص متعددة الجهات
    good, bad, first = [], [], 0
    stories = {i.story_id for i in items if i.story_id}
    from marsad.models.analysis import Story

    for sid in stories:
        st = db.get(Story, sid)
        if st is None or st.source_count < 2:
            continue
        view = story_view(db, st)
        if view["first"] and view["first"]["item_id"] in ids:
            first += 1
            i = next(x for x in items if x.id == view["first"]["item_id"])
            if not excluded(i, "originality"):
                good.append(_row(i, "نشرتها أولًا"))
        for r in view["relations"]:
            if r["item_id"] not in ids:
                continue
            i = next(x for x in items if x.id == r["item_id"])
            if excluded(i, "originality") or r["kind"] == "من الموقع نفسه":
                continue
            (bad if r["kind"] == "نسخ دون نسبة" else good).append(_row(i, r["kind"] + (f" عن {r['from_outlet']}" if r.get("from_outlet") else "")))
    out["originality"] = _indicator("originality", good, bad, max(5, ms // 3), {"first_count": first}, cap=cap)

    # المؤشرات اللغوية: حكم بشري إن وُجد (الأغلبية) يتقدّم على الآلة
    for key in LINGUISTIC:
        good, bad, agree = [], [], []
        for i in items:
            if excluded(i, key):
                continue
            m = machine_label(i, key)
            if m is None:
                continue
            h = human.get((i.id, key))
            final = (sum(h) * 2 > len(h)) if h else m
            if h:
                agree.append((m, sum(h) * 2 > len(h)))
            note = {"sensational": "عنوان مثير", "headline": "العنوان لا يطابق المتن", "opinion": "لغة تقييمية كثيفة"}[key]
            (bad if final else good).append(_row(i, (note if final else "") + (" (بمراجعة بشرية)" if h else "")))
        out[key] = _indicator(key, good, bad, ms, {"reviewed": len(agree), "kappa_machine_human": kappa(agree)}, cap=cap)

    # التوازن: من المواد التي تنقل تصريحات، هل تنقل عن طرفين أو أكثر
    good, bad = [], []
    if ids:
        speakers: dict[int, set] = {}
        for s in db.scalars(select(Statement).where(Statement.item_id.in_(ids))):
            speakers.setdefault(s.item_id, set()).add(s.entity_id)
        for i in items:
            if i.id in speakers and not excluded(i, "balance"):
                (good if len(speakers[i.id]) >= 2 else bad).append(_row(i, f"{len(speakers[i.id])} طرف"))
    out["balance"] = _indicator("balance", good, bad, max(5, ms // 3), cap=cap)

    # الشفافية: بنود معلنة، لا عيّنة
    t = outlet.transparency or {}
    declared = [k for k in JTI_ITEMS if str(t.get(k, "")).strip()]
    out["transparency"] = {"key": "transparency", "ar": INDICATORS["transparency"]["ar"], "how": INDICATORS["transparency"]["how"],
                           "sample": len(JTI_ITEMS), "min_sample": 0, "enough": True, "value": round(len(declared) / len(JTI_ITEMS), 3),
                           "ci": None, "good": len(declared), "bad": len(JTI_ITEMS) - len(declared),
                           "items": [{"key": k, "ar": v, "declared": k in declared, "detail": str(t.get(k, ""))[:300]} for k, v in JTI_ITEMS.items()],
                           "examples_bad": [], "examples_good": []}

    weights = meth.weights or DEFAULT_WEIGHTS
    used = {k: weights.get(k, 0) for k, v in out.items() if v["value"] is not None and weights.get(k, 0) > 0}
    composite = None
    if len(used) >= 4 and sum(used.values()) > 0:
        composite = round(100 * sum(out[k]["value"] * w for k, w in used.items()) / sum(used.values()))
    return {"outlet": {"id": outlet.id, "name": outlet.name, "kind": outlet.kind, "website": outlet.website},
            "period": {"start": start.isoformat(), "end": end.isoformat(), "days": meth.period_days}, "items": len(items),
            "methodology_version": meth.version, "indicators": out, "composite": composite,
            "composite_basis": sorted(used), "missing": sorted(k for k, v in out.items() if v["value"] is None)}


def evolution(db: Session, outlet: Outlet, months: int = 6) -> list[dict]:
    meth = current_methodology(db)
    end = utcnow()
    rows = []
    for k in range(months - 1, -1, -1):
        e = end - timedelta(days=30 * k)
        r = compute(db, outlet, e, meth)
        rows.append({"end": e.isoformat(), "composite": r["composite"],
                     "values": {key: v["value"] for key, v in r["indicators"].items()}})
    return rows


def snapshot(db: Session, outlet: Outlet) -> Score:
    r = compute(db, outlet)
    s = Score(outlet_id=outlet.id, methodology_version=r["methodology_version"], period_start=datetime.fromisoformat(r["period"]["start"]),
              period_end=datetime.fromisoformat(r["period"]["end"]), composite=r["composite"],
              indicators={k: {x: v[x] for x in ("value", "ci", "sample", "good", "bad")} for k, v in r["indicators"].items()})
    db.add(s)
    db.flush()
    return s


def review_queue(db: Session, indicator: str, user: User, limit: int = 20) -> list[dict]:
    """عيّنة للمراجعة البشرية: مواد لها حكم آلي ولم يراجعها هذا المستخدم، موزعة على الجهات بالتساوي."""
    done = set(db.scalars(select(ReviewLabel.item_id).where(ReviewLabel.indicator == indicator, ReviewLabel.user_id == user.id)))
    since = utcnow() - timedelta(days=90)
    per_outlet: dict[int, list] = {}
    for i in db.scalars(select(Item).where(Item.captured_at >= since).order_by(Item.id.desc()).limit(3000)):
        if i.id in done:
            continue
        m = machine_label(i, indicator)
        if m is None:
            continue
        per_outlet.setdefault(i.outlet_id, []).append((i, m))
    out = []
    while len(out) < limit and any(per_outlet.values()):
        for oid in list(per_outlet):
            if per_outlet[oid] and len(out) < limit:
                i, _m = per_outlet[oid].pop(0)
                out.append({"item_id": i.id, "title": i.title, "text": i.text[:1500], "url": i.url})
    return out  # الحكم الآلي لا يُعرض للمراجع كي لا يتأثر به
