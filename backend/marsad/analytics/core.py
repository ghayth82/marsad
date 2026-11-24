"""حساب اللوحات. كل مؤشر يُعاد بالشكل {"n": العدد, "drill": {"kind": ..., "ids": [...]}}
فيفتح الصحفي المواد أو الادّعاءات التي حُسب منها. الحساب في Python على مواد الفترة فقط،
فيعمل بالشكل نفسه على PostgreSQL وSQLite."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marsad.analytics.topics import OTHER, TOPICS, governorates_in, topic_of
from marsad.db import utcnow
from marsad.engines.prompts import VERDICT_LABELS
from marsad.models import User
from marsad.models.analysis import Story
from marsad.models.claims import Claim, ClaimItem, Verdict
from marsad.models.engines import EngineRun
from marsad.models.monitoring import Item, ItemVersion, Outlet, Source
from marsad.text import normalize_ar

TZ = "Asia/Amman"
DRILL_CAP = 1000
EFFECT_HOURS = 6

PLATFORMS = {"rss": "مواقع", "sitemap": "مواقع", "page": "مواقع", "telegram": "تيليغرام", "youtube": "يوتيوب",
             "gdelt": "GDELT", "social": "التواصل", "manual": "إدخال يدوي"}
NO_ITEM = "إدخال يدوي"
TIP = "بلاغ من الجمهور"


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=ZoneInfo("UTC"))


def m(ids, kind: str) -> dict:
    ids = list(dict.fromkeys(ids))
    return {"n": len(ids), "drill": {"kind": kind, "ids": ids[:DRILL_CAP]}}


def period(days: int | None = 30, start: str | None = None, end: str | None = None,
           now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or utcnow()
    if start:
        tz = ZoneInfo(TZ)
        s = datetime.fromisoformat(start)
        s = s if s.tzinfo else s.replace(tzinfo=tz)
        e = datetime.fromisoformat(end) if end else now
        e = e if e.tzinfo else e.replace(tzinfo=tz)
        if len(end or "") == 10:  # تاريخ فقط: حتى نهاية اليوم
            e += timedelta(days=1)
        return s, (min(e, now) if e > s else now)
    return now - timedelta(days=max(1, min(int(days or 30), 3650))), now


# ---------- مساعدات الادّعاءات ----------

def item_time(it: Item) -> datetime:
    return _aware(it.published_at or it.captured_at)


def claim_seen(c: Claim) -> datetime:
    return _aware(c.first_seen_at or c.created_at)


def first_approval(c: Claim) -> Verdict | None:
    ok = [v for v in c.verdicts if v.status == "approved" and v.approved_at]
    return min(ok, key=lambda v: _aware(v.approved_at)) if ok else None


def final_verdict(c: Claim) -> Verdict | None:
    ok = [v for v in c.verdicts if v.status == "approved"]
    return ok[-1] if ok else None


def platform_of(db: Session, c: Claim, cache: dict) -> str:
    if c.origin == "tip":
        return TIP
    if not c.first_item_id:
        return NO_ITEM
    if c.first_item_id not in cache:
        it = db.get(Item, c.first_item_id)
        kind = it.source.kind if it and it.source else "manual"
        if kind == "social" and it is not None:
            kind_label = (it.source.meta or {}).get("platform") or PLATFORMS["social"]
        else:
            kind_label = PLATFORMS.get(kind, kind)
        cache[c.first_item_id] = kind_label
    return cache[c.first_item_id]


def claims_in(db: Session, start: datetime, end: datetime, topic: str | None = None,
              platform: str | None = None) -> list[tuple[Claim, str, str]]:
    """ادّعاءات ظهرت أول مرة في الفترة، مع موضوعها ومنصتها."""
    rows = db.scalars(select(Claim).where(func.coalesce(Claim.first_seen_at, Claim.created_at) >= start,
                                          func.coalesce(Claim.first_seen_at, Claim.created_at) < end)
                      .order_by(Claim.id)).all()
    cache: dict = {}
    out = []
    for c in rows:
        t, p = topic_of(c.text, c.tags), platform_of(db, c, cache)
        if topic and t != topic or platform and p != platform:
            continue
        out.append((c, t, p))
    return out


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def _stat(vals: list[float]) -> dict:
    if not vals:
        return {"median": None, "mean": None, "count": 0}
    return {"median": round(statistics.median(vals), 1), "mean": round(statistics.fmean(vals), 1), "count": len(vals)}


# ---------- لوحة التحقق ----------

def verification(db: Session, start: datetime, end: datetime, topic: str | None = None, platform: str | None = None) -> dict:
    cl = claims_in(db, start, end, topic, platform)
    decided, labels, ttv = [], defaultdict(list), []
    by_topic, by_platform = defaultdict(list), defaultdict(list)
    for c, t, p in cl:
        by_topic[t].append(c.id)
        by_platform[p].append(c.id)
        v = first_approval(c)
        if v:
            decided.append(c.id)
            labels[final_verdict(c).label].append(c.id)
            ttv.append(max(0.0, _hours(claim_seen(c), _aware(v.approved_at))))
    ids = [c.id for c, _, _ in cl]
    # الشائعات العائدة: ادّعاءات عادت بكلمات أخرى داخل الفترة (أيًّا كان تاريخ ظهورها الأول)
    ret_rows = db.execute(select(ClaimItem.claim_id, func.count()).where(ClaimItem.kind == "return",
                                                                         ClaimItem.added_at >= start, ClaimItem.added_at < end)
                          .group_by(ClaimItem.claim_id)).all()
    allowed = None if not (topic or platform) else set(ids) | {
        cid for cid, _ in ret_rows if _keep(db, cid, topic, platform)}
    returns = sorted(((cid, n) for cid, n in ret_rows if allowed is None or cid in allowed), key=lambda x: -x[1])
    return {
        "claims": m(ids, "claims"),
        "decided": m(decided, "claims"),
        "pending": m([i for i in ids if i not in set(decided)], "claims"),
        "labels": [{"label": lb, **m(labels.get(lb, []), "claims")} for lb in VERDICT_LABELS],
        "time_to_verdict_hours": _stat(ttv),
        "by_topic": sorted(({"key": k, **m(v, "claims")} for k, v in by_topic.items()), key=lambda x: -x["n"]),
        "by_platform": sorted(({"key": k, **m(v, "claims")} for k, v in by_platform.items()), key=lambda x: -x["n"]),
        "returns": {**m([cid for cid, _ in returns], "claims"),
                    "top": [{"claim_id": cid, "times": n, "text": db.get(Claim, cid).text[:140]} for cid, n in returns[:10]]},
    }


def _keep(db: Session, cid: int, topic: str | None, platform: str | None) -> bool:
    c = db.get(Claim, cid)
    return bool(c) and (not topic or topic_of(c.text, c.tags) == topic) and (not platform or platform_of(db, c, {}) == platform)


# ---------- لوحة الانتشار ----------

def spread(db: Session, c: Claim) -> dict:
    """منحنى انتشار ادّعاء: مواد ومصادر في كل ساعة (أو يوم إن طال)، وعلامة الحكم، وأثر التصحيح."""
    rows = db.execute(select(Item).join(ClaimItem, ClaimItem.item_id == Item.id).where(ClaimItem.claim_id == c.id)).scalars().all()
    pts = sorted((item_time(it), it) for it in rows)
    v = first_approval(c)
    vt = _aware(v.approved_at) if v else None
    if not pts:
        return {"claim_id": c.id, "bucket": "hour", "points": [], "verdict_at": vt.isoformat() if vt else None, "effect": None}
    t0, t1 = pts[0][0], max(pts[-1][0], vt or pts[-1][0])
    hourly = _hours(t0, t1) <= 24 * 14
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    base = t0.replace(minute=0, second=0, microsecond=0) if hourly else t0.replace(hour=0, minute=0, second=0, microsecond=0)
    buckets: dict[int, list[Item]] = defaultdict(list)
    for t, it in pts:
        buckets[int((t - base) / step)].append(it)
    n = int((t1 - base) / step) + 1
    points = [{"t": (base + i * step).isoformat(), "items": len(buckets.get(i, [])),
               "sources": len({x.source_id for x in buckets.get(i, [])}), "ids": [x.id for x in buckets.get(i, [])]}
              for i in range(n)]
    return {"claim_id": c.id, "text": c.text, "bucket": "hour" if hourly else "day", "points": points,
            "verdict_at": vt.isoformat() if vt else None, "effect": effect(pts, vt)}


def effect(pts: list[tuple[datetime, Item]], vt: datetime | None, hours: int = EFFECT_HOURS) -> dict | None:
    """معدّل الانتشار في الساعات الست قبل الحكم مقابل الست بعده."""
    if vt is None:
        return None
    w = timedelta(hours=hours)
    before = [it.id for t, it in pts if vt - w <= t < vt]
    after = [it.id for t, it in pts if vt <= t < vt + w]
    drop = None if not before else round(100 * (len(before) - len(after)) / len(before))
    return {"hours": hours, "before": m(before, "items"), "after": m(after, "items"), "drop_pct": drop}


def spread_overview(db: Session, start: datetime, end: datetime, topic: str | None = None,
                    platform: str | None = None, top: int = 12) -> dict:
    cl = claims_in(db, start, end, topic, platform)
    counts = dict(db.execute(select(ClaimItem.claim_id, func.count()).where(ClaimItem.claim_id.in_([c.id for c, _, _ in cl]))
                             .group_by(ClaimItem.claim_id)).all()) if cl else {}
    ranked = sorted(cl, key=lambda x: -counts.get(x[0].id, 0))[:top]
    return {"claims": [{"claim_id": c.id, "text": c.text[:160], "topic": t, "platform": p, "appearances": counts.get(c.id, 0),
                        "verdict": (final_verdict(c).label if final_verdict(c) else None), **{"spread": spread(db, c)}}
                       for c, t, p in ranked]}


def items_in(db: Session, start: datetime, end: datetime) -> list[Item]:
    return db.scalars(select(Item).where(func.coalesce(Item.published_at, Item.captured_at) >= start,
                                         func.coalesce(Item.published_at, Item.captured_at) < end)).all()


def geography(db: Session, start: datetime, end: datetime) -> dict:
    gov = defaultdict(list)
    heat = defaultdict(list)  # (يوم، ساعة) بتوقيت عمّان
    tz = ZoneInfo(TZ)
    for it in items_in(db, start, end):
        for g in governorates_in(it.norm or normalize_ar(f"{it.title} {it.text}")):
            gov[g].append(it.id)
        lt = item_time(it).astimezone(tz)
        heat[(lt.weekday(), lt.hour)].append(it.id)
    from marsad.analytics.topics import GOVERNORATES
    return {"governorates": [{"key": g, **m(gov.get(g, []), "items")} for g in GOVERNORATES],
            "heatmap": [{"day": d, "hour": h, **m(heat.get((d, h), []), "items")} for d in range(7) for h in range(24)]}


# ---------- لوحة المصادر ----------

def _domain(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def credits(item: Item, first: Item, first_outlet: Outlet | None) -> bool:
    """هل تذكر المادة الناشر الأول باسمه أو بنطاق موقعه؟"""
    body = item.norm or normalize_ar(f"{item.title} {item.text}")
    raw = f"{item.title} {item.text}".lower()
    name = normalize_ar(first_outlet.name) if first_outlet else ""
    dom = _domain(first.url)
    return bool(name and name in body) or bool(dom and dom in raw) or bool(first.url and first.url in raw)


def sources(db: Session, start: datetime, end: datetime) -> dict:
    items = items_in(db, start, end)
    by_outlet: dict[int, list[Item]] = defaultdict(list)
    for it in items:
        by_outlet[it.outlet_id].append(it)
    # التعديل والحذف من سجل النسخ (المادة قد تُعدَّل ثم تعود)
    edited = set(db.scalars(select(ItemVersion.item_id).where(ItemVersion.change == "edit",
                                                              ItemVersion.item_id.in_([i.id for i in items]))).all()) if items else set()
    deleted = {i.id for i in items if i.status == "deleted"}
    story_ids = {i.story_id for i in items if i.story_id}
    first_of = {}
    for s in db.scalars(select(Story).where(Story.id.in_(story_ids))).all() if story_ids else []:
        if s.first_item_id:
            first_of[s.id] = db.get(Item, s.first_item_id)
    delays, firsts, uncredited = defaultdict(list), defaultdict(list), defaultdict(list)
    outlets = {o.id: o for o in db.scalars(select(Outlet).where(Outlet.id.in_(list(by_outlet) or [0]))).all()}
    for it in items:
        f = first_of.get(it.story_id)
        if not f:
            continue
        if f.id == it.id:
            firsts[it.outlet_id].append(it.id)
            continue
        if f.outlet_id == it.outlet_id:
            continue
        delays[it.outlet_id].append(max(0.0, (item_time(it) - item_time(f)).total_seconds() / 60))
        fo = outlets.get(f.outlet_id) or db.get(Outlet, f.outlet_id)
        if not credits(it, f, fo):
            uncredited[it.outlet_id].append(it.id)
    rows = []
    for oid, its in by_outlet.items():
        ids = [i.id for i in its]
        e = [i for i in ids if i in edited]
        d = [i for i in ids if i in deleted]
        rows.append({"outlet_id": oid, "name": outlets[oid].name if oid in outlets else str(oid), "items": m(ids, "items"),
                     "edited": m(e, "items"), "deleted": m(d, "items"),
                     "edited_pct": round(100 * len(e) / len(ids), 1), "deleted_pct": round(100 * len(d) / len(ids), 1),
                     "first": m(firsts.get(oid, []), "items"),
                     "delay_minutes": _stat(delays.get(oid, [])),
                     "uncredited": m(uncredited.get(oid, []), "items")})
    rows.sort(key=lambda r: -r["items"]["n"])
    return {"outlets": rows, "note": "أرقام داخلية للعمل، لا تُنشر."}


# ---------- لوحة الفريق والمؤسسة ----------

def kappa_multi(pairs: list[tuple[str, str]]) -> float | None:
    """معامل كوهين كابا لتصنيفين متعددي الفئات على العناصر نفسها."""
    n = len(pairs)
    if n < 5:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else round((po - pe) / (1 - pe), 3)


def team(db: Session, start: datetime, end: datetime) -> dict:
    users = {u.id: u for u in db.scalars(select(User)).all()}
    per: dict[int, dict] = defaultdict(lambda: {"created": [], "proposed": [], "approved": [], "hours": []})
    for c in db.scalars(select(Claim).where(Claim.created_at >= start, Claim.created_at < end)).all():
        if c.created_by:
            per[c.created_by]["created"].append(c.id)
    vs = db.scalars(select(Verdict).where(Verdict.created_at >= start, Verdict.created_at < end)).all()
    reviewed = [v for v in vs if v.status in ("approved", "rejected") and v.author_id]
    for v in vs:
        if v.author_id:
            per[v.author_id]["proposed"].append(v.claim_id)
    for v in db.scalars(select(Verdict).where(Verdict.approved_at >= start, Verdict.approved_at < end,
                                              Verdict.status == "approved")).all():
        if v.approved_by:
            per[v.approved_by]["approved"].append(v.claim_id)
        if v.author_id:
            c = db.get(Claim, v.claim_id)
            per[v.author_id]["hours"].append(max(0.0, _hours(claim_seen(c), _aware(v.approved_at))))
    # اتفاق المحرك مع الحكم النهائي: كل ادّعاء له اقتراح من المحركات وحكم معتمد
    pairs = []
    # المعرّفات أولًا: DISTINCT على صفوف فيها JSON لا يعمل في PostgreSQL
    eng_ids = db.scalars(select(Verdict.claim_id).where(Verdict.engine_batch_id.is_not(None), Verdict.created_at >= start,
                                                       Verdict.created_at < end).distinct()).all()
    for c in db.scalars(select(Claim).where(Claim.id.in_(eng_ids))).all() if eng_ids else []:
        eng = next((v for v in c.verdicts if v.engine_batch_id), None)
        fin = final_verdict(c)
        if eng and fin:
            pairs.append((eng.label, fin.label))
    cost = db.scalar(select(func.coalesce(func.sum(EngineRun.cost_usd), 0.0)).where(EngineRun.created_at >= start,
                                                                                 EngineRun.created_at < end)) or 0.0
    approved_n = db.scalar(select(func.count()).select_from(Verdict).where(Verdict.status == "approved",
                                                                          Verdict.approved_at >= start, Verdict.approved_at < end)) or 0
    acc = [v for v in reviewed if v.status == "approved"]
    return {
        "people": sorted(({"user_id": uid, "name": users[uid].full_name if uid in users else "—",
                           "created": m(d["created"], "claims"), "proposed": m(d["proposed"], "claims"),
                           "approved": m(d["approved"], "claims"), "hours_to_verdict": _stat(d["hours"])}
                          for uid, d in per.items()), key=lambda r: r["name"]),
        "review_acceptance_pct": round(100 * len(acc) / len(reviewed), 1) if reviewed else None,
        "reviewed": len(reviewed),
        "engine_agreement": {"pairs": len(pairs), "kappa": kappa_multi(pairs),
                             "agree_pct": round(100 * sum(a == b for a, b in pairs) / len(pairs), 1) if pairs else None},
        "engine_cost_usd": round(float(cost), 4),
        "cost_per_verdict_usd": round(float(cost) / approved_n, 4) if approved_n else None,
        "note": "تصف حجم العمل لا ترتّب الأشخاص.",
    }


# ---------- تقرير الأثر ----------

def impact(db: Session, start: datetime, end: datetime) -> dict:
    vs = db.scalars(select(Verdict).where(Verdict.status == "approved", Verdict.approved_at >= start,
                                          Verdict.approved_at < end)).all()
    claims = {}
    for v in vs:
        c = db.get(Claim, v.claim_id)
        fa = first_approval(c)
        if fa and fa.id == v.id:  # أول اعتماد فقط، فلا يُعدّ التصحيح تحققًا جديدًا
            claims[c.id] = (c, _aware(v.approved_at))
    corrected, corrected_items, dropped, measured, misleading = [], [], [], [], []
    for cid, (c, vt) in claims.items():
        fin = final_verdict(c)
        if fin and fin.label != "صحيح":
            misleading.append(cid)
        item_ids = [ci.item_id for ci in c.appearances]
        if item_ids:
            changed = db.scalars(select(ItemVersion.item_id).where(ItemVersion.item_id.in_(item_ids),
                                                                  ItemVersion.change.in_(("edit", "delete")),
                                                                  ItemVersion.captured_at > vt)).all()
            if changed:
                corrected.append(cid)
                corrected_items.extend(changed)
        pts = sorted((item_time(it), it) for it in db.scalars(select(Item).where(Item.id.in_(item_ids or [0]))).all())
        e = effect(pts, vt)
        if e and e["before"]["n"]:
            measured.append(cid)
            if e["after"]["n"] < e["before"]["n"]:
                dropped.append(cid)
    n = len(claims)
    return {
        "verified": m(list(claims), "claims"),
        "not_true": m(misleading, "claims"),
        "publisher_corrected": {**m(corrected, "claims"), "items": m(corrected_items, "items"),
                                "pct": round(100 * len(corrected) / n, 1) if n else None},
        "spread_measured": m(measured, "claims"),
        "spread_dropped": {**m(dropped, "claims"), "pct": round(100 * len(dropped) / len(measured), 1) if measured else None},
        "method": ("«صحّحه ناشره»: مادة ظهر فيها الادّعاء عُدّلت أو حُذفت بعد اعتماد الحكم. "
                   f"«هبط انتشارها»: عدد المواد في {EFFECT_HOURS} ساعات بعد الحكم أقل منه في {EFFECT_HOURS} ساعات قبله."),
    }


# ---------- الفلاتر والتفصيل ----------

def options() -> dict:
    return {"topics": list(TOPICS) + [OTHER], "platforms": sorted(set(PLATFORMS.values()) | {TIP}),
            "periods": [7, 30, 90]}


def rows(db: Session, kind: str, ids: list[int]) -> list[dict]:
    ids = ids[:DRILL_CAP]
    if kind == "claims":
        found = {c.id: c for c in db.scalars(select(Claim).where(Claim.id.in_(ids))).all()}
        out = []
        for i in ids:
            if i in found:
                c = found[i]
                fv = final_verdict(c)
                out.append({"id": i, "title": c.text[:200], "link": f"/claims/{i}", "external": False,
                            "meta": fv.label if fv else "دون حكم", "at": claim_seen(c).isoformat()})
        return out
    if kind == "items":
        found = {it.id: it for it in db.scalars(select(Item).where(Item.id.in_(ids))).all()}
        outlets = {o.id: o.name for o in db.scalars(select(Outlet)).all()}
        return [{"id": i, "title": found[i].title or found[i].url, "link": found[i].url, "external": True,
                 "meta": outlets.get(found[i].outlet_id, ""), "at": item_time(found[i]).isoformat()}
                for i in ids if i in found]
    raise ValueError("نوع غير معروف")


def all_dashboards(db: Session, start: datetime, end: datetime, topic: str | None, platform: str | None,
                   with_team: bool) -> dict:
    out = {"period": {"start": start.isoformat(), "end": end.isoformat()},
           "verification": verification(db, start, end, topic, platform),
           "spread": spread_overview(db, start, end, topic, platform),
           "geography": geography(db, start, end),
           "sources": sources(db, start, end),
           "impact": impact(db, start, end)}
    if with_team:
        out["team"] = team(db, start, end)
    return out

