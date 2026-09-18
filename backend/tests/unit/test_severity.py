"""Unit tests for deterministic severity rules."""

import pytest

from app.processing.severity import (
    DEFAULT_SEVERITY,
    EVENT_SEVERITY,
    HEARTBEAT_TYPE,
    is_alarm_type,
    severity_for,
    severity_rank,
)


def test_known_event_severities():
    expected = {
        "fire_alarm": "critical",
        "panic_button": "critical",
        "smoke_detected": "high",
        "perimeter_breach": "high",
        "door_forced": "high",
        "camera_offline": "medium",
        "motion_detected": "medium",
        "object_detected": "medium",
        "heartbeat": "informational",
    }
    for event_type, severity in expected.items():
        assert severity_for(event_type) == severity


def test_unknown_type_gets_default():
    assert severity_for("something_else") == DEFAULT_SEVERITY == "low"


def test_same_type_always_same_severity():
    for event_type in EVENT_SEVERITY:
        for _ in range(5):
            assert severity_for(event_type) == severity_for(event_type)


def test_rank_ordering():
    assert severity_rank("critical") > severity_rank("high") > severity_rank("medium")
    assert severity_rank("medium") > severity_rank("low") > severity_rank("informational")
    assert severity_rank("unknown") == severity_rank("informational")


def test_heartbeat_is_not_alarm():
    assert HEARTBEAT_TYPE == "heartbeat"
    assert not is_alarm_type("heartbeat")
    assert is_alarm_type("fire_alarm")
    assert is_alarm_type("motion_detected")


@pytest.mark.parametrize(
    "event_type,expected",
    [
        ("fire_alarm", True),
        ("panic_button", True),
        ("smoke_detected", True),
        ("perimeter_breach", True),
        ("door_forced", True),
        ("camera_offline", True),
        ("motion_detected", True),
        ("object_detected", True),
        ("heartbeat", False),
    ],
)
def test_alarm_types(event_type, expected):
    assert is_alarm_type(event_type) is expected