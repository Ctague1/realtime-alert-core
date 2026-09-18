"""Shared helpers for integration tests."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone


def make_event(
    event_type: str = "perimeter_breach",
    sensor_id: str = "sensor-001",
    site_id: str = "site-100",
    event_id: str | None = None,
    ts: str | None = None,
    confidence: float = 0.9,
) -> dict:
    return {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "sensor_id": sensor_id,
        "site_id": site_id,
        "type": event_type,
        "confidence": confidence,
        "ts": ts or datetime.now(timezone.utc).isoformat() + "Z",
    }


async def xadd_event(redis, stream: str, event: dict) -> str:
    return await redis.xadd(
        stream,
        {
            "payload": json.dumps(event, separators=(",", ":")),
            "received_at": datetime.now(timezone.utc).isoformat(),
        },
    )


async def wait_for(predicate, timeout: float = 15.0, interval: float = 0.1):
    """Poll until predicate() is truthy or the timeout expires.

    ``predicate`` may be synchronous or return an awaitable.
    """
    import asyncio

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")