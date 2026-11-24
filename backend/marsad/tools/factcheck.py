"""«هل تحقق منها أحد قبلي؟»: بحث في Google Fact Check Tools (مجاني بمفتاح) وفي سجل البرنامج نفسه.

المفتاح يضعه المدير من الإدارة ويُحفظ مشفّرًا. بلا مفتاح يُقال ذلك بوضوح ويبقى البحث المحلي.
"""

from __future__ import annotations

import os

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.db import utcnow
from marsad.models import User
from marsad.models.claims import Claim
from marsad.rbac.service import get_setting, set_setting
from marsad.text import similar

KEY = "factcheck.google"


def api_base() -> str:
    return os.environ.get("MARSAD_FACTCHECK_API", "https://factchecktools.googleapis.com").rstrip("/")


def info(db: Session) -> dict:
    s = get_setting(db, KEY, {}) or {}
    return {"configured": bool(s.get("key")), "masked": s.get("masked")}


def set_key(db: Session, key: str | None, actor: User) -> dict:
    if not key:
        set_setting(db, KEY, {}, actor)
        db.flush()
        return info(db)
    key = key.strip()
    r = _search(key, "test", "en", page_size=1)
    if r.get("error"):
        raise ValueError(r["error"])
    set_setting(db, KEY, {"key": crypto.encrypt(key), "masked": crypto.mask(key)}, actor)
    db.flush()
    return info(db)


def _key(db: Session) -> str | None:
    enc = (get_setting(db, KEY, {}) or {}).get("key")
    try:
        return crypto.decrypt(enc) if enc else None
    except ValueError:
        return None


def _search(key: str, query: str, lang: str, page_size: int = 10) -> dict:
    try:
        r = httpx.get(f"{api_base()}/v1alpha1/claims:search",
                      params={"query": query[:300], "languageCode": lang, "pageSize": page_size, "key": key}, timeout=20)
        d = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"تعذّر الاتصال بخدمة Google Fact Check: {e.__class__.__name__}"}
    if r.status_code != 200:
        msg = (d.get("error") or {}).get("message") if isinstance(d, dict) else ""
        return {"error": f"رفضت الخدمة الطلب ({r.status_code}){': ' + msg if msg else ''}"}
    return d


def search(db: Session, c: Claim, local_limit: int = 5) -> dict:
    """نتائج عالمية (بالعربية ثم الإنجليزية) ونتائج من سجل البرنامج، وتُحفظ في البطاقة."""
    out = {"checked_at": utcnow().isoformat(), "configured": False, "global": [], "error": "", "local": []}
    key = _key(db)
    if key:
        out["configured"] = True
        seen = set()
        for lang in ("ar", "en"):
            d = _search(key, c.text, lang)
            if d.get("error"):
                out["error"] = d["error"]
                break
            for cl in d.get("claims", []) or []:
                for rv in cl.get("claimReview", []) or []:
                    url = rv.get("url", "")
                    if url in seen:
                        continue
                    seen.add(url)
                    out["global"].append({"claim": cl.get("text", ""), "claimant": cl.get("claimant", ""),
                                          "publisher": (rv.get("publisher") or {}).get("name", ""),
                                          "site": (rv.get("publisher") or {}).get("site", ""),
                                          "rating": rv.get("textualRating", ""), "date": rv.get("reviewDate", "")[:10],
                                          "url": url, "title": rv.get("title", ""), "language": rv.get("languageCode", lang)})
    else:
        out["note"] = "البحث في قواعد التحقق العالمية غير مفعّل: يضيف المدير مفتاح Google Fact Check من الإدارة ← التخزين والإعدادات."
    # سجل البرنامج: ادّعاءات سابقة مشابهة بحكم معتمد
    rows = []
    for other in db.scalars(select(Claim).where(Claim.id != c.id).order_by(Claim.id.desc()).limit(2000)).all():
        approved = [v for v in other.verdicts if v.status == "approved"]
        if not approved:
            continue
        s = similar(c.text, other.text)
        if s >= 0.55:
            rows.append({"claim_id": other.id, "text": other.text, "label": approved[-1].label, "score": round(s, 2),
                         "link": f"/claims/{other.id}"})
    out["local"] = sorted(rows, key=lambda r: -r["score"])[:local_limit]
    c.meta = {**(c.meta or {}), "factcheck": out}
    return out
