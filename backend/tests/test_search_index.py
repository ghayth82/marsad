"""فهارس البحث: الادّعاءات والكيانات والقصص تُفهرس تلقائيًا حين تُحفظ وتُحذف، ويُعاد بناؤها،
والبحث يمر بها حين يكون Meilisearch متاحًا وبالقاعدة حين لا يكون. Meilisearch هنا بديل صغير في الذاكرة."""
import re

import pytest


class FakeMeili:
    def __init__(self):
        self.idx: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}

    def post(self, url, headers=None, json=None, timeout=None):
        path = url.split("://", 1)[1].split("/", 1)[1]
        parts = path.split("/")
        if parts == ["indexes"]:
            self.idx.setdefault(json["uid"], {})
            return Resp({})
        kind = parts[1]
        if parts[2:] == ["documents"]:
            for d in json:
                self.idx.setdefault(kind, {})[d["id"]] = d
            return Resp({})
        if parts[2:] == ["documents", "delete-batch"]:
            for i in json:
                self.idx.get(kind, {}).pop(i, None)
            return Resp({})
        if parts[2:] == ["search"]:
            return Resp(self._search(kind, json))
        raise AssertionError(url)

    def patch(self, url, headers=None, json=None, timeout=None):
        self.settings[url.rstrip("/").split("/")[-2]] = json
        return Resp({})

    def _search(self, kind, j):
        attrs = self.settings[kind]["searchableAttributes"]
        terms = j["q"].split()
        hits = []
        for d in self.idx.get(kind, {}).values():
            hay = " ".join((" ".join(d[a]) if isinstance(d.get(a), list) else str(d.get(a) or "")) for a in attrs)
            if not all(t in hay for t in terms):
                continue
            ok = True
            for f in (j.get("filter") or "").split(" AND ") if j.get("filter") else []:
                k, op, v = re.match(r"(\w+) (=|>=|<=) (.+)", f).groups()
                v = v.strip('"')
                dv = d.get(k)
                ok &= (str(dv) == v) if op == "=" else (dv is not None and (dv >= float(v) if op == ">=" else dv <= float(v)))
            if ok:
                hits.append(d)
        for s in reversed(j.get("sort") or []):
            k, direction = s.split(":")
            hits.sort(key=lambda d: d.get(k) or 0, reverse=direction == "desc")
        out = hits[j.get("offset", 0): j.get("offset", 0) + j["limit"]]
        return {"hits": [{"id": d["id"]} for d in out], "estimatedTotalHits": len(hits)}


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        return None


@pytest.fixture
def meili(monkeypatch):
    from marsad import search

    fake = FakeMeili()
    monkeypatch.setenv("MARSAD_MEILI_URL", "http://meili.test")
    monkeypatch.setattr(search.httpx, "post", fake.post)
    monkeypatch.setattr(search.httpx, "patch", fake.patch)
    search._ready.clear()
    yield fake
    search._ready.clear()


def test_claims_indexed_on_save_and_delete_and_searched_through_index(admin, meili):
    from marsad.db import get_db
    from marsad.models.claims import Claim

    cid = admin.post("/api/claims", json={"text": "أعلنت الوزارة تأجيل الامتحانات الوزارية أسبوعين"}).json()["id"]
    assert meili.idx["claims"][cid]["norm"] and "text" not in meili.idx["claims"][cid]  # النص الموحّد فقط
    # همزة مختلفة في الاستعلام: البحث الموحّد يجدها
    assert [c["id"] for c in admin.get("/api/claims", params={"q": "الإمتحانات"}).json()] == [cid]
    # تعديل الحالة يصل إلى الفهرس، والتصفية بها تعمل
    db = next(get_db())
    db.get(Claim, cid).status = "dismissed"
    db.commit()
    assert meili.idx["claims"][cid]["status"] == "dismissed"
    assert admin.get("/api/claims", params={"q": "الامتحانات", "status": "new"}).json() == []
    db.delete(db.get(Claim, cid))
    db.commit()
    db.close()
    assert cid not in meili.idx["claims"]


def test_entities_found_by_alias_and_stories_by_title(admin, meili):
    from marsad.db import get_db
    from marsad.models.analysis import Entity, EntityMention, Story
    from marsad.models.monitoring import Item, Outlet, Source

    db = next(get_db())
    o = Outlet(name="خبرني")
    db.add(o)
    db.flush()
    s = Source(outlet_id=o.id, url="https://kh.example/", kind="rss", read_url="https://kh.example/rss")
    db.add(s)
    db.flush()
    it = Item(source_id=s.id, outlet_id=o.id, url="https://kh.example/1", title="خبر", text="", content_hash="x")
    e = Entity(name="وزارة التربية والتعليم", norm="وزارة التربية والتعليم", kind="org", aliases=["التربية", "Ministry of Education"])
    st = Story(title="أسعار الأدوية ترتفع في الصيدليات", item_count=3, source_count=2)
    db.add_all([it, e, st])
    db.flush()
    db.add(EntityMention(entity_id=e.id, item_id=it.id))
    db.commit()
    eid, sid = e.id, st.id
    assert st.norm  # يُضبط تلقائيًا
    db.close()
    assert [x["id"] for x in admin.get("/api/entities", params={"q": "Ministry of Education"}).json()] == [eid]
    assert [x["id"] for x in admin.get("/api/stories", params={"q": "الادويه"}).json()] == [sid]
    assert admin.get("/api/stories", params={"q": "الادويه", "min_sources": 3}).json() == []


def test_rebuild_fills_indexes_from_database(admin, meili, monkeypatch):
    from marsad import search
    from marsad.db import get_db

    monkeypatch.delenv("MARSAD_MEILI_URL")  # تُحفظ والبحث غير متاح: لا شيء يُفهرس
    cid = admin.post("/api/claims", json={"text": "ادعاء محفوظ قبل تشغيل محرك البحث"}).json()["id"]
    monkeypatch.setenv("MARSAD_MEILI_URL", "http://meili.test")
    assert cid not in meili.idx.get("claims", {})
    db = next(get_db())
    out = search.rebuild(db)
    db.close()
    assert out["claims"] >= 1 and cid in meili.idx["claims"]
    assert meili.settings["items"]["searchableAttributes"] == ["norm_title", "norm"]


def test_story_search_without_index_covers_all_stories(admin):
    """دون Meilisearch: البحث في العنوان الموحّد في القاعدة، لا في أحدث ألفين فقط كما كان."""
    from datetime import datetime, timedelta, timezone

    from marsad.db import get_db
    from marsad.models.analysis import Story

    db = next(get_db())
    old = Story(title="انقطاع الكهرباء في الكرك", item_count=2, source_count=1,
                updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    db.add(old)
    now = datetime.now(timezone.utc)
    db.add_all([Story(title=f"قصة رقم {n}", item_count=2, source_count=1, updated_at=now - timedelta(minutes=n)) for n in range(2100)])
    db.commit()
    oid = old.id
    db.close()
    assert [x["id"] for x in admin.get("/api/stories", params={"q": "الكهربا"}).json()] == [oid]
