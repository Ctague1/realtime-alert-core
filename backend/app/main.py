"""Project Sentinel - FastAPI application.

Services provided:
  * sensor-stream ingestion (WebSocket client -> Redis Streams)
  * REST API (alarms, sites, sensors, snapshot, health, metrics)
  * dashboard WebSocket endpoint (live updates + snapshot reconciliation)

The processing worker runs as a separate process/container
(``python -m app.worker``) so a worker restart is distinct from a backend
restart.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routers
from .config import get_settings
from .db import close_db_pool, init_db_pool
from .ingestion import sensor_client as sensor_client_mod
from .ingestion.sensor_client import SensorClient
from .logging_config import setup_logging
from .redis_client import close_redis, ensure_stream_and_group, get_redis
from .services.dashboard_hub import close_hub, get_hub

sensor_client: SensorClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sensor_client
    settings = get_settings()
    setup_logging(settings.log_level)

    await init_db_pool()
    await ensure_stream_and_group(settings.stream_name, settings.group_name)
    await get_redis().ping()

    hub = get_hub()
    await hub.start()

    if settings.ingestion_enabled:
        sensor_client = SensorClient()
        sensor_client_mod.client = sensor_client
        ingest_task = asyncio.create_task(sensor_client.run(), name="sensor-ingestion")
        app.state.ingest_task = ingest_task

    yield

    if settings.ingestion_enabled:
        ingest_task.cancel()
        try:
            await ingest_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    await hub.stop()
    await close_db_pool()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Project Sentinel",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in routers:
        app.include_router(router)
    return app


app = create_app()