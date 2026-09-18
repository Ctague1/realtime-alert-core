"""Alarm REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..schemas import AlarmOut
from ..services import alarm_service
from ..services import queries

router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.get("", response_model=list[AlarmOut])
async def list_alarms(
    status: str = Query("active", description="active | ACTIVE | ACKNOWLEDGED | RESOLVED"),
    limit: int = Query(100, ge=1, le=1000),
    site_id: str | None = None,
    sensor_id: str | None = None,
) -> list[dict]:
    try:
        return await queries.list_alarms(status=status, limit=limit, site_id=site_id, sensor_id=sensor_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{alarm_id}", response_model=AlarmOut)
async def get_alarm(alarm_id: int) -> dict:
    alarm = await queries.get_alarm(alarm_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="alarm not found")
    return alarm


@router.post("/{alarm_id}/acknowledge", response_model=AlarmOut)
async def acknowledge(alarm_id: int) -> dict:
    try:
        alarm, _site = await alarm_service.acknowledge_alarm(alarm_id)
    except alarm_service.AlarmError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return alarm


@router.post("/{alarm_id}/resolve", response_model=AlarmOut)
async def resolve(alarm_id: int) -> dict:
    try:
        alarm, _site = await alarm_service.resolve_alarm(alarm_id)
    except alarm_service.AlarmError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return alarm