"""Pydantic schemas for inbound events and outbound API payloads."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SensorEvent(BaseModel):
    """Inbound raw event as received from the sensor WebSocket stream."""

    event_id: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    severity_hint: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ts: str = Field(min_length=1)


class AlarmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alarm_id: int
    event_id: str
    sensor_id: str
    site_id: str
    type: str
    severity: str
    status: str
    created_at: str
    source_ts: Optional[str] = None
    confidence: Optional[float] = None
    acknowledged_at: Optional[str] = None
    resolved_at: Optional[str] = None


class SiteOut(BaseModel):
    site_id: str
    status: str
    active_alarm_count: int
    highest_active_severity: Optional[str]
    latest_event_ts: Optional[str]
    updated_at: str


class SensorOut(BaseModel):
    sensor_id: str
    site_id: str
    status: str
    online: bool
    last_event_ts: Optional[str]
    last_heartbeat_ts: Optional[str]
    latest_event_type: Optional[str]
    updated_at: str


class Snapshot(BaseModel):
    alarms: list[AlarmOut]
    sites: list[SiteOut]
    sensors: list[SensorOut]