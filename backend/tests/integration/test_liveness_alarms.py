"""Sensor-liveness and alarm-state integration tests."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.db import get_db_pool
from app.processing.liveness import offline_sensor_count, scan_liveness
from app.processing.normalize import normalize_event
from app.redis_client import get_redis
from app.services import alarm_service, state_service

from .helpers import make_event


def _norm(event: dict):
    return normalize_event(
        event,
        received_at=datetime.now(timezone.utc),
        redis_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
    )


async def _seed_liveness(sensor_id: str, age_seconds: float) -> None:
    settings = get_settings()
    r = get_redis()
    now_ms = time.time() * 1000
    await r.hset(settings.liveness_hash, sensor_id, str(int(now_ms - age_seconds * 1000)))


@pytest.mark.integration
async def test_heartbeat_keeps_sensor_online():
    pool = await get_db_pool()
    await state_service.process_event(_norm(make_event(event_type="heartbeat", sensor_id="sensor-050")), datetime.now(timezone.utc))
    await _seed_liveness("sensor-050", age_seconds=5)
    offline, online = await scan_liveness(pool)
    assert offline == []
    assert await offline_sensor_count(pool) == 0


@pytest.mark.integration
async def test_stale_sensor_becomes_offline():
    pool = await get_db_pool()
    await state_service.process_event(_norm(make_event(event_type="heartbeat", sensor_id="sensor-051")), datetime.now(timezone.utc))
    await _seed_liveness("sensor-051", age_seconds=120)
    offline, online = await scan_liveness(pool)
    assert any(s["sensor_id"] == "sensor-051" for s in offline)
    assert await offline_sensor_count(pool) == 1


@pytest.mark.integration
async def test_offline_sensor_recovers_on_next_event():
    pool = await get_db_pool()
    await state_service.process_event(_norm(make_event(event_type="heartbeat", sensor_id="sensor-052")), datetime.now(timezone.utc))
    await _seed_liveness("sensor-052", age_seconds=120)
    await scan_liveness(pool)
    assert await offline_sensor_count(pool) == 1

    # A fresh accepted event (fresh liveness hash entry) recovers the sensor.
    await _seed_liveness("sensor-052", age_seconds=2)
    offline, online = await scan_liveness(pool)
    assert offline == []
    assert any(s["sensor_id"] == "sensor-052" for s in online)
    assert await offline_sensor_count(pool) == 0


@pytest.mark.integration
async def test_process_batch_attributes_recovery_to_recovered_sensor():
    pool = await get_db_pool()
    await state_service.process_event(
        _norm(make_event(event_type="heartbeat", sensor_id="sensor-060")),
        datetime.now(timezone.utc),
    )
    # Mark the sensor offline in the authoritative store.
    await pool.execute("UPDATE sensors SET online = false WHERE sensor_id = 'sensor-060'")

    # A batch containing a heartbeat from the offline sensor and an alarm from
    # a healthy sensor: only the offline sensor's latest event is flagged.
    evt_recovered = make_event(event_type="heartbeat", sensor_id="sensor-060")
    evt_other = make_event(event_type="fire_alarm", sensor_id="sensor-061")
    outcomes = await state_service.process_batch(
        [_norm(evt_recovered), _norm(evt_other)],
        datetime.now(timezone.utc),
    )
    assert outcomes[evt_recovered["event_id"]].sensor_recovered is True
    assert outcomes[evt_other["event_id"]].sensor_recovered is False

    # The recovered sensor is flipped back online.
    row = await pool.fetchrow("SELECT online FROM sensors WHERE sensor_id = 'sensor-060'")
    assert row["online"] is True


@pytest.mark.integration
async def test_alarm_acknowledge_then_resolve():
    pool = await get_db_pool()
    await state_service.process_event(
        _norm(make_event(event_type="panic_button", sensor_id="sensor-053", site_id="site-133")),
        datetime.now(timezone.utc),
    )
    alarm = await pool.fetchrow("SELECT * FROM alarms LIMIT 1")
    alarm_id = alarm["alarm_id"]

    acked, site = await alarm_service.acknowledge_alarm(alarm_id)
    assert acked["status"] == "ACKNOWLEDGED"
    assert acked["acknowledged_at"] is not None

    resolved, site = await alarm_service.resolve_alarm(alarm_id)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None

    # Site state reflects resolution.
    assert site["active_alarm_count"] == 0
    assert site["highest_active_severity"] is None


@pytest.mark.integration
async def test_invalid_transitions_rejected():
    pool = await get_db_pool()
    await state_service.process_event(
        _norm(make_event(event_type="panic_button", sensor_id="sensor-054")),
        datetime.now(timezone.utc),
    )
    alarm = await pool.fetchrow("SELECT * FROM alarms LIMIT 1")
    alarm_id = alarm["alarm_id"]

    # RESOLVED -> ACKNOWLEDGED is not allowed.
    await alarm_service.resolve_alarm(alarm_id)
    with pytest.raises(alarm_service.AlarmError) as exc_info:
        await alarm_service.acknowledge_alarm(alarm_id)
    assert exc_info.value.status_code == 409

    # Idempotent repeats are fine.
    again, _ = await alarm_service.resolve_alarm(alarm_id)
    assert again["status"] == "RESOLVED"


@pytest.mark.integration
async def test_missing_alarm_404():
    with pytest.raises(alarm_service.AlarmError) as exc_info:
        await alarm_service.resolve_alarm(999999)
    assert exc_info.value.status_code == 404