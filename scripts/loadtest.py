"""قياس أداء «مرصد التحقق» مع حجم بيانات كبير: مساحة القاعدة والفهرس وزمن البحث والتصفح.

يملأ قاعدة PostgreSQL تجريبية بأخبار مصطنعة على مراحل (مثلًا 100 ألف ثم 500 ألف ثم مليون)، ويقيس بعد كل مرحلة:
المساحة (القاعدة بجداولها وفهارسها، وفهرس Meilisearch)، وزمن طلبات الواجهة الفعلية (بحث، تصفح، فتح خبر،
ادّعاءات، كيانات، قصص) عبر Meilisearch وعبر القاعدة وحدها.

لا يمس بيانات حقيقية: يعمل على قاعدة وفهرس يُحددان صراحةً ويُفرَّغان في البداية.

    python scripts/loadtest.py --db postgresql+psycopg://... --meili http://127.0.0.1:7700 \
        --phases 100000,500000,1000000 --out loadtest-report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# كلمات شائعة في الأخبار العربية (تتكرر بتوزيع زيف كما في النصوص الحقيقية)، وأسماء نادرة مصطنعة
COMMON = """الحكومة الوزير وزارة الأردن عمان المملكة رئيس الوزراء مجلس النواب الأعيان الملك القرار المشروع القانون الأسعار
الاقتصاد البنك المركزي التضخم الموازنة الضريبة الدعم الطاقة الكهرباء المياه النفط الغاز الوقود المحروقات التعليم المدارس
الجامعات الطلبة الامتحانات الصحة المستشفيات الأطباء الدواء الأدوية اللقاح الفيروس المرضى الطريق السير الحوادث الأمن الشرطة
الدفاع المدني الجيش الحدود اللاجئين سوريا العراق فلسطين غزة القدس مصر السعودية الإمارات قطر الكويت لبنان أمريكا روسيا الصين
أوروبا الأمم المتحدة الجامعة العربية المؤتمر الاجتماع الزيارة الاتفاقية المفاوضات الانتخابات البلدية النقابة العمال البطالة الرواتب
الأجور المتقاعدين الاستثمار المشاريع الشركة الشركات القطاع الخاص العام السياحة الزراعة المزارعين الأمطار الطقس المنخفض الحرارة
الثلوج الرياح الغبار المحافظة إربد الزرقاء العقبة الكرك معان المفرق جرش عجلون مادبا الطفيلة البلقاء السلط أعلن أكد قال أشار
أوضح بين كشف نفى دعا طالب حذر أعلنت أكدت قالت أشارت أوضحت بينت كشفت نفت دعت طالبت حذرت اليوم أمس غدا الأسبوع الشهر العام
الماضي المقبل الجاري خلال بعد قبل منذ حتى على في من إلى عن مع بين أن إن كان كانت يكون تكون هذا هذه ذلك تلك التي الذي الذين
وقد قد لم لن لا ما كما أيضا حيث إذ إلا غير كل بعض جميع عدد نحو حوالي أكثر أقل ألف مليون مليار دينار دولار نسبة بالمئة ارتفاع
انخفاض زيادة تراجع نمو أزمة خطة برنامج مبادرة حملة تقرير دراسة بيان مصدر مصادر مسؤول مسؤولون خبراء مواطنين المواطنين الشارع
الرأي العام وسائل الإعلام مواقع التواصل منصة فيديو صورة شائعة شائعات تحقق مضلل كاذب صحيح الحقيقة""".split()

LETTERS = "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"


def build_vocab(rng: np.random.Generator, n_rare: int = 60000) -> tuple[list[str], list[str]]:
    rare = set()
    while len(rare) < n_rare:
        k = int(rng.integers(4, 8))
        rare.add("".join(LETTERS[int(i)] for i in rng.integers(0, len(LETTERS), k)))
    return COMMON, sorted(rare)


def zipf_probs(n: int, s: float = 1.07) -> np.ndarray:
    p = 1.0 / np.arange(1, n + 1) ** s
    return p / p.sum()


class Gen:
    """نصوص مصطنعة بطول خبر حقيقي تقريبًا (نحو 330 كلمة، نحو ألفي حرف)."""

    def __init__(self, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self.common, self.rare = build_vocab(self.rng)
        self.pc = zipf_probs(len(self.common))
        self.pr = zipf_probs(len(self.rare), 0.9)

    def words(self, n: int) -> list[str]:
        k_rare = int(self.rng.binomial(n, 0.12))
        c = self.rng.choice(len(self.common), n - k_rare, p=self.pc)
        r = self.rng.choice(len(self.rare), k_rare, p=self.pr)
        w = [self.common[i] for i in c] + [self.rare[i] for i in r]
        self.rng.shuffle(w)
        return w

    def text(self, n: int = 330) -> str:
        return " ".join(self.words(n))


# ---------- التحميل ----------

def copy_rows(conn, table: str, cols: list[str], rows) -> None:
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)


def load_phase(conn, gen: Gen, start: int, end: int, n_outlets: int, now: datetime, log) -> None:
    """يضيف المواد من start إلى end (أرقامها)، ومعها نسخها وقصصها وادّعاءاتها وكياناتها بنسب واقعية."""
    from marsad.text import normalize_ar

    span = timedelta(days=3 * 365)
    batch = 10000
    t0 = time.time()
    for b in range(start, end, batch):
        hi = min(b + batch, end)
        items, versions = [], []
        for i in range(b + 1, hi + 1):
            title = " ".join(gen.words(int(gen.rng.integers(7, 13))))
            text = gen.text()
            norm = normalize_ar(f"{title} {text}")
            o = (i % n_outlets) + 1
            at = now - span * (1 - i / end) - timedelta(seconds=int(gen.rng.integers(0, 600)))
            h = hashlib.sha256(norm.encode()).hexdigest()
            sid = (i // 5) + 1  # نحو خمس مواد لكل قصة
            items.append((i, o, o, f"https://site{o}.example/news/{i}", title, text, "", "ar", at, at, "[]", "live", h, 1,
                          norm, sid, "{}"))
            versions.append((i, i, 1, "new", title, text, h, "", "", at))
        with conn.transaction():
            copy_rows(conn, "items", ["id", "source_id", "outlet_id", "url", "title", "text", "author", "language", "published_at",
                                      "captured_at", "media", "status", "content_hash", "version", "norm", "story_id", "meta"], items)
            copy_rows(conn, "item_versions", ["id", "item_id", "version", "change", "title", "text", "content_hash", "archive_path",
                                              "archive_sha256", "captured_at"], versions)
            # القصص: واحدة لكل خمس مواد
            s_lo, s_hi = (b // 5) + 1, (hi // 5) + 1
            stories = []
            for sid in range(s_lo, s_hi + 1):
                title = " ".join(gen.words(int(gen.rng.integers(6, 11))))
                at = now - span * (1 - min(sid * 5, end) / end)
                stories.append((sid, title, normalize_ar(title), sid * 5, 5, int(gen.rng.integers(1, 6)), at, at, False))
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM stories")
                have = cur.fetchone()[0]
            copy_rows(conn, "stories", ["id", "title", "norm", "first_item_id", "item_count", "source_count", "created_at", "updated_at",
                                        "locked"], [s for s in stories if s[0] > have])
            # ادّعاء لكل عشرين مادة
            claims = []
            for cid in range(b // 20 + 1, hi // 20 + 1):
                t = " ".join(gen.words(int(gen.rng.integers(12, 25))))
                at = now - span * (1 - cid * 20 / end)
                claims.append((cid, t, normalize_ar(t), "", "new", "auto", cid * 20, "[]", "{}", at, "normal"))
            copy_rows(conn, "claims", ["id", "text", "norm", "speaker", "status", "origin", "first_item_id", "tags", "meta", "created_at",
                                       "priority"], claims)
            # كيان لكل عشر مواد، وثلاث إشارات لكل مادة
            ents = []
            for eid in range(b // 10 + 1, hi // 10 + 1):
                name = " ".join(gen.rare[int(x)] for x in gen.rng.integers(0, len(gen.rare), 2))
                ents.append((eid, name, f"{normalize_ar(name)} {eid}", ["person", "org", "place"][eid % 3], "[]", True, now))
            copy_rows(conn, "entities", ["id", "name", "norm", "kind", "aliases", "is_public", "created_at"], ents)
            ment = []
            top = max(hi // 10, 1)
            for i in range(b + 1, hi + 1):
                for e in set(int(x) for x in gen.rng.zipf(1.6, 3) % top + 1):
                    ment.append((e, i, 0.0, 1))
            copy_rows(conn, "entity_mentions", ["entity_id", "item_id", "tone", "count"], ment)
        log(f"  {hi:,} مادة ({(hi - start) / max(time.time() - t0, 1e-6):,.0f} مادة/ث)")
    with conn.cursor() as cur:
        for t in ("items", "item_versions", "stories", "claims", "entities", "entity_mentions"):
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT MAX(id) FROM {t}))")
        cur.execute("ANALYZE")
    conn.commit()


# ---------- الفهرسة في Meilisearch ----------

def meili_wait(base: str, h: dict, http, since: str | None = None) -> None:
    """ينتظر انتهاء المهام. since: يُفحص الفشل فيما أُضيف بعده فقط (حذف فهرس غير موجود في البداية ليس فشلًا)."""
    while True:
        r = http.get(f"{base}/tasks", headers=h, params={"statuses": "enqueued,processing", "limit": 1}).json()
        if not r.get("results"):
            if since is None:
                return
            failed = http.get(f"{base}/tasks", headers=h, params={"statuses": "failed", "limit": 3, "afterEnqueuedAt": since}).json().get("results")
            if failed:
                raise SystemExit(f"فشلت فهرسة Meilisearch: {failed[0].get('error')}")
            return
        time.sleep(1)


def meili_index(conn, base: str, h: dict, http, kind: str, sql: str, lo: int, hi: int, to_doc) -> float:
    from marsad import search

    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    http.post(f"{base}/indexes", headers=h, json={"uid": kind, "primaryKey": "id"})
    http.patch(f"{base}/indexes/{kind}/settings", headers=h, json=search.INDEXES[kind]["settings"])
    t0 = time.time()
    with conn.cursor(name=f"cur_{kind}_{lo}") as cur:
        cur.itersize = 20000
        cur.execute(sql, (lo, hi))
        buf = []
        for row in cur:
            buf.append(to_doc(row))
            if len(buf) >= 20000:
                http.post(f"{base}/indexes/{kind}/documents", headers={**h, "Content-Type": "application/json"}, content=json.dumps(buf, ensure_ascii=False).encode(),
                          timeout=300)
                buf = []
        if buf:
            http.post(f"{base}/indexes/{kind}/documents", headers={**h, "Content-Type": "application/json"}, content=json.dumps(buf, ensure_ascii=False).encode(), timeout=300)
    meili_wait(base, h, http, since)
    return time.time() - t0


# ---------- القياس ----------

def timed(client, url: str, params: dict | None = None, reps: int = 5) -> dict:
    ms, n = [], None
    for _ in range(reps):
        t = time.perf_counter()
        r = client.get(url, params=params)
        ms.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 200, (url, r.status_code, r.text[:300])
        j = r.json()
        n = j.get("total") if isinstance(j, dict) else len(j)
    return {"median_ms": round(statistics.median(ms)), "max_ms": round(max(ms)), "results": n}


def sizes(conn, base: str | None, h: dict, http) -> dict:
    out = {}
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database())")
        out["db_total"] = cur.fetchone()[0]
        cur.execute("""SELECT relname, pg_total_relation_size(c.oid), pg_relation_size(c.oid), pg_indexes_size(c.oid)
                       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 2 DESC LIMIT 8""")
        out["tables"] = [{"table": r[0], "total": r[1], "data": r[2], "indexes": r[3]} for r in cur.fetchall()]
        cur.execute("SELECT indexrelname, pg_relation_size(indexrelid) FROM pg_stat_user_indexes WHERE indexrelname LIKE '%trgm'")
        out["trgm"] = dict(cur.fetchall())
    if base:
        out["meili"] = http.get(f"{base}/stats", headers=h).json().get("databaseSize")
    return out


def explain(conn, sql: str, arg: str) -> str:
    with conn.cursor() as cur:
        cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + sql, (arg,))
        plan = cur.fetchone()[0][0]
    def walk(p):
        yield p.get("Node Type", "") + (f" ({p['Index Name']})" if p.get("Index Name") else "")
        for c in p.get("Plans", []):
            yield from walk(c)
    return f"{round(plan['Execution Time'])} ms · " + " → ".join(walk(plan["Plan"]))


def gb(b) -> str:
    return f"{b / 2**30:.2f} غ.ب" if b >= 2**30 else f"{b / 2**20:.0f} م.ب"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--meili", default="")
    ap.add_argument("--meili-key", default="")
    ap.add_argument("--phases", default="100000,500000,1000000")
    ap.add_argument("--out", default="loadtest-report.md")
    a = ap.parse_args()
    phases = [int(x) for x in a.phases.split(",")]

    home = Path(tempfile.mkdtemp(prefix="marsad-load-"))
    os.environ.update({"MARSAD_HOME": str(home), "MARSAD_DATABASE_URL": a.db, "MARSAD_SECRET_KEY": "loadtest-" + "x" * 40})
    os.environ.pop("MARSAD_MEILI_URL", None)
    import httpx
    import psycopg

    from marsad import search
    from marsad.db import init_engine
    from marsad.migrate import upgrade

    log = lambda m: print(m, flush=True)  # noqa: E731
    engine = init_engine()
    with engine.begin() as c:  # قاعدة تجريبية فارغة
        c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    upgrade(engine)
    dsn = a.db.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(dsn)
    now = datetime.now(timezone.utc)
    n_outlets = 100
    with conn.transaction():
        copy_rows(conn, "outlets", ["id", "name", "kind", "country", "website", "logo_url", "tags", "transparency", "created_at"],
                  [(o, f"موقع إخباري {o}", "news", "الأردن", f"https://site{o}.example", "", "[]", "{}", now) for o in range(1, n_outlets + 1)])
        copy_rows(conn, "sources", ["id", "outlet_id", "url", "kind", "read_url", "title", "tags", "check_minutes", "active", "status",
                                    "last_error", "consecutive_errors", "meta", "created_at"],
                  [(o, o, f"https://site{o}.example/feed", "rss", "", f"موقع {o}", "[]", 15, True, "ok", "", 0, "{}", now)
                   for o in range(1, n_outlets + 1)])
        with conn.cursor() as cur:  # ترقيات البيانات والفهرسة عند البدء لا تعمل أثناء القياس
            for k, v in (("entities_rev", 99), ("pubtime_rev", 99), ("storage_rev", 99), ("search_rev", search.SEARCH_REV)):
                cur.execute("INSERT INTO system_settings (key, value, updated_at) VALUES (%s, %s, now())", (k, json.dumps(v)))

    from fastapi.testclient import TestClient

    from marsad.main import create_app

    client = TestClient(create_app(), base_url="http://localhost", headers={"X-Marsad": "1"})
    client.__enter__()
    r = client.post("/api/setup", json={"email": "load@example.com", "password": "load-test-pass-1", "full_name": "قياس"})
    assert r.status_code == 200, r.text

    base = a.meili.rstrip("/") if a.meili else None
    h = {"Authorization": f"Bearer {a.meili_key}"} if a.meili_key else {}
    http = httpx.Client(timeout=120)
    if base:
        for kind in search.INDEXES:
            http.delete(f"{base}/indexes/{kind}", headers=h)
        meili_wait(base, h, http)

    gen = Gen()
    common_q, mid_q = "الحكومة", "الامتحانات"
    rare_q = gen.rare[500]  # اسم نادر: يظهر في مواد قليلة
    two_q = "أسعار الأدوية"
    results = []
    done = 0
    for target in phases:
        log(f"المرحلة: {target:,} مادة")
        t = time.time()
        load_phase(conn, gen, done, target, n_outlets, now, log)
        load_s = time.time() - t
        idx = {}
        if base:
            ts = lambda d: int(d.timestamp()) if d else None  # noqa: E731
            idx["items"] = meili_index(conn, base, h, http, "items",
                                       "SELECT id, title, norm, source_id, outlet_id, status, published_at, captured_at, story_id FROM items WHERE id > %s AND id <= %s ORDER BY id",
                                       done, target, lambda r: {"id": r[0], "norm_title": search.normalize_ar(r[1]), "norm": r[2][:20000],
                                                                "source_id": r[3], "outlet_id": r[4], "status": r[5],
                                                                "published_ts": ts(r[6]), "captured_ts": ts(r[7]), "story_id": r[8]})
            idx["claims"] = meili_index(conn, base, h, http, "claims", "SELECT id, norm, status, created_at FROM claims WHERE id > %s AND id <= %s",
                                        done // 20, target // 20, lambda r: {"id": r[0], "norm": r[1], "speaker": "", "status": r[2], "created_ts": ts(r[3])})
            idx["entities"] = meili_index(conn, base, h, http, "entities", "SELECT id, norm, kind FROM entities WHERE id > %s AND id <= %s",
                                          done // 10, target // 10, lambda r: {"id": r[0], "norm": r[1], "aliases": [], "kind": r[2]})
            idx["stories"] = meili_index(conn, base, h, http, "stories",
                                         "SELECT id, norm, item_count, source_count, updated_at FROM stories WHERE id > %s AND id <= %s",
                                         done // 5, target // 5 + 1, lambda r: {"id": r[0], "norm": r[1], "item_count": r[2], "source_count": r[3], "updated_ts": ts(r[4])})
        done = target
        log("  القياس…")
        m = {}

        def both(label, url, params):
            if base:
                os.environ["MARSAD_MEILI_URL"], os.environ["MARSAD_MEILI_KEY"] = base, a.meili_key
                m[label + " · Meilisearch"] = timed(client, url, params)
            os.environ.pop("MARSAD_MEILI_URL", None)
            m[label + " · القاعدة وحدها"] = timed(client, url, params, reps=3)

        both("بحث الأخبار: كلمة شائعة جدًا", "/api/items", {"q": common_q, "limit": 50})
        both("بحث الأخبار: كلمة متوسطة", "/api/items", {"q": mid_q, "limit": 50})
        both("بحث الأخبار: اسم نادر", "/api/items", {"q": rare_q, "limit": 50})
        both("بحث الأخبار: كلمتان", "/api/items", {"q": two_q, "limit": 50})
        both("بحث الأخبار: كلمة + موقع واحد", "/api/items", {"q": mid_q, "outlet_id": 7, "limit": 50})
        both("بحث الادّعاءات", "/api/claims", {"q": mid_q, "limit": 50})
        with conn.cursor() as cur:  # اسم كيان موجود فعلًا (كلمته الأولى)
            cur.execute("SELECT name FROM entities WHERE id = %s", (max(target // 20, 1),))
            ent_q = cur.fetchone()[0].split()[0]
        both("بحث الكيانات", "/api/entities", {"q": ent_q, "limit": 50})
        both("بحث القصص", "/api/stories", {"q": mid_q, "limit": 40})
        os.environ.pop("MARSAD_MEILI_URL", None)
        m["تصفح أحدث الأخبار (الصفحة الأولى)"] = timed(client, "/api/items", {"limit": 50})
        m["تصفح الأخبار: الصفحة 100"] = timed(client, "/api/items", {"limit": 50, "offset": 4950})
        m["تصفح أخبار موقع واحد"] = timed(client, "/api/items", {"limit": 50, "outlet_id": 7})
        m["تصفح الأخبار بفترة شهر"] = timed(client, "/api/items", {"limit": 50, "date_from": (now - timedelta(days=60)).isoformat(),
                                                                   "date_to": (now - timedelta(days=30)).isoformat()})
        m["فتح خبر واحد"] = timed(client, f"/api/items/{target // 2}")
        m["قائمة الكيانات الأكثر ذكرًا"] = timed(client, "/api/entities", {"limit": 50}, reps=3)
        m["قائمة القصص"] = timed(client, "/api/stories", {"limit": 40})
        m["قائمة الادّعاءات"] = timed(client, "/api/claims", {"limit": 50})
        plans = {
            "بحث الادّعاءات في القاعدة": explain(conn, "SELECT id FROM claims WHERE norm LIKE '%%' || %s || '%%' ORDER BY created_at DESC LIMIT 50", mid_q),
            "بحث الأخبار في القاعدة": explain(conn, "SELECT id FROM items WHERE norm LIKE '%%' || %s || '%%' ORDER BY captured_at DESC, id DESC LIMIT 50", rare_q),
        }
        sz = sizes(conn, base, h, http)
        results.append({"items": target, "load_s": round(load_s), "index_s": {k: round(v) for k, v in idx.items()}, "sizes": sz,
                        "timings": m, "plans": plans})
        log(json.dumps(results[-1], ensure_ascii=False, indent=1))

    client.__exit__(None, None, None)
    report = render(results, bool(base))
    Path(a.out).write_text(report, encoding="utf-8")
    Path(a.out).with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report)
    return 0


def machine() -> str:
    ram = ""
    try:
        kb = int(next(x for x in open("/proc/meminfo") if x.startswith("MemTotal")).split()[1])
        ram = f"، ذاكرة {kb / 2**20:.0f} غ.ب"
    except (OSError, StopIteration, ValueError):
        pass
    return f"الجهاز: {os.cpu_count()} أنوية{ram}، PostgreSQL وMeilisearch على الجهاز نفسه."


def render(results: list[dict], meili: bool) -> str:
    lines = ["# قياس الأداء مع حجم بيانات كبير", "", machine(), "",
             "بيانات مصطنعة: كل خبر نحو 330 كلمة (نحو ألفي حرف)، ومعه نسخته الأولى، وقصة لكل خمسة أخبار، "
             "وادّعاء لكل عشرين، وكيان لكل عشرة، وثلاث إشارات إلى كيانات في كل خبر. الصفحات المؤرشفة والصور لا تدخل في القياس.", ""]
    cols = [f"{r['items']:,} خبر" for r in results]
    lines += ["## المساحة", "", "| | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    lines.append("| قاعدة البيانات كاملة | " + " | ".join(gb(r["sizes"]["db_total"]) for r in results) + " |")
    if meili:
        lines.append("| فهرس Meilisearch | " + " | ".join(gb(r["sizes"].get("meili") or 0) for r in results) + " |")
    lines.append("| منها فهارس البحث النصي (pg_trgm) | " + " | ".join(gb(sum(r["sizes"]["trgm"].values())) for r in results) + " |")
    lines.append("| زمن إدخال المرحلة | " + " | ".join(f"{r['load_s']} ث" for r in results) + " |")
    if meili:
        lines.append("| زمن فهرسة الأخبار الجديدة | " + " | ".join(f"{r['index_s'].get('items', 0)} ث" for r in results) + " |")
    lines += ["", "## زمن الاستجابة (الوسيط بالمللي ثانية، وبين قوسين عدد النتائج)", "",
              "| الطلب | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for k in results[0]["timings"]:
        lines.append(f"| {k} | " + " | ".join(f"{r['timings'][k]['median_ms']} ({r['timings'][k]['results']})" for r in results) + " |")
    lines += ["", "## خطط التنفيذ في PostgreSQL (هل يُستعمل فهرس البحث النصي؟)", ""]
    for r in results:
        for k, v in r["plans"].items():
            lines.append(f"- {r['items']:,} · {k}: {v}")
    lines += ["", "## أكبر الجداول عند آخر مرحلة", "", "| الجدول | الكل | البيانات | الفهارس |", "|---|---|---|---|"]
    for t in results[-1]["sizes"]["tables"]:
        lines.append(f"| {t['table']} | {gb(t['total'])} | {gb(t['data'])} | {gb(t['indexes'])} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
