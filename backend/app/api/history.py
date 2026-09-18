"""History & correlation endpoints.

* ``GET /sites/{site_id}/timeline``   - per-site incident/event timeline
* ``GET /sensors/{sensor_id}/timeline`` - per-sensor event timeline
* ``GET /correlations``               - detected patterns / escalations

All data is read from the authoritative PostgreSQL state, so timelines survive
restarts and are consistent with the live dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..schemas import CorrelationOut, SensorTimeline, SiteTimeline
from ..services import queries

router = APIRouter(tags=["history"])


@router.get("/sites/{site_id}/timeline", response_model=SiteTimeline)
async def site_timeline(
    site_id: str, limit: int = Query(100, ge=1, le=500)
) -> dict:
    site = await queries.get_site(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    events = await queries.list_site_events(site_id, limit)
    correlations = await queries.list_correlations(site_id=site_id, limit=20)
    return {"site": site, "events": events, "correlations": correlations}


@router.get("/sensors/{sensor_id}/timeline", response_model=SensorTimeline)
async def sensor_timeline(
    sensor_id: str, limit: int = Query(100, ge=1, le=500)
) -> dict:
    sensor = await queries.get_sensor(sensor_id)
    if sensor is None:
        raise HTTPException(status_code=404, detail="sensor not found")
    events = await queries.list_sensor_events(sensor_id, limit)
    return {"sensor": sensor, "events": events}


@router.get("/correlations", response_model=list[CorrelationOut])
async def list_correlations(
    site_id: str | None = None, limit: int = Query(50, ge=1, le=500)
) -> list[dict]:
    return await queries.list_correlations(site_id=site_id, limit=limit)