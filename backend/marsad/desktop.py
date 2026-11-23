"""نقطة تشغيل الخادم الداخلي في نسخة الجهاز (يُغلَّف بـ PyInstaller باسم marsad-server).

غلاف سطح المكتب (Tauri) يستدعيه هكذا:
    marsad-server prepare             تطبيق طلب تغيير المكان وإنشاء المجلدات، ويطبع المسارات
    marsad-server serve --port 8080   الخادم + العامل في عملية واحدة
    marsad-server migrate             الترحيلات فقط

ويمرّر له: MARSAD_HOME، MARSAD_CONFIG_DIR، MARSAD_DATABASE_URL، MARSAD_STATIC_DIR.
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marsad-server")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sub.add_parser("migrate")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    if args.cmd == "prepare":
        from marsad.core.storage_config import prepare

        return prepare()

    if args.cmd == "migrate":
        from marsad.db import get_engine, init_engine, migrate
        from marsad.tasks import ensure_queue_schema

        init_engine()
        migrate()
        ensure_queue_schema(get_engine())
        return 0

    os.environ.setdefault("MARSAD_EMBEDDED_WORKER", "1")
    os.environ.setdefault("MARSAD_MODE", "desktop")
    import uvicorn

    from marsad.main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
