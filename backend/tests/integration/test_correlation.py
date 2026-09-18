"""History & correlation integration tests.

These exercise the correlation engine (pattern detection + escalation) and the
timeline read endpoints against the real PostgreSQL + Redis used by the suite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import get_db_pool
from app.processing.correlation import detect_correlations
from app.processing.normalize import normalize_event
from app.services import state_service

from .helpers import make_event


def _norm(event: dict, age_seconds: float):
    """Normalize an event whose source_ts is `age_seconds` in the past."""
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat() + "Z"
    evt = {**event, "ts": ts}
    return normalize_event(
        evt,
        received_at=datetime.now(timezone.utc),
        redis_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
    )


async def _seed_alarm(
    event_type: str,
    sensor_id: str,
    site_id: str,
    age_seconds: float = 10,
) -> int:
    """Persist an alarm event; return its alarm_id."""
    await state_service.process_event(
        _norm(
            make_event(event_type=event_type, sensor_id=sensor_id, site_id=site_id),
            age_seconds,
        ),
        datetime.now(timezone.utc),
    )
    pool = await get_db_pool()
    row = await pool.fetchrow(
        "SELECT alarm_id FROM alarms ORDER BY alarm_id DESC LIMIT 1"
    )
    return row["alarm_id"]


async def _severities(alarm_ids: list[int]) -> list[str]:
    pool = await get_db_pool()
    rows = await pool.fetch(
        "SELECT severity, escalated FROM alarms WHERE alarm_id = ANY($1::bigint[])",
        alarm_ids,
    )
    return [dict(r) for r in rows]


@pytest.mark.integration
async def test_repeat_event_escalates_one_step():
    # 3x door_forced from the same sensor within the window.
    ids = [
        await _seed_alarm("door_forced", "sensor-070", "site-150"),
        await _seed_alarm("door_forced", "sensor-070", "site-150"),
        await _seed_alarm("door_forced", "sensor-070", "site-150"),
    ]
    pool = await get_db_pool()
    corrs = await detect_correlations(pool)

    rules = [c["rule"] for c in corrs]
    assert "repeat_event" in rules
    repeat = next(c for c in corrs if c["rule"] == "repeat_event")
    assert repeat["sensor_id"] == "sensor-070"
    assert set(repeat["alarm_ids"]) == set(ids)
    # door_forced is high -> escalates to critical.
    assert repeat["severity_before"] == "high"
    assert repeat["severity_after"] == "critical"

    rows = await _severities(ids)
    assert all(r["escalated"] for r in rows)
    assert all(r["severity"] == "critical" for r in rows)


@pytest.mark.integration
async def test_multi_signal_site_escalates_to_critical():
    ids = [
        await _seed_alarm("door_forced", "sensor-071", "site-151"),
        await _seed_alarm("perimeter_breach", "sensor-072", "site-151"),
        await _seed_alarm("smoke_detected", "sensor-073", "site-151"),
    ]
    pool = await get_db_pool()
    corrs = await detect_correlations(pool)

    rules = [c["rule"] for c in corrs]
    assert "multi_signal_site" in rules
    multi = next(c for c in corrs if c["rule"] == "multi_signal_site")
    assert multi["site_id"] == "site-151"
    assert multi["severity_after"] == "critical"
    assert set(multi["alarm_ids"]) == set(ids)

    rows = await _severities(ids)
    assert all(r["escalated"] for r in rows)
    # perimeter_breach/smoke_detected are high, door_forced high -> all critical.
    assert all(r["severity"] == "critical" for r in rows)


@pytest.mark.integration
async def test_critical_burst_records_incident():
    ids = [
        await _seed_alarm("fire_alarm", "sensor-074", "site-152"),
        await _seed_alarm("fire_alarm", "sensor-075", "site-152"),
        await _seed_alarm("panic_button", "sensor-076", "site-152"),
    ]
    pool = await get_db_pool()
    corrs = await detect_correlations(pool)

    rules = [c["rule"] for c in corrs]
    assert "critical_burst" in rules
    burst = next(c for c in corrs if c["rule"] == "critical_burst")
    assert burst["severity_before"] == "critical"
    assert burst["severity_after"] == "critical"

    rows = await _severities(ids)
    assert all(r["escalated"] for r in rows)


@pytest.mark.integration
async def test_escalation_is_idempotent():
    await _seed_alarm("door_forced", "sensor-077", "site-153")
    await _seed_alarm("door_forced", "sensor-077", "site-153")
    await _seed_alarm("door_forced", "sensor-077", "site-153")
    pool = await get_db_pool()

    first = await detect_correlations(pool)
    assert any(c["rule"] == "repeat_event" for c in first)

    # A second scan must not re-detect the same pattern or create rows.
    second = await detect_correlations(pool)
    repeat = [c for c in second if c["rule"] == "repeat_event"]
    assert repeat == []

    row = await pool.fetchval("SELECT count(*) FROM correlations")
    assert row == 1


@pytest.mark.integration
async def test_timeline_endpoints(api_server):
    """Timeline endpoints return the persisted history for a site/sensor."""
    import httpx

    await _seed_alarm("fire_alarm", "sensor-080", "site-160", age_seconds=5)
    await _seed_alarm("heartbeat", "sensor-081", "site-160", age_seconds=4)
    await _seed_alarm("motion_detected", "sensor-082", "site-160", age_seconds=3)

    async with httpx.AsyncClient(base_url=api_server, timeout=10) as client:
        site_resp = await client.get("/sites/site-160/timeline?limit=50")
        assert site_resp.status_code == 200
        body = site_resp.json()
        assert body["site"]["site_id"] == "site-160"
        types = {e["type"] for e in body["events"]}
        assert {"fire_alarm", "heartbeat", "motion_detected"} <= types
        assert all(e["site_id"] == "site-160" for e in body["events"])

        sensor_resp = await client.get("/sensors/sensor-080/timeline?limit=50")
        assert sensor_resp.status_code == 200
        sbody = sensor_resp.json()
        assert sbody["sensor"]["sensor_id"] == "sensor-080"
        assert all(e["sensor_id"] == "sensor-080" for e in sbody["events"])

        missing = await client.get("/sites/site-999/timeline")
        assert missing.status_code == 404