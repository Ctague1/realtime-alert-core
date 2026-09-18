"""End-to-end pipeline integration tests (Redis Streams -> worker -> PostgreSQL).

These run the real worker loop against the real Redis + PostgreSQL used by
the test suite, verifying the durability/at-least-once/idempotency contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from app.config import get_settings
from app.db import get_db_pool
from app.metrics import get_metrics
from app.processing.worker import ProcessingWorker
from app.redis_client import get_redis
from app.services import state_service

from .helpers import make_event, wait_for, xadd_event


@contextlib.asynccontextmanager
async def worker_running():
    settings = get_settings()
    worker = ProcessingWorker()
    task = asyncio.create_task(worker.run())
    # Give the worker time to start reading.
    await asyncio.sleep(0.3)
    try:
        yield worker
    finally:
        await worker.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


async def count_events() -> int:
    pool = await get_db_pool()
    return await pool.fetchval("SELECT count(*) FROM events")


async def count_alarms() -> int:
    pool = await get_db_pool()
    return await pool.fetchval("SELECT count(*) FROM alarms")


def _ge(coro_loader, n):
    async def _pred():
        return (await coro_loader()) >= n

    return _pred


async def _pending(settings) -> int:
    r = get_redis()
    return (await r.xpending(settings.stream_name, settings.group_name))["pending"]


def _pending_zero(settings):
    async def _pred() -> bool:
        return (await _pending(settings)) == 0

    return _pred


async def fetch_event(event_id: str):
    pool = await get_db_pool()
    return await pool.fetchrow("SELECT * FROM events WHERE event_id = $1", event_id)


async def fetch_alarm(event_id: str):
    pool = await get_db_pool()
    return await pool.fetchrow("SELECT * FROM alarms WHERE event_id = $1", event_id)


@pytest.mark.integration
async def test_happy_path_event_reaches_postgres():
    settings = get_settings()
    r = get_redis()
    event = make_event()
    await xadd_event(r, settings.stream_name, event)

    async with worker_running():
        await wait_for(_ge(count_events, 1))

    row = await fetch_event(event["event_id"])
    assert row is not None
    assert row["event_id"] == event["event_id"]
    assert row["type"] == "perimeter_breach"
    assert row["severity"] == "high"
    assert row["processed_at"] is not None
    assert row["raw"]["sensor_id"] == event["sensor_id"]


@pytest.mark.integration
async def test_alarm_and_site_sensor_state_created():
    settings = get_settings()
    r = get_redis()
    event = make_event(event_type="fire_alarm", sensor_id="sensor-007", site_id="site-105")
    await xadd_event(r, settings.stream_name, event)

    async with worker_running():
        await wait_for(_ge(count_alarms, 1))

    pool = await get_db_pool()
    alarm = await pool.fetchrow("SELECT * FROM alarms WHERE event_id = $1", event["event_id"])
    assert alarm["status"] == "ACTIVE"
    assert alarm["severity"] == "critical"

    # Site state is rebuilt by the periodic aggregation task.
    await state_service.recompute_all_sites(pool)
    site = await pool.fetchrow("SELECT * FROM sites WHERE site_id = 'site-105'")
    assert site["active_alarm_count"] == 1
    assert site["highest_active_severity"] == "critical"

    sensor = await pool.fetchrow("SELECT * FROM sensors WHERE sensor_id = 'sensor-007'")
    assert sensor["online"] is True
    assert sensor["latest_event_type"] == "fire_alarm"


@pytest.mark.integration
async def test_duplicate_event_id_is_idempotent():
    settings = get_settings()
    r = get_redis()
    event = make_event(sensor_id="sensor-010", site_id="site-110")

    async with worker_running():
        await xadd_event(r, settings.stream_name, event)
        await wait_for(_ge(count_events, 1))
        # Deliver the same event_id twice more (duplicate + retry).
        await xadd_event(r, settings.stream_name, event)
        await xadd_event(r, settings.stream_name, event)
        await asyncio.sleep(1.0)

    assert await count_events() == 1
    assert await count_alarms() == 1
    assert get_metrics().snapshot()["counters"]["duplicates_detected"] >= 2


@pytest.mark.integration
async def test_heartbeat_updates_sensor_but_creates_no_alarm():
    settings = get_settings()
    r = get_redis()
    event = make_event(event_type="heartbeat", sensor_id="sensor-020", site_id="site-120")
    await xadd_event(r, settings.stream_name, event)

    async with worker_running():
        await wait_for(_ge(count_events, 1))

    assert await count_alarms() == 0
    pool = await get_db_pool()
    sensor = await pool.fetchrow("SELECT * FROM sensors WHERE sensor_id = 'sensor-020'")
    assert sensor["last_heartbeat_ts"] is not None
    assert sensor["online"] is True
    assert get_metrics().snapshot()["counters"]["events_heartbeat"] >= 1


@pytest.mark.integration
async def test_worker_restart_recovers_pending_messages():
    """Simulate a worker crash: add events, run a worker that ACKs nothing,
    then start a fresh worker that must reclaim via XAUTOCLAIM."""
    # Shorten the claim idle window so the test runs quickly; recovery still
    # exercises the real XAUTOCLAIM path.
    import os

    old_idle = os.environ.get("PENDING_CLAIM_IDLE_MS")
    old_interval = os.environ.get("PENDING_CLAIM_INTERVAL")
    os.environ["PENDING_CLAIM_IDLE_MS"] = "1000"
    os.environ["PENDING_CLAIM_INTERVAL"] = "0.5"
    from app.config import reload_settings

    reload_settings()
    try:
        await _run_restart_scenario()
    finally:
        if old_idle is None:
            os.environ.pop("PENDING_CLAIM_IDLE_MS", None)
        else:
            os.environ["PENDING_CLAIM_IDLE_MS"] = old_idle
        if old_interval is None:
            os.environ.pop("PENDING_CLAIM_INTERVAL", None)
        else:
            os.environ["PENDING_CLAIM_INTERVAL"] = old_interval
        reload_settings()


async def _run_restart_scenario():
    settings = get_settings()
    r = get_redis()

    class FailingWorker(ProcessingWorker):
        async def _process_entries(self, entries, is_retry=False):
            # Simulates a crash before ACK - leave the messages pending.
            return None

    failing = FailingWorker()
    task = asyncio.create_task(failing.run())
    await asyncio.sleep(0.3)
    events = [make_event(sensor_id="sensor-030", site_id="site-130") for _ in range(5)]
    for ev in events:
        await xadd_event(r, settings.stream_name, ev)
    await asyncio.sleep(1.0)
    await failing.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task

    # Nothing was ACKed -> all 5 messages are pending.
    pending = await r.xpending(settings.stream_name, settings.group_name)
    assert pending["pending"] == 5

    # A real worker (with XAUTOCLAIM on startup) must recover them.
    async with worker_running():
        await wait_for(_ge(count_events, 5), timeout=20)

    assert await count_events() == 5
    pending = await r.xpending(settings.stream_name, settings.group_name)
    assert pending["pending"] == 0


@pytest.mark.integration
async def test_500_event_burst_is_absorbed_and_drained():
    settings = get_settings()
    r = get_redis()
    async with worker_running():
        for i in range(500):
            await xadd_event(
                r,
                settings.stream_name,
                make_event(sensor_id=f"sensor-{(i % 200) + 1:03d}", site_id="site-100"),
            )
        await wait_for(_ge(count_events, 500), timeout=30)
        # Backlog (unprocessed pending messages) drains to zero.
        await wait_for(_pending_zero(settings), timeout=30)

    assert await count_events() == 500
    assert get_metrics().snapshot()["counters"]["events_processed"] >= 500


@pytest.mark.integration
async def test_malformed_event_is_rejected_safely():
    settings = get_settings()
    r = get_redis()
    # Malformed payload (missing required fields) must not crash the worker.
    await r.xadd(
        settings.stream_name,
        {"payload": json.dumps({"event_id": "evt_bad"}), "received_at": "2026-01-01T00:00:00Z"},
    )
    good = make_event(sensor_id="sensor-040", site_id="site-140")
    await xadd_event(r, settings.stream_name, good)

    async with worker_running():
        await wait_for(_ge(count_events, 1))

    assert await fetch_event(good["event_id"]) is not None
    assert get_metrics().snapshot()["counters"]["processing_failures"] == 0
    # The malformed message is rejected (data error) and acked, not retried.
    assert get_metrics().snapshot()["counters"]["events_rejected"] >= 1
    pending = await r.xpending(settings.stream_name, settings.group_name)
    assert pending["pending"] == 0