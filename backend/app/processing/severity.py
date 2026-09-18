"""Deterministic effective-severity rules.

The sensor stream's ``severity_hint`` is optional and untrusted; the
processing layer computes the effective severity from the event type alone
so the same type always maps to the same severity.

Example mapping (the authoritative definition used by the system):

    fire_alarm         -> critical
    panic_button       -> critical
    smoke_detected     -> high
    perimeter_breach   -> high
    door_forced        -> high
    camera_offline     -> medium
    motion_detected    -> medium
    object_detected    -> medium
    heartbeat          -> informational
    (unknown type)     -> low
"""

from __future__ import annotations

EVENT_SEVERITY = {
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

DEFAULT_SEVERITY = "low"

SEVERITY_ORDER = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "informational": 0,
}

ALARM_TYPES = frozenset(EVENT_SEVERITY.keys()) - {"heartbeat"}
HEARTBEAT_TYPE = "heartbeat"


def severity_for(event_type: str) -> str:
    return EVENT_SEVERITY.get(event_type, DEFAULT_SEVERITY)


def is_alarm_type(event_type: str) -> bool:
    return event_type in ALARM_TYPES


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, 0)