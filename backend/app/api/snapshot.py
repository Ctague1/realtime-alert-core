"""Authoritative snapshot endpoint used for dashboard reconciliation.

On (re)connect the dashboard fetches this instead of relying on transient
WebSocket messages it may have missed while disconnected.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import Snapshot
from ..services import queries

router = APIRouter(tags=["snapshot"])


@router.get("/snapshot", response_model=Snapshot)
async def snapshot() -> dict:
    alarms, sites, sensors = await _fetch_snapshot()
    return {"alarms": alarms, "sites": sites, "sensors": sensors}


async def _fetch_snapshot() -> tuple[list[dict], list[dict], list[dict]]:
    # Bounded homepage previews only: the true record counts come from /stats,
    # and the dedicated "view all" pages fetch the full dataset through
    # server-side pagination (/browse/*), so the snapshot never loads the
    # entire table into the dashboard.
    alarms = await queries.list_alarms(status="active", limit=100)
    sites = await queries.list_sites()
    sensors = await queries.list_sensors(limit=2000)
    return alarms, sites, sensors