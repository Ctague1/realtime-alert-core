"""Site REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas import SiteOut
from ..services import queries

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("", response_model=list[SiteOut])
async def list_sites() -> list[dict]:
    return await queries.list_sites()


@router.get("/{site_id}", response_model=SiteOut)
async def get_site(site_id: str) -> dict:
    site = await queries.get_site(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return site