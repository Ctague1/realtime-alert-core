"""REST routes."""

from __future__ import annotations

from .alarms import router as alarms_router
from .health import router as health_router
from .metrics import router as metrics_router
from .sensors import router as sensors_router
from .sites import router as sites_router
from .snapshot import router as snapshot_router
from .ws import router as ws_router

routers = [
    health_router,
    alarms_router,
    sites_router,
    sensors_router,
    snapshot_router,
    ws_router,
    metrics_router,
]