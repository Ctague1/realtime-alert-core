"""Shared pytest fixtures.

Before any test runs, environment variables are pointed at the local test
infrastructure (Redis on db 1, a dedicated ``sentinel_test`` database) and
the settings singleton is rebuilt so every import sees the test
configuration.
"""

from __future__ import annotations

import asyncio
import os
import socket

import pytest
import pytest_asyncio
import uvicorn

os.environ.setdefault("PGHOST", "localhost")
os.environ.setdefault("PGPORT", "5433")
os.environ.setdefault("PGDATABASE", "sentinel_test")
os.environ.setdefault("PGUSER", "sentinel")
os.environ.setdefault("PGPASSWORD", "sentinel")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("HEARTBEAT_OFFLINE_TIMEOUT", "30")
# The API server test fixture must not try to ingest from a sensor stream.
os.environ.setdefault("SENSOR_INGESTION_ENABLED", "false")

from app.config import reload_settings  # noqa: E402
from app.db import close_db_pool, init_db_pool  # noqa: E402
from app.metrics import reset_metrics  # noqa: E402
from app.redis_client import close_redis, get_redis  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

setup_logging("WARNING")
reload_settings()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def infrastructure():
    await init_db_pool()
    await get_redis().flushdb()
    yield
    await close_db_pool()
    await close_redis()


@pytest_asyncio.fixture(autouse=True)
async def clean_state():
    """Reset DB + Redis + metrics before every test."""
    reset_metrics()
    from app.db import get_db_pool

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE correlations, alarms, events, sensors, sites RESTART IDENTITY CASCADE"
        )
    await get_redis().flushdb()
    yield


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture
async def api_server():
    """A real uvicorn server on the test event loop (full app lifespan)."""
    from app.main import create_app

    app = create_app()
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        await asyncio.sleep(0.05)
        if server.started:
            break
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass