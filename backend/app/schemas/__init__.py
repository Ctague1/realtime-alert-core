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


class TimelineEvent(BaseModel):
    event_id: str
    sensor_id: str
    site_id: str
    type: str
    severity: str
    confidence: Optional[float] = None
    source_ts: str
    processed_at: Optional[str] = None
    alarm_id: Optional[int] = None
    alarm_status: Optional[str] = None
    escalated: Optional[bool] = None


class CorrelationOut(BaseModel):
    correlation_id: int
    rule: str
    site_id: str
    sensor_id: Optional[str] = None
    window_start: str
    window_end: str
    severity_before: str
    severity_after: str
    event_ids: list[str]
    alarm_ids: list[int]
    description: str = ""
    detected_at: str


class SiteTimeline(BaseModel):
    site: SiteOut
    events: list[TimelineEvent]
    correlations: list[CorrelationOut]


class SensorTimeline(BaseModel):
    sensor: SensorOut
    events: list[TimelineEvent]