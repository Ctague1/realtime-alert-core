"""PostgreSQL access.

asyncpg connection pool used by the API and the processing worker. The
schema is created automatically against the configured database so the whole
system works from a clean checkout.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import asyncpg

from .config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


def _find_schema() -> Path:
    """Locate database/migrations/init.sql relative to this file.

    Works both in the repository layout (backend/app/db.py with database/
    a sibling of backend/) and the container layout (/app/app/db.py with
    database/ under /app/), by searching upwards from this module.
    """
    override = os.getenv("SENTINEL_SCHEMA_PATH")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        candidate = parent / "database" / "migrations" / "init.sql"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not locate database/migrations/init.sql; set SENTINEL_SCHEMA_PATH"
    )


async def _register_codecs(conn: asyncpg.Connection) -> None:
    """Decode jsonb columns into native Python objects."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def init_db_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=settings.pg_dsn,
        min_size=settings.pg_pool_min,
        max_size=settings.pg_pool_max,
        command_timeout=30,
        init=_register_codecs,
    )
    await apply_schema(_pool)
    logger.info("PostgreSQL pool ready (db=%s)", settings.pg_db)
    return _pool


async def get_db_pool() -> asyncpg.Pool:
    if _pool is None:
        return await init_db_pool()
    return _pool


async def apply_schema(pool: asyncpg.Pool) -> None:
    """Apply init.sql idempotently (all statements use IF NOT EXISTS)."""
    schema = _find_schema()
    sql = schema.read_text()
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def close_db_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None