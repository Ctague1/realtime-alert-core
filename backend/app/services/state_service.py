"""Authoritative state persistence (PostgreSQL).

All writes performed here are **idempotent**:

* ``events.event_id`` is the primary key.
* ``alarms.event_id`` carries a UNIQUE constraint.

Every operation is ``INSERT ... ON CONFLICT ... DO NOTHING/DO UPDATE``, so
re-delivery of a message (after a worker crash, an XAUTOCLAIM recovery, or a
genuine duplicate from the sensor stream) cannot corrupt logical state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from ..db import get_db_pool
from ..metrics import get_metrics
from ..processing.normalize import NormalizedEvent
from ..processing.severity import is_alarm_type

logger = logging.getLogger(__name__)


@dataclass
class ProcessOutcome:
    new_event: bool = False
    new_alarm: bool = False
    duplicate: bool = False
    sensor_recovered: bool = False
    alarm_id: int | None = None
    alarm: dict | None = None
    site: dict | None = None
    sensor: dict | None = None


async def recompute_all_sites(pool) -> list[dict]:
    """Recompute site state from the authoritative alarms/events tables.

    Runs periodically (cheap: only a handful of sites) so site counters are
    always consistent with the alarms table and self-heal any drift.
    """
    rows = await pool.fetch(
        """
        SELECT
            s.site_id,
            s.status,
            (
                SELECT count(*) FROM alarms a
                WHERE a.site_id = s.site_id AND a.status <> 'RESOLVED'
            ) AS active_alarm_count,
            (
                SELECT a.severity FROM alarms a
                WHERE a.site_id = s.site_id AND a.status <> 'RESOLVED'
                ORDER BY CASE a.severity
                             WHEN 'critical' THEN 4
                             WHEN 'high' THEN 3
                             WHEN 'medium' THEN 2
                             WHEN 'low' THEN 1
                             ELSE 0
                         END DESC, a.created_at DESC
                LIMIT 1
            ) AS highest_active_severity,
            (
                SELECT max(e.source_ts) FROM events e
                WHERE e.site_id = s.site_id
            ) AS latest_event_ts,
            now() AS updated_at
        FROM sites s
        """
    )
    if not rows:
        return []
    result: list[dict] = []
    for row in rows:
        await pool.execute(
            """
            UPDATE sites SET
                active_alarm_count = $2,
                highest_active_severity = $3,
                latest_event_ts = COALESCE($4, sites.latest_event_ts),
                updated_at = now()
            WHERE site_id = $1
            """,
            row["site_id"],
            row["active_alarm_count"],
            row["highest_active_severity"],
            row["latest_event_ts"],
        )
        result.append(
            {
                "site_id": row["site_id"],
                "status": row["status"],
                "active_alarm_count": row["active_alarm_count"],
                "highest_active_severity": row["highest_active_severity"],
                "latest_event_ts": _iso(row["latest_event_ts"]),
                "updated_at": _iso(row["updated_at"]),
            }
        )
    return result


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _row_to_sensor(row) -> dict:
    return {
        "sensor_id": row["sensor_id"],
        "site_id": row["site_id"],
        "status": row["status"],
        "online": row["online"],
        "last_event_ts": _iso(row["last_event_ts"]),
        "last_heartbeat_ts": _iso(row["last_heartbeat_ts"]),
        "latest_event_type": row["latest_event_type"],
        "updated_at": _iso(row["updated_at"]),
    }


def _row_to_site(row) -> dict:
    return {
        "site_id": row["site_id"],
        "status": row["status"],
        "active_alarm_count": row["active_alarm_count"],
        "highest_active_severity": row["highest_active_severity"],
        "latest_event_ts": _iso(row["latest_event_ts"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _row_to_alarm(row, source_ts, confidence) -> dict:
    return {
        "alarm_id": row["alarm_id"],
        "event_id": row["event_id"],
        "sensor_id": row["sensor_id"],
        "site_id": row["site_id"],
        "type": row["type"],
        "severity": row["severity"],
        "status": row["status"],
        "created_at": _iso(row["created_at"]),
        "source_ts": _iso(source_ts),
        "confidence": confidence,
        "acknowledged_at": _iso(row["acknowledged_at"]),
        "resolved_at": _iso(row["resolved_at"]),
    }


async def process_event(evt: NormalizedEvent, persisted_at: datetime) -> ProcessOutcome:
    """Persist a single event (used by tests / single-shot paths)."""
    outcomes = await process_batch([evt], persisted_at)
    return outcomes[evt.event_id]


async def process_batch(
    events: list[NormalizedEvent], persisted_at: datetime
) -> dict[str, ProcessOutcome]:
    """Persist a batch of normalized events in one transaction.

    Batching is what lets the worker sustain the generator's throughput: a
    single multi-row transaction replaces per-event transactions, drastically
    reducing commit/lock overhead while preserving idempotency (every insert
    is ``ON CONFLICT DO NOTHING`` keyed on ``event_id``).
    """
    if not events:
        return {}

    pool = await get_db_pool()
    outcomes = {evt.event_id: ProcessOutcome() for evt in events}

    # Aggregate per-sensor so each sensor is written at most once per batch.
    sensors: dict[str, dict] = {}
    for evt in events:
        agg = sensors.setdefault(
            evt.sensor_id,
            {
                "site_id": evt.site_id,
                "last_event_ts": evt.source_ts,
                "last_heartbeat_ts": None,
                "latest_event_type": evt.type,
            },
        )
        if evt.source_ts > agg["last_event_ts"]:
            agg["last_event_ts"] = evt.source_ts
            agg["latest_event_type"] = evt.type
            agg["site_id"] = evt.site_id
        if evt.type == "heartbeat" and (
            agg["last_heartbeat_ts"] is None or evt.source_ts > agg["last_heartbeat_ts"]
        ):
            agg["last_heartbeat_ts"] = evt.source_ts

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Ensure sites exist (cheap, idempotent).
            for site_id in {evt.site_id for evt in events}:
                await conn.execute(
                    "INSERT INTO sites (site_id, name) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING",
                    site_id,
                )

            # 2. Detect online recovery, then upsert sensors in one statement
            #    per sensor (aggregated).
            prev_rows = await conn.fetch(
                "SELECT sensor_id, online FROM sensors WHERE sensor_id = ANY($1::text[])",
                list(sensors.keys()),
            )
            prev_online = {row["sensor_id"]: row["online"] for row in prev_rows}
            recovered_sensors = {
                sensor_id
                for sensor_id in sensors
                if sensor_id in prev_online and not prev_online[sensor_id]
            }
            for sensor_id, agg in sensors.items():
                await conn.execute(
                    """
                    INSERT INTO sensors
                        (sensor_id, site_id, status, online, last_event_ts, last_heartbeat_ts,
                         latest_event_type, updated_at)
                    VALUES
                        ($1, $2, 'unknown', true, $3, $4, $5, $6)
                    ON CONFLICT (sensor_id) DO UPDATE SET
                        site_id           = EXCLUDED.site_id,
                        online            = true,
                        last_event_ts     = EXCLUDED.last_event_ts,
                        last_heartbeat_ts = COALESCE(EXCLUDED.last_heartbeat_ts, sensors.last_heartbeat_ts),
                        latest_event_type = EXCLUDED.latest_event_type,
                        updated_at        = EXCLUDED.updated_at
                    """,
                    sensor_id,
                    agg["site_id"],
                    agg["last_event_ts"],
                    agg["last_heartbeat_ts"],
                    agg["latest_event_type"],
                    persisted_at,
                )

            # 3. Insert events in one multi-row statement.
            if len(events) == 1:
                evt = events[0]
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO events
                        (event_id, sensor_id, site_id, type, severity, confidence,
                         source_ts, received_at, redis_ts, processed_at, raw)
                    VALUES
                        ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (event_id) DO NOTHING
                    RETURNING event_id
                    """,
                    evt.event_id,
                    evt.sensor_id,
                    evt.site_id,
                    evt.type,
                    evt.severity,
                    evt.confidence,
                    evt.source_ts,
                    evt.received_at,
                    evt.redis_ms,
                    persisted_at,
                    evt.raw,
                )
                new_event_ids = {inserted["event_id"]} if inserted else set()
            else:
                sql, params = _multi_insert_events(events, persisted_at)
                rows = await conn.fetch(sql, *params)
                new_event_ids = {row["event_id"] for row in rows}

            # 4. Insert alarms in one multi-row statement (alarm types only).
            alarm_events = [evt for evt in events if is_alarm_type(evt.type)]
            new_alarm_ids: dict[str, int] = {}
            if alarm_events:
                if len(alarm_events) == 1:
                    evt = alarm_events[0]
                    row = await conn.fetchrow(
                        """
                        INSERT INTO alarms
                            (event_id, sensor_id, site_id, type, severity, status, created_at)
                        VALUES
                            ($1, $2, $3, $4, $5, 'ACTIVE', $6)
                        ON CONFLICT (event_id) DO NOTHING
                        RETURNING event_id, alarm_id
                        """,
                        evt.event_id,
                        evt.sensor_id,
                        evt.site_id,
                        evt.type,
                        evt.severity,
                        evt.source_ts,
                    )
                    if row is not None:
                        new_alarm_ids[row["event_id"]] = row["alarm_id"]
                else:
                    sql, params = _multi_insert_alarms(alarm_events)
                    rows = await conn.fetch(sql, *params)
                    new_alarm_ids = {row["event_id"]: row["alarm_id"] for row in rows}

            # 5. Fetch fresh sensor rows for the batch.
            sensor_rows = await conn.fetch(
                """
                SELECT sensor_id, site_id, status, online, last_event_ts,
                       last_heartbeat_ts, latest_event_type, updated_at
                FROM sensors WHERE sensor_id = ANY($1::text[])
                """,
                list(sensors.keys()),
            )
            sensor_by_id = {row["sensor_id"]: _row_to_sensor(row) for row in sensor_rows}

    metrics = get_metrics()
    # Attribute online-recovery to the latest event of each recovered sensor
    # so the dashboard broadcasts each recovered sensor exactly once.
    last_event_for_sensor: dict[str, int] = {}
    for idx, evt in enumerate(events):
        if evt.sensor_id in recovered_sensors:
            prev = last_event_for_sensor.get(evt.sensor_id)
            if prev is None or evt.source_ts >= events[prev].source_ts:
                last_event_for_sensor[evt.sensor_id] = idx
    for idx, evt in enumerate(events):
        outcome = outcomes[evt.event_id]
        outcome.new_event = evt.event_id in new_event_ids
        outcome.duplicate = evt.event_id not in new_event_ids
        if last_event_for_sensor.get(evt.sensor_id) == idx:
            outcome.sensor_recovered = True
        if evt.event_id in new_alarm_ids:
            outcome.new_alarm = True
            outcome.alarm_id = new_alarm_ids[evt.event_id]
            outcome.alarm = _make_alarm_dict(evt)
            outcome.alarm["alarm_id"] = outcome.alarm_id
        outcome.sensor = sensor_by_id.get(evt.sensor_id)
        if outcome.new_alarm:
            metrics.inc("new_alarms")
        if outcome.duplicate:
            metrics.inc("duplicates_detected")

    return outcomes


def _make_alarm_dict(evt: NormalizedEvent) -> dict:
    return {
        "alarm_id": 0,
        "event_id": evt.event_id,
        "sensor_id": evt.sensor_id,
        "site_id": evt.site_id,
        "type": evt.type,
        "severity": evt.severity,
        "status": "ACTIVE",
        "created_at": _iso(evt.source_ts),
        "source_ts": _iso(evt.source_ts),
        "confidence": evt.confidence,
        "acknowledged_at": None,
        "resolved_at": None,
    }


def _multi_insert_events(events: list[NormalizedEvent], persisted_at: datetime) -> tuple[str, list]:
    columns = [
        "event_id",
        "sensor_id",
        "site_id",
        "type",
        "severity",
        "confidence",
        "source_ts",
        "received_at",
        "redis_ts",
        "processed_at",
        "raw",
    ]
    params: list = []
    value_rows: list[str] = []
    idx = 1
    for evt in events:
        placeholders = ", ".join(f"${idx + i}" for i in range(len(columns)))
        value_rows.append(f"({placeholders})")
        params.extend(
            [
                evt.event_id,
                evt.sensor_id,
                evt.site_id,
                evt.type,
                evt.severity,
                evt.confidence,
                evt.source_ts,
                evt.received_at,
                evt.redis_ms,
                persisted_at,
                evt.raw,
            ]
        )
        idx += len(columns)
    sql = (
        "INSERT INTO events (" + ", ".join(columns) + ") VALUES "
        + ", ".join(value_rows)
        + " ON CONFLICT (event_id) DO NOTHING RETURNING event_id"
    )
    return sql, params


def _multi_insert_alarms(alarm_events: list[NormalizedEvent]) -> tuple[str, list]:
    columns = [
        "event_id",
        "sensor_id",
        "site_id",
        "type",
        "severity",
        "status",
        "created_at",
    ]
    params: list = []
    value_rows: list[str] = []
    idx = 1
    for evt in alarm_events:
        placeholders = ", ".join(f"${idx + i}" for i in range(len(columns)))
        value_rows.append(f"({placeholders})")
        params.extend(
            [
                evt.event_id,
                evt.sensor_id,
                evt.site_id,
                evt.type,
                evt.severity,
                "ACTIVE",
                evt.source_ts,
            ]
        )
        idx += len(columns)
    sql = (
        "INSERT INTO alarms (" + ", ".join(columns) + ") VALUES "
        + ", ".join(value_rows)
        + " ON CONFLICT (event_id) DO NOTHING RETURNING event_id, alarm_id"
    )
    return sql, params