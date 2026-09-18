"""Read-side queries against the authoritative PostgreSQL state."""

from __future__ import annotations

from ..db import get_db_pool
from .state_service import _iso, _row_to_alarm, _row_to_sensor, _row_to_site

_ALARM_SELECT = """
    SELECT a.alarm_id, a.event_id, a.sensor_id, a.site_id, a.type, a.severity,
           a.status, a.created_at, a.acknowledged_at, a.resolved_at,
           e.source_ts, e.confidence
    FROM alarms a
    JOIN events e ON e.event_id = a.event_id
"""

_STATUS_FILTERS = {
    "active": "a.status <> 'RESOLVED'",
    "ACTIVE": "a.status = 'ACTIVE'",
    "ACKNOWLEDGED": "a.status = 'ACKNOWLEDGED'",
    "RESOLVED": "a.status = 'RESOLVED'",
}


async def list_alarms(
    status: str = "active",
    limit: int = 100,
    site_id: str | None = None,
    sensor_id: str | None = None,
) -> list[dict]:
    if status not in _STATUS_FILTERS:
        raise ValueError(f"invalid status filter: {status}")
    pool = await get_db_pool()
    clauses = [_STATUS_FILTERS[status]]
    params: list = []
    if site_id:
        params.append(site_id)
        clauses.append(f"a.site_id = ${len(params)}")
    if sensor_id:
        params.append(sensor_id)
        clauses.append(f"a.sensor_id = ${len(params)}")
    params.append(limit)
    where = " AND ".join(clauses)
    rows = await pool.fetch(
        f"""
        {_ALARM_SELECT}
        WHERE {where}
        ORDER BY CASE a.severity
                     WHEN 'critical' THEN 4
                     WHEN 'high' THEN 3
                     WHEN 'medium' THEN 2
                     WHEN 'low' THEN 1
                     ELSE 0
                 END DESC, a.created_at DESC, a.alarm_id DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [_row_to_alarm(row, row["source_ts"], row["confidence"]) for row in rows]


async def get_alarm(alarm_id: int) -> dict | None:
    pool = await get_db_pool()
    row = await pool.fetchrow(f"{_ALARM_SELECT} WHERE a.alarm_id = $1", alarm_id)
    if row is None:
        return None
    return _row_to_alarm(row, row["source_ts"], row["confidence"])


async def get_alarms(alarm_ids: list[int]) -> dict[int, dict]:
    """Fetch many alarms in a single query (used by the correlation scan)."""
    if not alarm_ids:
        return {}
    pool = await get_db_pool()
    rows = await pool.fetch(
        f"{_ALARM_SELECT} WHERE a.alarm_id = ANY($1::bigint[])",
        alarm_ids,
    )
    return {
        row["alarm_id"]: _row_to_alarm(row, row["source_ts"], row["confidence"])
        for row in rows
    }


async def list_sites() -> list[dict]:
    pool = await get_db_pool()
    rows = await pool.fetch(
        """
        SELECT site_id, status, active_alarm_count, highest_active_severity,
               latest_event_ts, updated_at
        FROM sites
        ORDER BY CASE highest_active_severity
                     WHEN 'critical' THEN 4
                     WHEN 'high' THEN 3
                     WHEN 'medium' THEN 2
                     WHEN 'low' THEN 1
                     ELSE 0
                 END DESC, site_id
        """
    )
    return [_row_to_site(row) for row in rows]


async def get_site(site_id: str) -> dict | None:
    pool = await get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT site_id, status, active_alarm_count, highest_active_severity,
               latest_event_ts, updated_at
        FROM sites WHERE site_id = $1
        """,
        site_id,
    )
    return _row_to_site(row) if row else None


async def list_sensors(
    site_id: str | None = None, online: bool | None = None, limit: int = 500
) -> list[dict]:
    pool = await get_db_pool()
    clauses: list[str] = []
    params: list = []
    if site_id:
        params.append(site_id)
        clauses.append(f"site_id = ${len(params)}")
    if online is not None:
        params.append(online)
        clauses.append(f"online = ${len(params)}")
    params.append(limit)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await pool.fetch(
        f"""
        SELECT sensor_id, site_id, status, online, last_event_ts,
               last_heartbeat_ts, latest_event_type, updated_at
        FROM sensors
        {where}
        ORDER BY online DESC, sensor_id
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [_row_to_sensor(row) for row in rows]


async def get_sensor(sensor_id: str) -> dict | None:
    pool = await get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT sensor_id, site_id, status, online, last_event_ts,
               last_heartbeat_ts, latest_event_type, updated_at
        FROM sensors WHERE sensor_id = $1
        """,
        sensor_id,
    )
    return _row_to_sensor(row) if row else None


async def list_sensor_ids() -> list[str]:
    pool = await get_db_pool()
    rows = await pool.fetch("SELECT sensor_id FROM sensors")
    return [row["sensor_id"] for row in rows]


# ---------------------------------------------------------------------------
# History / timeline
# ---------------------------------------------------------------------------

_TIMELINE_SELECT = """
    SELECT e.event_id, e.sensor_id, e.site_id, e.type, e.severity, e.confidence,
           e.source_ts, e.processed_at,
           a.alarm_id, a.status AS alarm_status, a.escalated
    FROM events e
    LEFT JOIN alarms a ON a.event_id = e.event_id
"""


def _row_to_timeline_event(row) -> dict:
    return {
        "event_id": row["event_id"],
        "sensor_id": row["sensor_id"],
        "site_id": row["site_id"],
        "type": row["type"],
        "severity": row["severity"],
        "confidence": row["confidence"],
        "source_ts": _iso(row["source_ts"]),
        "processed_at": _iso(row["processed_at"]),
        "alarm_id": row["alarm_id"],
        "alarm_status": row["alarm_status"],
        "escalated": row["escalated"],
    }


async def list_site_events(site_id: str, limit: int = 100) -> list[dict]:
    pool = await get_db_pool()
    rows = await pool.fetch(
        f"""
        {_TIMELINE_SELECT}
        WHERE e.site_id = $1
        ORDER BY e.source_ts DESC, e.event_id
        LIMIT $2
        """,
        site_id,
        limit,
    )
    return [_row_to_timeline_event(row) for row in rows]


async def list_sensor_events(sensor_id: str, limit: int = 100) -> list[dict]:
    pool = await get_db_pool()
    rows = await pool.fetch(
        f"""
        {_TIMELINE_SELECT}
        WHERE e.sensor_id = $1
        ORDER BY e.source_ts DESC, e.event_id
        LIMIT $2
        """,
        sensor_id,
        limit,
    )
    return [_row_to_timeline_event(row) for row in rows]


def _row_to_correlation(row) -> dict:
    return {
        "correlation_id": row["correlation_id"],
        "rule": row["rule"],
        "site_id": row["site_id"],
        "sensor_id": row["sensor_id"],
        "window_start": _iso(row["window_start"]),
        "window_end": _iso(row["window_end"]),
        "severity_before": row["severity_before"],
        "severity_after": row["severity_after"],
        "event_ids": row["event_ids"],
        "alarm_ids": row["alarm_ids"],
        "description": row["description"],
        "detected_at": _iso(row["detected_at"]),
    }


async def get_correlation(correlation_id: int) -> dict | None:
    pool = await get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT correlation_id, rule, site_id, sensor_id, window_start, window_end,
               severity_before, severity_after, event_ids, alarm_ids, description,
               detected_at
        FROM correlations WHERE correlation_id = $1
        """,
        correlation_id,
    )
    return _row_to_correlation(row) if row else None


async def list_correlations(
    site_id: str | None = None, limit: int = 50
) -> list[dict]:
    pool = await get_db_pool()
    clauses: list[str] = []
    params: list = []
    if site_id:
        params.append(site_id)
        clauses.append(f"site_id = ${len(params)}")
    params.append(limit)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await pool.fetch(
        f"""
        SELECT correlation_id, rule, site_id, sensor_id, window_start, window_end,
               severity_before, severity_after, event_ids, alarm_ids, description,
               detected_at
        FROM correlations
        {where}
        ORDER BY detected_at DESC, correlation_id DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [_row_to_correlation(row) for row in rows]