"""Event normalization.

Builds the canonical internal representation of an event from the raw
payload, capturing the timestamps needed for latency analysis:

    source_ts      - the sensor's own timestamp
    received_at    - backend receive timestamp (ingestion)
    redis_ms       - Redis stream ID millisecond component (durable append)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .severity import severity_for


def parse_source_ts(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating a trailing 'Z'.

    The provided generator emits ``datetime.utcnow().isoformat() + "Z"``
    (naive UTC). We normalise to an aware UTC datetime and tolerate timestamps
    that already carry a numeric offset (e.g. ``...+00:00Z``).
    """
    value = raw.strip()
    if value[-1:] in ("Z", "z"):
        value = value[:-1]
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str
    sensor_id: str
    site_id: str
    type: str
    severity: str
    confidence: float | None
    source_ts: datetime
    received_at: datetime
    redis_ms: int | None
    raw: dict = field(repr=False)


def normalize_event(raw: dict, received_at: datetime, redis_ms: int | None) -> NormalizedEvent:
    """Validate + canonicalise a raw sensor event.

    Raises ValueError for malformed input. ``severity_hint`` is intentionally
    not trusted - the effective severity is derived from the event type.
    """
    event_id = raw.get("event_id")
    sensor_id = raw.get("sensor_id")
    site_id = raw.get("site_id")
    event_type = raw.get("type")
    ts = raw.get("ts")
    if not all((event_id, sensor_id, site_id, event_type, ts)):
        raise ValueError("event missing required fields (event_id/sensor_id/site_id/type/ts)")

    confidence = raw.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid confidence: {confidence!r}") from exc
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence out of range: {confidence}")

    return NormalizedEvent(
        event_id=str(event_id),
        sensor_id=str(sensor_id),
        site_id=str(site_id),
        type=str(event_type),
        severity=severity_for(str(event_type)),
        confidence=confidence,
        source_ts=parse_source_ts(str(ts)),
        received_at=received_at,
        redis_ms=redis_ms,
        raw=dict(raw),
    )