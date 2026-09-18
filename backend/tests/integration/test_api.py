"""REST API + dashboard WebSocket integration tests.

A real uvicorn server is started on the test event loop so the full app
(including lifespan, Redis, PostgreSQL) is exercised over HTTP.
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
import pytest_asyncio

from app.config import reload_settings
from app.db import get_db_pool
from app.processing.normalize import normalize_event
from app.services.state_service import process_event
from datetime import datetime, timezone

os.environ["SENSOR_INGESTION_ENABLED"] = "false"
reload_settings()


async def _seed_event(event_type: str, sensor_id: str, site_id: str) -> dict:
    evt = {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "sensor_id": sensor_id,
        "site_id": site_id,
        "type": event_type,
        "confidence": 0.9,
        "ts": datetime.now(timezone.utc).isoformat() + "Z",
    }
    norm = normalize_event(evt, received_at=datetime.now(timezone.utc), redis_ms=0)
    await process_event(norm, datetime.now(timezone.utc))
    return evt


@pytest_asyncio.fixture
async def seeded(api_server):
    await _seed_event("fire_alarm", "sensor-301", "site-201")
    await _seed_event("perimeter_breach", "sensor-302", "site-202")
    await _seed_event("heartbeat", "sensor-303", "site-201")
    return api_server


async def test_health(api_server):
    async with httpx.AsyncClient(base_url=api_server, timeout=10) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["checks"]["postgres"] is True
        assert body["checks"]["redis"] is True


async def test_alarms_lifecycle(seeded):
    async with httpx.AsyncClient(base_url=seeded, timeout=10) as client:
        alarms = (await client.get("/alarms")).json()
        assert len(alarms) >= 2
        # Prioritisation: critical (fire_alarm) before high (perimeter_breach).
        assert alarms[0]["severity"] == "critical"
        assert alarms[0]["type"] == "fire_alarm"

        alarm_id = alarms[0]["alarm_id"]
        resp = await client.post(f"/alarms/{alarm_id}/acknowledge")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACKNOWLEDGED"

        resp = await client.post(f"/alarms/{alarm_id}/resolve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "RESOLVED"

        # Invalid transition: resolving again is a no-op; acknowledging a
        # resolved alarm is rejected.
        resp = await client.post(f"/alarms/{alarm_id}/acknowledge")
        assert resp.status_code == 409

        # 404 for missing alarm.
        assert (await client.get("/alarms/999999")).status_code == 404


async def test_sites_and_sensors(seeded):
    pool = await get_db_pool()
    from app.services.state_service import recompute_all_sites

    await recompute_all_sites(pool)
    async with httpx.AsyncClient(base_url=seeded, timeout=10) as client:
        sites = (await client.get("/sites")).json()
        by_id = {s["site_id"]: s for s in sites}
        assert by_id["site-201"]["active_alarm_count"] == 1
        assert by_id["site-201"]["highest_active_severity"] == "critical"

        sensors = (await client.get("/sensors")).json()
        assert len(sensors) >= 3
        sensor = await client.get("/sensors/sensor-303")
        assert sensor.status_code == 200
        assert sensor.json()["online"] is True


async def test_snapshot(seeded):
    async with httpx.AsyncClient(base_url=seeded, timeout=10) as client:
        snap = (await client.get("/snapshot")).json()
        assert "alarms" in snap and "sites" in snap and "sensors" in snap
        assert snap["alarms"]  # non-empty


async def test_metrics(seeded):
    async with httpx.AsyncClient(base_url=seeded, timeout=10) as client:
        metrics = (await client.get("/metrics")).json()
        assert "counters" in metrics
        assert "events_processed" in metrics["counters"]


async def test_dashboard_ws_snapshot_on_connect(seeded):
    ws_url = seeded.replace("http://", "ws://") + "/ws/dashboard"
    import websockets

    async with websockets.connect(ws_url) as ws:
        first = json.loads(await ws.recv())
        assert first["kind"] == "snapshot"
        assert isinstance(first["alarms"], list)
        assert isinstance(first["sites"], list)
        assert isinstance(first["sensors"], list)