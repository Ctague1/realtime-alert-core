"""Processing worker - Redis Streams consumer group.

At-least-once processing loop:

    1. XREADGROUP   - read a bounded batch from the consumer group
    2. process      - normalize + deduplicate + persist as ONE multi-row
                      transaction (batched writes sustain the generator rate)
    3. XACK         - acknowledge *only after* the DB transaction committed
    4. recover      - XAUTOCLAIM pending entries abandoned by dead consumers
    5. liveness     - periodic scan for offline sensors
    6. site state   - periodic aggregation task
    7. metrics      - export gauges/snapshots to Redis for the backend

If the worker crashes before ACK the message stays in the pending entries
list; another worker (or this one after restart) reclaims it via XAUTOCLAIM
and reprocesses it idempotently.
"""

from __future__ import annotations

import asyncio
import json
import logging

from ..config import get_settings
from ..db import get_db_pool
from ..logging_config import get_logger
from ..metrics import get_metrics
from ..redis_client import ensure_stream_and_group, get_redis, stream_length
from ..services import queries
from ..services.dashboard_hub import get_hub
from ..services.state_service import process_batch, recompute_all_sites
from .correlation import detect_correlations
from .liveness import offline_sensor_count, scan_liveness
from .normalize import normalize_event, parse_source_ts, utcnow

logger = get_logger("sentinel.worker")


class ProcessingWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        settings = self.settings
        await ensure_stream_and_group(settings.stream_name, settings.group_name)
        logger.info(
            "worker starting (consumer=%s, batch=%d)",
            settings.consumer_name,
            settings.worker_batch_size,
        )
        self._tasks = [
            asyncio.create_task(self._periodic_claim(), name="worker-claim"),
            asyncio.create_task(self._liveness_scan(), name="worker-liveness"),
            asyncio.create_task(self._metrics_export(), name="worker-metrics"),
            asyncio.create_task(self._site_recompute(), name="worker-sites"),
            asyncio.create_task(self._correlation_scan(), name="worker-correlations"),
        ]
        try:
            while not self._stop.is_set():
                await self._read_and_process()
        finally:
            for task in self._tasks:
                task.cancel()
            for task in self._tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    async def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------- xreadgroup
    async def _read_and_process(self) -> None:
        settings = self.settings
        r = get_redis()
        try:
            result = await r.xreadgroup(
                settings.group_name,
                settings.consumer_name,
                {settings.stream_name: ">"},
                count=settings.worker_batch_size,
                block=settings.worker_block_ms,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if "NOGROUP" in str(exc):
                # Stream/group vanished (e.g. Redis flushed). Recreate.
                await ensure_stream_and_group(settings.stream_name, settings.group_name)
            else:
                # Transient connection/read error - not a data-processing
                # failure; retry (leaves the backlog untouched).
                logger.warning("XREADGROUP transient error; retrying: %s", str(exc)[:200])
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            return

        if not result:
            await self._update_backlog_gauge()
            return

        entries = result[0][1]
        await self._process_entries(entries, is_retry=False)

    # -------------------------------------------------------------- process
    async def _process_entries(self, entries, is_retry: bool) -> None:
        """Normalize + persist a batch of stream messages atomically."""
        metrics = get_metrics()
        settings = self.settings
        r = get_redis()

        good: list[tuple[str, object, int]] = []  # (msg_id, evt, redis_ms)
        bad: list[tuple[str, str]] = []  # (msg_id, error)

        for msg_id, fields in entries:
            try:
                raw = json.loads(fields["payload"])
                received_at = parse_source_ts(fields.get("received_at", raw.get("ts")))
                redis_ms = int(msg_id.split("-")[0])
                evt = normalize_event(raw, received_at, redis_ms)
                good.append((msg_id, evt, redis_ms))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                bad.append((msg_id, str(exc)[:300]))

        if is_retry:
            metrics.inc("retries", len(entries))

        # Deterministic data errors cannot be fixed by retry: ack + record.
        for msg_id, error in bad:
            metrics.inc("events_rejected")
            logger.warning(
                "message rejected (data error), acked to avoid poison pill",
                extra={"stream_id": msg_id, "error": error},
            )
            try:
                await r.xack(settings.stream_name, settings.group_name, msg_id)
            except Exception:  # noqa: BLE001
                logger.exception("failed to ack rejected message")

        if not good:
            return

        events = [evt for _, evt, _ in good]
        worker_started = utcnow()
        try:
            outcomes = await process_batch(events, worker_started)
        except asyncio.CancelledError:
            raise
        except Exception:
            metrics.inc("processing_failures")
            logger.exception(
                "batch processing failed; %d message(s) left unacked for retry",
                len(good),
            )
            return

        # ACK only after the transaction committed.
        persisted_at = utcnow()
        batch_process_ms = (persisted_at - worker_started).total_seconds() * 1000
        alarm_updates: list[dict] = []
        sensor_updates: list[dict] = []
        ack_ids: list[str] = []
        for msg_id, evt, redis_ms in good:
            outcome = outcomes[evt.event_id]
            queue_ms = (worker_started.timestamp() - redis_ms / 1000.0) * 1000
            total_ms = (persisted_at - evt.received_at).total_seconds() * 1000
            metrics.observe("queue_latency_ms", queue_ms)
            metrics.observe("process_latency_ms", batch_process_ms)
            metrics.observe("total_processing_ms", total_ms)
            ack_ids.append(msg_id)
            metrics.inc("events_processed")
            if evt.type == "heartbeat":
                metrics.inc("events_heartbeat")
            metrics.inc("events_acked")
            if outcome.alarm is not None:
                alarm_updates.append(
                    {
                        "alarm": outcome.alarm,
                        "sensor": outcome.sensor,
                        "latency_ms": {
                            "queue": round(queue_ms, 2),
                            "process": round(batch_process_ms, 2),
                            "total": round(total_ms, 2),
                        },
                    }
                )
            elif outcome.sensor_recovered and outcome.sensor:
                sensor_updates.append(outcome.sensor)

        if ack_ids:
            try:
                await r.xack(settings.stream_name, settings.group_name, *ack_ids)
            except Exception:  # noqa: BLE001
                logger.exception("batch XACK failed", extra={"count": len(ack_ids)})

        if alarm_updates:
            await get_hub().publish({"kind": "alarms", "updates": alarm_updates})
        for sensor in sensor_updates:
            await get_hub().publish({"kind": "sensor", "sensor": sensor})
        await self._update_backlog_gauge()

        logger.debug("processed batch", extra={"count": len(good)})

    # --------------------------------------------------------------- pending
    async def _periodic_claim(self) -> None:
        settings = self.settings
        # Recover abandoned pending messages immediately on startup, then
        # periodically.
        while not self._stop.is_set():
            try:
                await self._claim_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("pending-message claim pass failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.pending_claim_interval)
            except asyncio.TimeoutError:
                continue

    async def _claim_pending(self) -> None:
        settings = self.settings
        r = get_redis()
        try:
            _, claimed, _ = await r.xautoclaim(
                settings.stream_name,
                settings.group_name,
                settings.consumer_name,
                min_idle_time=settings.pending_claim_idle_ms,
                start_id="0",
                count=settings.pending_claim_count,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if "NOGROUP" in str(exc):
                await ensure_stream_and_group(settings.stream_name, settings.group_name)
            else:
                logger.exception("pending-message claim pass failed")
            return
        if not claimed:
            return
        logger.info("claimed %d abandoned pending message(s)", len(claimed))
        await self._process_entries(claimed, is_retry=True)

    # -------------------------------------------------------------- liveness
    async def _liveness_scan(self) -> None:
        settings = self.settings
        while not self._stop.is_set():
            try:
                pool = await get_db_pool()
                offline, online = await scan_liveness(pool)
                for sensor in offline:
                    await get_hub().publish({"kind": "sensor", "sensor": sensor})
                    logger.info(
                        "sensor offline",
                        extra={
                            "sensor_id": sensor["sensor_id"],
                            "site_id": sensor["site_id"],
                        },
                    )
                for sensor in online:
                    await get_hub().publish({"kind": "sensor", "sensor": sensor})
                    logger.info(
                        "sensor online",
                        extra={
                            "sensor_id": sensor["sensor_id"],
                            "site_id": sensor["site_id"],
                        },
                    )
                get_metrics().gauge("sensors_offline", await offline_sensor_count(pool))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("liveness scan failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.heartbeat_scan_interval)
            except asyncio.TimeoutError:
                continue

    # -------------------------------------------------------- site recompute
    async def _site_recompute(self) -> None:
        """Periodically rebuild site state from the authoritative tables and
        push the fresh rows to the dashboard. Runs on a fixed cadence so the
        per-event hot path stays free of expensive aggregation queries."""
        settings = self.settings
        while not self._stop.is_set():
            try:
                pool = await get_db_pool()
                sites = await recompute_all_sites(pool)
                if sites:
                    await get_hub().publish({"kind": "sites", "sites": sites})
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("site recompute failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=settings.site_recompute_interval
                )
            except asyncio.TimeoutError:
                continue

    # -------------------------------------------------------- correlation
    async def _correlation_scan(self) -> None:
        """Periodically detect correlated/pattern events and escalate.

        Detection is idempotent (only non-escalated alarms are considered) and
        serialized across worker replicas via a Redis lock. Escalated alarms
        and detected correlations are pushed to the dashboard.
        """
        settings = self.settings
        while not self._stop.is_set():
            try:
                pool = await get_db_pool()
                correlations = await detect_correlations(pool)
                if correlations:
                    # Batch-fetch all involved alarms in a single query.
                    alarm_ids = [
                        alarm_id
                        for corr in correlations
                        for alarm_id in corr["alarm_ids"]
                    ]
                    alarms_by_id = await queries.get_alarms(alarm_ids)
                    alarm_updates = [
                        {"alarm": alarm} for alarm in alarms_by_id.values()
                    ]
                    # Cap live broadcasts: the dashboard polls /alarms and
                    # /correlations every 10s, so anything not broadcast here
                    # is picked up by polling; keeping the frames modest avoids
                    # multi-megabyte WebSocket messages.
                    if alarm_updates:
                        await get_hub().publish(
                            {"kind": "alarms", "updates": alarm_updates[:250]}
                        )
                    await get_hub().publish(
                        {"kind": "correlations", "correlations": correlations[:100]}
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("correlation scan failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=settings.correlation_scan_interval
                )
            except asyncio.TimeoutError:
                continue

    # -------------------------------------------------------- metric export
    async def _metrics_export(self) -> None:
        """Periodically persist gauges from PostgreSQL and publish this
        worker's metrics snapshot to Redis so the backend /metrics endpoint
        can aggregate processing-side observability."""
        settings = self.settings
        while not self._stop.is_set():
            try:
                pool = await get_db_pool()
                row = await pool.fetchrow(
                    """
                    SELECT
                        count(*) FILTER (WHERE status = 'ACTIVE') AS active,
                        count(*) FILTER (WHERE status = 'ACKNOWLEDGED') AS acknowledged,
                        count(*) FILTER (WHERE status = 'RESOLVED') AS resolved
                    FROM alarms
                    """
                )
                metrics = get_metrics()
                metrics.gauge("alarms_active", row["active"])
                metrics.gauge("alarms_acknowledged", row["acknowledged"])
                metrics.gauge("alarms_resolved", row["resolved"])
                metrics.gauge("sensors_offline", await offline_sensor_count(pool))
                await self._update_backlog_gauge()

                r = get_redis()
                await r.set(
                    settings.metrics_export_key,
                    json.dumps(
                        {"snapshot": metrics.snapshot(), "consumer": settings.consumer_name},
                        default=str,
                    ),
                    ex=int(max(settings.metrics_export_interval * 3, 15)),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("metrics export failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.metrics_export_interval)
            except asyncio.TimeoutError:
                continue

    # ---------------------------------------------------------------- helpers
    async def _update_backlog_gauge(self) -> None:
        try:
            settings = self.settings
            r = get_redis()
            length = await stream_length(settings.stream_name)
            pending = await r.xpending(settings.stream_name, settings.group_name)
            get_metrics().gauge("stream_length", length)
            # backlog_depth = genuinely unprocessed messages (pending / unacked).
            get_metrics().gauge("backlog_depth", pending.get("pending", 0))
        except Exception:  # noqa: BLE001
            pass