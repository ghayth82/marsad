"""التحليل والربط: تجميع القصص، أول ناشر، النقل والنسخ، مقارنة الروايات، الكيانات والتصريحات والتناقض والنبرة.

طرق خفيفة تعمل دون إنترنت ودون نماذج: بصمات من مقاطع حروف متداخلة على النص العربي الموحّد
(تلتقط إعادة الصياغة واختلاف الصرف)، وقواعد للكيانات والتصريحات. كل نتيجة اقتراح يراجعه الصحفي،
ويستطيع نقل مادة بين القصص أو دمج قصتين أو فصلهما، فيُقفل التعديل اليدوي أمام التجميع الآلي.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.db import utcnow
from marsad.models.analysis import Entity, EntityMention, Statement, Story
from marsad.models.monitoring import Item, Outlet
from marsad.text import normalize_ar, similar

WINDOW = timedelta(hours=72)
STORY_THRESHOLD = 0.20  # معايَر على العيّنة الذهبية (tests/gold/stories.json): النطاق الآمن 0.18–0.22
COPY_THRESHOLD = 0.80

# كلمات شائعة لا تميّز الحدث
STOP = set(normalize_ar("""في من على إلى الى عن مع أن ان إن كان كانت التي الذي الذين هذا هذه ذلك تلك ما لا لم لن قد
و أو ثم كما بعد قبل حيث عند خلال بين أي كل غير اليوم أمس وقال قال وقالت قالت وأضاف أضاف وأكد أكد وأشار أشار
حول بشأن ضمن مثل منذ حتى إلا لكن بل هو هي هم نحن أنه أنها له لها لهم به بها فيه فيها عليه عليها""").split())


# ---------- البصمات والتشابه ----------

def _tokens(text: str) -> list[str]:
    return [t for t in normalize_ar(text).split() if t not in STOP and len(t) > 1]


def _stem(t: str) -> str:
    """تجريد خفيف: أداة التعريف وحروف العطف والجر الملتصقة واللواحق الشائعة."""
    for p in ("وبال", "فال", "بال", "كال", "وال", "لل", "ال"):
        if t.startswith(p) and len(t) - len(p) >= 3:
            t = t[len(p):]
            break
    if len(t) > 4 and t[0] in "وفب":
        t = t[1:]
    for s in ("ات", "ون", "ين", "ها", "هم", "يه", "ه", "ي"):
        if t.endswith(s) and len(t) - len(s) >= 3:
            t = t[: -len(s)]
            break
    return t


def signature(title: str, text: str, top: int = 300) -> dict[str, float]:
    """بصمة مختصرة: كلمات مجردة + مقاطع حروف (3-4) من العنوان والمطلع، بأوزان العنوان أعلى."""
    feats: Counter = Counter()
    lead = " ".join(text.split()[:90])
    for part, w in ((title, 3.0), (lead, 1.0)):
        toks = [_stem(t) for t in _tokens(part)]
        for t in toks:
            feats["w:" + t] += 2 * w
            g = f"#{t}#"
            for n in (3, 4):
                for i in range(len(g) - n + 1):
                    feats[f"c:{g[i:i + n]}"] += 0.5 * w
        for a, b in zip(toks, toks[1:]):
            feats[f"b:{a} {b}"] += w
        for num in re.findall(r"\d+(?:[.,]\d+)?", normalize_ar(part)):
            feats["n:" + num] += 5 * w  # الأرقام أقوى دليل على أن المادتين عن الحدث نفسه
    items = feats.most_common(top)
    norm = math.sqrt(sum(v * v for _, v in items)) or 1.0
    return {k: round(v / norm, 5) for k, v in items}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def item_signature(i: Item) -> dict[str, float]:
    sig = (i.meta or {}).get("sig")
    if not sig:
        sig = signature(i.title, i.text)
        i.meta = {**(i.meta or {}), "sig": sig}
    return sig


# ---------- تجميع القصص ----------

def _refresh_story(db: Session, story: Story) -> None:
    items = list(db.scalars(select(Item).where(Item.story_id == story.id)))
    story.item_count = len(items)
    story.source_count = len({i.source_id for i in items})
    if items:
        first = min(items, key=lambda x: first_time(x)[0])
        story.first_item_id = first.id
        story.title = first.title
        story.updated_at = max(i.captured_at for i in items)


def assign_story(db: Session, item: Item) -> Story:
    """يضم المادة إلى أقرب قصة في آخر 72 ساعة، أو ينشئ قصة جديدة."""
    sig = item_signature(item)
    since = (item.published_at or item.captured_at or utcnow()) - WINDOW
    best, best_s = None, 0.0
    for other in db.scalars(select(Item).where(Item.story_id.is_not(None), Item.id != (item.id or -1),
                                               Item.captured_at >= since)):
        s = cosine(sig, item_signature(other))
        if s > best_s:
            best, best_s = other, s
    if best is not None and best_s >= STORY_THRESHOLD:
        story = db.get(Story, best.story_id)
    else:
        story = Story(title=item.title, created_at=item.captured_at or utcnow())
        db.add(story)
        db.flush()
    item.story_id = story.id
    item.meta = {**(item.meta or {}), "story_score": round(best_s, 3)}
    db.flush()
    _refresh_story(db, story)
    return story


def move_item(db: Session, item: Item, story_id: int | None) -> Story:
    """قرار الصحفي: نقل مادة إلى قصة أخرى، أو إلى قصة جديدة (story_id = None)."""
    old = db.get(Story, item.story_id) if item.story_id else None
    if story_id is None:
        target = Story(title=item.title, created_at=item.captured_at, locked=True)
        db.add(target)
        db.flush()
    else:
        target = db.get(Story, story_id)
        target.locked = True
    item.story_id = target.id
    db.flush()
    _refresh_story(db, target)
    if old:
        old.locked = True
        _refresh_story(db, old)
    return target


def merge_stories(db: Session, keep: Story, other: Story) -> Story:
    for i in db.scalars(select(Item).where(Item.story_id == other.id)):
        i.story_id = keep.id
    db.flush()
    keep.locked = True
    _refresh_story(db, keep)
    _refresh_story(db, other)
    return keep


# ---------- أول ناشر، والنقل والنسخ ----------

def first_time(i: Item) -> tuple[datetime, str]:
    """أبكر وقت موثوق للمادة: المعلن إن لم يتجاوز وقت رصدنا، وإلا وقت الرصد."""
    if i.published_at and i.published_at <= (i.captured_at + timedelta(minutes=5)):
        return i.published_at, "وقت النشر المعلن"
    return i.captured_at, "وقت رصدنا لها"


ATTRIB = re.compile(r"(نقلا عن|نقلًا عن|وفقا ل|وفقًا ل|حسب|بحسب|ذكرت|ذكر موقع|اوردت|أوردت|افادت|أفادت|قالت صحيفه|قالت وكاله|عن وكاله)", re.I)


def story_view(db: Session, story: Story) -> dict:
    items = sorted(db.scalars(select(Item).where(Item.story_id == story.id)), key=lambda x: first_time(x)[0])
    outlets = {o.id: o for o in db.scalars(select(Outlet).where(Outlet.id.in_({i.outlet_id for i in items})))}
    timeline, rel = [], []
    for idx, i in enumerate(items):
        t, basis = first_time(i)
        timeline.append({"item_id": i.id, "title": i.title, "outlet": outlets[i.outlet_id].name, "url": i.url,
                         "time": t.isoformat(), "basis": basis, "published_at": i.published_at.isoformat() if i.published_at else None,
                         "captured_at": i.captured_at.isoformat(), "archive_sha256": i.versions[0].archive_sha256 if i.versions else "",
                         "status": i.status})
        if idx == 0:
            continue
        norm = normalize_ar(i.text)
        own = [e for e in items[:idx] if e.outlet_id == i.outlet_id]
        earlier = [e for e in items[:idx] if e.outlet_id != i.outlet_id]  # النسخ بين مواقع مختلفة فقط
        own_update = any(similar(e.text[:3000], i.text[:3000]) >= 0.5 for e in own if e.text and i.text)
        if not earlier or own_update:  # تحديث الموقع لخبره ليس نسخًا عن غيره
            rel.append({"item_id": i.id, "outlet": outlets[i.outlet_id].name, "kind": "من الموقع نفسه",
                        "from_item_id": None, "from_outlet": None, "similarity": 0.0, "adds": []})
            continue
        named = [e for e in earlier if normalize_ar(outlets[e.outlet_id].name) in norm]
        best = max(earlier, key=lambda e: similar(e.text[:3000], i.text[:3000]) if e.text and i.text else 0)
        sim = similar(best.text[:3000], i.text[:3000]) if best.text and i.text else 0.0
        if named:
            kind, src = "نقل مع نسبة", named[0]
        elif sim >= COPY_THRESHOLD:
            kind, src = "نسخ دون نسبة", best
        elif ATTRIB.search(norm):
            kind, src = "ينسب لمصدر آخر", None
        else:
            kind, src = "تغطية خاصة", None
        new_sents = _novel_sentences(i.text, " ".join(e.text for e in earlier))
        rel.append({"item_id": i.id, "outlet": outlets[i.outlet_id].name, "kind": kind,
                    "from_item_id": src.id if src else None, "from_outlet": outlets[src.outlet_id].name if src else None,
                    "similarity": round(sim, 2), "adds": new_sents[:3]})
    return {"story": {"id": story.id, "title": story.title, "item_count": story.item_count, "source_count": story.source_count,
                      "locked": story.locked, "updated_at": story.updated_at.isoformat()},
            "first": timeline[0] if timeline else None, "timeline": timeline, "relations": rel,
            "comparison": compare_narratives(items, outlets)}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!؟?])\s+|\n+", text) if len(s.strip()) > 25]


def _novel_sentences(text: str, before: str) -> list[str]:
    nb = normalize_ar(before)
    out = []
    for s in _sentences(text):
        toks = [t for t in _tokens(s) if len(t) > 2]
        if toks and sum(t in nb for t in toks) / len(toks) < 0.5:
            out.append(s)
    return out


# ---------- مقارنة الروايات ----------

NUM = re.compile(r"(\d+(?:[.,]\d+)?)\s*(%|٪|بالمئه|بالمئة|دينار|دولار|شخصا|شخص|قتيلا|قتيل|مصابا|اصابه|جريحا|طن|لتر|مليون|مليار|الف|ألف)?")


def _numbers(text: str) -> list[dict]:
    out = []
    norm = normalize_ar(text)
    for m in NUM.finditer(norm):
        val = m.group(1)
        if len(val) == 4 and val.startswith(("19", "20")):  # سنوات
            continue
        ctx = norm[max(0, m.start() - 30):m.start()].split()[-3:]
        unit = m.group(2) or ""
        if not unit:  # الوحدة = الكلمة التالية للرقم («3 اشخاص»، «25 فلسا»)
            nxt = norm[m.end():m.end() + 30].split()
            unit = _stem(nxt[0]) if nxt and not nxt[0].isdigit() and nxt[0] not in STOP else ""
        out.append({"value": val, "unit": unit, "context": " ".join(ctx)})
    return out


def compare_narratives(items: list[Item], outlets: dict[int, Outlet]) -> dict:
    """المتفق عليه والمختلف فيه: الأرقام والأسماء والمصادر المنسوب إليها."""
    by_unit: dict[str, dict[str, set[str]]] = {}
    for i in items:
        for n in _numbers(f"{i.title}. {i.text[:4000]}"):
            if not n["unit"]:
                continue
            by_unit.setdefault(n["unit"], {}).setdefault(n["value"], set()).add(outlets[i.outlet_id].name)
    numbers = [{"unit": u, "values": [{"value": v, "outlets": sorted(o)} for v, o in vals.items()],
                "agreed": len(vals) == 1} for u, vals in by_unit.items()]
    ents: dict[str, set[str]] = {}
    for i in items:
        for e in extract_entities(f"{i.title}. {i.text[:4000]}"):
            ents.setdefault(e["name"], set()).add(outlets[i.outlet_id].name)
    total = len({i.outlet_id for i in items})
    names = [{"name": k, "outlets": sorted(v), "share": f"{len(v)} من {total}"} for k, v in
             sorted(ents.items(), key=lambda x: -len(x[1]))][:25]
    sources = []
    for i in items:
        for m in re.finditer(r"(?:وفقا ل|وفقًا ل|نقلا عن|نقلًا عن|بحسب|حسب|قال|قالت|صرح|أكد|اكد)\s+(\S+(?:\s\S+){0,2})", i.text[:4000]):
            sources.append({"outlet": outlets[i.outlet_id].name, "attributed_to": m.group(1)})
    anonymous = [outlets[i.outlet_id].name for i in items if re.search(r"مصدر (مطلع|مسؤول|رفيع|خاص)|مصادر (مطلعه|مطلعة|خاصه|خاصة)", i.text)]
    return {"numbers": numbers, "names": names, "attributions": sources[:40], "anonymous_sources": sorted(set(anonymous)),
            "disagreements": [n for n in numbers if not n["agreed"]]}


# ---------- الكيانات والتصريحات ----------

ROLE = r"(وزير|وزيرة|رئيس|رئيسة|مدير|مديرة|محافظ|أمين عام|امين عام|الناطق باسم|المتحدث باسم|الناطق الرسمي باسم|المتحدث الرسمي باسم|سفير|قائد)"
TITLE = r"(الملك|الأمير|الامير|الشيخ|الدكتور|د\.|المهندس|العين|النائب|السيدة|السيد)"
ORG = r"(وزارة|وزاره|هيئة|هيئه|مؤسسة|مؤسسه|شركة|شركه|جامعة|جامعه|بلدية|بلديه|دائرة|دائره|مجلس|نقابة|نقابه|حزب|البنك|بنك|سلطة|سلطه|مديرية|مديريه|المؤسسة|الأمن العام|الامن العام|الحكومة|الحكومه|الديوان)"
PLACE = r"(محافظة|محافظه|مدينة|مدينه|لواء|منطقة|منطقه|قرية|قريه|مطار|ميناء|معبر|شارع|طريق)"
_STOP_NEXT = set(normalize_ar("في من على إلى عن مع أن إن قد اليوم أمس يوم الذي التي الذين وقال قال وأكد أكد أن بأن و إنه انه لن لا لم ليس ما كما بعد قبل خلال عند منذ حول بشأن").split())
_W = r"[ء-ي]+"


def _defs(words: list[str], first_free: bool) -> list[str]:
    """تكملة الاسم: الكلمة الأولى حرة (إن سُمح)، وما بعدها معرّفة فقط (ال/وال) — «وزارة الطاقة والثروة المعدنية»."""
    out = []
    for k, w in enumerate(words):
        n = normalize_ar(w)
        if n in _STOP_NEXT or len(out) >= 4:
            break
        if (k == 0 and first_free) or n.startswith(("ال", "وال")):
            out.append(w)
        else:
            break
    return out


def extract_entities(text: str) -> list[dict]:
    """كيانات من القواعد. يكمّلها محرك ذكاء اصطناعي إن وُجد. «وزير الطاقة صالح الخرابشة» = منصب + شخص."""
    found: list[tuple[str, str]] = []
    for m in re.finditer(ROLE + rf"\s+((?:{_W}\s?){{1,6}})", text):
        words = m.group(2).split()
        port = _defs(words, first_free=False)
        if port:
            found.append(("person", f"{m.group(1)} {' '.join(port)}"))
        rest = words[len(port):]
        name = []
        for w in rest:
            n = normalize_ar(w)
            # الاسم الأول غير معرّف، وما بعده قد يكون معرّفًا (اسم العائلة: «صالح الخرابشة»)
            if n in _STOP_NEXT or (not name and n.startswith("ال")) or len(name) >= 3:
                break
            name.append(w)
        if len(name) >= 2:
            found.append(("person", " ".join(name)))
    for m in re.finditer(TITLE + rf"\s+((?:{_W}\s?){{1,3}})", text):
        name = []
        for w in m.group(2).split():
            if normalize_ar(w) in _STOP_NEXT or len(name) >= 3:
                break
            name.append(w)
        if name:
            found.append(("person", f"{m.group(1)} {' '.join(name)}" if len(name) < 2 or m.group(1) in ("الملك", "الأمير", "الامير") else " ".join(name)))
    for m in re.finditer(ORG + rf"(?:\s+((?:{_W}\s?){{1,5}}))?", text):
        trig = m.group(1)
        rest = _defs((m.group(2) or "").split(), first_free=not trig.startswith("ال"))
        if rest or trig.startswith("ال"):
            found.append(("org", f"{trig} {' '.join(rest)}".strip()))
    for m in re.finditer(PLACE + rf"\s+((?:{_W}\s?){{1,3}})", text):
        rest = _defs(m.group(2).split(), first_free=True)
        if rest:
            found.append(("place", f"{m.group(1)} {' '.join(rest)}"))
    out, seen = [], set()
    for kind, name in found:
        key = (normalize_ar(name), kind)
        if key not in seen and len(key[0]) > 4:
            seen.add(key)
            out.append({"name": name.strip(), "kind": kind, "norm": key[0]})
    return out


QUOTE = re.compile(r"(?:قال|قالت|صرح|صرّح|أكد|اكد|أكدت|اكدت|أوضح|اوضح|أعلن|اعلن|أعلنت|اعلنت|نفى|نفت|تعهد|وعد)\s+(?:(?:إن|ان|أن|بأن)\s+)?([^.!؟\n]{20,300})")
PROMISE = re.compile(r"(سوف|سيتم|سنعمل|سنقوم|سي[ء-ي]+|ستُ?[ء-ي]+|بحلول|خلال الأيام|خلال الاسابيع|خلال الأسابيع|العام المقبل|الشهر المقبل|تعهد|وعد)")
NEG = re.compile(r"\b(لا|لم|لن|ليس|ليست|نفى|نفت|ينفي|تنفي|غير صحيح|عار عن)\b")

POS = set(normalize_ar("نجاح ناجح إنجاز انجاز تقدم تحسن ارتفاع_ثقة دعم ترحيب إشادة اشاده إيجابي ايجابي مميز تطوير أفضل افضل نمو مكافحة إصلاح اصلاح").replace("_", " ").split())
NEGW = set(normalize_ar("فشل فساد أزمة ازمة انتقاد اتهام اتهامات تراجع خسارة خسائر فضيحة فضيحه سلبي كارثة كارثه تقصير إهمال اهمال احتجاج غضب مخالفات تجاوزات").split())


def tone(text: str) -> float:
    toks = normalize_ar(text).split()
    p = sum(t in POS for t in toks)
    n = sum(t in NEGW for t in toks)
    return round((p - n) / (p + n), 2) if p + n else 0.0


def _entity(db: Session, name: str, kind: str) -> Entity:
    norm = normalize_ar(name)
    e = db.scalar(select(Entity).where(Entity.norm == norm, Entity.kind == kind))
    if e is None:
        alias = db.scalars(select(Entity).where(Entity.kind == kind))
        e = next((x for x in alias if norm in [normalize_ar(a) for a in (x.aliases or [])]), None)
    if e is None:
        e = Entity(name=name, norm=norm, kind=kind, aliases=[])
        db.add(e)
        db.flush()
    return e


def process_entities(db: Session, item: Item) -> list[Entity]:
    """الكيانات والإشارات والنبرة والتصريحات لمادة واحدة."""
    text = f"{item.title}. {item.text[:8000]}"
    ents = []
    for x in extract_entities(text):
        e = _entity(db, x["name"], x["kind"])
        sents = [s for s in re.split(r"[.!؟\n]", text) if x["norm"] in normalize_ar(s)]
        m = db.scalar(select(EntityMention).where(EntityMention.entity_id == e.id, EntityMention.item_id == item.id))
        if m is None:
            db.add(EntityMention(entity_id=e.id, item_id=item.id, tone=tone(" ".join(sents)), count=max(1, len(sents))))
        ents.append(e)
    # التصريحات: جملة قول بعد ذكر كيان (أقرب كيان شخص أو مؤسسة قبل الفعل)
    for m in QUOTE.finditer(text):
        span = m.group(1)
        cut = re.search(r"\s(?:إن|ان|أن|بأن)\s", span[:120])
        head, q = (span[:cut.start()], span[cut.end():]) if cut else ("", span)
        around = normalize_ar(text[max(0, m.start() - 120):m.start()] + " " + head)
        cands = [e for e in ents if e.kind in ("person", "org") and e.norm in around]
        if not cands:
            continue
        speaker = max(cands, key=lambda e: (e.kind == "person" and " " in e.norm and not e.norm.startswith(("وزير", "رييس", "مدير")), len(e.norm)))
        q = q.strip()
        if len(q) < 15:
            continue
        if not db.scalar(select(Statement.id).where(Statement.entity_id == speaker.id, Statement.item_id == item.id, Statement.quote == q)):
            db.add(Statement(entity_id=speaker.id, item_id=item.id, quote=q, said_at=item.published_at or item.captured_at,
                             is_promise=bool(PROMISE.search(q))))
    db.flush()
    return ents


def contradictions(db: Session, entity: Entity) -> list[dict]:
    """تناقض محتمل بين تصريحين للكيان نفسه: موضوع واحد ورقمان مختلفان، أو نفي مقابل إثبات. للمراجعة البشرية."""
    sts = list(db.scalars(select(Statement).where(Statement.entity_id == entity.id).order_by(Statement.said_at)))
    out = []
    for i, a in enumerate(sts):
        for b in sts[i + 1:]:
            ta, tb = set(_tokens(a.quote)) - {"تم"}, set(_tokens(b.quote))
            overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
            if overlap < 0.3:
                continue
            na = {(n["unit"], n["value"]) for n in _numbers(a.quote) if n["unit"]}
            nb = {(n["unit"], n["value"]) for n in _numbers(b.quote) if n["unit"]}
            units = {u for u, _ in na} & {u for u, _ in nb}
            reason = None
            if any({v for u2, v in na if u2 == u} != {v for u2, v in nb if u2 == u} for u in units):
                reason = "رقمان مختلفان في الموضوع نفسه"
            elif bool(NEG.search(normalize_ar(a.quote))) != bool(NEG.search(normalize_ar(b.quote))) and overlap >= 0.5:
                reason = "نفي مقابل إثبات"
            if reason:
                out.append({"reason": reason, "overlap": round(overlap, 2),
                            "a": {"id": a.id, "quote": a.quote, "item_id": a.item_id, "said_at": a.said_at.isoformat() if a.said_at else None},
                            "b": {"id": b.id, "quote": b.quote, "item_id": b.item_id, "said_at": b.said_at.isoformat() if b.said_at else None}})
    return out


def analyze_item(db: Session, item: Item) -> None:
    """يُستدعى لكل مادة جديدة أو معدّلة."""
    item.meta = {k: v for k, v in (item.meta or {}).items() if k != "sig"}
    if item.story_id is None or not db.get(Story, item.story_id) or not db.get(Story, item.story_id).locked:
        assign_story(db, item)
    process_entities(db, item)
    from marsad.claims.core import auto_extract

    auto_extract(db, item)  # تسجيل ظهور ادّعاء معروف، وتنبيه عودة شائعة مكشوفة، وادّعاءات من مواد الشائعات
