"""Shared pytest fixtures.

Before any test runs, environment variables are pointed at the local test
infrastructure (Redis on db 1, a dedicated ``sentinel_test`` database) and
the settings singleton is rebuilt so every import sees the test
configuration.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

os.environ.setdefault("PGHOST", "localhost")
os.environ.setdefault("PGPORT", "5433")
os.environ.setdefault("PGDATABASE", "sentinel_test")
os.environ.setdefault("PGUSER", "sentinel")
os.environ.setdefault("PGPASSWORD", "sentinel")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("HEARTBEAT_OFFLINE_TIMEOUT", "30")

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
        await conn.execute("TRUNCATE alarms, events, sensors, sites RESTART IDENTITY CASCADE")
    await get_redis().flushdb()
    yield