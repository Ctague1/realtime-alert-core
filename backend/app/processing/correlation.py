"""Event correlation and pattern-based escalation.

Runs periodically in the processing worker. Scans recent, non-escalated,
non-resolved alarms for deterministic patterns and *escalates* the alarms
involved. Every detection is recorded in the ``correlations`` audit table so
the dashboard can show an incident/event timeline per site.

Rules
-----
``repeat_event``
    At least ``correlation_repeat_threshold`` alarms of the **same type** from
    the **same sensor** within ``correlation_window`` seconds. Each involved
    alarm is escalated one severity step (low -> medium -> high -> critical).

``multi_signal_site``
    At least ``correlation_multi_signal_threshold`` **distinct alarm types**
    at the **same site** within the window, with at least one high/critical
    alarm. The involved alarms escalate to **critical** (a site under
    coordinated attack pattern).

``critical_burst``
    At least ``correlation_burst_threshold`` **critical** alarms at the same
    site within the window. Recorded as a burst incident (severity stays
    critical) so operators see the correlation trail.

Escalation is **idempotent**:

* Only alarms with ``escalated = false`` are considered by the scan queries.
* Every escalation ``UPDATE`` is guarded by ``escalated = false``; if nothing
  new was escalated the correlation row is rolled back.
* A Redis lock (``SET NX``) ensures multiple worker replicas never scan
  concurrently; the lock has a short TTL so a crashed worker cannot block the
  scan forever.
"""

from __future__ import annotations

import logging

from ..config import get_settings
from ..redis_client import get_redis
from ..services.queries import get_correlation
from .severity import severity_rank

logger = logging.getLogger(__name__)

# Severity escalation ladder (informational never escalates).
_SEVERITY_STEPS = ["low", "medium", "high", "critical"]


def _step_up(severity: str) -> str:
    if severity in _SEVERITY_STEPS:
        idx = _SEVERITY_STEPS.index(severity)
        if idx < len(_SEVERITY_STEPS) - 1:
            return _SEVERITY_STEPS[idx + 1]
    return severity


async def detect_correlations(pool) -> list[dict]:
    """Run all correlation rules once; return the correlations detected.

    Escalation is applied as a side effect. Returns a list of correlation
    dicts (newly detected + escalated), ready for the dashboard.
    """
    settings = get_settings()
    r = get_redis()
    lock_ttl = int(settings.correlation_scan_interval * 2 + 5)
    acquired = await r.set(settings.correlation_lock_key, "1", nx=True, ex=lock_ttl)
    if not acquired:
        # Another worker replica holds the scan lock.
        return []
    try:
        found: list[dict] = []
        found += await _detect_repeat_event(pool)
        found += await _detect_multi_signal_site(pool)
        found += await _detect_critical_burst(pool)
        return found
    finally:
        try:
            await r.delete(settings.correlation_lock_key)
        except Exception:  # noqa: BLE001
            # Lock TTL will expire it anyway.
            pass


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

async def _detect_repeat_event(pool) -> list[dict]:
    settings = get_settings()
    rows = await pool.fetch(
        """
        SELECT a.sensor_id, a.site_id, a.type,
               array_agg(a.alarm_id ORDER BY a.created_at)::bigint[] AS alarm_ids,
               array_agg(a.event_id  ORDER BY a.created_at)          AS event_ids,
               array_agg(a.severity  ORDER BY a.created_at)          AS severities,
               min(a.created_at) AS window_start,
               max(a.created_at) AS window_end,
               count(*) AS n
        FROM alarms a
        WHERE a.escalated = false
          AND a.status <> 'RESOLVED'
          AND a.created_at > now() - make_interval(secs => $1)
        GROUP BY a.sensor_id, a.site_id, a.type
        HAVING count(*) >= $2
        ORDER BY max(a.created_at) DESC
        LIMIT $3
        """,
        settings.correlation_window,
        settings.correlation_repeat_threshold,
        50,
    )
    out: list[dict] = []
    for row in rows:
        before = _highest_severity(row["severities"])
        corr = await _apply_correlation(
            pool,
            rule="repeat_event",
            site_id=row["site_id"],
            sensor_id=row["sensor_id"],
            window_start=row["window_start"],
            window_end=row["window_end"],
            severity_before=before,
            severity_after=_step_up(before),
            event_ids=list(row["event_ids"]),
            alarm_ids=list(row["alarm_ids"]),
            description=(
                f"{row['n']}x {row['type']} from {row['sensor_id']} within "
                f"{settings.correlation_window:g}s"
            ),
        )
        if corr:
            out.append(corr)
    return out


async def _detect_multi_signal_site(pool) -> list[dict]:
    settings = get_settings()
    rows = await pool.fetch(
        """
        SELECT a.site_id,
               array_agg(DISTINCT a.type ORDER BY a.type) AS types,
               array_agg(a.alarm_id ORDER BY a.created_at)::bigint[] AS alarm_ids,
               array_agg(a.event_id  ORDER BY a.created_at)          AS event_ids,
               array_agg(a.severity  ORDER BY a.created_at)          AS severities,
               min(a.created_at) AS window_start,
               max(a.created_at) AS window_end,
               count(*) AS n
        FROM alarms a
        WHERE a.escalated = false
          AND a.status <> 'RESOLVED'
          AND a.created_at > now() - make_interval(secs => $1)
        GROUP BY a.site_id
        HAVING count(DISTINCT a.type) >= $2
           AND bool_or(a.severity IN ('high', 'critical'))
        ORDER BY max(a.created_at) DESC
        LIMIT $3
        """,
        settings.correlation_window,
        settings.correlation_multi_signal_threshold,
        50,
    )
    out: list[dict] = []
    for row in rows:
        before = _highest_severity(row["severities"])
        corr = await _apply_correlation(
            pool,
            rule="multi_signal_site",
            site_id=row["site_id"],
            sensor_id=None,
            window_start=row["window_start"],
            window_end=row["window_end"],
            severity_before=before,
            severity_after="critical",
            event_ids=list(row["event_ids"]),
            alarm_ids=list(row["alarm_ids"]),
            description=(
                f"{row['n']} alarms of {len(row['types'])} distinct types at "
                f"{row['site_id']}: {', '.join(row['types'])}"
            ),
        )
        if corr:
            out.append(corr)
    return out


async def _detect_critical_burst(pool) -> list[dict]:
    settings = get_settings()
    rows = await pool.fetch(
        """
        SELECT a.site_id,
               array_agg(a.alarm_id ORDER BY a.created_at)::bigint[] AS alarm_ids,
               array_agg(a.event_id  ORDER BY a.created_at)          AS event_ids,
               min(a.created_at) AS window_start,
               max(a.created_at) AS window_end,
               count(*) AS n
        FROM alarms a
        WHERE a.escalated = false
          AND a.status <> 'RESOLVED'
          AND a.severity = 'critical'
          AND a.created_at > now() - make_interval(secs => $1)
        GROUP BY a.site_id
        HAVING count(*) >= $2
        ORDER BY max(a.created_at) DESC
        LIMIT $3
        """,
        settings.correlation_window,
        settings.correlation_burst_threshold,
        50,
    )
    out: list[dict] = []
    for row in rows:
        corr = await _apply_correlation(
            pool,
            rule="critical_burst",
            site_id=row["site_id"],
            sensor_id=None,
            window_start=row["window_start"],
            window_end=row["window_end"],
            severity_before="critical",
            severity_after="critical",
            event_ids=list(row["event_ids"]),
            alarm_ids=list(row["alarm_ids"]),
            description=(
                f"{row['n']} critical alarms at {row['site_id']} within "
                f"{settings.correlation_window:g}s"
            ),
        )
        if corr:
            out.append(corr)
    return out


def _highest_severity(severities: list[str]) -> str:
    return max(severities, key=severity_rank)


class _NoEscalation(Exception):
    """Internal: every involved alarm was already escalated - roll back."""


async def _apply_correlation(
    pool,
    *,
    rule: str,
    site_id: str,
    sensor_id: str | None,
    window_start,
    window_end,
    severity_before: str,
    severity_after: str,
    event_ids: list[str],
    alarm_ids: list[int],
    description: str,
) -> dict | None:
    """Insert the correlation row and escalate the involved alarms atomically.

    Returns the correlation dict, or ``None`` if every involved alarm had
    already been escalated (the row is rolled back).
    """
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO correlations
                        (rule, site_id, sensor_id, window_start, window_end,
                         severity_before, severity_after, event_ids, alarm_ids,
                         description)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING correlation_id
                    """,
                    rule,
                    site_id,
                    sensor_id,
                    window_start,
                    window_end,
                    severity_before,
                    severity_after,
                    event_ids,
                    alarm_ids,
                    description,
                )
                updated = await conn.fetch(
                    """
                    UPDATE alarms SET
                        severity = $1,
                        escalated = true,
                        escalated_at = now(),
                        correlation_id = $2
                    WHERE alarm_id = ANY($3::bigint[])
                      AND escalated = false
                    RETURNING alarm_id
                    """,
                    severity_after,
                    row["correlation_id"],
                    alarm_ids,
                )
                if not updated:
                    raise _NoEscalation()
        except _NoEscalation:
            logger.info("correlation %s skipped (alarms already escalated)", rule)
            return None
    logger.info(
        "correlation detected: rule=%s site=%s sensor=%s alarms=%d escalated=%s->%s",
        rule,
        site_id,
        sensor_id or "-",
        len(updated),
        severity_before,
        severity_after,
    )
    return await get_correlation(row["correlation_id"])