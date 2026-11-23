"""العامل المستقل (نسخة الخادم): python -m marsad.worker"""

from __future__ import annotations

import asyncio
import logging

from marsad.core.paths import ensure_storage
from marsad.db import get_engine, init_engine, migrate
from marsad.tasks import build_app, ensure_queue_schema

log = logging.getLogger("marsad.worker")


async def run(app=None, **options) -> None:
    app = app or build_app()
    async with app.open_async():
        await app.run_worker_async(**options)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ensure_storage()
    init_engine()
    migrate()
    ensure_queue_schema(get_engine())
    asyncio.run(run(install_signal_handlers=True))


if __name__ == "__main__":
    main()
