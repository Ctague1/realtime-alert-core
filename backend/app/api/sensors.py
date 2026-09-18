"""Sensor REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..schemas import SensorOut
from ..services import queries

router = APIRouter(prefix="/sensors", tags=["sensors"])


@router.get("", response_model=list[SensorOut])
async def list_sensors(
    site_id: str | None = None,
    online: bool | None = None,
    limit: int = Query(500, ge=1, le=2000),
) -> list[dict]:
    return await queries.list_sensors(site_id=site_id, online=online, limit=limit)


@router.get("/{sensor_id}", response_model=SensorOut)
async def get_sensor(sensor_id: str) -> dict:
    sensor = await queries.get_sensor(sensor_id)
    if sensor is None:
        raise HTTPException(status_code=404, detail="sensor not found")
    return sensor