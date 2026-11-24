"""نقطة تشغيل الخادم: uvicorn marsad.main:app"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from marsad.api import admin, analysis, auth, cases, claims, engines, labs, presence, ratings, reports, social, sources, org, stats, tools
from marsad.core.paths import ensure_storage
from marsad.db import get_db, get_engine, init_engine, migrate
from marsad.rbac.service import seed_builtin_roles

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _bootstrap() -> None:
    from marsad.tasks import ensure_queue_schema

    ensure_storage()
    migrate()
    ensure_queue_schema(get_engine())
    db = next(get_db())
    try:
        seed_builtin_roles(db)
        db.commit()
        _schedule_data_upgrades(db)
    finally:
        db.close()


def _schedule_data_upgrades(db) -> None:
    """ترقيات بيانات تُجرى مرة واحدة بعد تحسين البرنامج (مثل إعادة استخراج الكيانات)، في الخلفية."""
    import threading

    from sqlalchemy import select

    from marsad.analysis.core import ENTITIES_REV, reprocess_if_needed
    from marsad.models.monitoring import Item
    from marsad.monitor.pubtime import PUBTIME_REV, refresh_from_archive
    from marsad.rbac.service import get_setting, set_setting

    need_ent = int(get_setting(db, "entities_rev", 1) or 1) < ENTITIES_REV
    need_pub = int(get_setting(db, "pubtime_rev", 1) or 1) < PUBTIME_REV
    if not (need_ent or need_pub):
        return
    if db.scalar(select(Item.id).limit(1)) is None:  # قاعدة جديدة: لا شيء يُعاد
        set_setting(db, "entities_rev", ENTITIES_REV)
        set_setting(db, "pubtime_rev", PUBTIME_REV)
        db.commit()
        return

    def run() -> None:
        log = logging.getLogger(__name__)
        s = next(get_db())
        try:
            if need_pub:
                log.info("وقت النشر من الأرشيف: %s", refresh_from_archive(s))
                set_setting(s, "pubtime_rev", PUBTIME_REV)
                s.commit()
            reprocess_if_needed(s)
        except Exception:
            log.exception("فشلت ترقية البيانات")
        finally:
            s.close()

    threading.Thread(target=run, name="entities-upgrade", daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_engine()
    _bootstrap()
    worker = None
    if os.environ.get("MARSAD_EMBEDDED_WORKER") == "1":
        # نسخة الجهاز: العامل داخل عملية الخادم نفسها
        from marsad.worker import run

        worker = asyncio.create_task(run(install_signal_handlers=False))
    yield
    if worker:
        worker.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await worker


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="مرصد التحقق", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # كل طلب يغيّر شيئًا يجب أن يأتي من واجهتنا (ترويسة لا يرسلها نموذج من موقع آخر)
        bearer = request.url.path.startswith("/api/v1/") and (request.headers.get("authorization") or "").lower().startswith("bearer ")
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS \
                and request.headers.get("x-marsad") != "1" and not bearer:
            return JSONResponse({"detail": "طلب مرفوض"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        from marsad.models import SystemSetting
        from marsad.tasks import HEARTBEAT_KEY

        db = next(get_db())
        try:
            row = db.get(SystemSetting, HEARTBEAT_KEY)
            return {"ok": True, "worker_heartbeat": row.value if row else None}
        finally:
            db.close()

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(engines.router)
    app.include_router(sources.router)
    app.include_router(analysis.router)
    app.include_router(claims.router)
    app.include_router(labs.router)
    app.include_router(ratings.router)
    app.include_router(cases.router)
    app.include_router(social.router)
    app.include_router(reports.router)
    app.include_router(presence.router)
    app.include_router(stats.router)
    app.include_router(tools.router)
    app.include_router(org.router)
    app.include_router(org.v1)
    app.include_router(org.public)

    if static_dir is None:
        from marsad.core.paths import app_home

        # بالترتيب: ما يمرّره المُثبِّت، ثم الواجهة بجانب الكود (التطوير والخادم)، ثم بجانب مجلد البرنامج
        candidates = [os.environ.get("MARSAD_STATIC_DIR"),
                      Path(__file__).resolve().parents[2] / "frontend" / "dist",
                      app_home() / "frontend" / "dist"]
        static_dir = next((Path(c) for c in candidates if c and Path(c).is_dir()), Path(candidates[1]))
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):  # مسار واجهة برمجية غير موجود: 404 لا صفحة الواجهة
                return JSONResponse({"detail": "غير موجود"}, status_code=404)
            root = static_dir.resolve()
            f = (root / path).resolve()
            ok = path and f.is_file() and f.is_relative_to(root)
            return FileResponse(f if ok else root / "index.html")

    return app


app = create_app()
