"""Dashboard notification hub.

The processing worker (a separate process) publishes transient dashboard
updates on a Redis pub/sub channel. This hub lives in the backend process,
subscribes to that channel and fans each update out to every connected
dashboard WebSocket client.

Important: pub/sub is used **only** for transient live updates. Authoritative
state lives in PostgreSQL; the dashboard re-fetches a full snapshot whenever
it (re)connects, so missed transient messages are never fatal.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from ..config import get_settings
from ..metrics import get_metrics
from ..redis_client import get_redis

logger = logging.getLogger(__name__)


class DashboardHub:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._clients: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------ ws clients
    async def connect(self, queue: asyncio.Queue) -> None:
        self._clients.add(queue)
        get_metrics().gauge("ws_clients", len(self._clients))

    async def disconnect(self, queue: asyncio.Queue) -> None:
        self._clients.discard(queue)
        get_metrics().gauge("ws_clients", len(self._clients))

    # ------------------------------------------------------------- pub/sub
    async def start(self) -> None:
        self._task = asyncio.create_task(self._subscribe(), name="dashboard-subscribe")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _subscribe(self) -> None:
        # Reconnect loop: a Redis restart (or any pub/sub connection drop)
        # ends the subscription; we must re-subscribe instead of dying, or a
        # live dashboard would silently stop receiving updates until the
        # backend restarts.
        retry = 1.0
        while not self._stop.is_set():
            r = get_redis()
            pubsub = r.pubsub()
            try:
                await pubsub.subscribe(self.settings.dashboard_channel)
                logger.info("subscribed to dashboard channel %s", self.settings.dashboard_channel)
                retry = 1.0
                async for message in pubsub.listen():
                    if self._stop.is_set():
                        return
                    if message.get("type") != "message":
                        continue
                    payload = message.get("data")
                    if isinstance(payload, str):
                        await self.broadcast_raw(payload)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # Redis disconnected (e.g. restart) - re-subscribe after a
                # short backoff instead of exiting permanently.
                logger.warning(
                    "dashboard subscription dropped; reconnecting in %.1fs", retry
                )
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()
            if self._stop.is_set():
                return
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=retry)
            except asyncio.TimeoutError:
                retry = min(retry * 2, 15.0)

    # ------------------------------------------------------------ broadcast
    async def publish(self, update: dict) -> None:
        """Publish an update (used when worker runs inside this process)."""
        r = get_redis()
        try:
            await r.publish(
                self.settings.dashboard_channel,
                json.dumps(update, default=str, separators=(",", ":")),
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to publish dashboard update")

    async def broadcast_raw(self, payload: str) -> None:
        if not self._clients:
            return
        dead: list[asyncio.Queue] = []
        for queue in list(self._clients):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            await self.disconnect(queue)


hub: DashboardHub | None = None


def get_hub() -> DashboardHub:
    global hub
    if hub is None:
        hub = DashboardHub()
    return hub


async def close_hub() -> None:
    global hub
    if hub is not None:
        await hub.stop()
        hub = None