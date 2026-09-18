"""Health / readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..db import get_db_pool
from ..redis_client import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    checks = {"redis": False, "postgres": False, "ingestion": False}
    try:
        await get_redis().ping()
        checks["redis"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        pool = await get_db_pool()
        row = await pool.fetchval("SELECT 1")
        checks["postgres"] = row == 1
    except Exception:  # noqa: BLE001
        pass

    from ..ingestion import sensor_client as sensor_client_mod

    if sensor_client_mod.client is not None:
        checks["ingestion"] = sensor_client_mod.client.is_connected

    ok = all(checks.values())
    return {
        "status": "ok" if ok else "degraded",
        "service": settings.service_name,
        "checks": checks,
    }


@router.get("/ready")
async def ready() -> dict:
    settings = get_settings()
    try:
        await get_redis().ping()
        await get_db_pool().fetchval("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"not ready: {exc}") from exc
    return {"status": "ready", "service": settings.service_name}