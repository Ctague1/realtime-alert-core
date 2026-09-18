"""Alarm acknowledgement / resolution with backend-side validation.

State lifecycle:

    ACTIVE -> ACKNOWLEDGED -> RESOLVED
    ACTIVE -> RESOLVED

Both operations are idempotent: acknowledging an already-acknowledged alarm
is a no-op success; resolving an already-resolved alarm is a no-op success.
A state transition that would move *backwards* (e.g. acknowledging a RESOLVED
alarm) is rejected with a 409.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..db import get_db_pool
from .state_service import _iso, _row_to_alarm, _row_to_site

VALID_TRANSITIONS = {
    "ACTIVE": ("ACKNOWLEDGED", "RESOLVED"),
    "ACKNOWLEDGED": ("RESOLVED",),
    "RESOLVED": (),
}


class AlarmError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def _fetch_alarm(conn, alarm_id: int) -> tuple[dict | None, dict | None]:
    row = await conn.fetchrow(
        """
        SELECT a.alarm_id, a.event_id, a.sensor_id, a.site_id, a.type, a.severity,
               a.status, a.created_at, a.acknowledged_at, a.resolved_at,
               e.source_ts, e.confidence
        FROM alarms a
        JOIN events e ON e.event_id = a.event_id
        WHERE a.alarm_id = $1
        """,
        alarm_id,
    )
    if row is None:
        return None, None
    alarm = _row_to_alarm(row, row["source_ts"], row["confidence"])
    return alarm, row


async def _refresh_site(conn, site_id: str) -> dict | None:
    row = await conn.fetchrow(
        """
        UPDATE sites SET
            active_alarm_count = (
                SELECT count(*) FROM alarms a
                WHERE a.site_id = $1 AND a.status <> 'RESOLVED'
            ),
            highest_active_severity = (
                SELECT a.severity FROM alarms a
                WHERE a.site_id = $1 AND a.status <> 'RESOLVED'
                ORDER BY CASE a.severity
                             WHEN 'critical' THEN 4
                             WHEN 'high' THEN 3
                             WHEN 'medium' THEN 2
                             WHEN 'low' THEN 1
                             ELSE 0
                         END DESC, a.created_at DESC
                LIMIT 1
            ),
            updated_at = now()
        WHERE site_id = $1
        RETURNING site_id, status, active_alarm_count, highest_active_severity,
                  latest_event_ts, updated_at
        """,
        site_id,
    )
    return _row_to_site(row) if row else None


async def _transition(alarm_id: int, target: str) -> tuple[dict, dict]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            alarm, row = await _fetch_alarm(conn, alarm_id)
            if row is None:
                raise AlarmError("alarm not found", 404)
            current = row["status"]
            if current == target:
                # Idempotent no-op.
                pass
            elif target not in VALID_TRANSITIONS.get(current, ()):
                raise AlarmError(
                    f"invalid transition {current} -> {target}", 409
                )
            else:
                now = datetime.now(timezone.utc)
                if target == "ACKNOWLEDGED":
                    await conn.execute(
                        "UPDATE alarms SET status='ACKNOWLEDGED', acknowledged_at=$1, updated_at=now() WHERE alarm_id=$2",
                        now,
                        alarm_id,
                    )
                else:
                    await conn.execute(
                        "UPDATE alarms SET status='RESOLVED', resolved_at=$1, updated_at=now() WHERE alarm_id=$2",
                        now,
                        alarm_id,
                    )
                alarm, _ = await _fetch_alarm(conn, alarm_id)
            site = await _refresh_site(conn, row["site_id"])
    return alarm, site


async def acknowledge_alarm(alarm_id: int) -> tuple[dict, dict]:
    return await _transition(alarm_id, "ACKNOWLEDGED")


async def resolve_alarm(alarm_id: int) -> tuple[dict, dict]:
    return await _transition(alarm_id, "RESOLVED")