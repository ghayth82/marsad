"""نقطة تشغيل الخادم الداخلي في نسخة الجهاز (يُغلَّف بـ PyInstaller باسم marsad-server).

غلاف سطح المكتب (Tauri) يستدعيه هكذا:
    marsad-server prepare             تطبيق طلب تغيير المكان وإنشاء المجلدات، ويطبع المسارات
    marsad-server serve --port 8080   الخادم + العامل في عملية واحدة
    marsad-server migrate             الترحيلات فقط
    marsad-server transfer export|import ملف   ملف النقل إلى خادم أو جهاز آخر

ويمرّر له: MARSAD_HOME، MARSAD_CONFIG_DIR، MARSAD_DATABASE_URL، MARSAD_STATIC_DIR.
"""

from __future__ import annotations

import argparse
import os
import sys


def _utf8_streams() -> None:
    """غلاف سطح المكتب يقرأ المخرجات UTF-8، وويندوز يجعلها cp1252 حين تُحوَّل إلى ملف أو أنبوب،
    فتفشل طباعة أي مسار عربي (مثل «النسخ الاحتياطي»). نفرض UTF-8 على المخرجين."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    parser = argparse.ArgumentParser(prog="marsad-server")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sub.add_parser("migrate")
    tr = sub.add_parser("transfer")
    tr.add_argument("action", choices=["export", "import"])
    tr.add_argument("file")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    if args.cmd == "prepare":
        from marsad.core.storage_config import prepare

        return prepare()

    if args.cmd == "transfer":
        from marsad.transfer import main as transfer_main

        return transfer_main([args.action, args.file])

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
