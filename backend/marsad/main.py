"""نقطة تشغيل الخادم: uvicorn marsad.main:app"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from marsad.api import admin, auth
from marsad.core.paths import ensure_storage
from marsad.db import create_all, get_db, init_engine
from marsad.rbac.service import seed_builtin_roles

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _bootstrap() -> None:
    ensure_storage()
    create_all()
    db = next(get_db())
    try:
        seed_builtin_roles(db)
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_engine()
    _bootstrap()
    yield


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="مرصد التحقق", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # كل طلب يغيّر شيئًا يجب أن يأتي من واجهتنا (ترويسة لا يرسلها نموذج من موقع آخر)
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS \
                and request.headers.get("x-marsad") != "1":
            return JSONResponse({"detail": "طلب مرفوض"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    app.include_router(auth.router)
    app.include_router(admin.router)

    static_dir = static_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            root = static_dir.resolve()
            f = (root / path).resolve()
            ok = path and f.is_file() and f.is_relative_to(root)
            return FileResponse(f if ok else root / "index.html")

    return app


app = create_app()
