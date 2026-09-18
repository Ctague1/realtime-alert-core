"""Sensor-liveness policy and offline detection.

Policy
------
* A sensor's liveness is refreshed by **any** event it emits (heartbeat or
  alarm). The ingestion layer records a ``sensor:liveness`` hash entry keyed
  by ``sensor_id`` with the *acceptance time* (the Redis stream append
  timestamp) each time an event is durably accepted.

* Because liveness is keyed to acceptance (Redis), it is independent of
  processing lag: a busy worker that is briefly behind does not cause a live
  sensor to look offline.

* Offline detection: a sensor is declared offline when no event has been
  accepted for ``heartbeat_offline_timeout`` seconds (default 30s). Given the
  provided generator emits ~1 event/s per sensor, several missed
  heartbeats/events are required - a single missed heartbeat never marks a
  sensor offline.

* Return to online: as soon as a fresh event is accepted for a sensor that
  was marked offline, the sensor is flipped back online and the transition is
  broadcast to the dashboard.
"""

from __future__ import annotations

import logging
import time

from ..config import get_settings
from ..metrics import get_metrics
from ..redis_client import get_redis
from ..services.state_service import _row_to_sensor

logger = logging.getLogger(__name__)


async def _fetch_sensor_rows(pool, sensor_ids: list[str]) -> dict[str, dict]:
    if not sensor_ids:
        return {}
    rows = await pool.fetch(
        """
        SELECT sensor_id, site_id, status, online, last_event_ts,
               last_heartbeat_ts, latest_event_type, updated_at
        FROM sensors WHERE sensor_id = ANY($1::text[])
        """,
        sensor_ids,
    )
    return {row["sensor_id"]: _row_to_sensor(row) for row in rows}


async def scan_liveness(pool) -> tuple[list[dict], list[dict]]:
    """Return (offline_transitions, online_transitions) after syncing DB state.

    Offline transitions: sensors whose last accepted event is older than the
    timeout. Online transitions: sensors that were offline but have a fresh
    accepted event (recovered).
    """
    settings = get_settings()
    r = get_redis()
    metrics = get_metrics()
    raw = await r.hgetall(settings.liveness_hash)  # {sensor_id: ms_str}
    if not raw:
        return [], []

    now_ms = time.time() * 1000
    timeout_ms = settings.heartbeat_offline_timeout * 1000

    offline_ids = [sid for sid, ts in raw.items() if now_ms - int(ts) > timeout_ms]
    fresh_ids = [sid for sid, ts in raw.items() if now_ms - int(ts) <= timeout_ms]

    offline_transitions: list[dict] = []
    online_transitions: list[dict] = []

    if offline_ids:
        rows = await pool.fetch(
            """
            UPDATE sensors SET online = false, updated_at = now()
            WHERE sensor_id = ANY($1::text[]) AND online = true
            RETURNING sensor_id, site_id, status, online, last_event_ts,
                      last_heartbeat_ts, latest_event_type, updated_at
            """,
            offline_ids,
        )
        if rows:
            metrics.inc("sensor_offline_transitions", len(rows))
            offline_transitions = [_row_to_sensor(row) for row in rows]

    if fresh_ids:
        rows = await pool.fetch(
            """
            UPDATE sensors SET online = true, updated_at = now()
            WHERE sensor_id = ANY($1::text[]) AND online = false
            RETURNING sensor_id, site_id, status, online, last_event_ts,
                      last_heartbeat_ts, latest_event_type, updated_at
            """,
            fresh_ids,
        )
        if rows:
            metrics.inc("sensor_online_transitions", len(rows))
            online_transitions = [_row_to_sensor(row) for row in rows]

    return offline_transitions, online_transitions


async def offline_sensor_count(pool) -> int:
    row = await pool.fetchrow(
        "SELECT count(*) AS n FROM sensors WHERE online = false"
    )
    return int(row["n"]) if row else 0