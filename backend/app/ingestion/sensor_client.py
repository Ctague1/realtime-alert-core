"""Sensor-stream ingestion.

Connects to the provided sensor WebSocket generator, consumes events,
validates them, and appends accepted events to the durable Redis Stream.

Durability boundary
-------------------
An event is **accepted** only once it has been successfully appended to the
Redis Stream (``XADD``). Events that were received but not yet appended are
*not* accepted and are never claimed to be durable.

Backpressure
------------
There is deliberately **no unbounded in-memory queue**. If Redis is
unavailable the consumer stops reading from the sensor WebSocket, which
propagates TCP backpressure to the generator (the generator's ``send`` then
blocks instead of discarding). A small bounded buffer (``maxlen``) absorbs a
short Redis blip without stalling the stream.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from datetime import datetime, timezone

import websockets
from pydantic import ValidationError

from ..config import get_settings
from ..logging_config import get_logger
from ..metrics import get_metrics
from ..redis_client import get_redis
from ..schemas import SensorEvent

logger = get_logger("sentinel.ingestion")

# Module-level singleton, owned by the FastAPI lifespan. Health checks read it.
client: "SensorClient | None" = None


class SensorClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._stop = asyncio.Event()
        self._buffer: deque[tuple[float, dict]] = deque(maxlen=10_000)
        self.connected = False
        self.last_connect_attempt: datetime | None = None
        self.connected_since: datetime | None = None

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        """Main loop: connect, consume, reconnect with exponential backoff."""
        backoff = self.settings.sensor_reconnect_base
        while not self._stop.is_set():
            try:
                await self._consume_forever()
                # Clean disconnect (server closed): reconnect after a short pause.
                await self._wait_or_stop(backoff)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("sensor connection failed; will retry")
                await self._wait_or_stop(backoff)
            backoff = min(backoff * 2, self.settings.sensor_reconnect_max)

    async def stop(self) -> None:
        self._stop.set()

    async def _wait_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return

    # --------------------------------------------------------------- consume
    async def _consume_forever(self) -> None:
        url = self.settings.sensor_ws_url
        logger.info("connecting to sensor stream at %s", url)
        self.last_connect_attempt = datetime.utcnow()
        connect_kwargs = {"ping_interval": 20, "ping_timeout": 20, "max_queue": 32}
        try:
            async with websockets.connect(url, **connect_kwargs) as ws:
                self.connected = True
                self.connected_since = datetime.utcnow()
                logger.info("connected to sensor stream")
                async for raw_message in ws:
                    if self._stop.is_set():
                        return
                    event = self._try_parse(raw_message)
                    if event is None:
                        continue
                    self._buffer.append(event)
                    await self._flush_buffer(block=True)
        finally:
            was = self.connected
            self.connected = False
            if was:
                logger.info("sensor stream connection closed")

    def _try_parse(self, raw_message: str) -> tuple[float, dict] | None:
        metrics = get_metrics()
        try:
            data = json.loads(raw_message)
            validated = SensorEvent.model_validate(data)
            metrics.inc("events_received")
            # received_at recorded at the moment the event arrived from the
            # sensor WebSocket (backend receive timestamp).
            return time.time(), validated.model_dump()
        except (json.JSONDecodeError, ValidationError) as exc:
            metrics.inc("events_rejected")
            logger.warning(
                "rejected malformed event",
                extra={"message": str(exc)[:500]},
            )
            return None

    # --------------------------------------------------------------- flush
    async def _flush_buffer(self, block: bool) -> None:
        """Append buffered events to Redis until the buffer is empty.

        ``block=True`` keeps reading/retrying until Redis is reachable; this
        is what converts a Redis outage into backpressure instead of loss.
        """
        settings = self.settings
        r = get_redis()
        metrics = get_metrics()
        while self._buffer and not self._stop.is_set():
            received_ts, event = self._buffer[0]
            try:
                stream_id = await r.xadd(
                    settings.stream_name,
                    {
                        "payload": json.dumps(event, separators=(",", ":")),
                        "received_at": datetime.fromtimestamp(received_ts, tz=timezone.utc).isoformat(),
                    },
                    maxlen=settings.stream_maxlen,
                    approximate=True,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                if block:
                    # Backpressure: do not keep consuming into an unbounded
                    # buffer; retry Redis instead.
                    logger.warning(
                        "Redis append failed; applying backpressure",
                        extra={"event_id": event.get("event_id")},
                    )
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=0.5)
                    except asyncio.TimeoutError:
                        pass
                    continue
                return
            self._buffer.popleft()
            redis_ms = int(stream_id.split("-")[0]) if isinstance(stream_id, str) else None
            if redis_ms is not None:
                metrics.observe("ingest_latency_ms", redis_ms - received_ts * 1000)
                # Record liveness at *acceptance* time (durable in Redis), so
                # sensor offline detection is independent of processing lag.
                try:
                    await r.hset(settings.liveness_hash, event["sensor_id"], str(redis_ms))
                except Exception:  # noqa: BLE001
                    logger.warning("failed to update liveness hash")
            metrics.inc("events_accepted")
            logger.debug(
                "event accepted into stream",
                extra={"event_id": event.get("event_id"), "stream_id": stream_id},
            )

    # ---------------------------------------------------------------- status
    @property
    def is_connected(self) -> bool:
        return self.connected