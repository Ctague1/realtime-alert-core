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


# ---------------------------------------------------------------------------
# Paginated browse queries (dedicated "view all" pages)
#
# Every page query returns (items, total) in a single round-trip using a
# window function for the filtered total, so the frontend never has to guess
# the count from the size of the current page.
# ---------------------------------------------------------------------------


def _alarm_filter_clauses(
    status: str, site_id: str | None, sensor_id: str | None
) -> tuple[list[str], list]:
    if status not in _STATUS_FILTERS:
        raise ValueError(f"invalid status filter: {status}")
    clauses = [_STATUS_FILTERS[status]]
    params: list = []
    if site_id:
        params.append(site_id)
        clauses.append(f"a.site_id = ${len(params)}")
    if sensor_id:
        params.append(sensor_id)
        clauses.append(f"a.sensor_id = ${len(params)}")
    return clauses, params


_ALARM_PAGE_SELECT = """
    SELECT count(*) OVER () AS _total,
           a.alarm_id, a.event_id, a.sensor_id, a.site_id, a.type, a.severity,
           a.status, a.created_at, a.acknowledged_at, a.resolved_at,
           e.source_ts, e.confidence
    FROM alarms a
    JOIN events e ON e.event_id = a.event_id
"""

_ALARM_ORDER = """
    ORDER BY CASE a.severity
                 WHEN 'critical' THEN 4
                 WHEN 'high' THEN 3
                 WHEN 'medium' THEN 2
                 WHEN 'low' THEN 1
                 ELSE 0
             END DESC, a.created_at DESC, a.alarm_id DESC
"""


async def list_alarms_page(
    status: str = "active",
    page: int = 1,
    page_size: int = 50,
    site_id: str | None = None,
    sensor_id: str | None = None,
) -> tuple[list[dict], int]:
    """Return (alarms, total) for one page of the filtered alarm set."""
    clauses, params = _alarm_filter_clauses(status, site_id, sensor_id)
    pool = await get_db_pool()
    offset = (page - 1) * page_size
    params.append(page_size)
    params.append(offset)
    rows = await pool.fetch(
        f"""
        {_ALARM_PAGE_SELECT}
        WHERE {' AND '.join(clauses)}
        {_ALARM_ORDER}
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    if not rows:
        return [], await count_alarms(status, site_id, sensor_id)
    total = rows[0]["_total"]
    items = [_row_to_alarm(row, row["source_ts"], row["confidence"]) for row in rows]
    return items, total


async def count_alarms(
    status: str = "active",
    site_id: str | None = None,
    sensor_id: str | None = None,
) -> int:
    clauses, params = _alarm_filter_clauses(status, site_id, sensor_id)
    pool = await get_db_pool()
    row = await pool.fetchrow(
        f"SELECT count(*) AS n FROM alarms a WHERE {' AND '.join(clauses)}",
        *params,
    )
    return row["n"]


def _site_filter_clauses(severity: str | None) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []
    if severity:
        if severity == "clear":
            clauses.append("highest_active_severity IS NULL")
        else:
            params.append(severity)
            clauses.append(f"highest_active_severity = ${len(params)}")
    return clauses, params


_SITE_ORDER = """
    ORDER BY CASE highest_active_severity
                 WHEN 'critical' THEN 4
                 WHEN 'high' THEN 3
                 WHEN 'medium' THEN 2
                 WHEN 'low' THEN 1
                 ELSE 0
             END DESC, site_id
"""


async def list_sites_page(
    page: int = 1,
    page_size: int = 50,
    severity: str | None = None,
) -> tuple[list[dict], int]:
    """Return (sites, total) for one page, optionally filtered by severity."""
    clauses, params = _site_filter_clauses(severity)
    pool = await get_db_pool()
    offset = (page - 1) * page_size
    params.append(page_size)
    params.append(offset)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await pool.fetch(
        f"""
        SELECT count(*) OVER () AS _total,
               site_id, status, active_alarm_count, highest_active_severity,
               latest_event_ts, updated_at
        FROM sites
        {where}
        {_SITE_ORDER}
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    if not rows:
        return [], await count_sites(severity)
    total = rows[0]["_total"]
    return [_row_to_site(row) for row in rows], total


async def count_sites(severity: str | None = None) -> int:
    clauses, params = _site_filter_clauses(severity)
    pool = await get_db_pool()
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = await pool.fetchrow(f"SELECT count(*) AS n FROM sites {where}", *params)
    return row["n"]


def _sensor_filter_clauses(
    site_id: str | None, online: bool | None
) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []
    if site_id:
        params.append(site_id)
        clauses.append(f"site_id = ${len(params)}")
    if online is not None:
        params.append(online)
        clauses.append(f"online = ${len(params)}")
    return clauses, params


async def list_sensors_page(
    page: int = 1,
    page_size: int = 50,
    site_id: str | None = None,
    online: bool | None = None,
) -> tuple[list[dict], int]:
    """Return (sensors, total) for one page, optionally filtered."""
    clauses, params = _sensor_filter_clauses(site_id, online)
    pool = await get_db_pool()
    offset = (page - 1) * page_size
    params.append(page_size)
    params.append(offset)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await pool.fetch(
        f"""
        SELECT count(*) OVER () AS _total,
               sensor_id, site_id, status, online, last_event_ts,
               last_heartbeat_ts, latest_event_type, updated_at
        FROM sensors
        {where}
        ORDER BY online DESC, sensor_id
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    if not rows:
        return [], await count_sensors(site_id, online)
    total = rows[0]["_total"]
    return [_row_to_sensor(row) for row in rows], total


async def count_sensors(
    site_id: str | None = None, online: bool | None = None
) -> int:
    clauses, params = _sensor_filter_clauses(site_id, online)
    pool = await get_db_pool()
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = await pool.fetchrow(
        f"SELECT count(*) AS n FROM sensors {where}", *params
    )
    return row["n"]


def _correlation_filter_clauses(
    site_id: str | None, rule: str | None
) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []
    if site_id:
        params.append(site_id)
        clauses.append(f"site_id = ${len(params)}")
    if rule:
        params.append(rule)
        clauses.append(f"rule = ${len(params)}")
    return clauses, params


async def list_correlations_page(
    page: int = 1,
    page_size: int = 50,
    site_id: str | None = None,
    rule: str | None = None,
) -> tuple[list[dict], int]:
    """Return (correlations, total) for one page, optionally filtered."""
    clauses, params = _correlation_filter_clauses(site_id, rule)
    pool = await get_db_pool()
    offset = (page - 1) * page_size
    params.append(page_size)
    params.append(offset)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await pool.fetch(
        f"""
        SELECT count(*) OVER () AS _total,
               correlation_id, rule, site_id, sensor_id, window_start, window_end,
               severity_before, severity_after, event_ids, alarm_ids, description,
               detected_at
        FROM correlations
        {where}
        ORDER BY detected_at DESC, correlation_id DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    if not rows:
        return [], await count_correlations(site_id, rule)
    total = rows[0]["_total"]
    return [_row_to_correlation(row) for row in rows], total


async def count_correlations(
    site_id: str | None = None, rule: str | None = None
) -> int:
    clauses, params = _correlation_filter_clauses(site_id, rule)
    pool = await get_db_pool()
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = await pool.fetchrow(
        f"SELECT count(*) AS n FROM correlations {where}", *params
    )
    return row["n"]


async def count_stats() -> dict:
    """Aggregate record counts used by the dashboard summary.

    Single round-trip; totals are computed from the authoritative tables
    (never derived from a truncated page of rows).
    """
    pool = await get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT
            (SELECT count(*) FROM alarms WHERE status <> 'RESOLVED')
                AS alarms_active,
            (SELECT count(*) FROM alarms WHERE status = 'ACKNOWLEDGED')
                AS alarms_acknowledged,
            (SELECT count(*) FROM alarms
                WHERE status <> 'RESOLVED' AND severity = 'critical')
                AS alarms_critical,
            (SELECT count(*) FROM alarms
                WHERE status <> 'RESOLVED' AND severity = 'high')
                AS alarms_high,
            (SELECT count(*) FROM alarms
                WHERE status <> 'RESOLVED' AND severity = 'medium')
                AS alarms_medium,
            (SELECT count(*) FROM alarms
                WHERE status <> 'RESOLVED' AND severity = 'low')
                AS alarms_low,
            (SELECT count(*) FROM sensors) AS sensors_total,
            (SELECT count(*) FROM sensors WHERE online = false)
                AS sensors_offline,
            (SELECT count(*) FROM sites) AS sites_total,
            (SELECT count(*) FROM sites WHERE active_alarm_count > 0)
                AS sites_active,
            (SELECT count(*) FROM correlations) AS correlations_total
        """
    )
    return dict(row)