"""أسماء كاملة: لا «الملك عبد»، ولا «الملك عبدالله الثاني الوفد»؛ وإعادة المعالجة تحفظ عمل الصحفي."""
import pytest

from marsad.analysis.core import entity_norm, extract_entities


def names(t):
    return [e["name"] for e in extract_entities(t)]


@pytest.mark.parametrize("text,expected", [
    ("استقبل الملك عبدُالله الثاني الوفد", "الملك عبدالله الثاني"),     # ضمة
    ("استقبل الملك عبداللّه الثاني اليوم", "الملك عبدالله الثاني"),     # شدة
    ("استقبل الملك عبد ﷲ الثاني الوفد", "الملك عبد الله الثاني"),       # لفظ الجلالة حرفًا واحدًا
    ("التقى جلالة الملك عبدالله الثاني ابن الحسين اليوم", "الملك عبدالله الثاني ابن الحسين"),
    ("استقبل سمو الأمير الحسين بن عبدالله الثاني ولي العهد", "الأمير الحسين بن عبدالله الثاني"),
    ("قال الدكتور محمد أحمد الخطيب توقيع الاتفاقية", "محمد أحمد الخطيب"),
    ("أكدت الشيخة مريم الصباح أن", "مريم الصباح"),
])
def test_full_names(text, expected):
    assert names(text) == [expected]


def test_same_person_one_key():
    assert entity_norm("الملك عبد الله الثاني") == entity_norm("الملك عبدالله الثاني") == entity_norm("الملك عبدُالله الثاني")


def test_reprocess_fixes_names_and_keeps_journalist_work(admin):
    from sqlalchemy import select

    from marsad.analysis.core import reprocess_entities
    from marsad.db import get_db
    from marsad.models.analysis import Entity, EntityMention
    from marsad.models.monitoring import Item, Outlet, Source
    from marsad.models.tools import Promise
    from marsad.db import utcnow

    db = next(get_db())
    o = Outlet(name="خبرني")
    db.add(o)
    db.flush()
    s = Source(outlet_id=o.id, url="https://k.example/", kind="rss", read_url="https://k.example/f")
    db.add(s)
    db.flush()
    it = Item(source_id=s.id, outlet_id=o.id, url="https://k.example/1", title="استقبل الملك عبدُالله الثاني الوفد",
              text="", captured_at=utcnow(), content_hash="x", version=1)
    db.add(it)
    bad = Entity(name="الملك عبد", norm="الملك عبد", kind="person", aliases=[])         # قديم خاطئ: يُحذف
    aliased = Entity(name="العين فلان", norm="العين فلان", kind="person", aliases=["فلان"])  # أضاف له الصحفي اسمًا بديلًا
    promised = Entity(name="وزير قديم", norm="وزير قديم", kind="person", aliases=[])     # عليه وعد متابع
    db.add_all([bad, aliased, promised])
    db.flush()
    db.add(EntityMention(entity_id=bad.id, item_id=it.id, tone=0, count=1))
    db.add(Promise(entity_id=promised.id, text="وعد"))
    db.commit()

    out = reprocess_entities(db)
    assert out["items"] == 1 and out["removed"] == 1
    have = {e.name for e in db.scalars(select(Entity))}
    assert "الملك عبد" not in have and {"الملك عبدالله الثاني", "العين فلان", "وزير قديم"} <= have
    db.close()
