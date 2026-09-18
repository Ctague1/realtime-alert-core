"""Unit tests for event normalization."""

from datetime import datetime, timezone

import pytest

from app.processing.normalize import normalize_event, parse_source_ts

BASE = {
    "event_id": "evt_abc123",
    "sensor_id": "sensor-001",
    "site_id": "site-100",
    "type": "fire_alarm",
    "confidence": 0.87,
    "ts": "2026-09-15T14:03:12.481Z",
}


def test_parse_source_ts_z_suffix():
    dt = parse_source_ts("2026-09-15T14:03:12.481Z")
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)


def test_parse_source_ts_no_tz():
    dt = parse_source_ts("2026-09-15T14:03:12.481")
    assert dt.tzinfo is not None  # assumed UTC
    assert dt.hour == 14


def test_parse_source_ts_with_offset():
    dt = parse_source_ts("2026-09-15T16:03:12.481+02:00")
    assert dt.hour == 14  # normalised to UTC


def test_normalize_full():
    evt = normalize_event(BASE, received_at=datetime.now(timezone.utc), redis_ms=123)
    assert evt.event_id == "evt_abc123"
    assert evt.sensor_id == "sensor-001"
    assert evt.site_id == "site-100"
    assert evt.type == "fire_alarm"
    assert evt.severity == "critical"
    assert evt.confidence == 0.87
    assert evt.redis_ms == 123
    assert evt.raw["event_id"] == "evt_abc123"


def test_severity_hint_is_ignored():
    data = dict(BASE, severity_hint="low")
    evt = normalize_event(data, received_at=datetime.now(timezone.utc), redis_ms=None)
    # fire_alarm is always critical even if the hint claims "low"
    assert evt.severity == "critical"


def test_missing_required_field_rejected():
    for field in ("event_id", "sensor_id", "site_id", "type", "ts"):
        data = dict(BASE)
        del data[field]
        with pytest.raises(ValueError):
            normalize_event(data, received_at=datetime.now(timezone.utc), redis_ms=None)


def test_invalid_confidence_rejected():
    for bad in ("high", -0.5, 1.5, "abc"):
        data = dict(BASE, confidence=bad)
        with pytest.raises(ValueError):
            normalize_event(data, received_at=datetime.now(timezone.utc), redis_ms=None)


def test_missing_confidence_allowed():
    data = dict(BASE)
    data.pop("confidence", None)
    evt = normalize_event(data, received_at=datetime.now(timezone.utc), redis_ms=None)
    assert evt.confidence is None


def test_heartbeat_normalized():
    data = dict(BASE, type="heartbeat")
    evt = normalize_event(data, received_at=datetime.now(timezone.utc), redis_ms=None)
    assert evt.severity == "informational"