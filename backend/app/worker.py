"""Processing-worker entrypoint.

Runs the Redis Streams consumer-group worker in its own process/container so
it can be restarted and scaled independently of the FastAPI backend:

    python -m app.worker
"""

from __future__ import annotations

import asyncio
import signal

from .config import get_settings
from .db import close_db_pool, init_db_pool
from .logging_config import setup_logging
from .processing.worker import ProcessingWorker
from .redis_client import close_redis, get_redis


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    await init_db_pool()
    await get_redis().ping()

    worker = ProcessingWorker()
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        asyncio.create_task(worker.stop())

    loop.add_signal_handler(signal.SIGTERM, _stop)
    loop.add_signal_handler(signal.SIGINT, _stop)

    try:
        await worker.run()
    finally:
        await close_db_pool()
        await close_redis()


if __name__ == "__main__":
    asyncio.run(main())