"""Paginated browse + stats endpoints for the dashboard "view all" pages.

Existing list endpoints (``/alarms``, ``/sites``, ``/sensors``,
``/correlations``) keep their legacy bare-list contract; these new endpoints
serve the dedicated pages with server-side pagination and true totals:

* ``GET /stats``                      - authoritative record counts
* ``GET /browse/alarms``              - paginated alarms
* ``GET /browse/sites``               - paginated site state
* ``GET /browse/sensors``             - paginated sensors
* ``GET /browse/correlations``        - paginated correlations

All page responses use the same shape::

    {"items": [...], "page": 1, "page_size": 50, "total": 12345,
     "total_pages": 247}
"""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query

from ..schemas import (
    AlarmOut,
    CorrelationOut,
    Page,
    SensorOut,
    SiteOut,
    StatsOut,
)
from ..services import queries

router = APIRouter(tags=["browse", "stats"])


def _page(items: list, page: int, page_size: int, total: int) -> dict:
    total_pages = math.ceil(total / page_size) if total else 0
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


@router.get("/stats", response_model=StatsOut)
async def stats() -> dict:
    return await queries.count_stats()


@router.get("/browse/alarms", response_model=Page[AlarmOut])
async def browse_alarms(
    status: str = Query("active", description="active | ACTIVE | ACKNOWLEDGED | RESOLVED"),
    site_id: str | None = None,
    sensor_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    try:
        items, total = await queries.list_alarms_page(
            status=status, page=page, page_size=page_size,
            site_id=site_id, sensor_id=sensor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _page(items, page, page_size, total)


@router.get("/browse/sites", response_model=Page[SiteOut])
async def browse_sites(
    severity: str | None = Query(None, description="critical | high | medium | low | clear"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    items, total = await queries.list_sites_page(
        page=page, page_size=page_size, severity=severity
    )
    return _page(items, page, page_size, total)


@router.get("/browse/sensors", response_model=Page[SensorOut])
async def browse_sensors(
    site_id: str | None = None,
    online: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    items, total = await queries.list_sensors_page(
        page=page, page_size=page_size, site_id=site_id, online=online
    )
    return _page(items, page, page_size, total)


@router.get("/browse/correlations", response_model=Page[CorrelationOut])
async def browse_correlations(
    site_id: str | None = None,
    rule: str | None = Query(None, description="repeat_event | multi_signal_site | critical_burst"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    items, total = await queries.list_correlations_page(
        page=page, page_size=page_size, site_id=site_id, rule=rule
    )
    return _page(items, page, page_size, total)