"""Dashboard WebSocket endpoint.

On connect the full authoritative snapshot is sent. After that, transient
live updates (new alarms, site/sensor changes) are streamed from the
dashboard hub. The dashboard must not rely on receiving every transient
message while disconnected - it re-fetches /snapshot on reconnect.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..logging_config import get_logger
from ..services.dashboard_hub import get_hub
from .snapshot import _fetch_snapshot

router = APIRouter(tags=["dashboard"])
logger = get_logger("sentinel.ws")


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    hub = get_hub()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    await hub.connect(queue)
    try:
        alarms, sites, sensors = await _fetch_snapshot()
        await websocket.send_text(
            json.dumps(
                {"kind": "snapshot", "alarms": alarms, "sites": sites, "sensors": sensors},
                default=str,
            )
        )
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"kind": "ping"}))
                continue
            await websocket.send_text(payload)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("dashboard websocket error")
    finally:
        await hub.disconnect(queue)