"""Redis client and Redis Stream helpers.

`redis.asyncio` is used throughout. The stream is the durable event buffer;
a consumer group provides at-least-once delivery with explicit ACKs and
pending-entry recovery.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from .config import get_settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=32,
            health_check_interval=15,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def ensure_stream_and_group(stream: str, group: str) -> None:
    """Create the stream and consumer group if they do not exist yet."""
    r = get_redis()
    try:
        await r.xgroup_create(stream, group, id="0", mkstream=True)
        logger.info("Created Redis stream '%s' and group '%s'", stream, group)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            # Group already exists - normal case.
            logger.debug("Consumer group '%s' already exists", group)
        else:
            raise


async def stream_length(stream: str) -> int:
    """Approximate number of entries still buffered in the stream."""
    r = get_redis()
    try:
        return await r.xlen(stream)
    except Exception:  # noqa: BLE001 - metrics should never crash the caller
        return -1