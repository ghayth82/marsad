"""بوابة المحركات: كل مهمة ذكية تمر من هنا.

- وضع المحرك الواحد: محرك واحد (افتراضي أو لكل مهمة).
- وضع المحركات المتعددة: كل محرك ينفّذ المهمة كاملة وحده، ثم محرك دمج يقترح مخرجًا واحدًا
  مع نسبة كل معلومة لمحركها وعرض كل خلاف.
- القرار دائمًا للصحفي: لا يُعتمد مخرج دون decide()، ويُسجَّل من اعتمده ومتى.
- حد الإنفاق الشهري لكل محرك مدفوع: عند بلوغه يتوقف ويصل تنبيه.
- تعطّل محرك لا يوقف البقية.
"""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marsad import crypto
from marsad.audit import record
from marsad.db import get_db, utcnow
from marsad.engines import prompts
from marsad.engines.providers import PROVIDERS, ProviderError, complete
from marsad.models import User
from marsad.models.engines import Engine, EngineBatch, EngineDecision, EngineRun, MergeRun, Notification
from marsad.rbac.service import get_setting, set_setting
from marsad.text import similar

SETTINGS_KEY = "engines.settings"
DEFAULT_SETTINGS = {
    "mode": "single",            # single | multi
    "default_engine_id": None,
    "task_engines": {},          # المهمة ← المحرك (وضع المحرك الواحد)
    "multi_engine_ids": [],
    "merge_engine_id": None,
    "default_limit_usd": 20.0,   # حد افتراضي لكل محرك مدفوع (سؤال البناء 8)
}


class EngineError(Exception):
    pass


# ---------- الإعدادات ----------

def get_engine_settings(db: Session) -> dict:
    return {**DEFAULT_SETTINGS, **(get_setting(db, SETTINGS_KEY, {}) or {})}


def save_engine_settings(db: Session, actor: User, changes: dict) -> dict:
    cur = get_engine_settings(db)
    new = {**cur, **{k: v for k, v in changes.items() if k in DEFAULT_SETTINGS}}
    if new["mode"] not in ("single", "multi"):
        raise EngineError("الوضع إما محرك واحد أو عدة محركات")
    ids = {e.id for e in db.scalars(select(Engine))}
    for k in ("default_engine_id", "merge_engine_id"):
        if new[k] is not None and new[k] not in ids:
            raise EngineError("محرك غير موجود")
    if any(i not in ids for i in new["multi_engine_ids"]) or any(v not in ids for v in new["task_engines"].values()):
        raise EngineError("محرك غير موجود")
    if new["mode"] == "multi" and len(new["multi_engine_ids"]) < 2:
        raise EngineError("وضع المحركات المتعددة يحتاج محركين على الأقل")
    set_setting(db, SETTINGS_KEY, new, actor)
    return new


# ---------- الكلفة والحدود ----------

def _month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def month_spend(db: Session, engine_id: int) -> float:
    total = db.scalar(select(func.coalesce(func.sum(EngineRun.cost_usd), 0.0)).where(
        EngineRun.engine_id == engine_id, EngineRun.created_at >= _month_start()))
    return round(float(total or 0.0), 6)  # تشغيلات الدمج مسجّلة كتشغيلات للمحرك أيضًا


def limit_for(db: Session, e: Engine) -> float | None:
    if e.local:
        return None
    return e.monthly_limit_usd if e.monthly_limit_usd is not None else get_engine_settings(db)["default_limit_usd"]


def cost(e: Engine, tin: int, tout: int) -> float | None:
    if e.local:
        return 0.0
    if e.price_in is None or e.price_out is None:
        return None
    return round(tin / 1e6 * e.price_in + tout / 1e6 * e.price_out, 6)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)  # تقدير محافظ للعربية


def estimate(db: Session, task: str, data: dict, engine_ids: list[int]) -> dict:
    system, user = prompts.render(task, data)
    tin = estimate_tokens(system + user)
    tout = prompts.PROMPTS[task]["max_tokens"]
    rows = []
    for e in db.scalars(select(Engine).where(Engine.id.in_(engine_ids))):
        c = cost(e, tin, tout)
        lim = limit_for(db, e)
        spent = month_spend(db, e.id)
        rows.append({"engine_id": e.id, "name": e.name, "max_cost_usd": c, "spent_usd": spent, "limit_usd": lim,
                     "would_exceed": bool(lim is not None and c is not None and spent + c > lim)})
    total = sum(r["max_cost_usd"] or 0 for r in rows)
    return {"input_tokens_est": tin, "max_output_tokens": tout, "engines": rows, "max_total_usd": round(total, 6)}


def notify(db: Session, kind: str, text: str, user_id: int | None = None) -> None:
    today = _month_start().replace(day=utcnow().day)
    exists = db.scalar(select(Notification.id).where(Notification.kind == kind, Notification.text == text,
                                                     Notification.created_at >= today))
    if not exists:
        db.add(Notification(kind=kind, text=text, user_id=user_id))


# ---------- التشغيل ----------

def resolve_engines(db: Session, task: str, mode: str | None, engine_ids: list[int] | None,
                    merge_engine_id: int | None) -> tuple[str, list[int], int | None]:
    st = get_engine_settings(db)
    mode = mode or st["mode"]
    if engine_ids:
        ids = engine_ids
    elif mode == "multi":
        ids = st["multi_engine_ids"]
    else:
        one = st["task_engines"].get(task) or st["default_engine_id"]
        ids = [one] if one else []
    if not ids:
        raise EngineError("لم يُحدَّد محرك. أضف محركًا من شاشة المحركات واختره افتراضيًا.")
    if mode == "single":
        ids = ids[:1]
    merge = (merge_engine_id or st["merge_engine_id"]) if mode == "multi" else None
    return mode, ids, merge


def create_batch(db: Session, user: User, task: str, data: dict, mode: str | None = None,
                 engine_ids: list[int] | None = None, merge_engine_id: int | None = None) -> EngineBatch:
    if task not in prompts.PROMPTS:
        raise EngineError("مهمة غير معروفة")
    if not (str(data.get("text", "")).strip() or str(data.get("claim", "")).strip()):
        raise EngineError("لا يوجد نص للتحليل")
    mode, ids, merge = resolve_engines(db, task, mode, engine_ids, merge_engine_id)
    found = {e.id: e for e in db.scalars(select(Engine).where(Engine.id.in_(ids)))}
    missing = [i for i in ids if i not in found]
    if missing:
        raise EngineError("محرك غير موجود")
    disabled = [found[i].name for i in ids if not found[i].enabled]
    if disabled:
        raise EngineError(f"محرك معطّل: {'، '.join(disabled)}")
    b = EngineBatch(task=task, input=data, mode=mode, engine_ids=ids, merge_engine_id=merge, created_by=user.id)
    db.add(b)
    db.flush()
    record(db, user, "engines.run", "batch", str(b.id), None, {"task": task, "mode": mode, "engines": ids})
    return b


def _call(e: Engine, api_key: str | None, system: str, user: str, max_tokens: int) -> dict:
    t0 = time.monotonic()
    try:
        c = complete(e.provider, model=e.model, system=system, user=user, api_key=api_key,
                     base_url=e.base_url, max_tokens=max_tokens, options=e.options or {})
        return {"ok": True, "c": c, "ms": int((time.monotonic() - t0) * 1000)}
    except ProviderError as err:
        return {"ok": False, "error": str(err), "ms": int((time.monotonic() - t0) * 1000)}
    except Exception as err:  # أي عطل غير متوقع لا يوقف المحركات الأخرى
        return {"ok": False, "error": f"عطل غير متوقع: {err.__class__.__name__}", "ms": int((time.monotonic() - t0) * 1000)}


def _key(e: Engine) -> str | None:
    return crypto.decrypt(e.api_key_enc) if e.api_key_enc else None


def _run_engines(db: Session, batch: EngineBatch, engines: list[Engine], system: str, user: str,
                 max_tokens: int, prompt_id: str, prompt_version: str, task: str,
                 validate_fn) -> list[EngineRun]:
    """يشغّل المحركات معًا، ويسجّل كل تشغيل. المحرك الذي بلغ حده لا يُستدعى."""
    allowed, runs = [], []
    for e in engines:
        lim, spent = limit_for(db, e), month_spend(db, e.id)
        est = cost(e, estimate_tokens(system + user), max_tokens)
        if not e.local and est is None:
            runs.append(EngineRun(batch_id=batch.id, engine_id=e.id, engine_name=e.name, task=task, prompt_id=prompt_id,
                                  prompt_version=prompt_version, model=e.model, request={"system": system, "user": user},
                                  status="error", error="أدخل سعر هذا المحرك في شاشة المحركات ليُحسب حد الإنفاق"))
            continue
        if lim is not None and spent + (est or 0) > lim:
            runs.append(EngineRun(batch_id=batch.id, engine_id=e.id, engine_name=e.name, task=task, prompt_id=prompt_id,
                                  prompt_version=prompt_version, model=e.model, request={"system": system, "user": user},
                                  status="limit", error=f"بلغ حد الإنفاق الشهري ({lim:g} $)"))
            notify(db, "engine.limit", f"توقف المحرك «{e.name}»: بلغ حد الإنفاق الشهري ({lim:g} $).")
            continue
        try:
            key = _key(e)
        except ValueError as err:
            runs.append(EngineRun(batch_id=batch.id, engine_id=e.id, engine_name=e.name, task=task, prompt_id=prompt_id,
                                  prompt_version=prompt_version, model=e.model, request={"system": system, "user": user},
                                  status="error", error=str(err)))
            continue
        allowed.append((e, key))

    with ThreadPoolExecutor(max_workers=max(1, len(allowed))) as pool:
        futures = [(e, pool.submit(_call, e, key, system, user, max_tokens)) for e, key in allowed]
        results = [(e, f.result()) for e, f in futures]

    for e, r in results:
        run = EngineRun(batch_id=batch.id, engine_id=e.id, engine_name=e.name, task=task, prompt_id=prompt_id,
                        prompt_version=prompt_version, model=e.model, request={"system": system, "user": user},
                        duration_ms=r["ms"])
        if not r["ok"]:
            run.status, run.error = "error", r["error"]
            notify(db, "engine.error", f"تعطّل المحرك «{e.name}» أثناء مهمة؛ أكملت المحركات الأخرى. السبب: {r['error']}")
        else:
            c = r["c"]
            run.output_text, run.model_version = c.text, c.model_version
            run.input_tokens, run.output_tokens = c.input_tokens, c.output_tokens
            run.cost_usd = cost(e, c.input_tokens, c.output_tokens)
            try:
                run.output, run.status = validate_fn(prompts.parse_json(c.text)), "ok"
            except (ValueError, TypeError) as err:
                run.status, run.error = "invalid", f"مخرج غير صالح: {err}"
        runs.append(run)
    for run in runs:
        db.add(run)
    db.flush()
    return runs


def execute_batch(batch_id: int) -> None:
    """ينفّذ الطلب (يُستدعى في الخلفية). جلسة قاعدة خاصة به."""
    db = next(get_db())
    try:
        b = db.get(EngineBatch, batch_id)
        if b is None or b.status == "done":
            return
        b.status = "running"
        db.commit()
        engines = [e for e in db.scalars(select(Engine).where(Engine.id.in_(b.engine_ids)))]
        engines.sort(key=lambda e: b.engine_ids.index(e.id))
        p = prompts.PROMPTS[b.task]
        system, user = prompts.render(b.task, b.input)
        _run_engines(db, b, engines, system, user, p["max_tokens"], b.task, p["version"], b.task,
                     lambda out: prompts.validate(b.task, out))
        db.commit()
        db.refresh(b)
        if b.mode == "multi" and b.merge_engine_id:
            ok = [r for r in b.runs if r.status == "ok"]
            if len(ok) >= 2:
                merge(db, b, db.get(Engine, b.merge_engine_id))
        b.status, b.finished_at = "done", utcnow()
        db.commit()
    except Exception as err:
        db.rollback()
        b = db.get(EngineBatch, batch_id)
        if b:
            b.status, b.finished_at = "done", utcnow()
            db.add(MergeRun(batch_id=batch_id, merge_engine_name="—", source_run_ids=[], status="error",
                            error=f"عطل في التنفيذ: {err.__class__.__name__}"))
            db.commit()
        raise
    finally:
        db.close()


def merge(db: Session, b: EngineBatch, e: Engine | None) -> MergeRun:
    if e is None:
        raise EngineError("اختر محرك الدمج")
    db.refresh(b)
    ok = [r for r in b.runs if r.status == "ok" and r.task == b.task]
    outputs = {r.engine_name: r.output for r in ok}
    system, user = prompts.render_merge(b.task, b.input, outputs)
    mp = prompts.MERGE_PROMPT

    def validate_merge(out: dict) -> dict:
        final = prompts.validate(b.task, out.get("final") or {})
        return {"final": final, "attribution": out.get("attribution") or [],
                "disagreements": out.get("disagreements") or []}

    run = _run_engines(db, b, [e], system, user, mp["max_tokens"], "merge", mp["version"], "merge", validate_merge)[0]
    m = MergeRun(batch_id=b.id, engine_run_id=run.id, merge_engine_name=e.name, source_run_ids=[r.id for r in ok],
                 output=run.output, status=run.status, error=run.error)
    db.add(m)
    db.flush()
    db.refresh(b)
    return m


# ---------- المقارنة (دون محرك) ----------

def compare(b: EngineBatch) -> dict:
    """المتفق عليه والمختلف فيه، محسوبًا مباشرة من المخرجات (لا يعتمد على محرك الدمج)."""
    ok = [r for r in b.runs if r.status == "ok" and r.output and r.task == b.task]
    out: dict = {"engines": len(b.engine_ids), "succeeded": len(ok)}
    if b.task == "classify_verdict" and ok:
        votes = Counter(r.output["label"] for r in ok)
        top, n = votes.most_common(1)[0]
        tie = len([v for v in votes.values() if v == n]) > 1
        out.update({
            "votes": dict(votes),
            "agreement": round(n / len(ok), 3),
            "suggested": None if tie else top,
            "evidence": {r.engine_name: r.output["evidence"] for r in ok},
            "unanimous": len(votes) == 1,
            "disagreement": "none" if len(votes) == 1 else ("minor" if n / len(ok) >= 0.5 else "major"),
        })
        items: list[dict] = []
        for r in ok:
            for it in r.output.get("items", []):
                _group(items, f"{it.get('type', '')}: {it.get('value', '')}", r.engine_name, extra=it)
        out["items"] = _finish(items, len(ok))
    elif b.task == "extract_claims" and ok:
        items: list[dict] = []
        for r in ok:
            for c in r.output["claims"]:
                _group(items, c["text"], r.engine_name, extra=c)
        out["items"] = _finish(items, len(ok))
    return out


def _group(items: list[dict], text: str, engine: str, extra: dict) -> None:
    for g in items:
        if similar(g["text"], text) >= 0.8:
            if engine not in g["engines"]:
                g["engines"].append(engine)
            return
    items.append({"text": text, "engines": [engine], "data": extra})


def _finish(items: list[dict], n: int) -> list[dict]:
    for g in items:
        g["agreed"] = len(g["engines"]) >= 2
        g["share"] = f"{len(g['engines'])} من {n}"
    return sorted(items, key=lambda g: -len(g["engines"]))


# ---------- قرار الصحفي ----------

def decide(db: Session, user: User, b: EngineBatch, output: dict, source: str, note: str = "") -> EngineDecision:
    if b.status != "done":
        raise EngineError("انتظر انتهاء التشغيل")
    try:
        clean = prompts.validate(b.task, output)
    except ValueError as err:
        raise EngineError(str(err)) from None
    d = db.scalar(select(EngineDecision).where(EngineDecision.batch_id == b.id))
    before = None if d is None else {"output": d.output, "source": d.source}
    if d is None:
        d = EngineDecision(batch_id=b.id, output=clean, source=source, note=note, decided_by=user.id)
        db.add(d)
    else:
        d.output, d.source, d.note, d.decided_by, d.decided_at = clean, source, note, user.id, utcnow()
    record(db, user, "engines.decision", "batch", str(b.id), before, {"output": clean, "source": source})
    return d


# ---------- دقة كل محرك ----------

def accuracy(db: Session) -> list[dict]:
    """نسبة اتفاق كل محرك مع قرارات الصحفيين، لكل مهمة. للاستئناس لا للقرار."""
    stats: dict[tuple[str, str], list[int]] = {}
    for d in db.scalars(select(EngineDecision)):
        b = db.get(EngineBatch, d.batch_id)
        for r in b.runs:
            if r.status != "ok" or r.task != b.task:
                continue
            key = (r.engine_name, b.task)
            s = stats.setdefault(key, [0, 0])
            if b.task == "classify_verdict":
                s[0] += int(r.output["label"] == d.output["label"])
                s[1] += 1
            elif b.task == "extract_claims":
                accepted = [c["text"] for c in d.output["claims"]]
                for c in accepted:
                    s[1] += 1
                    s[0] += int(any(similar(c, x["text"]) >= 0.8 for x in r.output["claims"]))
    return [{"engine": k[0], "task": k[1], "task_name": prompts.PROMPTS[k[1]]["name"],
             "agree": v[0], "total": v[1], "rate": round(v[0] / v[1], 3) if v[1] else None}
            for k, v in sorted(stats.items())]


def engine_public(db: Session, e: Engine, acc: list[dict] | None = None) -> dict:
    rates = [a for a in (acc or []) if a["engine"] == e.name and a["total"]]
    agree = sum(a["agree"] for a in rates)
    total = sum(a["total"] for a in rates)
    return {"id": e.id, "name": e.name, "provider": e.provider, "provider_label": PROVIDERS.get(e.provider, {}).get("label", e.provider),
            "model": e.model, "base_url": e.base_url, "local": e.local, "has_key": bool(e.api_key_enc),
            "key_hint": e.api_key_hint, "price_in": e.price_in, "price_out": e.price_out,
            "monthly_limit_usd": e.monthly_limit_usd, "effective_limit_usd": limit_for(db, e),
            "spent_usd": month_spend(db, e.id), "enabled": e.enabled,
            "agreement": round(agree / total, 3) if total else None, "decisions": total,
            "options": {k: v for k, v in (e.options or {}).items() if not k.startswith("fake_")} if e.provider != "fake" else e.options}
